"""Compile UI 0.8.7 after v085. The original artwork and math are untouched."""
from pathlib import Path
import hashlib,json
from PIL import Image, ImageDraw, ImageFilter, ImageOps
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'web/assets/fullframe-v086'

QA_PATHS=(
    'tests/test_approved_ui_v082.py','tests/test_presentation_v081.py',
    'tests/test_portrait_v085.py','tools/qa_approved_v082.py',
    'tools/qa_portrait_v085.py','tools/qa_live_release.py',
    'tools/local_preview.py','tools/qa_locked_ui.py',
    'tools/qa_motion_v081.py','tools/qa_reels_v083.py',
)

def replace_checked(text,old,new,label):
    """Apply a reviewed edit once, or recognize its exact previous output."""
    applied=text.count(new)
    if applied==1:return text
    if applied or text.count(old)!=1:
        raise ValueError('Review fullframe source drift: '+label)
    return text.replace(old,new,1)

def release_label(text,label):
    if not any(version in text for version in ('0.8.5','0.8.6','0.8.7')):
        raise ValueError('Expected v085/v086/v087 release label: '+label)
    return text.replace('0.8.5','0.8.7').replace('0.8.6','0.8.7')

def rewrite_qa(name,text):
    """Upgrade v085-generated QA after its source integrity checks have run.

    The v085 sources/spec remain immutable. Missing edit anchors fail the build
    instead of silently shipping an old geometry contract or incomplete loader.
    """
    if name not in QA_PATHS:raise ValueError('Unexpected QA target: '+name)
    if name not in ('tools/local_preview.py','tools/qa_locked_ui.py','tools/qa_motion_v081.py'):
        text=release_label(text,name)
    def edit(old,new):
        nonlocal text
        text=replace_checked(text,old,new,name+' / '+old[:70])
    if name in ('tools/qa_locked_ui.py','tools/qa_motion_v081.py'):
        edit('from playwright.sync_api import sync_playwright, expect\n',
             'from playwright.sync_api import sync_playwright, expect\nfrom qa_fullframe_v086 import assert_layout\n')
        edit("'assets/portrait-v085/portrait.css'])",
             "'assets/portrait-v085/portrait.css','assets/fullframe-v086/layout.css'])")
        if name=='tools/qa_locked_ui.py':
            edit("            assert abs(box['width']/box['height']-864/1859)<.001",
                 '            assert_layout(page,w,h)')
            edit("                page.add_script_tag(content=(WEB/'assets/reel-v083/splash.js').read_text())",
                 "                page.add_script_tag(content=(WEB/'assets/reel-v083/splash.js').read_text())\n                page.add_script_tag(content=(WEB/'assets/fullframe-v086/layout.js').read_text())")
        else:
            edit("            assert abs(s['w']/s['h']-864/1859)<.001 and g['overflow']<=1",
                 "            assert_layout(page,w,h)\n            assert g['overflow']<=1")
            edit("'../reel-v083/splash.js']:page.add_script_tag",
                 "'../reel-v083/splash.js','../fullframe-v086/layout.js']:page.add_script_tag")
    elif name=='tools/local_preview.py':
        edit("'assets/reel-v083/splash.js']:page.add_script_tag",
             "'assets/reel-v083/splash.js','assets/fullframe-v086/layout.js']:page.add_script_tag")
    elif name=='tools/qa_reels_v083.py':
        edit('from playwright.sync_api import sync_playwright,expect\n',
             'from playwright.sync_api import sync_playwright,expect\nfrom qa_fullframe_v086 import assert_reel_order\n')
        old="""     assert motion['starts']==motion['stops']==[1,2,3,4,5],motion
     assert motion['atlasPixels']<5000000 and motion['mode']=='gpu-composited-atlas',motion
     assert motion['completed'] and not motion['cancelled'],motion
     starts=[e for e in qa['events'] if e['phase']=='start'][:5]
     stops=[e for e in qa['events'] if e['phase']=='stop'][:5]
     assert [e['column'] for e in starts]==[1,2,3,4,5]
     assert [e['column'] for e in stops]==[1,2,3,4,5]
     assert all(b['at']>=a['at'] for a,b in zip(starts,starts[1:]))"""
        # Accept the earlier v086 partial edit when rebuilding that derivative.
        partial="assert motion['completed'] and (case=='resize' or not motion['cancelled']),motion  # Resize may retire only the visual atlas; final board/replay still checked below."
        if partial in text:
            text=replace_checked(text,partial,"assert motion['completed'] and not motion['cancelled'],motion",name+' / previous resize patch')
        edit(old,"""     assert_reel_order(motion,qa['events'],allow_interrupted=case=='resize')
     assert motion['atlasPixels']<5000000 and motion['mode']=='gpu-composited-atlas',motion""")
    elif name=='tools/qa_live_release.py':
        # Accept a previously generated v086 verifier, retaining the same
        # guarded transforms and asset directory for this component family.
        text=text.replace('release=086','release=085').replace('v086_live_mobile','v085_live_mobile')
        edit('from playwright.sync_api import sync_playwright, expect\n',
             'from playwright.sync_api import sync_playwright, expect\nfrom qa_fullframe_v086 import assert_layout\n')
        edit("'assets/portrait-v085/portrait.css']",
             "'assets/portrait-v085/portrait.css','assets/fullframe-v086/layout.css','assets/fullframe-v086/layout.js','index.html','sw.js','assets/fullframe-v086/rail.webp','assets/fullframe-v086/hud.webp']")
        slices="paths += ['assets/fullframe-v086/'+name+'.webp' for name in ['crown-left','crown-center','crown-right','board-left','board-center','board-right','controls-left','controls-center','controls-right']]\n"
        # approved.css is already in the v085 hash list. These eight additional
        # files cover the PWA shell and visible notch/footer background sources.
        shell="paths += ['manifest.webmanifest','assets/approved-v082/pwa.js','style.css','assets/locked-v08/game.css','assets/locked-v08/polish.css','assets/approved-v082/backdrop.webp','assets/approved-v082/extension-top.webp','assets/approved-v082/extension-bottom.webp']\n"
        hashes=slices+shell+"assert len(paths)==len(set(paths)), 'Duplicate live release hash paths'\nexpected={p:hashlib"
        if slices in text and hashes not in text:
            # Upgrade a previously generated v086 verifier without repeating
            # its nine slice paths; unexpected partial edits still fail closed.
            edit(slices+"expected={p:hashlib",hashes)
        else:
            edit("expected={p:hashlib",hashes)
        edit('/assets/portrait-v085/release.json','/assets/fullframe-v086/release.json')
        edit('release=085','release=087')
        edit('v085_live_mobile','v087_live_mobile')
        release_check="    expect(page.locator('#game-stage')).to_have_attribute('data-release','0.8.7')"
        edit(release_check,release_check+'''
    expect(page.locator('meta[name="viewport"]')).to_have_attribute('content',re.compile(r'(?:^|,)\\s*viewport-fit\\s*=\\s*cover\\s*(?:,|$)'))
    expect(page.locator('meta[name="apple-mobile-web-app-capable"]')).to_have_attribute('content','yes')
    expect(page.locator('meta[name="apple-mobile-web-app-status-bar-style"]')).to_have_attribute('content','black-translucent')
    expect(page.locator('link[rel="manifest"]')).to_have_attribute('href','/manifest.webmanifest')''')
        edit("    page.locator('#board').evaluate('(e)=>Promise.all",
             "    page.set_viewport_size({'width':390,'height':690});page.wait_for_timeout(200)\n    fullframe=assert_layout(page,390,690)['stage']\n    assert not errors,errors\n    page.locator('#board').evaluate('(e)=>Promise.all")
        edit("'ui_release':'0.8.7'", "'ui_release':'0.8.7','fullframe_390x690':fullframe")
    return text

