"""Native browser layout/round checks. Safe-area insets are simulated, not an iPhone certification."""
from pathlib import Path
import argparse,json,sys,threading
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from mahjong_legend.server import DemoSession,make_server
from mahjong_legend.engine import verify_round
from playwright.sync_api import sync_playwright,expect
OUT=ROOT/'qa/fullframe-v086'
MEASURE='''()=>{
 const node=s=>typeof s==='string'?document.querySelector(s):s;
 const r=s=>{const b=node(s).getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height,right:b.right,bottom:b.bottom};};
 const paint=(e,pseudo)=>{const c=getComputedStyle(e,pseudo);return {image:c.backgroundImage.includes('url('),size:c.backgroundSize,visible:c.display!=='none'&&c.visibility==='visible'&&Number(c.opacity)>0};};
 const pseudo=(e,which)=>{
   const c=getComputedStyle(e,which),parent=r(e),fixed=c.position==='fixed';
   const pw=fixed?innerWidth:parent.w,ph=fixed?innerHeight:parent.h;
   const number=v=>Number.isFinite(parseFloat(v))?parseFloat(v):null;
   const left=number(c.left),right=number(c.right),top=number(c.top),bottom=number(c.bottom);
   const width=number(c.width)??Math.max(0,pw-(left??0)-(right??0));
   const height=number(c.height)??Math.max(0,ph-(top??0)-(bottom??0));
   const x=(fixed?0:parent.x)+(left??pw-(right??0)-width);
   const y=(fixed?0:parent.y)+(top??ph-(bottom??0)-height);
   return {x,y,w:width,h:height,right:x+width,bottom:y+height,...paint(e,which),active:c.content!=='none'&&c.content!=='normal'};
 };
 const art=document.querySelector('.fullframe-art'),root=document.documentElement,body=document.body,view=visualViewport;
 return {
   stage:{...r('#game-stage'),...paint(node('#game-stage')),mode:node('#game-stage').dataset.fullframe},board:r('#board'),notice:r('.announcement'),meters:r('.credits-strip'),controls:r('.play-controls'),logo:r('.logo-fx'),disk:r('.spin-disk'),
   tiles:[...document.querySelectorAll('#board .tile')].map(e=>{const b=e.getBoundingClientRect();return b.width/b.height;}),
   buttons:['menu-btn','sound-btn','turbo-btn','minus-btn','spin-btn','plus-btn','auto-btn'].map(id=>r('#'+id)),
   overflow:[root.scrollWidth-innerWidth,root.scrollHeight-innerHeight],
   viewport:{layoutWidth:innerWidth,layoutHeight:innerHeight,clientWidth:root.clientWidth,clientHeight:root.clientHeight,visualWidth:view?.width??innerWidth,visualHeight:view?.height??innerHeight,standalone:matchMedia('(display-mode: standalone)').matches||!!navigator.standalone},
   root:{...r(root),...paint(root)},body:{...r(body),...paint(body)},backdrop:pseudo(body,'::before'),
   art:{container:{...r(art),...paint(art)},before:pseudo(art,'::before'),after:pseudo(art,'::after'),
     bands:[...art.querySelectorAll(':scope > i')].map(e=>({name:e.className,...r(e),...paint(e),parts:[...e.children].filter(p=>getComputedStyle(p).display!=='none').map(p=>({...r(p),...paint(p)}))}))}
 };
}'''

