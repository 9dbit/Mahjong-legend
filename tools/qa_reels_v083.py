"""Real browser regression: decoded artwork, bounded canvases, ordered starts/stops.
Default tests HTTP/CSP. --offline is a clearly labelled sandbox fallback.
"""
from pathlib import Path
import argparse,json,re,sys,threading
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from mahjong_legend.server import DemoSession,make_server
from mahjong_legend.engine import verify_round
from playwright.sync_api import sync_playwright,expect
OUT=ROOT/'qa/reel-v083'
PROBE=r'''() => {
 window.reelQA={events:[],frames:0,blank:0,undecoded:0,maxCanvases:0,invalidAtlas:0,minimumTiles:23,slowFrames:0,previous:0,shards:0};
 document.addEventListener('mahjong:reel',e=>reelQA.events.push(e.detail));
 new MutationObserver(records=>{for(const r of records)for(const n of r.addedNodes)if(n.nodeType===1){if(n.matches?.('.tile-fragment'))reelQA.shards++;reelQA.shards+=n.querySelectorAll?.('.tile-fragment').length||0;}}).observe(document.querySelector('#game-stage'),{childList:true,subtree:true});
 const sample=(time)=>{
  const q=reelQA, canvases=[...document.querySelectorAll('.reel-canvas')];
  q.maxCanvases=Math.max(q.maxCanvases,canvases.length);
  const cols=[...document.querySelectorAll('#board > .reel')];
  const tiles=cols.map(c=>c.querySelectorAll(':scope > .tile').length);
  q.minimumTiles=Math.min(q.minimumTiles,tiles.reduce((a,b)=>a+b,0));
  if(cols.length!==5 || tiles.join(',')!=='4,5,5,5,4')q.blank++;
  if(canvases.some(c=>c.width<2 || c.height<2 || !c.parentElement?.classList.contains('reel-surface')))q.invalidAtlas++;
  if(document.querySelector('#game-stage').dataset.motionPhase==='preparing'){
   const im=[...document.querySelectorAll('#board .tile-image')];
   if(im.length!==23||im.some(i=>!i.complete||!i.naturalWidth))q.undecoded++;
  }
  if(q.previous&&time-q.previous>34)q.slowFrames++;
  q.previous=time;q.frames++;window.reelSampleFrame=requestAnimationFrame(sample);
 };window.reelSampleFrame=requestAnimationFrame(sample);
}'''
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--offline',action='store_true');ap.add_argument('--browser');ap.add_argument('--engine',default='chromium');ap.add_argument('--case',default='all');args=ap.parse_args()
 OUT.mkdir(parents=True,exist_ok=True);session=DemoSession();server=None
 if not args.offline:
  server=make_server(port=0,session=session);threading.Thread(target=server.serve_forever,daemon=True).start()
 report={'release':'0.8.4','engine':args.engine,'transport':'embedded assets + real Python engine' if args.offline else 'HTTP + CSP','cases':[]}
 try:
  with sync_playwright() as p:
   browser=getattr(p,args.engine).launch(headless=True,**({'executable_path':args.browser} if args.browser else {}))
   cases=['normal','slow-decode','repeat','turbo','skip','resize','reduced-motion','decode-error','winning-cascade']
   for case in (cases if args.case=='all' else [args.case]):
    print('CASE',case,flush=True)
    session.reset();session.seed=f'{148 if case=="winning-cascade" else 2:064x}'
    page=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=3,is_mobile=True,has_touch=True,reduced_motion='reduce' if case=='reduced-motion' else 'no-preference',service_workers='block')
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    if args.offline:
     from local_preview import offline
     session=offline(page,seed=148 if case=='winning-cascade' else 2)
    else:page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
    expect(page.locator('#stage-notice')).to_have_text('SIAP BERMAIN')
    expect(page.locator('#soft-tech-continue')).to_be_enabled(timeout=10000)
    page.locator('#soft-tech-continue').click()
    expect(page.locator('#soft-tech-splash')).to_be_hidden()
    page.evaluate(PROBE)
    if case=='turbo':page.locator('#turbo-btn').click()
    if case in ['slow-decode','decode-error']:
     page.evaluate('''mode=>{const original=HTMLImageElement.prototype.decode;let once=true;HTMLImageElement.prototype.decode=function(){const promise=original.call(this);if(mode==='decode-error'&&once){once=false;return Promise.reject(new Error('Test decode error'));}return mode==='slow-decode'?promise.then(()=>new Promise(r=>setTimeout(r,550))):promise;};}''',case)
    count=3 if case=='repeat' else 1
    for n in range(count):
     page.locator('#spin-btn').click()
     if case in ['skip','resize']:
      expect(page.locator('.reel-canvas').first).to_be_visible(timeout=20000)
      if case=='skip':page.locator('#spin-btn').click()
      else:page.set_viewport_size({'width':430,'height':932})
     if case=='normal':
      expect(page.locator('.reel-canvas').first).to_be_visible(timeout=20000)
      page.screenshot(path=str(OUT/f'{args.engine}-rolling.png'))
     expect(page.locator('#spin-count')).to_have_text(str(n+1),timeout=90000)
     expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
     assert session.spins==n+1
    qa=page.evaluate('reelQA');motion=page.evaluate('MahjongReels.diagnostics()')
    assert qa['blank']==0 and qa['invalidAtlas']==0 and qa['minimumTiles']==23,qa
    assert qa['undecoded']==0,qa
    assert qa['maxCanvases']<=5,qa
    assert page.locator('.reel-canvas').count()==0
    if case not in ['skip','reduced-motion','decode-error','winning-cascade']:
     assert motion['starts']==motion['stops']==[1,2,3,4,5],motion
     assert motion['atlasPixels']<5000000 and motion['mode']=='gpu-composited-atlas',motion
     assert motion['completed'] and not motion['cancelled'],motion
     starts=[e for e in qa['events'] if e['phase']=='start'][:5]
     stops=[e for e in qa['events'] if e['phase']=='stop'][:5]
     assert [e['column'] for e in starts]==[1,2,3,4,5]
     assert [e['column'] for e in stops]==[1,2,3,4,5]
     assert all(b['at']>=a['at'] for a,b in zip(starts,starts[1:]))
    if True:
     lastboard=None
     for event in session.last_round['events']:
      if event['type']=='screen_start':lastboard=event['board']
      elif event['type']=='cascade':lastboard=event.get('after') or event['before']
     rendered=page.locator('#board').evaluate('(e)=>[...e.children].map(c=>[...c.children].map(t=>t._tile))')
     assert rendered==lastboard,(case,rendered,lastboard)
    if case=='decode-error':assert page.evaluate('MahjongReels.diagnostics().errors.length')>=1, 'Expected recorded decode fallback'
    if case=='winning-cascade':assert qa['shards']>=9, 'Visible shard animation did not run: '+str(qa)
    assert verify_round(session.last_round,session.cfg)['valid']
    assert not errors,errors
    page.evaluate('cancelAnimationFrame(window.reelSampleFrame)')
    report['cases'].append({'case':case,'spin_requests':session.spins,'probe':qa,'motion':motion,'replay':'PASS','final_board':'retained on decode failure' if case=='decode-error' else 'MATCH'})
    print('PASS',case,flush=True)
    page.close()
   browser.close()
 finally:
  if server:server.shutdown();server.server_close()
  (OUT/f'report-{args.engine}.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({'engine':args.engine,'cases_passed':len(report['cases']),'transport':report['transport']}))
if __name__=='__main__':main()
