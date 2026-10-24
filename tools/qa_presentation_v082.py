"""Exercise ceramic shatter, menu geometry, viewport fill and audible audio graphs.

Uses the real local HTTP server and its unmodified CSP. A seeded DemoSession is
test-only; production endpoints never receive a deterministic seed override.
Native effect clocks are paused only while collecting a readable shatter frame.
Audio checks observe WebAudio output/loop nodes, not a mocked player. They do not
prove physical device speakers or iOS hardware output.
"""
from pathlib import Path
import argparse
import json
import re
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mahjong_legend.server import DemoSession, make_server
from mahjong_legend.engine import verify_round
from playwright.sync_api import sync_playwright, expect

OUT = ROOT / 'qa/presentation-v082'

AUDIO_PROBE = r"""(() => {
  const probe = window.qaAudioNodes = {loops: new Set(), maximumLoops: 0};
  const proto = (window.BaseAudioContext || window.AudioContext || window.webkitAudioContext)?.prototype;
  if (!proto?.createBufferSource) return;
  const native = proto.createBufferSource;
  proto.createBufferSource = function(...args) {
    const source = native.apply(this, args), start = source.start;
    source.start = function(...values) {
      const result = start.apply(this, values);
      if (this.loop && this.buffer?.duration > 10) {
        probe.loops.add(this);
        probe.maximumLoops = Math.max(probe.maximumLoops, probe.loops.size);
      }
      return result;
    };
    source.addEventListener('ended', () => probe.loops.delete(source));
    return source;
  };
})();"""