def assert_artwork_coverage(g):
    """Require real artwork coverage, not only a viewport-sized empty stage."""
    stage=g['stage'];art=g['art'];viewport=g['viewport'];epsilon=.6
    def covers(outer,inner):
        return (outer['x']<=inner['x']+epsilon and outer['y']<=inner['y']+epsilon
                and outer['right']>=inner['right']-epsilon and outer['bottom']>=inner['bottom']-epsilon)
    # Root backing fills the CSS/layout viewport even when browser chrome makes
    # the visual viewport smaller, and fills side regions in landscape.
    screen={'x':0,'y':0,'right':viewport['layoutWidth'],'bottom':viewport['layoutHeight']}
    assert g['root']['visible'] and g['body']['visible'] and covers(g['root'],screen) and covers(g['body'],screen),g
    assert g['root']['image'] and g['root']['size']=='cover',g['root']
    assert any(layer['visible'] and layer['image'] and covers(layer,screen)
               for layer in (g['root'],g['body'],g['backdrop'])),g
    assert stage['visible'] and art['container']['visible'] and covers(art['container'],stage),art
    assert [band['name'] for band in art['bands']]==[
        'art-crown','art-rail','art-board','art-hud','art-controls'],art
    if stage.get('mode')=='landscape':
        # Landscape gives the console its own full-size side panel. Check both
        # painted regions rather than demanding a squeezed portrait stack.
        crown,rail,board,hud,controls=art['bands']
        cursor=stage['y']
        for band in [art['before'],crown,rail,board]:
            assert abs(band['y']-cursor)<=epsilon,(cursor,band)
            assert band['x']<=stage['x']+epsilon and abs(band['right']-crown['right'])<=epsilon,band
            assert band['visible'] and (band['h']<=.01 or band['image'] or band.get('parts')),band
            cursor=band['bottom']
        panel=art['after']
        assert panel['visible'] and panel['image'] and panel['active'],panel
        assert abs(panel['x']-crown['right'])<=epsilon and abs(panel['right']-stage['right'])<=epsilon,panel
        assert abs(panel['y']-stage['y'])<=epsilon and abs(panel['bottom']-stage['bottom'])<=epsilon,panel
        assert abs(hud['bottom']-controls['y'])<=epsilon,(hud,controls)
        for band in [hud,controls]:
            assert band['visible'] and band['image'] and covers(panel,band),band
        return
    cursor=stage['y']
    for band in [art['before'],*art['bands'],art['after']]:
        assert abs(band['y']-cursor)<=epsilon,(cursor,band)
        assert band['h']>=-.01 and band['x']<=stage['x']+epsilon and band['right']>=stage['right']-epsilon,band
        if band['h']>.01:
            assert band['visible'],band
            parts=band.get('parts',[])
            if parts:
                assert len(parts)==3,band
                edge=band['x']
                for part in parts:
                    assert part['visible'] and part['image'] and part['w']>.01,part
                    assert abs(part['x']-edge)<=epsilon and abs(part['y']-band['y'])<=epsilon and abs(part['bottom']-band['bottom'])<=epsilon,(band,part)
                    edge=part['right']
                assert abs(edge-band['right'])<=epsilon,band
            else:
                assert band['image'] and band.get('active',True),band
        cursor=band['bottom']
    assert abs(cursor-stage['bottom'])<=epsilon,(cursor,stage)

def assert_background_images(page):
    """Decode every CSS artwork/background image, including pseudo-elements."""
    decoded=page.evaluate('''async()=>{
      const entries=[[document.documentElement,null,'root'],[document.body,null,'body'],[document.body,'::before','backdrop']];
      const art=document.querySelector('.fullframe-art');
      entries.push([art,'::before','top-extension'],[art,'::after','bottom-extension']);
      for(const e of art.querySelectorAll('i,b')){
        const label=e.className||e.parentElement.className+'-part';
        entries.push([e,null,label],[e,'::before',label+'-before'],[e,'::after',label+'-after']);
      }
      const jobs=[];
      for(const [e,pseudo,label] of entries){
        const value=getComputedStyle(e,pseudo).backgroundImage;
        for(const match of value.matchAll(/url\\((?:"([^"]+)"|'([^']+)'|([^)]*))\\)/g)){
          const src=match[1]||match[2]||match[3];
          jobs.push((async()=>{const image=new Image();image.src=src;try{await image.decode();return {label,ok:image.complete&&image.naturalWidth>0&&image.naturalHeight>0,width:image.naturalWidth,height:image.naturalHeight};}catch(error){return {label,ok:false,error:String(error)};}})());
        }
      }
      return Promise.all(jobs);
    }''')
    # Count is not a visual contract: independent native controls deliberately
    # retire three baked button strips. Every referenced image must decode.
    assert decoded and all(item['ok'] for item in decoded),decoded
    return decoded

def assert_control_hits(page):
    hits=page.evaluate('''()=>['menu-btn','sound-btn','turbo-btn','minus-btn','spin-btn','plus-btn','auto-btn'].map(id=>{
      const e=document.getElementById(id),r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
      return {id,ok:!!hit&&(hit===e||e.contains(hit))};
    })''')
    assert all(hit['ok'] for hit in hits),hits

