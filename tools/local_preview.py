"""Offline renderer uses real Python outcomes; it is not a production endpoint."""
from pathlib import Path
import sys,json,base64,re,mimetypes
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mahjong_legend.server import DemoSession
from mahjong_legend.engine import verify_round
WEB=ROOT/'web'
def offline(page,seed=148):
    session=DemoSession();session.seed=f'{seed:064x}'
    def api(path,payload):
        if path=='/api/state':return session.state()
        if path=='/api/spin':return session.spin(payload['bet'])
        if path=='/api/verify':return verify_round(payload['round'],session.cfg)
        if path=='/api/reset':return session.reset()
        if path=='/api/last-round':return {'round':session.last_round}
        raise ValueError(path)
    def uri(path):
        f=WEB/path.split('?')[0].lstrip('/')
        return 'data:'+(mimetypes.guess_type(f.name)[0] or 'application/octet-stream')+';base64,'+base64.b64encode(f.read_bytes()).decode()
    assets={'/'+str(f.relative_to(WEB)):uri('/'+str(f.relative_to(WEB))) for f in WEB.rglob('*') if f.suffix in ['.webp','.png','.wav','.m4a','.ogg']}
    html=(WEB/'index.html').read_text()
    styles=re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"[^>]*>',html)
    css='\n'.join((WEB/p.split('?')[0].lstrip('/')).read_text() for p in styles)
    css=re.sub(r"url\(['\"]?([^)\"']+)['\"]?\)",lambda m:'url("'+uri(m[1])+'")' if m[1].startswith('/') else m[0],css)
    html=re.sub(r'<script[^>]*src="[^"]+"[^>]*></script>','',html)
    html=re.sub(r'<link[^>]+rel="(?:stylesheet|manifest|apple-touch-icon)"[^>]+>','',html).replace('</head>','<style>'+css+'</style></head>')
    html=re.sub(r'src="(/[^"]+)"',lambda m:'src="'+uri(m[1])+'"',html)
    page.expose_function('qaAPI',api);page.set_content(html)
    page.evaluate('''assets=>{const d=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src');Object.defineProperty(HTMLImageElement.prototype,'src',{set(v){d.set.call(this,assets[v]||v)},get:d.get});const f=window.fetch.bind(window);window.fetch=async(path,opts={})=>path.startsWith('/api/')?new Response(JSON.stringify(await window.qaAPI(path,opts.body?JSON.parse(opts.body):null)),{status:200,headers:{'Content-Type':'application/json'}}):f(assets[path]||path);}''',assets)
    for f in ['assets/locked-v08/audio.js','assets/locked-v08/game.js']:page.add_script_tag(content=(WEB/f).read_text())
    return session
if __name__=='__main__':
    from playwright.sync_api import sync_playwright,expect
    out=ROOT/'qa/approved-v082';out.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium');page=b.new_page(viewport={'width':390,'height':844},device_scale_factor=2,is_mobile=True,has_touch=True)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)));offline(page)
        expect(page.locator('#stage-notice')).to_have_text('SIAP BERMAIN');page.wait_for_timeout(300);page.screenshot(path=str(out/'idle.png'))
        page.locator('#menu-btn').click();page.wait_for_timeout(400);page.screenshot(path=str(out/'menu.png'))
        page.locator('[data-panel=settings]').click();page.screenshot(path=str(out/'settings.png'));page.wait_for_timeout(1000)
        print('errors',errors);print('audio',page.evaluate('window.MahjongWildAudio.state'));b.close()
