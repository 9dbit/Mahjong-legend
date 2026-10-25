"""Measure real tile geometry and input-to-motion under delayed results.

HTTP is the default; offline mode only adapts transport for sandbox policy.
No animation pauses, fake outcomes, or app-side image decoding by the test.
"""
from pathlib import Path
import argparse, io, json, sys, threading
from PIL import Image
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from mahjong_legend.server import DemoSession, make_server
from mahjong_legend.engine import verify_round
OUT=ROOT/'qa/portrait-v085'

PROBE=r'''() => {
 window.inputQA={inputAt:null,firstMovedMs:null,requests:0,responseAt:null,events:[],maxCanvases:0,missing:0,active:true};
 const q=window.inputQA,button=document.querySelector('#spin-btn'),nativeFetch=window.fetch.bind(window);
 button.addEventListener('pointerdown',()=>{if(q.inputAt===null)q.inputAt=performance.now();},{capture:true});
 document.addEventListener('mahjong:reel',e=>q.events.push(e.detail));
 window.fetch=async(url,options)=>{
   if(String(url).includes('/api/spin')){
     q.requests++; await new Promise(r=>setTimeout(r,1800));
     const result=await nativeFetch(url,options); q.responseAt=performance.now(); return result;
   }return nativeFetch(url,options);
 };
 const origins=new WeakMap();
 const tick=()=>{
   if(!q.active)return;
   const cs=[...document.querySelectorAll('.reel-canvas')];q.maxCanvases=Math.max(q.maxCanvases,cs.length);
   for(const c of cs){
     const tr=getComputedStyle(c).transform;
     if(!origins.has(c))origins.set(c,tr);
     else if(tr!==origins.get(c)&&q.firstMovedMs===null&&q.inputAt!==null)q.firstMovedMs=performance.now()-q.inputAt;
   }
   const im=[...document.querySelectorAll('#board > .reel > .tile > .tile-image')];
   if(im.length!==23||im.some(i=>!i.complete||i.naturalWidth===0))q.missing++;
   requestAnimationFrame(tick);
 };requestAnimationFrame(tick);
}'''