def install_viewport_fixture(page,standalone,visual_height,offline=False):
    """Contract simulation only: retain a real layout viewport and vary VV."""
    script='''(()=>{
      if(window.__ffViewportFixture)return;
      const standalone=STANDALONE,view=new EventTarget(),media=new EventTarget();
      Object.assign(view,{height:VISUAL_HEIGHT,scale:1,offsetLeft:0,offsetTop:0,pageLeft:0,pageTop:0});
      Object.defineProperty(view,'width',{get:()=>innerWidth});
      Object.defineProperty(media,'matches',{get:()=>standalone});media.media='(display-mode: standalone)';
      media.addListener=f=>media.addEventListener('change',f);media.removeListener=f=>media.removeEventListener('change',f);
      const nativeMatch=window.matchMedia.bind(window);
      window.matchMedia=q=>q==='(display-mode: standalone)'?media:nativeMatch(q);
      Object.defineProperty(navigator,'standalone',{configurable:true,get:()=>standalone});
      Object.defineProperty(window,'visualViewport',{configurable:true,get:()=>view});
      window.__ffViewportFixture={setHeight:(height,emit=true)=>{view.height=height;if(emit)view.dispatchEvent(new Event('resize'));}};
    })();'''.replace('STANDALONE',json.dumps(standalone)).replace('VISUAL_HEIGHT',str(visual_height))
    page.add_init_script(script)
    if offline:page.evaluate(script)

def set_safe_area(page,top,bottom,left=0,right=0):
    page.locator('#game-stage').evaluate('''(e,insets)=>{
      for(const [edge,value] of Object.entries(insets))e.style.setProperty('--ff-safe-'+edge,value+'px');
      MahjongViewport.refresh();
    }''',{'top':top,'bottom':bottom,'left':left,'right':right})
    page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')

def assert_layout(page,w,h,top=0,bottom=0,left=0,right=0):
    g=page.evaluate(MEASURE);s=g['stage']
    assert abs(s['h']-h)<1,(w,h,g)
    assert s['x']>=-.5 and s['y']>=-.5 and s['right']<=w+.5 and s['bottom']<=h+.5,(w,h,g)
    if w<=h:assert abs(s['x'])<.5 and abs(s['w']-w)<.5,(w,h,g)
    if w>=1000 and h>=620:
        # One centered scene must contain the crown, reel board, banner,
        # meters and all five controls, never separate them across the monitor.
        assert s['mode']=='desktop',(w,h,g)
        assert 350<=s['w']<=640.5 and s['w']<w*.8,(w,h,g)
        assert abs(s['x']+s['w']/2-w/2)<.6,(w,h,g)
        assert g['board']['w']>=200 and g['board']['x']>=s['x']-.5 and g['board']['right']<=s['right']+.5,(w,h,g)
        assert g['notice']['x']>=s['x']-.5 and g['notice']['right']<=s['right']+.5,(w,h,g)
        assert g['controls']['x']>=s['x']-.5 and g['controls']['right']<=s['right']+.5,(w,h,g)
    assert max(g['overflow'])<=1,g
    assert len(g['tiles'])==23 and all(abs(v-2/3)<.002 for v in g['tiles']),g
    if s.get('mode')=='landscape':
        assert g['board']['right']<=g['notice']['x']+.5,g
    else:
        assert g['board']['bottom']<=g['notice']['y']+.5,g
    assert g['notice']['bottom']<=g['meters']['y']+.5,g
    assert g['meters']['bottom']<=g['controls']['y']+.5,g
    assert g['controls']['bottom']<=h-bottom+.6,g
    assert all(b['y']>=top-.5 and b['bottom']<=h-bottom+.6 and b['x']>=left-.5 and b['right']<=w-right+.6 for b in g['buttons']),g
    assert all(min(b['w'],b['h'])>=8 for b in g['buttons']),g['buttons']
    assert all(min(b['w'],b['h'])>=43.99 for b in g['buttons'][2:]),g['buttons']
    assert min(g['disk']['w'],g['disk']['h'])>=16,g['disk']
    assert abs(g['disk']['w']/g['disk']['h']-1)<.02,g['disk']
    assert abs(g['logo']['w']/g['logo']['h']-358/135)<.03,g['logo']
    for a,b in zip(g['buttons'][2:],g['buttons'][3:]):assert a['right']<=b['x']+.6,(a,b)
    assert_artwork_coverage(g)
    return g

