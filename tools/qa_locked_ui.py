"""Engine-backed Chromium QA. Default: real local HTTP; --offline: embedded assets.
Seeds are controlled only in this test process. No fixture endpoint is shipped.
Locator assertions avoid eval-based polling under the application's strict CSP.
"""
from pathlib import Path
import argparse, base64, json, mimetypes, re, sys, threading
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mahjong_legend.server import DemoSession, make_server
from mahjong_legend.engine import verify_round
from playwright.sync_api import sync_playwright, expect
WEB=ROOT/'web'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--browser')
    args=parser.parse_args()
    out=ROOT/'qa';out.mkdir(exist_ok=True)
    session=DemoSession()
    server=make_server(port=0,session=session)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}'
    def uri(path):
        f=WEB/path.split('?')[0].lstrip('/')
        return 'data:'+(mimetypes.guess_type(f.name)[0] or 'application/octet-stream')+';base64,'+base64.b64encode(f.read_bytes()).decode()
    asset_map={};offline_html=''
    if args.offline:
        asset_map={'/'+str(f.relative_to(WEB)):uri('/'+str(f.relative_to(WEB))) for f in WEB.rglob('*') if f.suffix in ('.webp','.png','.wav','.m4a','.ogg')}
        offline_html=re.sub(r'<script[^>]*src="[^"]+"[^>]*></script>','',(WEB/'index.html').read_text())
        css='\n'.join((WEB/p).read_text() for p in ['style.css','assets/locked-v08/game.css','assets/locked-v08/polish.css','assets/approved-v082/approved.css'])
        css=re.sub(r"url\(['\"]?([^)\"']+)['\"]?\)",lambda m:'url("'+uri(m[1])+'")' if m[1].startswith('/') else m[0],css)
        offline_html=re.sub(r'<link[^>]+rel="stylesheet"[^>]+>','',offline_html).replace('</head>','<style>'+css+'</style></head>')
        offline_html=re.sub(r'src="(/[^\"]+)"',lambda m:'src="'+uri(m[1])+'"',offline_html)
    def api(path,payload):
        if path=='/api/state':return session.state()
        if path=='/api/spin':return session.spin(payload['bet'])
        if path=='/api/verify':return verify_round(payload['round'],session.cfg)
        if path=='/api/last-round':return {'round':session.last_round}
        if path=='/api/reset':return session.reset()
        raise ValueError(path)
    report={'transport':'embedded-assets-engine-binding' if args.offline else 'real-local-http','viewports':[],'cases':[]}
    try:
      with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,**({'executable_path':args.browser} if args.browser else {}))
        def load(seed=311,width=390,height=844,reduce=False):
            session.reset();session.seed=f'{seed:064x}'
            page=browser.new_page(viewport={'width':width,'height':height},device_scale_factor=2 if width<500 else 1,is_mobile=width<500,has_touch=width<500,reduced_motion='reduce' if reduce else 'no-preference')
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            if args.offline:
                page.expose_function('qaAPI',api);page.set_content(offline_html)
                page.evaluate('''assets=>{const d=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src');Object.defineProperty(HTMLImageElement.prototype,'src',{set(v){d.set.call(this,assets[v]||v)},get:d.get});const f=window.fetch.bind(window);window.fetch=async(path,opts={})=>path.startsWith('/api/')?new Response(JSON.stringify(await window.qaAPI(path,opts.body?JSON.parse(opts.body):null)),{status:200,headers:{'Content-Type':'application/json'}}):f(assets[path]||path);const A=window.Audio;window.Audio=function(path){return new A(assets[path]||path)};}''',asset_map)
                page.add_script_tag(content=(WEB/'assets/locked-v08/audio.js').read_text())
                page.add_script_tag(content=(WEB/'assets/locked-v08/game.js').read_text())
            else:page.goto(url,wait_until='networkidle')
            expect(page.locator('#stage-notice')).to_have_text('SIAP BERMAIN')
            page.locator('#board').evaluate('(b)=>Promise.all([...b.querySelectorAll("img")].map(i=>i.decode()))')
            assert page.locator('#board .tile').count()==23
            assert page.locator('#mult-track').inner_text().split()==['x1','x2','x3','x5']
            return page,errors
        for w,h in [(320,568),(375,667),(390,844),(430,932),(1440,900)]:
            page,errors=load(width=w,height=h)
            box=page.locator('#game-stage').bounding_box()
            assert abs(box['width']/box['height']-9/16)<.001
            assert box['x']>=-.5 and box['y']>=-.5 and box['x']+box['width']<=w+.5 and box['y']+box['height']<=h+.5
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(out/f'v08_{w}x{h}.png'))
            assert not errors,errors
            report['viewports'].append({'width':w,'height':h,'stage':box,'errors':errors});page.close()
        for name,seed,reduce in [('x5',148,False),('gold_to_wild',4,False),('bonus',357,True),('loss',2,True)]:
            page,errors=load(seed=seed,reduce=reduce)
            page.evaluate("""()=>{window.qaSeen={shards:0,wild:false,x5:false,bonus:false};new MutationObserver(ms=>{for(const m of ms)for(const n of m.addedNodes)if(n.nodeType===1){if(n.matches?.('.shard'))qaSeen.shards++;if(n.matches?.('.wild')||n.querySelector?.('.wild'))qaSeen.wild=true;}if(document.querySelector('#mult-track .active')?.textContent==='x5')qaSeen.x5=true;if(document.querySelector('#phase-tag').textContent.startsWith('FREE'))qaSeen.bonus=true;}).observe(document.querySelector('#game-stage'),{subtree:true,childList:true,attributes:true});}""")
            page.locator('#spin-btn').click()
            expect(page.locator('#spin-count')).to_have_text('1',timeout=60000)
            expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
            assert session.spins==1
            expected=session.state()['balance']
            displayed=page.locator('#balance').inner_text().replace('.','').replace(',','.')
            assert abs(float(displayed)-float(expected))<.011
            assert not errors,errors
            seen=page.evaluate('qaSeen')
            if name=='x5':assert seen['x5'] and seen['shards']>0,seen
            if name=='gold_to_wild':assert seen['wild'],seen
            if reduce:assert seen['shards']==0,seen
            page.locator('#menu-btn').click();page.locator('[data-panel="fairness"]').click();page.locator('#verify-btn').click()
            expect(page.locator('#verification-result')).to_have_text(re.compile('^PASS'))
            page.locator('[data-panel="settings"]').click()
            audio=page.evaluate('window.MahjongWildAudio.state')
            assert audio['unlocked'] and audio['context']=='running',audio
            page.locator('#close-dialog').click()
            if name=='x5':page.screenshot(path=str(out/'v08_completed_cascade.png'))
            report['cases'].append({'name':name,'seed':seed,'seen':seen,'audio':audio,'balance':expected,'replay':'PASS','errors':errors});page.close()
        page,errors=load(seed=148)
        page.locator('#spin-btn').click();expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Lewati animasi')
        page.locator('#spin-btn').click();expect(page.locator('#spin-count')).to_have_text('1')
        expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
        assert session.spins==1 and not errors
        report['cases'].append({'name':'skip-no-double-spin','spins':session.spins});page.close();browser.close()
    finally:server.shutdown();server.server_close();thread.join(timeout=2)
    (out/'browser_results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'transport':report['transport'],'viewports_passed':len(report['viewports']),'cases_passed':len(report['cases'])}))

if __name__=='__main__':main()
