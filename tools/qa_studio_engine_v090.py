"""Real browser regression: ticket pinning, offered bet strings, retry, replay.

Always creates an isolated disposable database. No production credentials or
public deployment are used by this verifier.
"""
import argparse
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from wsgiref.simple_server import make_server, WSGIRequestHandler

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]

class Quiet(WSGIRequestHandler):
    def log_message(self,*args): pass


def assert_approved_masked_corners(page):
    """Screenshot acceptance: native-size outer tile sprites and jade in front."""
    data=page.evaluate("""() => {
      const stage=document.getElementById('game-stage');
      const board=document.getElementById('board');
      const outer=[...board.children].filter(e=>e.classList.contains('short'));
      const rect=board.getBoundingClientRect();
      const standard=board.children[1].querySelector('.tile').getBoundingClientRect();
      const corners=outer.map(e=>{
        const r=e.getBoundingClientRect();
        return {tiles:e.children.length,top:r.top,height:r.height,width:r.width,
          pseudo:['::before','::after'].map(p=>{
            const c=getComputedStyle(e,p);
            return {display:c.display,position:c.position,width:parseFloat(c.width),
               height:parseFloat(c.height),image:c.backgroundImage};
          })};
      });
      const jade=[...document.querySelectorAll('.reel-theatre > .jade-cloud-foreground')].map(e=>{
        const c=getComputedStyle(e),r=e.getBoundingClientRect();
        return {display:c.display,background:c.backgroundImage,z:parseInt(c.zIndex,10),
          width:r.width,height:r.height,pointer:c.pointerEvents};
      });
      const behind=[...document.querySelectorAll('.art-board > .mobile-ornament--cloud')]
        .map(e=>getComputedStyle(e).visibility);
      return {mode:stage.dataset.fullframe,enabled:stage.dataset.cornerReels,
        rows:[...board.children].map(e=>e.querySelectorAll(':scope > .tile').length),
        rect:{top:rect.top,height:rect.height},standard:{width:standard.width,height:standard.height},
        clip:getComputedStyle(board).clipPath,corners,jade,behind};
    }""")
    assert data['enabled']=='masked-v103',data
    master=page.evaluate("""() => ({
      mode:document.querySelector('#game-stage').dataset.masterArt,
      top:[...document.querySelectorAll('.reel-theatre > .jade-top-corner')].map(e=>({
        background:getComputedStyle(e).backgroundImage,
        display:getComputedStyle(e).display,positive:parseFloat(getComputedStyle(e).zIndex)>8
      }))
    })""")
    assert master['mode'] in ('v105-fallback','v105-locked'),master
    assert len(master['top'])==2 and all(x['positive'] for x in master['top']),master
    if data['mode'] in ('portrait','desktop'):
        assert all(x['display']!='none' and 'jade-corner-v105.svg' in x['background']
                   for x in master['top']),master
    assert data['rows']==[4,5,5,5,4],data
    assert len(data['corners'])==2,data
    if data['mode'] in ('portrait','desktop'):
        assert 'polygon(' in data['clip'],data
        assert len(data['jade'])==2 and data['behind']==['hidden','hidden'],data
        for cloud in data['jade']:
            assert cloud['display']!='none' and cloud['z']>8 and cloud['pointer']=='none',cloud
            assert 'mobile-cloud-' in cloud['background'],cloud
            assert cloud['width']>0 and cloud['height']>0,cloud
        for corner in data['corners']:
            assert corner['tiles']==4,corner
            assert abs(corner['height']/data['rect']['height']-1.2)<.013,corner
            assert abs(corner['top']-(data['rect']['top']-.1*data['rect']['height']))<2.5,corner
            for piece in corner['pseudo']:
                assert piece['display']!='none' and piece['position']=='relative',piece
                assert '/tiles/' in piece['image'] and '.webp' in piece['image'],piece
                assert abs(piece['width']-data['standard']['width'])<2, (piece,data)
                assert abs(piece['height']-data['standard']['height'])<2, (piece,data)
    return data