SHATTER_PROBE = r"""() => {
  const native = Element.prototype.animate;
  const p = window.qaCeramic = {hold: true, effects: [], crackSeen: false, dropSeen: false};
  new MutationObserver(() => {
    if (document.querySelector('.tile.cracked')) p.crackSeen = true;
    if (document.querySelector('#game-stage').dataset.motionPhase === 'drop') p.dropSeen = true;
  }).observe(document.querySelector('#game-stage'), {subtree: true, attributes: true, childList: true});
  Element.prototype.animate = function(frames, options) {
    const a = native.call(this, frames, options);
    if (this.closest('#effects-layer')) {
      p.effects.push(a);
      if (p.hold) {
        const t = a.effect.getTiming();
        a.pause(); a.currentTime = t.delay + t.duration * .36;
      }
    }
    return a;
  };
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', choices=['chromium', 'webkit'], default='chromium')
    ap.add_argument('--browser')
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report = {'engine': args.engine, 'transport': 'real HTTP + CSP', 'viewports': [], 'cases': [],
              'limits': ['Audio graph verified; physical speaker quality is not verified.',
                         'Safe-area and background lifecycle cases use controlled browser inputs.']}
    session = DemoSession()
    server = make_server(port=0, session=session)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'

    try:
      with sync_playwright() as p:
        launch = {'headless': True}
        if args.browser:
            launch['executable_path'] = args.browser
        if args.engine == 'chromium':
            launch['args'] = ['--no-sandbox', '--disable-dev-shm-usage']
        browser = getattr(p, args.engine).launch(**launch)

        def load(w=390, h=844, seed=148, preferences=None):
            session.reset(); session.seed = f'{seed:064x}'
            context = browser.new_context(viewport={'width': w, 'height': h},
                device_scale_factor=2 if w < 500 else 1,
                is_mobile=w < 900, has_touch=w < 900)
            context.add_init_script(AUDIO_PROBE)
            if preferences:
                context.add_init_script('Object.entries(' + json.dumps(preferences) +
                    ').forEach(([k,v])=>localStorage.setItem(k,v));')
            page = context.new_page(); errors = []; failures = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('response', lambda r: failures.append({'url': r.url, 'status': r.status})
                    if r.status >= 400 else None)
            response = page.goto(url, wait_until='networkidle')
            assert response.headers.get('content-security-policy'), 'Real CSP absent'
            expect(page.locator('#stage-notice')).to_have_text('SIAP BERMAIN')
            page.locator('#board').evaluate('(b)=>Promise.all([...b.querySelectorAll("img")].map(i=>i.decode()))')
            assert page.locator('#board .tile').count() == 23
            return context, page, errors, failures

        def clean(errors, failures):
            assert not errors, errors
            assert not failures, failures

        def audio_state(page):
            return page.evaluate('window.MahjongWildAudio.state')

        def wait_eval(page, predicate, timeout=15000):
            # Playwright wait_for_function internally uses globalThis.eval, which
            # strict CSP may reject in WebKit. Direct protocol evaluation keeps
            # the production CSP intact and does not add unsafe-eval to the app.
            deadline=time.monotonic()+timeout/1000
            while time.monotonic()<deadline:
                if page.evaluate(predicate):
                    return
                page.wait_for_timeout(50)
            raise AssertionError({'predicate':predicate,'audio':audio_state(page)})

        def viewport_geometry(page):
            return page.evaluate(r'''() => {
              const b=e=>{const r=e.getBoundingClientRect();return{x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};
              const root=getComputedStyle(document.documentElement), body=getComputedStyle(document.body);
              const before=getComputedStyle(document.body,'::before'),after=getComputedStyle(document.body,'::after');
              return {width:innerWidth,height:innerHeight,stage:b(document.querySelector('#game-stage')),
                body:b(document.body),overflowX:document.documentElement.scrollWidth-innerWidth,
                overflowY:document.documentElement.scrollHeight-innerHeight,
                padding:[body.paddingTop,body.paddingRight,body.paddingBottom,body.paddingLeft].map(parseFloat),
                background:body.backgroundImage,before:{position:before.position,top:before.top,bottom:before.bottom,background:before.backgroundImage},
                after:{position:after.position,top:after.top,bottom:after.bottom,background:after.backgroundImage},
                viewportMeta:document.querySelector('meta[name="viewport"]').content};
            }''')

        def check_viewport(g):
            s=g['stage']; top,right,bottom,left=g['padding']
            assert abs(s['w']/s['h']-9/16) < .002, g
            assert g['overflowX'] <= 1 and g['overflowY'] <= 1, g
            assert s['x'] >= left-1 and s['right'] <= g['width']-right+1, g
            assert s['y'] >= top-1 and s['bottom'] <= g['height']-bottom+1, g
            assert abs(g['body']['y']) <= 1 and abs(g['body']['h']-g['height']) <= 1, g
            assert g['background'] != 'none' and 'cover' in g['viewportMeta'], g
            for layer in ['before','after']:
                assert g[layer]['position']=='fixed' and g[layer]['top']=='0px' and g[layer]['bottom']=='0px', g
                assert g[layer]['background']!='none', g

        for w,h in [(320,568),(390,844),(844,390)]:
            context,page,errors,failures=load(w,h)
            initial=viewport_geometry(page);check_viewport(initial)
            page.screenshot(path=str(OUT/f'{args.engine}_{w}x{h}_viewport.png'))
            page.evaluate("""() => {const s=document.documentElement.style;
                s.setProperty('--safe-top','47px');s.setProperty('--safe-bottom','34px');
                s.setProperty('--safe-left','8px');s.setProperty('--safe-right','8px');}""")
            safe=viewport_geometry(page);check_viewport(safe)
            page.evaluate("""() => ['--safe-top','--safe-bottom','--safe-left','--safe-right'].forEach(k=>document.documentElement.style.removeProperty(k))""")
            if w < 500:
                page.locator('#menu-btn').click()
                menu_results=[]
                for tab in ['rules','paytable','history','fairness','settings']:
                    button=page.locator(f'[data-panel="{tab}"]');button.click()
                    expect(button).to_have_attribute('aria-selected','true')
                    expect(page.locator('#panel-'+tab)).to_be_visible()
                    assert page.locator('.info-panel:not(.hidden)').count()==1
                    geometry=page.evaluate(r'''tab=>{
                      const b=e=>{const r=e.getBoundingClientRect();return{x:r.x,y:r.y,right:r.right,bottom:r.bottom,w:r.width,h:r.height}};
                      const d=document.querySelector('#game-dialog'),body=d.querySelector('.dialog-body');
                      return{dialog:b(d),head:b(d.querySelector('.dialog-head')),tabs:b(d.querySelector('.dialog-tabs')),body:b(body),
                        panelOverflow:document.querySelector('#panel-'+tab).scrollWidth-document.querySelector('#panel-'+tab).clientWidth,
                        buttons:[...d.querySelectorAll('.tab')].map(b),
                        rows:[...document.querySelectorAll('#panel-'+tab+' .setting-row')].map(e=>({box:b(e),children:[...e.children].map(b)}))};
                    }''',tab)
                    d=geometry['dialog']
                    assert d['x']>=-1 and d['right']<=w+1 and d['y']>=-1 and d['bottom']<=h+1,(w,tab,geometry)
                    assert geometry['panelOverflow']<=1,(w,tab,geometry)
                    assert geometry['head']['bottom']<=geometry['tabs']['y']+1,(w,tab,geometry)
                    assert geometry['tabs']['bottom']<=geometry['body']['y']+1,(w,tab,geometry)
                    for i,a in enumerate(geometry['buttons']):
                        assert a['w']>0 and a['h']>=30,(w,tab,a)
                        for b in geometry['buttons'][i+1:]:
                            overlap=min(a['right'],b['right'])-max(a['x'],b['x'])
                            overlap_y=min(a['bottom'],b['bottom'])-max(a['y'],b['y'])
                            assert overlap<=1 or overlap_y<=1,(w,tab,geometry['buttons'])
                    for row in geometry['rows']:
                        for a in row['children']:
                            assert a['x']>=row['box']['x']-1 and a['right']<=row['box']['right']+1,(w,tab,row)
                        if len(row['children'])==2:
                            a,b=row['children'];assert a['right']<=b['x']+1 or a['bottom']<=b['y']+1,(w,tab,row)
                    if tab in ['paytable','settings']:
                        page.screenshot(path=str(OUT/f'{args.engine}_{w}x{h}_{tab}.png'))
                    menu_results.append({'tab':tab,'overflow':geometry['panelOverflow']})
                page.locator('#reset-btn').scroll_into_view_if_needed()
                expect(page.locator('#reset-btn')).to_be_visible()
                old_balance=session.state()['balance'];page.locator('#reset-btn').click()
                expect(page.locator('#reset-dialog')).to_be_visible()
                page.screenshot(path=str(OUT/f'{args.engine}_{w}x{h}_reset.png'))
                page.locator('#reset-cancel').click()
                expect(page.locator('#reset-dialog')).not_to_be_visible()
                assert session.state()['balance']==old_balance and session.spins==0
                page.locator('[data-panel="rules"]').focus();page.keyboard.press('End')
                expect(page.locator('[data-panel="settings"]')).to_be_focused()
                expect(page.locator('#panel-settings')).to_be_visible()
                page.screenshot(path=str(OUT/f'{args.engine}_{w}x{h}_menu.png'))
                page.locator('#close-dialog').click();page.locator('#auto-btn').click()
                expect(page.locator('#auto-dialog')).to_be_visible()
                auto_geometry=page.locator('#auto-dialog').evaluate('(e)=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,overflow:e.scrollWidth-e.clientWidth}}')
                assert auto_geometry['x']>=-1 and auto_geometry['right']<=w+1 and auto_geometry['y']>=-1 and auto_geometry['bottom']<=h+1 and auto_geometry['overflow']<=1,auto_geometry
                page.screenshot(path=str(OUT/f'{args.engine}_{w}x{h}_auto.png'))
                page.locator('#auto-cancel').click()
                assert session.spins==0
                report['cases'].append({'case':f'menus-{w}','tabs':menu_results,'reset_cancel':'PASS','keyboard_tabs':'PASS'})
            clean(errors,failures);report['viewports'].append({'initial':initial,'simulated_safe_area':safe});context.close()

        # Fresh storage: one real user click unlocks the audible graph and music.
        context,page,errors,failures=load()
        initial_audio=audio_state(page)
        assert not initial_audio['unlocked'] and not initial_audio['musicPlaying'],initial_audio
        page.locator('#menu-btn').click()
        wait_eval(page,"() => {const s=MahjongWildAudio.state;return s.context==='running' && s.musicPlaying && s.levelRms>0.00001}",timeout=20000)
        started=audio_state(page)
        assert started['musicEnabled'] and started['musicLoops']==1 and started['musicVolume']<=.35,started
        assert started['played'].get('tap',0)>0,started
        assert page.evaluate('qaAudioNodes.loops.size')==1
        page.locator('[data-panel="settings"]').click()
        page.locator('#setting-sound').click()
        wait_eval(page,"() => {const s=MahjongWildAudio.state;return !s.enabled && !s.musicPlaying && s.voices===0 && s.levelRms<0.00001}")
        page.locator('#setting-sound').click()
        wait_eval(page,"() => MahjongWildAudio.state.musicPlaying && MahjongWildAudio.state.levelRms>0.00001")
        page.locator('#setting-music').click()
        wait_eval(page,"() => !MahjongWildAudio.state.musicEnabled && !MahjongWildAudio.state.musicPlaying && qaAudioNodes.loops.size===0")
        page.locator('#setting-music').click()
        wait_eval(page,"() => MahjongWildAudio.state.musicPlaying && qaAudioNodes.loops.size===1")
        # Explicit lifecycle simulation is recorded as such, not device proof.
        for _ in range(3):
            page.evaluate("() => {Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));}")
            wait_eval(page,"() => !MahjongWildAudio.state.musicPlaying && qaAudioNodes.loops.size===0")
            page.evaluate("() => {Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'));}")
            wait_eval(page,"() => MahjongWildAudio.state.musicPlaying && qaAudioNodes.loops.size===1")
        after=audio_state(page)
        assert after['musicLoops']==1 and page.evaluate('qaAudioNodes.maximumLoops')==1,after
        report['cases'].append({'case':'first gesture, mute and music lifecycle','first_click':started,'after_lifecycle':after,'native_max_music_loops':1})
        clean(errors,failures);context.close()

        # Existing explicit OFF preferences survive the presentation update.
        context,page,errors,failures=load(preferences={'mw-sfx':'off','mw-music':'off'})
        page.locator('#menu-btn').click()
        saved=audio_state(page)
        assert not saved['enabled'] and not saved['musicEnabled'] and not saved['musicPlaying'],saved
        report['cases'].append({'case':'explicit saved mute preserved','audio':saved})
        clean(errors,failures);context.close()

        for skip in [False,True]:
            context,page,errors,failures=load()
            page.evaluate(SHATTER_PROBE)
            page.locator('#spin-btn').click()
            expect(page.locator('.ceramic-fragment').first).to_be_visible(timeout=20000)
            evidence=page.evaluate(r'''() => {
              const shards=[...document.querySelectorAll('.ceramic-fragment')];
              const visible=es=>es.filter(e=>parseFloat(getComputedStyle(e).opacity)>.5&&e.getBoundingClientRect().width>1).length;
              return{phase:document.querySelector('#game-stage').dataset.motionPhase,crackSeen:qaCeramic.crackSeen,
                removed:document.querySelectorAll('#board .tile.removed').length,shards:shards.length,visible:visible(shards),
                cuts:[...new Set(shards.map(e=>getComputedStyle(e.querySelector('.fragment-face')).clipPath))],
                complete:shards.every(e=>e.children.length===3&&e.querySelector('.fragment-depth')&&e.querySelector('.fragment-face')&&e.querySelector('.fragment-bevel')),
                textured:shards.every(e=>getComputedStyle(e.querySelector('.fragment-face')).backgroundImage.includes('/tiles/')),
                depth:shards.map(e=>getComputedStyle(e.querySelector('.fragment-depth')).transform),
                sparks:document.querySelectorAll('.ember').length,visibleSparks:visible([...document.querySelectorAll('.ember')]),
                stars:document.querySelectorAll('.impact-star').length,flashes:document.querySelectorAll('.ceramic-flash').length};
            }''')
            assert evidence['phase']=='shatter' and evidence['crackSeen'],evidence
            assert evidence['shards']>9 and evidence['visible']==evidence['shards'],evidence
            assert evidence['complete'] and evidence['textured'] and len(evidence['cuts'])>=6,evidence
            assert all(c.startswith('polygon(') for c in evidence['cuts']),evidence
            assert all(t!='none' for t in evidence['depth']),evidence
            assert evidence['sparks']>=6 and evidence['visibleSparks']>=6 and evidence['stars']>0 and evidence['flashes']>0,evidence
            assert evidence['removed']>0,evidence
            page.wait_for_timeout(150)
            assert page.locator('#game-stage').get_attribute('data-motion-phase')=='shatter','Refill ran before shatter completed'
            if skip:
                page.locator('#spin-btn').click()
            else:
                page.screenshot(path=str(OUT/f'{args.engine}_ceramic_shatter.png'))
                page.evaluate("() => {qaCeramic.hold=false;for(const a of qaCeramic.effects)if(a.playState==='paused')a.play();}")
            expect(page.locator('#spin-count')).to_have_text('1',timeout=90000)
            expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
            assert session.spins==1 and page.locator('#effects-layer').evaluate('(e)=>e.children.length')==0
            assert verify_round(session.last_round,session.cfg)['valid']
            final_audio=audio_state(page)
            assert not final_audio['reelPlaying'],final_audio
            if not skip:
                for key in ['spin','stop','crack','break','cascade']:
                    assert final_audio['played'].get(key,0)>0,(key,final_audio)
                assert final_audio['musicLoops']==1,final_audio
                page.locator('#menu-btn').click();page.locator('[data-panel="fairness"]').click();page.locator('#verify-btn').click()
                expect(page.locator('#verification-result')).to_have_text(re.compile('^PASS'))
            clean(errors,failures)
            report['cases'].append({'case':'skip during shatter' if skip else 'textured ceramic shatter and synchronized audio',
                'evidence':evidence,'audio':final_audio,'spins':session.spins,'replay':'PASS','effect_cleanup':'PASS'})
            context.close()
        browser.close()
        report['status']='PASS'
    finally:
        server.shutdown();server.server_close()
        (OUT/f'report-{args.engine}.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'engine':args.engine,'viewports':len(report['viewports']),'cases':len(report['cases'])}))


if __name__=='__main__':
    main()
