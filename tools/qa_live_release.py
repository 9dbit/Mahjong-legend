"""Verify exact UI 0.8.4 and a real virtual-credit round on the authorized URL."""
from pathlib import Path
import hashlib, json, os, time, re
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
URL=os.environ['MW_LIVE_URL'].rstrip('/')
ALLOWED='https://mahjong-legend-web-production.up.railway.app'
if URL!=ALLOWED:raise ValueError('Unexpected deployment target')
paths=['assets/reel-v083/reels.js','assets/reel-v083/reels.css','assets/reel-v083/splash.js','assets/reel-v083/splash.css','assets/locked-v08/game.js','assets/locked-v08/audio.js','assets/approved-v082/approved.css','assets/approved-v082/frame.webp']
expected={p:hashlib.sha256((ROOT/'web'/p).read_bytes()).hexdigest() for p in paths}
last_error='not yet checked'
for attempt in range(48):
    try:
        actual={}
        for p in paths:
            with urlopen(URL+'/'+p+'?release=084',timeout=10) as r:actual[p]=hashlib.sha256(r.read()).hexdigest()
        with urlopen(URL+'/api/state',timeout=10) as r:state=json.load(r)
        with urlopen(URL+'/assets/reel-v083/release.json',timeout=10) as r:release=json.load(r)
        if actual==expected and state['version']=='0.8.0' and release['release']=='0.8.4' and state['rules']['base_multipliers']==[1,2,3,5]:break
        last_error='Previous release still serving'
    except Exception as exc:last_error=str(exc)
    time.sleep(5)
else:raise RuntimeError('Release not verified: '+last_error)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':390,'height':844},device_scale_factor=2,is_mobile=True,has_touch=True)
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(URL,wait_until='networkidle')
    expect(page.locator('#stage-notice')).to_have_text('SIAP BERMAIN')
    expect(page.locator('#game-stage')).to_have_attribute('data-release','0.8.4')
    expect(page.locator('#soft-tech-continue')).to_be_enabled(timeout=15000)
    page.locator('#soft-tech-continue').click()
    expect(page.locator('#soft-tech-splash')).to_be_hidden()
    assert page.evaluate('MahjongWildAudio.state.unlocked')
    page.locator('#board').evaluate('(b)=>Promise.all([...b.querySelectorAll("img")].map(i=>i.decode()))')
    assert page.locator('#board .tile').count()==23
    assert page.locator('#mult-track').inner_text().split()==['x1','x2','x3','x5']
    assert page.locator('.title-lockup').evaluate('(e)=>getComputedStyle(e).opacity')=='0'
    assert page.locator('.logo-fx').count()==1
    page.locator('#menu-btn').click()
    page.locator('[data-panel="settings"]').click()
    page.locator('#setting-diagnostics').click()
    assert page.locator('#setting-diagnostics').inner_text()=='ON'
    page.locator('#close-dialog').click()
    with page.expect_response(lambda r:'/api/spin' in r.url and r.request.method=='POST') as response:page.locator('#spin-btn').click()
    result=response.value.json();assert response.value.status==200
    # Let the complete real spin render; do not skip the animation under test.
    expect(page.locator('#spin-count')).to_have_text('1',timeout=90000)
    assert page.evaluate('MahjongReels.diagnostics().mode') == 'gpu-composited-atlas'
    assert page.evaluate('MahjongReels.diagnostics().stops') == [1,2,3,4,5]
    expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
    value=float(page.locator('#balance').inner_text().replace('.','').replace(',','.'))
    assert abs(value-float(result['state']['balance']))<.011
    page.locator('#menu-btn').click();page.locator('[data-panel="fairness"]').click();page.locator('#verify-btn').click()
    expect(page.locator('#verification-result')).to_have_text(re.compile('^PASS'))
    page.locator('#close-dialog').click()
    assert not errors,errors
    out=ROOT/'qa';out.mkdir(exist_ok=True)
    page.locator('#board').evaluate('(e)=>Promise.all([...e.querySelectorAll("img")].map(i=>i.decode())))');page.screenshot(path=str(out/'v084_live_mobile.png'))
    report={'url':URL,'ui_release':'0.8.4','math_release':state['version'],'files_sha256':actual,'base_multipliers':[1,2,3,5],'real_https_spin':'PASS','reel_motion':page.evaluate('MahjongReels.diagnostics()'),'replay':'PASS','page_errors':errors,'audio':page.evaluate('window.MahjongWildAudio.state')}
    (out/'live_results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));browser.close()
