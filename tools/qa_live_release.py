"""Verify exact UI 0.8.2 and a real virtual-credit round on the authorized URL."""
from pathlib import Path
import hashlib, json, os, time, re
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
URL=os.environ['MW_LIVE_URL'].rstrip('/')
ALLOWED='https://mahjong-legend-web-production.up.railway.app'
if URL!=ALLOWED:raise ValueError('Unexpected deployment target')
paths=['assets/locked-v08/game.js','assets/locked-v08/audio.js','assets/approved-v082/approved.css','assets/approved-v082/frame.webp']
expected={p:hashlib.sha256((ROOT/'web'/p).read_bytes()).hexdigest() for p in paths}
last_error='not yet checked'
for attempt in range(48):
    try:
        actual={}
        for p in paths:
            with urlopen(URL+'/'+p+'?release=082',timeout=10) as r:actual[p]=hashlib.sha256(r.read()).hexdigest()
        with urlopen(URL+'/api/state',timeout=10) as r:state=json.load(r)
        with urlopen(URL+'/assets/approved-v082/release.json',timeout=10) as r:release=json.load(r)
        if actual==expected and state['version']=='0.8.0' and release['release']=='0.8.2' and state['rules']['base_multipliers']==[1,2,3,5]:break
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
    expect(page.locator('#game-stage')).to_have_attribute('data-release','0.8.2')
    page.locator('#board').evaluate('(b)=>Promise.all([...b.querySelectorAll("img")].map(i=>i.decode()))')
    assert page.locator('#board .tile').count()==23
    assert page.locator('#mult-track').inner_text().split()==['x1','x2','x3','x5']
    assert page.locator('.title-lockup').evaluate('(e)=>getComputedStyle(e).opacity')=='0'
    assert page.locator('.logo-fx').count()==1
    with page.expect_response(lambda r:r.url.endswith('/api/spin') and r.request.method=='POST') as response:page.locator('#spin-btn').click()
    result=response.value.json();assert response.value.status==200
    if page.locator('#spin-btn').get_attribute('aria-label')!='Spin':page.locator('#spin-btn').click()
    expect(page.locator('#spin-count')).to_have_text('1',timeout=45000)
    expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
    value=float(page.locator('#balance').inner_text().replace('.','').replace(',','.'))
    assert abs(value-float(result['state']['balance']))<.011
    page.locator('#menu-btn').click();page.locator('[data-panel="fairness"]').click();page.locator('#verify-btn').click()
    expect(page.locator('#verification-result')).to_have_text(re.compile('^PASS'))
    page.locator('#close-dialog').click()
    # A skip completes the logical round before newly inserted WebP elements
    # necessarily finish decoding. Verify the final painted board, not a partial
    # loading frame captured immediately after the replay HTTP response.
    page.locator('#board').evaluate('''async b=>{
      await Promise.all([...b.querySelectorAll('img')].map(i=>i.decode()));
      await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    }''')
    final_board=[e['board'] for e in result['round']['events'] if e['type']=='screen_end'][-1]
    painted=page.locator('#board .reel').evaluate_all('(es)=>es.map(e=>[...e.children].map(t=>t.dataset.symbol))')
    assert painted==[[t['symbol'] for t in col] for col in final_board]
    assert page.locator('#board .tile').evaluate_all('''es=>es.every(e=>{
      const i=e.querySelector('.tile-image');
      return i.complete&&i.naturalWidth>0&&getComputedStyle(e).visibility==='visible'&&Number(getComputedStyle(i).opacity)>.99;
    })''')
    assert not errors,errors
    out=ROOT/'qa';out.mkdir(exist_ok=True)
    page.screenshot(path=str(out/'v082_live_mobile.png'))
    report={'url':URL,'ui_release':'0.8.2','math_release':state['version'],'files_sha256':actual,'base_multipliers':[1,2,3,5],'real_https_spin':'PASS','replay':'PASS','final_painted_board':'PASS','page_errors':errors,'audio':page.evaluate('window.MahjongWildAudio.state')}
    (out/'live_results.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));browser.close()