def build(runtime_only=False):
    OUT.mkdir(parents=True,exist_ok=True)
    with Image.open(ROOT/'web/assets/portrait-v085/frame.webp') as art:
        slices={'rail':(0,305,864,394),'hud':(0,1332,864,1531)}
        for stem,top,bottom,edges in [('crown',0,305,(12,852)),('board',394,1332,(118,747)),('controls',1531,1859,(12,852))]:
            for suffix,left,right in [('left',0,edges[0]),('center',edges[0],edges[1]),('right',edges[1],864)]:
                slices[f'{stem}-{suffix}']=(left,top,right,bottom)
        for name,box in slices.items():
            art.crop(box).save(OUT/f'{name}.webp','WEBP',lossless=True,method=1)
    # Extend the approved decorative clouds into a soft, source-colored join.
    # Blur only a background edge strip; never repeat logo/control symbols in
    # the extra space. The protected center pixels are not blended or edited.
    with Image.open(ROOT/'web/assets/portrait-v085/frame.webp') as art:
        blend=Image.new('L',(220,1));draw=ImageDraw.Draw(blend)
        for x in range(220):
            t=max(0,min(1,(x/219-.25)/.75));t=t*t*(3-2*t)
            draw.point((x,0),fill=round(255*t))
        for stem,box,top,high in [('crown',(0,0,200,70),0,305),('controls',(0,1748,220,1859),1531,328)]:
            cloud=art.crop(box);cloud=cloud.resize((round(cloud.width*high/cloud.height),high),Image.Resampling.LANCZOS).crop((0,0,220,high))
            mask=blend.resize((220,high))
            left_edge=art.crop((12,top,13,top+high)).filter(ImageFilter.GaussianBlur(24)).resize((220,high))
            right_edge=art.crop((851,top,852,top+high)).filter(ImageFilter.GaussianBlur(24)).resize((220,high))
            Image.composite(left_edge,cloud,mask).save(OUT/f'{stem}-left.webp','WEBP',lossless=True,method=1)
            Image.composite(right_edge,ImageOps.mirror(cloud),ImageOps.mirror(mask)).save(OUT/f'{stem}-right.webp','WEBP',lossless=True,method=1)
    target=ROOT/'web/index.html';html=target.read_text().replace('?v=086','?v=087')
    html=replace_checked(html,'/assets/locked-v08/audio.js?v=085','/assets/locked-v08/audio.js?v=087','index / audio gain cache key')
    html=replace_checked(html,'</head>','  <link rel="stylesheet" href="/assets/fullframe-v086/layout.css?v=087">\n  <script src="/assets/fullframe-v086/layout.js?v=087" defer></script>\n</head>','index / fullframe loaders')
    # Compose from approved pixels. Dynamic values remain independent DOM nodes.
    skin='<div class="fullframe-art" aria-hidden="true"><i class="art-crown"><b></b><b></b><b></b></i><i class="art-rail"></i><i class="art-board"><b></b><b></b><b></b></i><i class="art-hud"></i><i class="art-controls"><b></b><b></b><b></b></i></div>'
    if 'class="fullframe-art"' in html and skin not in html:
        raise ValueError('Review fullframe source drift: index / artwork container')
    html=replace_checked(html,'<span class="pwa-footer-extension"',skin+'\n    <span class="pwa-footer-extension"','index / artwork container')
    target.write_text(release_label(html,'index').replace('?v=085','?v=087'))
    sw=ROOT/'web/sw.js';sw.write_text(replace_checked(sw.read_text().replace('presentation-086','presentation-085'),'presentation-085','presentation-087','service worker cache'))
    (OUT/'release.json').write_text(json.dumps({'release':'0.8.7','math_version':'0.8.0','fullframe':True,'tile_ratio':'2:3','virtual_credits_only':True})+'\n')
    (OUT/'manifest.json').write_text(json.dumps({'source':'web/assets/portrait-v085/frame.webp','slices':{k:v for k,v in slices.items() if k not in ['crown-left','crown-right','controls-left','controls-right']},'edge_extensions':{'crown':{'crop':[0,0,200,70],'scaled_height':305,'width':220},'controls':{'crop':[0,1748,220,1859],'scaled_height':328,'width':220},'right_cloud':'mirrored left cloud','join':{'left_source_x':12,'right_source_x':851,'source_strip_blur':24,'blend_start':.25,'blend_end':1,'curve':'smoothstep','protected_centers':'unchanged'}},'files':{f'{n}.webp':hashlib.sha256((OUT/f'{n}.webp').read_bytes()).hexdigest() for n in slices}},indent=2)+'\n')
    # These are release labels, not changes to the server-authoritative math.
    for name in ['game.js','reels.js']:
        script=ROOT/'web/assets/portrait-v085'/name
        old,new=('UI 0.8.5','UI 0.8.7') if name=='game.js' else ("const VERSION = '0.8.5'","const VERSION = '0.8.7'")
        previous=old.replace('0.8.5','0.8.6')
        runtime=replace_checked(script.read_text().replace(previous,old),old,new,name+' / release')
        if name=='game.js':
            # Landscape can make the whole portrait stage narrower than 200px.
            # An absolute 8px floor enlarged already-smaller CSS text and clipped
            # long balances. Fit the full value to its measured field instead.
            runtime=replace_checked(runtime,'Math.max(8,size*el.clientWidth/el.scrollWidth*.97)',
                                    'Math.max(1,size*el.clientWidth/el.scrollWidth*.97)',
                                    'game.js / narrow-counter fitting')
        script.write_text(runtime)
    server=ROOT/'mahjong_legend/server.py'
    server.write_text(replace_checked(server.read_text().replace("'ui': '0.8.6'","'ui': '0.8.5'"),"'ui': '0.8.5'","'ui': '0.8.7'",'server / UI release'))
    if not runtime_only:
        # Validate every derivative before writing any of them.
        rewritten={name:rewrite_qa(name,(ROOT/name).read_text()) for name in QA_PATHS}
        for name,text in rewritten.items():compile(text,name,'exec')
        for name,text in rewritten.items():(ROOT/name).write_text(text)
    print('UI 0.8.7 full-frame compiled; source artwork and math unchanged')
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--runtime-only',action='store_true')
    build(runtime_only=parser.parse_args().runtime_only)
