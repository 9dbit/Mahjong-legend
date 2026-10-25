"""Native browser layout/round checks. Safe-area insets are simulated, not an iPhone certification."""
from pathlib import Path
import argparse,io,json,sys,threading
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from mahjong_legend.server import DemoSession,make_server
from mahjong_legend.engine import verify_round
from playwright.sync_api import sync_playwright,expect
OUT=ROOT/'qa/fullframe-v086'
MEASURE='''()=>{const r=s=>{const e=document.querySelector(s),b=e.getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height,right:b.right,bottom:b.bottom};};return {stage:r('#game-stage'),board:r('#board'),notice:r('.announcement'),meters:r('.credits-strip'),controls:r('.play-controls'),logo:r('.logo-fx'),disk:r('.spin-disk'),tiles:[...document.querySelectorAll('#board .tile')].map(e=>{const b=e.getBoundingClientRect();return b.width/b.height;}),buttons:['menu-btn','sound-btn','turbo-btn','minus-btn','spin-btn','plus-btn','auto-btn'].map(id=>r('#'+id)),overflow:[document.documentElement.scrollWidth-innerWidth,document.documentElement.scrollHeight-innerHeight]};}'''
def assert_layout(page,w,h,top=0,bottom=0):
    g=page.evaluate(MEASURE);s=g['stage']
    assert abs(s['h']-h)<1,(w,h,g)
    if w<=h:assert abs(s['x'])<.5 and abs(s['w']-w)<.5,(w,h,g)
    assert max(g['overflow'])<=1,g
    assert len(g['tiles'])==23 and all(abs(v-2/3)<.002 for v in g['tiles']),g
    assert g['board']['bottom']<=g['notice']['y']+.5,g
    assert g['notice']['bottom']<=g['meters']['y']+.5,g
    assert g['meters']['bottom']<=g['controls']['y']+.5,g
    assert g['controls']['bottom']<=h-bottom+.6,g
    assert all(b['y']>=top-.5 and b['bottom']<=h-bottom+.6 for b in g['buttons']),g
    assert abs(g['disk']['w']/g['disk']['h']-1)<.02,g['disk']
    assert abs(g['logo']['w']/g['logo']['h']-358/135)<.03,g['logo']
    for a,b in zip(g['buttons'][2:],g['buttons'][3:]):assert a['right']<=b['x']+.6,(a,b)
    return g

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--offline',action='store_true');ap.add_argument('--browser');ap.add_argument('--engine',default='chromium',choices=['chromium','webkit']);args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);server=None;session=DemoSession();session.seed=f'{2:064x}'
    if not args.offline:
        server=make_server(port=0,session=session);threading.Thread(target=server.serve_forever,daemon=True).start()
    report={'ui':'0.8.6','engine':args.engine,'transport':'offline embedded assets + real Python engine' if args.offline else 'HTTP + CSP','layouts':[],'physical_iphone_tested':False}
    try:
      with sync_playwright() as p:
        b=getattr(p,args.engine).launch(headless=True,**({'executable_path':args.browser} if args.browser else {}))
        def start(w,h):
            nonlocal session
            page=b.new_page(viewport={'width':w,'height':h},is_mobile=True,has_touch=True,device_scale_factor=2)
            if args.offline:
                from local_preview import offline
                session=offline(page,seed=2)
            else:
                session.reset();session.seed=f'{2:064x}';page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
            expect(page.locator('#soft-tech-continue')).to_be_enabled(timeout=20000);page.locator('#soft-tech-continue').click();expect(page.locator('#soft-tech-splash')).to_be_hidden()
            page.wait_for_timeout(80);return page
        for w,h in [(320,568),(360,640),(390,690),(390,844),(430,932),(768,1024),(844,390)]:
            print('LAYOUT',w,h,flush=True);page=start(w,h);g=assert_layout(page,w,h)
            report['layouts'].append({'viewport':[w,h],'stage':g['stage'],'ratio_range':[min(g['tiles']),max(g['tiles'])],'overlap':False})
            if (w,h) in [(390,690),(390,844)]:page.screenshot(path=str(OUT/f'{args.engine}-{w}x{h}.png'))
            page.close()
        print('SAFE AREA',flush=True);page=start(390,844)
        page.locator('#game-stage').evaluate("e=>{e.style.setProperty('--ff-safe-top','59px');e.style.setProperty('--ff-safe-bottom','34px');MahjongViewport.refresh();}")
        page.wait_for_timeout(100);g=assert_layout(page,390,844,59,34)
        report['simulated_safe_area']={'top':59,'bottom':34,'stage':g['stage'],'controls':g['controls']}
        page.screenshot(path=str(OUT/f'{args.engine}-safe-area.png'));page.close()
        print('RESIZE SPIN',flush=True);page=start(390,690);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.evaluate('''()=>{window.ffProbe={requests:0,blank:0,active:true};const f=fetch;window.fetch=(u,o)=>{if(String(u).includes('/api/spin'))ffProbe.requests++;return f(u,o);};function tick(){if(!ffProbe.active)return;const ts=[...document.querySelectorAll('#board > .reel > .tile > .tile-image')];if(ts.length!==23||ts.some(i=>!i.complete||!i.naturalWidth))ffProbe.blank++;requestAnimationFrame(tick);}requestAnimationFrame(tick);}''')
        page.locator('#spin-btn').click();expect(page.locator('.reel-canvas').first).to_be_visible()
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(180)
        page.set_viewport_size({'width':390,'height':690})
        expect(page.locator('#spin-count')).to_have_text('1',timeout=60000);expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
        g=assert_layout(page,390,690);probe=page.evaluate('ffProbe.active=false;ffProbe')
        assert probe['requests']==1 and probe['blank']==0 and not errors,(probe,errors)
        assert session.spins==1 and verify_round(session.last_round,session.cfg)['valid']
        final=None
        for e in session.last_round['events']:
            if e['type']=='screen_start':final=e['board']
            elif e['type']=='cascade':final=e.get('after') or e['before']
        rendered=page.locator('#board').evaluate('(b)=>[...b.children].map(c=>[...c.children].filter(e=>e._tile).map(e=>e._tile))')
        assert final==rendered
        report['resize_during_spin']={'requests':1,'blank_samples':probe['blank'],'replay':'PASS','final_board':'MATCH','errors':errors}
        # Menu hit area remains aligned with its source artwork after reflow.
        page.locator('#menu-btn').click();expect(page.locator('#game-dialog')).to_be_visible();page.locator('#close-dialog').click()
        b.close()
    finally:
        if server:server.shutdown();server.server_close()
        (OUT/f'report-{args.engine}.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
