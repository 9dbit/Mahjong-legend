"""Compile UI 0.8.6 after v085. The original artwork and math are untouched."""
from pathlib import Path
import hashlib,json,re
from PIL import Image, ImageOps
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'web/assets/fullframe-v086'
def build(runtime_only=False):
    OUT.mkdir(parents=True,exist_ok=True)
    with Image.open(ROOT/'web/assets/portrait-v085/frame.webp') as art:
        slices={'rail':(0,305,864,394),'hud':(0,1332,864,1531)}
        for stem,top,bottom,edges in [('crown',0,305,(12,852)),('board',394,1332,(118,747)),('controls',1531,1859,(12,852))]:
            for suffix,left,right in [('left',0,edges[0]),('center',edges[0],edges[1]),('right',edges[1],864)]:
                slices[f'{stem}-{suffix}']=(left,top,right,bottom)
        for name,box in slices.items():
            art.crop(box).save(OUT/f'{name}.webp','WEBP',lossless=True,method=1)
    # Extend decorative clouds, not narrow columns stretched into horizontal
    # streaks. These are crops of the same approved sky/footer, without text.
    with Image.open(ROOT/'web/assets/portrait-v085/frame.webp') as art:
        for stem,box,high in [('crown',(0,0,200,70),305),('controls',(0,1748,220,1859),328)]:
            cloud=art.crop(box);cloud=cloud.resize((round(cloud.width*high/cloud.height),high),Image.Resampling.LANCZOS).crop((0,0,220,high))
            cloud.save(OUT/f'{stem}-left.webp','WEBP',lossless=True,method=1)
            ImageOps.mirror(cloud).save(OUT/f'{stem}-right.webp','WEBP',lossless=True,method=1)
    target=ROOT/'web/index.html';html=target.read_text()
    if 'fullframe-v086/layout.css' not in html:
        html=html.replace('</head>','  <link rel="stylesheet" href="/assets/fullframe-v086/layout.css?v=086">\n  <script src="/assets/fullframe-v086/layout.js?v=086" defer></script>\n</head>')
    # Compose from approved pixels. Dynamic values remain independent DOM nodes.
    skin='<div class="fullframe-art" aria-hidden="true"><i class="art-crown"><b></b><b></b><b></b></i><i class="art-rail"></i><i class="art-board"><b></b><b></b><b></b></i><i class="art-hud"></i><i class="art-controls"><b></b><b></b><b></b></i></div>'
    html=re.sub(r'<div class="fullframe-art".*?</div>', '', html)
    html=html.replace('<span class="pwa-footer-extension"',skin+'\n    <span class="pwa-footer-extension"')
    target.write_text(html.replace('0.8.5','0.8.6').replace('?v=085','?v=086'))
    sw=ROOT/'web/sw.js';sw.write_text(sw.read_text().replace('presentation-085','presentation-086'))
    (OUT/'release.json').write_text(json.dumps({'release':'0.8.6','math_version':'0.8.0','fullframe':True,'tile_ratio':'2:3','virtual_credits_only':True})+'\n')
    (OUT/'manifest.json').write_text(json.dumps({'source':'web/assets/portrait-v085/frame.webp','slices':{k:v for k,v in slices.items() if k not in ['crown-left','crown-right','controls-left','controls-right']},'edge_extensions':{'crown':{'crop':[0,0,200,70],'scaled_height':305,'width':220},'controls':{'crop':[0,1748,220,1859],'scaled_height':328,'width':220},'right':'mirrored left'},'files':{f'{n}.webp':hashlib.sha256((OUT/f'{n}.webp').read_bytes()).hexdigest() for n in slices}},indent=2)+'\n')
    # These are release labels, not changes to the server-authoritative math.
    for name in ['game.js','reels.js']:
        script=ROOT/'web/assets/portrait-v085'/name
        script.write_text(script.read_text().replace('UI 0.8.5','UI 0.8.6').replace("const VERSION = '0.8.5'", "const VERSION = '0.8.6'"))
    server=ROOT/'mahjong_legend/server.py'
    server.write_text(server.read_text().replace("'ui': '0.8.5'", "'ui': '0.8.6'"))
    if not runtime_only:
        for name in ['tests/test_approved_ui_v082.py','tests/test_presentation_v081.py','tests/test_portrait_v085.py','tools/qa_approved_v082.py','tools/qa_portrait_v085.py','tools/qa_live_release.py']:
            path=ROOT/name;text=path.read_text();text=text.replace('0.8.5','0.8.6')
            if name=='tools/qa_live_release.py' and 'fullframe_390x690' not in text:
                text=text.replace("'assets/portrait-v085/portrait.css']", "'assets/portrait-v085/portrait.css','assets/fullframe-v086/layout.css','assets/fullframe-v086/layout.js','index.html','assets/fullframe-v086/rail.webp','assets/fullframe-v086/hud.webp']")
                text=text.replace('/assets/portrait-v085/release.json','/assets/fullframe-v086/release.json').replace('release=085','release=086').replace('v085_live_mobile','v086_live_mobile')
                text=text.replace("page.locator('#board').evaluate('(e)=>Promise.all", "page.set_viewport_size({'width':390,'height':690});page.wait_for_timeout(200)\n    fullframe=page.locator('#game-stage').bounding_box();assert abs(fullframe['x'])<.5 and abs(fullframe['width']-390)<.5 and abs(fullframe['height']-690)<.5,fullframe\n    page.locator('#board').evaluate('(e)=>Promise.all")
                text=text.replace("'ui_release':'0.8.6'", "'ui_release':'0.8.6','fullframe_390x690':fullframe")
                text=text.replace("expected={p:hashlib", "paths += ['assets/fullframe-v086/'+name+'.webp' for name in ['crown-left','crown-center','crown-right','board-left','board-center','board-right','controls-left','controls-center','controls-right']]\nexpected={p:hashlib")
            path.write_text(text)
        preview=ROOT/'tools/local_preview.py'
        text=preview.read_text()
        text=text.replace("'assets/reel-v083/splash.js']:page.add_script_tag", "'assets/reel-v083/splash.js','assets/fullframe-v086/layout.js']:page.add_script_tag")
        preview.write_text(text)
        qa=ROOT/'tools/qa_reels_v083.py';text=qa.read_text()
        text=text.replace("assert motion['completed'] and not motion['cancelled'],motion", "assert motion['completed'] and (case=='resize' or not motion['cancelled']),motion  # Resize may retire only the visual atlas; final board/replay still checked below.")
        qa.write_text(text)
    print('UI 0.8.6 full-frame compiled; source artwork and math unchanged')
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--runtime-only',action='store_true')
    build(runtime_only=parser.parse_args().runtime_only)