def assert_visible_corner_pixels(page):
    """Screen pixels, not just CSS background declarations, must show tiles."""
    from PIL import Image
    image=Image.open(io.BytesIO(page.locator('#board').screenshot())).convert('RGB')
    width,height=image.size
    radius=max(3,round(min(width/5,height/5)*.115))
    results={}
    for side,fx in [('left',.1),('right',.9)]:
        for edge,fy in [('top',.05),('bottom',.95)]:
            x=round(width*fx);y=round(height*fy)
            patch=image.crop((max(0,x-radius),max(0,y-radius),
                              min(width,x+radius),min(height,y+radius)))
            pixels=[patch.getpixel((i,j)) for j in range(patch.height)
                    for i in range(patch.width)]
            bright=sum(r>115 and g>110 and (r+g+b)/3>140
                       for r,g,b in pixels)/len(pixels)
            results[f'{side}_{edge}']=round(bright,3)
            assert bright>.30,(page.url,side,edge,round(bright,3),
                                'corner tile invisible in screenshot',image.size)
    return results

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--engine',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--output',type=Path,default=ROOT/'qa/studio-engine-v090');args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='studio-engine-qa-') as temp:
        for key in ['DATABASE_URL','STUDIO_S3_BUCKET','STUDIO_S3_ENDPOINT','STUDIO_S3_ACCESS_KEY','STUDIO_S3_SECRET_KEY']:
            os.environ.pop(key,None)
        os.environ.update(DJANGO_SETTINGS_MODULE='studio_server.settings',STUDIO_PRODUCTION='0',
            STUDIO_SQLITE_PATH=temp+'/db.sqlite3',STUDIO_MEDIA_ROOT=temp+'/media',DJANGO_SECRET_KEY=secrets.token_urlsafe(48),
            ALLOWED_HOSTS='127.0.0.1,localhost,testserver')
        import django;django.setup()
        from django.core.management import call_command
        from django.core.wsgi import get_wsgi_application
        from django.contrib.auth import get_user_model
        from game_studio.models import Draft, Round, LedgerEntry
        from game_studio.releases import active_release, validate_draft, publish, activate
        from playwright.sync_api import sync_playwright, expect
        from qa_fullframe_v086 import assert_layout,set_safe_area
        with redirect_stdout(io.StringIO()): call_command('migrate',interactive=False);call_command('bootstrap_studio')
        owner=get_user_model().objects.create_superuser('qa-owner',password=secrets.token_urlsafe(32))
        baseline=active_release()
        server=make_server('127.0.0.1',0,get_wsgi_application(),handler_class=Quiet)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        report={'engine':args.engine,'errors':[],'version':'0.9.1'}
        pool=ThreadPoolExecutor(max_workers=1)
        def db(fn,*a,**kw): return pool.submit(fn,*a,**kw).result()
        try:
            with sync_playwright() as p:
                browser=getattr(p,args.engine).launch()
                context=browser.new_context(viewport={'width':390,'height':690},reduced_motion='reduce')
                page=context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
                page.goto(base,wait_until='networkidle')
                expect(page.locator('#soft-tech-continue')).to_be_enabled(timeout=30000)
                # A transient fallback can resolve after Continue first becomes
                # enabled. Confirm the final decoded audio state, not a stale label.
                page.wait_for_function(
                    "() => document.querySelector('#soft-tech-status')?.textContent.includes('MUSIK SIAP')",
                    timeout=7000)
                # Published audio MUST be fully decoded while the splash is
                # visible, with no autoplay before the trusted Continue click.
                prepared=page.evaluate('''() => ({
                  audio:MahjongWildAudio.state,
                  live:MahjongStudioRuntime?.liveAudioRelease,
                  status:document.querySelector('#soft-tech-status').textContent,
                })''')
                assert prepared['live']==str(baseline.id),prepared
                assert prepared['audio']['musicPrepared'],prepared
                assert not prepared['audio']['unlocked'] and not prepared['audio']['musicPlaying'],prepared
                assert 'MUSIK SIAP' in prepared['status'],prepared
                page.evaluate('''() => document.querySelector('#soft-tech-continue')
                  .addEventListener('pointerdown',()=>{window.__continueAt=performance.now();},
                    {capture:true,once:true})''')
                page.locator('#soft-tech-continue').click()
                page.wait_for_function('() => window.MahjongWildAudio.state.musicPlaying',timeout=2500)
                startup=page.evaluate('''() => ({
                  started:MahjongWildAudio.state.musicStartedAt,
                  clicked:window.__continueAt,
                  musicAsset:MahjongWildAudio.state.musicAsset,
                  playing:MahjongWildAudio.state.musicPlaying,
                })''')
                assert startup['playing'] and startup['started'] is not None,startup
                assert startup['clicked'] is not None,startup
                startup_delay=startup['started']-startup['clicked']
                assert 0<=startup_delay<950,('Continue music start must be sub-second',startup,startup_delay)
                expect(page.locator('#soft-tech-splash')).to_be_hidden()
                page.wait_for_function('window.MahjongStudioRuntime?.manifest')
                original=context.request.get(base+'/api/state').json()
                assert original['manifest']['release_id']==str(baseline.id)
                assert_layout(page,390,690)
                report['masked_corner_initial']=assert_approved_masked_corners(page)
                report['corner_pixels_portrait']=assert_visible_corner_pixels(page)
                report['master_v105_portrait']=page.evaluate("""() => ({
                  mode:document.querySelector('#game-stage').dataset.masterArt,
                  header:parseFloat(getComputedStyle(document.querySelector('#game-stage'))
                    .getPropertyValue('--ff-crown-height')),
                  board:document.querySelector('#board').getBoundingClientRect().height
                })""")
                assert report['master_v105_portrait']['header']>0
                page.screenshot(path=str(args.output/f'{args.engine}-game.png'))
                # Desktop portrait-shaped cabinet reports mode "desktop".
                # Regression must capture its pixels before any game round.
                page.set_viewport_size({'width':1536,'height':960})
                page.wait_for_function("() => document.getElementById('game-stage').dataset.fullframe === 'desktop'")
                assert_layout(page,1536,960)
                report['masked_corner_desktop']=assert_approved_masked_corners(page)
                report['corner_pixels_desktop']=assert_visible_corner_pixels(page)
                page.screenshot(path=str(args.output/f'{args.engine}-desktop-1536x960.png'))
                page.set_viewport_size({'width':390,'height':690})
                page.wait_for_function("() => document.getElementById('game-stage').dataset.fullframe === 'portrait'")
                assert_layout(page,390,690)
                assert context.request.get(base+'/api/studio/assets').status==401
                config=deepcopy(baseline.config)
                config['bet'].update(options=['1.0','2.50'],default='1.0',initial_balance='1500')
                config['audio']['output_gain']=1.1
                draft=db(Draft.objects.create,name='Browser regression',config=config,base_release=baseline,created_by=owner)
                assert db(validate_draft,draft)['valid'];release=db(publish,draft,owner,'Browser integration check')
                pinned=context.request.get(base+'/api/state').json()
                assert pinned['ticket']['id']==original['ticket']['id']
                # Music adopts published audio without spending the old ticket.
                public_audio=context.request.get(base+'/api/audio-live')
                assert public_audio.status==200 and public_audio.json()['release_id']==str(release.id)
                page.wait_for_function('(id)=>window.MahjongStudioRuntime?.liveAudioRelease===id',
                    arg=str(release.id),timeout=25000)
                assert page.evaluate('MahjongWildAudio.state.outputGain')==1.1
                assert context.request.get(base+'/api/state').json()['ticket']['id']==original['ticket']['id']
                with page.expect_response(lambda r:r.url==base+'/api/spin') as response:
                    page.locator('#spin-btn').click()
                first=response.value.json();request=response.value.request.post_data_json
                assert response.value.status==200,first
                assert request['ticket_id']==original['ticket']['id']
                assert first['round_release_id']==str(baseline.id)
                assert first['state']['manifest']['release_id']==str(release.id)
                expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin',timeout=60000)
                page.wait_for_function('(id)=>window.MahjongStudioRuntime.release===id',arg=str(release.id))
                assert page.evaluate('MahjongWildAudio.state.outputGain')==1.1
                headers={'X-ML-Request':'local-demo','Origin':base}
                duplicate=context.request.post(base+'/api/spin',data=request,headers=headers)
                assert duplicate.status==200 and duplicate.json()==first
                assert db(Round.objects.count)==1 and db(lambda:LedgerEntry.objects.filter(kind='round').count())==1
                verified=context.request.post(base+'/api/verify',data={'round':first['round']},headers=headers)
                assert verified.status==200 and verified.json()['valid']
                # The next UI request preserves the offered decimal string exactly.
                with page.expect_response(lambda r:r.url==base+'/api/spin') as response:
                    page.locator('#spin-btn').click()
                second=response.value.json()
                assert response.value.request.post_data_json['bet']=='1.0',response.value.request.post_data_json
                assert response.value.status==200,second
                expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin',timeout=60000)
                # Existing new-version ticket survives rollback; following one adopts baseline.
                current=context.request.get(base+'/api/state').json();db(activate,baseline,owner,'Rollback regression')
                assert context.request.get(base+'/api/state').json()['ticket']['id']==current['ticket']['id']
                assert context.request.get(base+'/api/audio-live').json()['release_id']==str(baseline.id)
                page.wait_for_function('(id)=>window.MahjongStudioRuntime?.liveAudioRelease===id',
                    arg=str(baseline.id),timeout=25000)
                assert page.evaluate('MahjongWildAudio.state.outputGain')==1.3
                with page.expect_response(lambda r:r.url==base+'/api/spin') as response: page.locator('#spin-btn').click()
                third=response.value.json();assert third['round_release_id']==str(release.id)
                assert third['state']['manifest']['release_id']==str(baseline.id)
                expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin',timeout=60000)
                before=third['state']['balance'];page.reload(wait_until='networkidle')
                assert context.request.get(base+'/api/state').json()['balance']==before
                # Reload opens the splash again: a gameplay QA screenshot must
                # deliberately dismiss it using the normal trusted gesture.
                expect(page.locator('#soft-tech-continue')).to_be_enabled(timeout=30000)
                page.locator('#soft-tech-continue').click()
                expect(page.locator('#soft-tech-splash')).to_be_hidden(timeout=10000)
                # Native-safe-area simulation keeps the new interactive footer clear.
                page.set_viewport_size({'width':390,'height':844});set_safe_area(page,59,34)
                assert_layout(page,390,844,59,34)
                report['masked_corner_pwa']=assert_approved_masked_corners(page)
                report['corner_pixels_pwa']=assert_visible_corner_pixels(page)
                page.screenshot(path=str(args.output/f'{args.engine}-pwa-390x844.png'))
                assert not report['errors'],report['errors']
                report.update(result='PASS',ticket_pinning=True,offered_decimal_strings=True,idempotent_retry=True,
                    rollback=True,replay=True,persistent_cookie_balance=True,accepted_rounds=3,
                    music_predecoded_before_continue=True,music_start_delay_ms=round(startup_delay,2),
                    ledger_rounds=db(lambda:LedgerEntry.objects.filter(kind='round').count()))
                browser.close()
        finally:
            server.shutdown();server.server_close()
            pool.shutdown()
        (args.output/f'{args.engine}.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))

if __name__=='__main__': main()
