"""Checks the approved live UI, non-silent audio graph, menus, PWA, and controls.
--offline is local sandbox rendering only; CI uses HTTP + production CSP.
"""
from pathlib import Path
import argparse,json,sys,threading,time,re
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from mahjong_legend.server import DemoSession,make_server
from playwright.sync_api import sync_playwright,expect
from local_preview import offline
OUT=ROOT/'qa/approved-v082'
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--offline',action='store_true');ap.add_argument('--browser');ap.add_argument('--engine',choices=['chromium','webkit'],default='chromium');args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);session=DemoSession();server=None
    if not args.offline:
        server=make_server(port=0,session=session);threading.Thread(target=server.serve_forever,daemon=True).start()
    report={'ui':'0.8.4','engine':args.engine,'transport':'embedded assets + Python engine' if args.offline else 'HTTP + CSP','viewports':[],'audio':{},'pwa':{}}
    try:
      with sync_playwright() as p:
        browser=getattr(p,args.engine).launch(headless=True,**({'executable_path':args.browser} if args.browser else {}))
        for w,h in ([(390,844)] if args.offline else [(360,640),(390,844),(430,932),(844,390)]):
            page=browser.new_page(viewport={'width':w,'height':h},device_scale_factor=2 if w<500 else 1,is_mobile=w<500,has_touch=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            if args.offline:offline(page)
            else:page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
            expect(page.locator('#stage-notice')).to_have_text('SIAP BERMAIN');expect(page.locator('#game-stage')).to_have_attribute('data-release','0.8.4')
            assert not page.evaluate('window.MahjongWildAudio.state.unlocked'), 'No autoplay before gesture'
            expect(page.locator('#soft-tech-continue')).to_be_enabled(timeout=10000)
            page.locator('#soft-tech-continue').click()
            expect(page.locator('#soft-tech-splash')).to_be_hidden()
            assert page.evaluate('window.MahjongWildAudio.state.unlocked'), 'Continue Play must unlock sound'
            geom=page.locator('body').evaluate('(e)=>({w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height,ow:document.documentElement.scrollWidth-innerWidth,oh:document.documentElement.scrollHeight-innerHeight})')
            assert abs(geom['w']-w)<1 and abs(geom['h']-h)<1 and geom['ow']<=1 and geom['oh']<=1,geom
            assert page.locator('#board .tile').count()==23
            # Live counters fit even after a large virtual payout, without changing state.
            previous_balance=page.locator('#balance').inner_text()
            page.locator('#balance').evaluate("e=>{e.textContent='99.999.999,99';dispatchEvent(new Event('resize'))}")
            for ident in ['balance','last-win','bet-value']:
                assert page.locator('#'+ident).evaluate('e=>e.scrollWidth-e.clientWidth')<=1
            page.locator('#balance').evaluate('(e,value)=>{e.textContent=value;dispatchEvent(new Event("resize"))}',previous_balance)
            # Buttons may never share an interactive rectangle.
            rects=[page.locator('#'+id).bounding_box() for id in ['turbo-btn','minus-btn','spin-btn','plus-btn','auto-btn']]
            for a,b in zip(rects,rects[1:]):assert a['x']+a['width']<=b['x']+.6,(a,b)
            page.screenshot(path=str(OUT/f'{args.engine}_{w}x{h}.png'))
            page.locator('#menu-btn').click()
            for _ in range(80):
                audio=page.evaluate('window.MahjongWildAudio.state')
                if audio['musicPlaying'] and audio['level']>.001:break
                page.wait_for_timeout(100)
            assert audio['context']=='running' and audio['counts'].get('tap',0)>=1 and audio['level']>.001,audio
            report['audio'][f'{w}x{h}']={'first_click_sfx':audio['counts']['tap'],'music':audio['musicPlaying'],'rms':audio['level'],'context':audio['context']}
            for panel in ['rules','paytable','history','fairness','settings']:
                page.locator('[data-panel="'+panel+'"]').click();expect(page.locator('#panel-'+panel)).to_be_visible()
                assert page.locator('#panel-'+panel).evaluate('e=>e.scrollWidth-e.clientWidth')<=1
                if w==390:page.screenshot(path=str(OUT/('menu-'+panel+'.png')))
            page.locator('#setting-sound').click();page.wait_for_timeout(150)
            muted=page.evaluate('window.MahjongWildAudio.state');assert not muted['enabled'] and not muted['musicPlaying'] and muted['level']<.0001,muted
            page.locator('#setting-sound').click();page.wait_for_timeout(250)
            page.locator('#test-audio-btn').click();expect(page.locator('#audio-status')).to_contain_text('Audio aktif')
            page.locator('#reset-btn').click();expect(page.locator('#reset-dialog')).to_be_visible()
            page.locator('#reset-cancel').click();expect(page.locator('#reset-dialog')).not_to_be_visible()
            page.locator('#close-dialog').click();page.locator('#auto-btn').click();expect(page.locator('#auto-dialog')).to_be_visible();page.locator('#auto-cancel').click()
            if not args.offline and w==390:
                # Root-scoped worker and correct install manifest, without offline gambling.
                manifest=page.request.get(f'http://127.0.0.1:{server.server_port}/manifest.webmanifest')
                assert manifest.ok and 'application/manifest+json' in manifest.headers['content-type']
                assert manifest.json()['display']=='standalone'
                sw=page.evaluate('navigator.serviceWorker.getRegistration().then(r=>!!r&&r.scope)')
                assert sw and sw.endswith('/'),sw
                page.context.set_offline(True);expect(page.locator('#spin-btn')).to_be_disabled();expect(page.locator('#connection-note')).to_be_visible()
                cache=page.evaluate("caches.keys().then(async names=>{let paths=[];for(const n of names){const c=await caches.open(n);paths.push(...(await c.keys()).map(r=>new URL(r.url).pathname));}return paths})")
                assert not any(path.startswith('/api/') for path in cache),cache
                page.context.set_offline(False);expect(page.locator('#spin-btn')).to_be_enabled()
                report['pwa']={'manifest':'PASS','root_service_worker':'PASS','offline_spin_blocked':'PASS','no_api_cache':'PASS'}
            assert not errors,errors
            report['viewports'].append({'width':w,'height':h,'body':geom,'menus':'PASS','controls':'PASS'});page.close()
        browser.close()
    finally:
        if server:server.shutdown();server.server_close()
        (OUT/f'qa-{args.engine}.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
if __name__=='__main__':main()
