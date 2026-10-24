"""Presentation QA with real engine fixtures; never ships deterministic endpoints.

--offline embeds assets and binds the same Python engine (local sandbox only).
Default uses a real HTTP server with its Content Security Policy unchanged.
"""
from pathlib import Path
import argparse, base64, hashlib, json, mimetypes, re, sys, threading, time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mahjong_legend.server import DemoSession, make_server
from mahjong_legend.engine import verify_round
from playwright.sync_api import sync_playwright, expect
WEB=ROOT/'web';OUT=ROOT/'qa/motion-v081'

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--offline',action='store_true');ap.add_argument('--browser');ap.add_argument('--engine',default='chromium',choices=['chromium','webkit']);args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);session=DemoSession();server=None
    if not args.offline:
        server=make_server(port=0,session=session);threading.Thread(target=server.serve_forever,daemon=True).start()
    def uri(path):
        f=WEB/path.split('?')[0].lstrip('/')
        return 'data:'+(mimetypes.guess_type(f.name)[0] or 'application/octet-stream')+';base64,'+base64.b64encode(f.read_bytes()).decode()
    html=(WEB/'index.html').read_text();asset_map={}
    if args.offline:
        asset_map={'/'+str(f.relative_to(WEB)):uri('/'+str(f.relative_to(WEB))) for f in WEB.rglob('*') if f.suffix in ('.webp','.png','.wav','.m4a','.ogg')}
        css='\n'.join((WEB/p).read_text() for p in ['style.css','assets/locked-v08/game.css','assets/locked-v08/polish.css','assets/approved-v082/approved.css'])
        css=re.sub(r"url\(['\"]?([^)\"']+)['\"]?\)",lambda m:'url("'+uri(m[1])+'")' if m[1].startswith('/') else m[0],css)
        html=re.sub(r'<script[^>]*src="[^"]+"[^>]*></script>','',html)
        html=re.sub(r'<link[^>]+rel="stylesheet"[^>]+>','',html).replace('</head>','<style>'+css+'</style></head>')
        html=re.sub(r'src="(/[^"]+)"',lambda m:'src="'+uri(m[1])+'"',html)
    def api(path,payload):
        if path=='/api/state':return session.state()
        if path=='/api/spin':return session.spin(payload['bet'])
        if path=='/api/verify':return verify_round(payload['round'],session.cfg)
        if path=='/api/last-round':return {'round':session.last_round}
        if path=='/api/reset':return session.reset()
        raise ValueError(path)
    report={'engine':args.engine,'transport':'embedded assets + Python engine' if args.offline else 'real HTTP + CSP','viewports':[],'cases':[]}
    try:
      with sync_playwright() as p:
        browser=getattr(p,args.engine).launch(headless=True,**({'executable_path':args.browser} if args.browser else {}))
        def load(w=390,h=844,seed=148,reduce=False):
            session.reset();session.seed=f'{seed:064x}'
            page=browser.new_page(viewport={'width':w,'height':h},device_scale_factor=2 if w<500 else 1,is_mobile=w<500,has_touch=w<500,reduced_motion='reduce' if reduce else 'no-preference')
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            if args.offline:
                page.expose_function('qaAPI',api);page.set_content(html)
                page.evaluate('''assets=>{const d=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src');Object.defineProperty(HTMLImageElement.prototype,'src',{set(v){d.set.call(this,assets[v]||v)},get:d.get});const f=window.fetch.bind(window);window.fetch=async(path,opts={})=>path.startsWith('/api/')?new Response(JSON.stringify(await window.qaAPI(path,opts.body?JSON.parse(opts.body):null)),{status:200,headers:{'Content-Type':'application/json'}}):f(assets[path]||path);const A=window.Audio;window.Audio=function(path){return new A(assets[path]||path)};}''',asset_map)
                for f in ['audio.js','game.js']:page.add_script_tag(content=(WEB/'assets/locked-v08'/f).read_text())
            else:page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
            expect(page.locator('#stage-notice')).to_have_text('SIAP BERMAIN')
            page.locator('#board').evaluate('(b)=>Promise.all([...b.querySelectorAll("img")].map(i=>i.decode()))')
            assert page.locator('#board .tile').count()==23
            assert page.locator('#mult-track').inner_text().split()==['x1','x2','x3','x5']
            return page,errors
        def geometry(page):
            return page.evaluate('''()=>{const b=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,right:r.right,bottom:r.bottom}};const meters=[...document.querySelectorAll('.credits-strip .meter')].map(e=>({box:b(e),label:b(e.querySelector('small')),value:b(e.querySelector('.meter-value')),overflow:e.querySelector('.meter-value').scrollWidth-e.querySelector('.meter-value').clientWidth}));return{stage:b(document.querySelector('#game-stage')),meters,logoTextOpacity:getComputedStyle(document.querySelector('.title-lockup')).opacity,overflow:document.documentElement.scrollWidth-innerWidth}}''')
        for w,h in [(320,568),(360,640),(375,667),(390,844),(430,932),(1440,900)]:
            page,errors=load(w,h);g=geometry(page);s=g['stage']
            assert abs(s['w']/s['h']-9/16)<.001 and g['overflow']<=1
            assert g['logoTextOpacity']=='0', 'Duplicate live logo lettering'
            for m in g['meters']:
                assert m['label']['h']<=1.1, 'Accessible labels are visually hidden to match the approved counters'
                assert m['value']['bottom']<=m['box']['bottom']+.6,m
                assert m['value']['x']>=m['box']['x']-.6 and m['value']['right']<=m['box']['right']+.6,m
            page.screenshot(path=str(OUT/f'{args.engine}_{w}x{h}.png'))
            page.locator('#menu-btn').click()
            for tab in ['rules','paytable','history','fairness','settings']:
                page.locator(f'[data-panel="{tab}"]').click()
                expect(page.locator('#panel-'+tab)).to_be_visible()
                overflow=page.locator('#panel-'+tab).evaluate('(e)=>e.scrollWidth-e.clientWidth')
                assert overflow<=1,(w,tab,overflow)
            page.locator('#reset-btn').scroll_into_view_if_needed()
            rb=page.locator('#reset-btn').bounding_box();db=page.locator('.dialog-body').bounding_box()
            assert rb['y']+rb['height']<=db['y']+db['height']+1,(w,rb,db)
            page.locator('.dialog-body').evaluate('(e)=>e.scrollTop=0')
            if w==320:page.screenshot(path=str(OUT/'settings-small.png'))
            assert not errors,errors
            report['viewports'].append({'width':w,'height':h,**g});page.close()
        def install_motion_probe(page, hold_shards=True):
            # Capture native Animation evidence synchronously at creation. A slow
            # WebKit runner may otherwise inspect a reel after runtime cancellation.
            # Only test screenshot clocks are held; keyframes/easing are unchanged.
            page.evaluate('''holdShards=>{
                const native=Element.prototype.animate;
                const probe=window.qaMotion={holdRoll:true,holdShards,roll:null,reels:[],shards:[]};
                Element.prototype.animate=function(frames,options){
                    const a=native.call(this,frames,options);
                    const timing=a.effect.getTiming();
                    if(this.classList.contains('reel-strip')){
                        if(!probe.roll)probe.roll=a.effect.getKeyframes().map(k=>({t:k.offset,y:parseFloat(k.transform.split(',')[1])}));
                        probe.reels.push(a);
                        if(probe.holdRoll){a.pause();a.currentTime=timing.delay+timing.duration*.4;}
                    }
                    if(this.classList.contains('tile-fragment')){
                        probe.shards.push(a);
                        if(probe.holdShards){a.pause();a.currentTime=timing.delay+timing.duration*.4;}
                    }
                    return a;
                };
            }''', hold_shards)
        def release_probe(page, phase):
            page.evaluate('''phase=>{
                const p=window.qaMotion;
                p[phase==='reels'?'holdRoll':'holdShards']=false;
                for(const a of p[phase])if(a.playState==='paused')a.play();
            }''', phase)
        page,errors=load()
        install_motion_probe(page)
        page.locator('#spin-btn').click()
        expect(page.locator('.reel-strip').first).to_be_visible()
        keys=page.evaluate('()=>window.qaMotion.roll')
        assert keys and len(keys)==61, 'Native reel keyframe evidence missing'
        # Strong speed increase in the middle, deceleration at the end.
        start=abs(keys[6]['y']-keys[0]['y']);middle=abs(keys[33]['y']-keys[27]['y']);end=abs(keys[60]['y']-keys[54]['y'])
        assert middle>start*4 and middle>end*4,(start,middle,end)
        page.screenshot(path=str(OUT/'reel-in-motion.png'))
        release_probe(page,'reels')
        expect(page.locator('.tile-fragment').first).to_be_visible(timeout=20000)
        # Fragments were paused atomically at native animation creation.
        count=page.locator('.tile-fragment').count();assert count>=9
        visible=page.locator('.tile-fragment').evaluate_all('(es)=>es.filter(e=>getComputedStyle(e).opacity>.5&&e.getBoundingClientRect().width>6).length');assert visible>=9
        page.screenshot(path=str(OUT/'visible-shatter.png'))
        release_probe(page,'shards')
        expect(page.locator('#spin-count')).to_have_text('1',timeout=90000)
        expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
        assert abs(float(page.locator('#balance').inner_text().replace('.','').replace(',','.'))-float(session.state()['balance']))<.011
        assert page.locator('.tile-fragment').count()==0
        page.locator('#menu-btn').click();page.locator('[data-panel="fairness"]').click();page.locator('#verify-btn').click();expect(page.locator('#verification-result')).to_have_text(re.compile('^PASS'))
        assert not errors,errors
        report['cases'].append({'case':'slow-fast-slow and visible fracture','speed':{'start':start,'middle':middle,'end':end},'fragments':count,'visible':visible,'replay':'PASS'});page.close()
        for name,seed,reduce,turbo in [('gold-wild',4,False,False),('bonus-reduced',357,True,False),('turbo',148,False,True),('skip',148,False,False)]:
            page,errors=load(seed=seed,reduce=reduce)
            if turbo:page.locator('#turbo-btn').click()
            if name=='skip':install_motion_probe(page,hold_shards=False)
            page.locator('#spin-btn').click()
            if name=='skip':
                expect(page.locator('.reel-strip').first).to_be_visible();page.locator('#spin-btn').click()
            expect(page.locator('#spin-count')).to_have_text('1',timeout=90000)
            expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
            assert session.spins==1 and page.locator('.tile-fragment').count()==0
            assert verify_round(session.last_round,session.cfg)['valid']
            if reduce:assert page.locator('.reel-strip').count()==0
            assert not errors,errors
            report['cases'].append({'case':name,'spins':session.spins,'replay':'PASS'});page.close()
        browser.close()
    finally:
        if server:server.shutdown();server.server_close()
        (OUT/f'report-{args.engine}.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'engine':args.engine,'transport':report['transport'],'viewports':len(report['viewports']),'cases':len(report['cases'])}))
if __name__=='__main__':main()