def board(page):
    return page.locator('#board').evaluate('(b)=>[...b.children].map(c=>[...c.children].filter(t=>t._tile).map(t=>t._tile))')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--offline',action='store_true');ap.add_argument('--browser');ap.add_argument('--engine',default='chromium');args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    session=DemoSession();session.seed=f'{2:064x}'
    server=None
    if not args.offline:
        server=make_server(port=0,session=session);threading.Thread(target=server.serve_forever,daemon=True).start()
    report={'release':'0.8.5','engine':args.engine,'transport':'offline embedded assets, real Python outcomes' if args.offline else 'HTTP + CSP','layouts':[]}
    try:
        with sync_playwright() as p:
            browser=getattr(p,args.engine).launch(headless=True,**({'executable_path':args.browser} if args.browser else {}))
            def start(width=390,height=844):
                nonlocal session
                page=browser.new_page(viewport={'width':width,'height':height},device_scale_factor=2,is_mobile=True,has_touch=True,service_workers='block')
                if args.offline:
                    from local_preview import offline
                    session=offline(page,seed=2)
                else:
                    session.reset();session.seed=f'{2:064x}'
                    page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
                expect(page.locator('#soft-tech-continue')).to_be_enabled(timeout=20000)
                page.locator('#soft-tech-continue').click();expect(page.locator('#soft-tech-splash')).to_be_hidden()
                return page
            for w,h in [(320,568),(390,844),(430,932),(844,390)]:
                print("LAYOUT",w,h,flush=True);page=start(w,h)
                metrics=page.evaluate('''()=>{
                  const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,bottom:r.bottom};};
                  return {tiles:[...document.querySelectorAll('#board .tile')].map(rect),board:rect(document.querySelector('#board')),notice:rect(document.querySelector('.announcement')),meters:rect(document.querySelector('.credits-strip')),controls:rect(document.querySelector('.play-controls')),x2:getComputedStyle(document.querySelector('.mult[data-value="2"] img')).filter,overflow:document.documentElement.scrollWidth-innerWidth};
                }''')
                assert len(metrics['tiles'])==23
                ratios=[t['w']/t['h'] for t in metrics['tiles']]
                assert all(abs(v-2/3)<.002 for v in ratios),ratios
                assert metrics['board']['bottom']<metrics['notice']['y']
                assert metrics['notice']['bottom']<metrics['meters']['y']
                assert metrics['meters']['bottom']<metrics['controls']['y']
                assert metrics['controls']['bottom']<=h+1,metrics
                assert metrics['overflow']<=1
                assert 'brightness(1.65)' in metrics['x2'],metrics['x2']
                report['layouts'].append({'viewport':[w,h],'ratio_range':[min(ratios),max(ratios)],'overlap':False})
                if w==390:page.screenshot(path=str(OUT/f'{args.engine}-idle.png'))
                page.close()
            print("DELAYED INPUT",flush=True);page=start();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.evaluate(PROBE)
            page.locator('#spin-btn').click()
            page.wait_for_timeout(650)
            early=page.evaluate('JSON.parse(JSON.stringify(inputQA))')
            assert early['requests']==1,early
            assert early['responseAt'] is None,'Response arrived before delayed-input observation'
            assert early['firstMovedMs'] is not None and early['firstMovedMs']<200,early
            assert early['missing']==0 and early['maxCanvases']<=5,early
            boxes=page.locator('#board > .reel').evaluate_all('(els)=>els.map(e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})')
            png=page.screenshot(path=str(OUT/f'{args.engine}-waiting-moving.png'))
            im=Image.open(io.BytesIO(png)).convert('RGB');scale=im.width/390
            coverage=[]
            for r in boxes:
                crop=im.crop(tuple(round(v*scale) for v in (r['x']+r['w']*.15,r['y'],r['x']+r['w']*.85,r['y']+r['h'])))
                pixels=list(crop.getdata());fraction=sum((g>90 and r>110) for r,g,b in pixels)/len(pixels)
                assert fraction>.65,('Painted ceramic coverage too low',fraction)
                coverage.append(round(fraction,3))
            print('WAIT SETTLED',page.locator('#stage-notice').inner_text(),flush=True);expect(page.locator('#spin-count')).to_have_text('1',timeout=45000)
            expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
            qa=page.evaluate('inputQA.active=false;JSON.parse(JSON.stringify(inputQA))')
            motion=page.evaluate('MahjongReels.diagnostics()')
            assert qa['requests']==1 and session.spins==1
            assert motion['starts']==motion['stops']==[1,2,3,4,5],motion
            assert motion['completed'] and not motion['cancelled'],motion
            assert not errors,errors
            expected=None
            for e in session.last_round['events']:
                if e['type']=='screen_start':expected=e['board']
                elif e['type']=='cascade':expected=e.get('after') or e['before']
            assert board(page)==expected
            assert verify_round(session.last_round,session.cfg)['valid']
            report['delayed_response']={'first_motion_ms':round(qa['firstMovedMs'],2),'network_delay_ms':1800,'requests':qa['requests'],'missing_frames':qa['missing'],'painted_coverage':coverage,'motion':motion,'final_board':'MATCH','replay':'PASS'}
            page.close()
            # Skip before the response: consume exactly the accepted request once.
            print("SKIP PENDING",flush=True);page=start();page.evaluate(PROBE);page.locator('#spin-btn').click();page.wait_for_timeout(120);page.locator('#spin-btn').click()
            print('WAIT SETTLED',page.locator('#stage-notice').inner_text(),flush=True);expect(page.locator('#spin-count')).to_have_text('1',timeout=45000)
            expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
            assert session.spins==1 and page.evaluate('inputQA.requests')==1
            assert page.locator('.reel-canvas').count()==0
            report['skip_pending']={'requests':1,'surfaces_after':0};page.close()
            # Rejected request restores the last visible board, without rebetting.
            print("REJECT",flush=True);page=start();before=board(page)
            page.evaluate('''()=>{const f=window.fetch.bind(window);window.rejected=0;window.fetch=async(u,o)=>{if(String(u).includes('/api/spin')){window.rejected++;await new Promise(r=>setTimeout(r,400));return new Response(JSON.stringify({error:'TEST_REJECTED'}),{status:503});}return f(u,o);};}''')
            page.locator('#spin-btn').click();expect(page.locator('#stage-notice')).to_have_text('TEST_REJECTED',timeout=10000)
            expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
            assert board(page)==before and session.spins==0 and page.evaluate('rejected')==1
            assert page.locator('.reel-canvas').count()==0
            report['rejected_request']={'retry_count':0,'original_board':'RETAINED'};page.close();browser.close()
    finally:
        if server:server.shutdown();server.server_close()
        (OUT/f'report-{args.engine}.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