def assert_reel_order(motion,events,allow_interrupted=False):
    """A viewport resize may retire an animation before every reel starts.

    All five reels must still settle exactly once. The caller separately checks
    accepted spin count, final engine board and replay. Uninterrupted animations
    retain the original complete left-to-right start/stop requirement.
    """
    expected=[1,2,3,4,5]
    assert motion['completed'] and motion['stops']==expected,motion
    starts=motion['starts']
    assert starts and starts==expected[:len(starts)],motion
    assert allow_interrupted or not motion['cancelled'],motion
    if not allow_interrupted or not motion['cancelled']:
        assert starts==expected,motion
    start_events=[e for e in events if e['phase']=='start']
    stop_events=[e for e in events if e['phase']=='stop']
    if allow_interrupted:
        # A pending decorative loop can be retired and restarted at column 1.
        # Within either presentation pass starts remain sequential and unique.
        previous=0
        for event in start_events:
            column=event['column']
            assert column==1 or column==previous+1,events
            assert column in expected,events
            previous=column
        assert start_events,events
        assert [e['column'] for e in stop_events]==expected,events
    else:
        # Repeated-spin QA includes more than one complete event sequence.
        assert [e['column'] for e in start_events[:5]]==expected,events
        assert [e['column'] for e in stop_events[:5]]==expected,events
    assert all(b['at']>=a['at'] for a,b in zip(start_events,start_events[1:])),events

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--offline',action='store_true');ap.add_argument('--browser');ap.add_argument('--engine',default='chromium',choices=['chromium','webkit']);args=ap.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);server=None;session=DemoSession();session.seed=f'{2:064x}'
    if not args.offline:
        server=make_server(port=0,session=session);threading.Thread(target=server.serve_forever,daemon=True).start()
    report={'ui':'0.8.7','engine':args.engine,'transport':'offline embedded assets + real Python engine' if args.offline else 'HTTP + CSP','layouts':[],'page_errors':[],'physical_iphone_tested':False}
    try:
      with sync_playwright() as p:
        b=getattr(p,args.engine).launch(headless=True,**({'executable_path':args.browser} if args.browser else {}))
        def start(w,h,standalone=None,visual_height=None):
            nonlocal session
            page=b.new_page(viewport={'width':w,'height':h},is_mobile=True,has_touch=True,device_scale_factor=2)
            errors=[]
            def record_error(error):
                errors.append(str(error))
                report['page_errors'].append({'viewport':[w,h],'message':str(error)})
            page.on('pageerror',record_error)
            if standalone is not None:
                install_viewport_fixture(page,standalone,visual_height,offline=args.offline)
            if args.offline:
                from local_preview import offline
                session=offline(page,seed=2)
            else:
                session.reset();session.seed=f'{2:064x}';page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
            expect(page.locator('#soft-tech-continue')).to_be_enabled(timeout=20000);page.locator('#soft-tech-continue').click();expect(page.locator('#soft-tech-splash')).to_be_hidden()
            page.wait_for_timeout(80)
            assert_background_images(page)
            assert not errors,errors
            return page,errors
        for w,h in [(320,568),(360,640),(390,690),(390,844),(430,932),(768,768),(768,1024),(844,390),
                    (1024,768),(1280,800),(1536,864),(1920,1080)]:
            print('LAYOUT',w,h,flush=True);page,errors=start(w,h);g=assert_layout(page,w,h)
            if (w,h) in [(390,690),(390,844),(1024,768),(1536,864),(1920,1080)]:
                page.screenshot(path=str(OUT/f'{args.engine}-{w}x{h}.png'))
            if w>=1000 and h>=620:assert_control_hits(page)
            assert not errors,errors
            report['layouts'].append({'viewport':[w,h],'stage':g['stage'],'ratio_range':[min(g['tiles']),max(g['tiles'])],'artwork_coverage':'PASS','background_decode':'PASS','overlap':False,'errors':errors})
            page.close()
        print('SAFE AREA',flush=True);page,errors=start(390,844)
        set_safe_area(page,59,34,12,24);g=assert_layout(page,390,844,59,34,12,24)
        assert_control_hits(page)
        page.screenshot(path=str(OUT/f'{args.engine}-safe-area.png'))
        assert not errors,errors
        report['simulated_safe_area']={'top':59,'bottom':34,'left':12,'right':24,'stage':g['stage'],'controls':g['controls'],'artwork_coverage':'PASS','errors':errors}
        page.close()
        print('SQUARE SAFE AREA',flush=True);page,errors=start(768,768)
        set_safe_area(page,59,34,12,24);g=assert_layout(page,768,768,59,34,12,24)
        assert_control_hits(page)
        report['square_safe_area']={'viewport':[768,768],'stage':g['stage'],'control_min_size':min(min(button['w'],button['h']) for button in g['buttons']),'artwork_coverage':'PASS','errors':errors}
        assert not errors,errors
        page.close()
        print('BROWSER VISUAL VIEWPORT',flush=True);page,errors=start(390,844,standalone=False,visual_height=690)
        set_safe_area(page,20,20,12,24);g=assert_layout(page,390,690,20,20,12,24)
        assert g['viewport']['layoutHeight']==844 and g['viewport']['visualHeight']==690 and g['viewport']['visualWidth']==390 and not g['viewport']['standalone'],g['viewport']
        assert_control_hits(page)
        report['simulated_browser_viewport']={'layout':[390,844],'visual':[390,690],'stage':g['stage'],'root':g['root'],'artwork_coverage':'PASS','errors':errors}
        assert not errors,errors
        page.close()
        print('STANDALONE RESTORE',flush=True);page,errors=start(390,844,standalone=True,visual_height=751)
        set_safe_area(page,59,34,12,24);g=assert_layout(page,390,844,59,34,12,24)
        assert g['viewport']['layoutHeight']==844 and g['viewport']['visualHeight']==751 and g['viewport']['visualWidth']==390 and g['viewport']['standalone'],g['viewport']
        assert_control_hits(page)
        page.evaluate('''()=>{window.ffResumeProbe={requests:0};const original=window.fetch;window.fetch=(input,options)=>{const url=input instanceof Request?input.url:String(input);if(url.includes('/api/spin'))ffResumeProbe.requests++;return original(input,options);};}''')
        page.locator('#spin-btn').click();expect(page.locator('.reel-canvas').first).to_be_visible()
        page.evaluate('''()=>{
          dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}));
          __ffViewportFixture.setHeight(690,false);
          const stage=document.getElementById('game-stage');stage.style.setProperty('--ff-safe-left','24px');stage.style.setProperty('--ff-safe-right','12px');
          dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));
        }''')
        page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        g=assert_layout(page,390,844,59,34,24,12)
        assert_background_images(page)
        expect(page.locator('#spin-count')).to_have_text('1',timeout=60000);expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
        assert page.evaluate('ffResumeProbe.requests')==1 and session.spins==1
        assert verify_round(session.last_round,session.cfg)['valid']
        assert_control_hits(page)
        # Repeated unchanged pageshow must retain paint and remain a no-op for
        # gameplay. The fixture represents an underreported standalone VV, not
        # an on-screen keyboard and not a physical iPhone background/resume test.
        page.evaluate("dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
        page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        g=assert_layout(page,390,844,59,34,24,12)
        assert page.evaluate('ffResumeProbe.requests')==1 and not errors,(errors,g)
        page.screenshot(path=str(OUT/f'{args.engine}-standalone-restored.png'))
        report['simulated_standalone_resume']={'layout':[390,844],'initial_visual':[390,751],'restored_visual':[390,690],'stage':g['stage'],'safe_area':{'top':59,'bottom':34,'left':24,'right':12},'artwork_coverage':'PASS','background_decode':'PASS','spin_requests':1,'replay':'PASS','errors':errors,'physical_device':False}
        page.close()
        print('RESIZE SPIN',flush=True);page,errors=start(390,690)
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
        assert not errors,errors
        b.close()
    finally:
        if server:server.shutdown();server.server_close()
        (OUT/f'report-{args.engine}.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
