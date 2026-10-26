#!/usr/bin/env python3
"""Real browser/API/worker acceptance test in a disposable local Studio database."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from urllib.parse import urlsplit
import re

REPO = Path(__file__).resolve().parents[1]


def server():
    import django
    django.setup()
    from django.core.handlers.wsgi import WSGIHandler
    from django.core.servers.basehttp import run
    from game_studio import views
    views.WEB = Path(os.environ['STUDIO_QA_WEB_ROOT'])
    run('127.0.0.1', int(os.environ['STUDIO_QA_PORT']), WSGIHandler(), threading=True)


async def verify(args, base, credentials, env):
    from playwright.async_api import async_playwright
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = {'browser': args.engine, 'checks': [], 'page_errors': [], 'request_errors': []}
    def worker():
        process = subprocess.run([sys.executable, str(REPO / 'manage.py'), 'studio_worker', '--once'],
                                 cwd=REPO, env=env, capture_output=True, text=True, timeout=180)
        if process.returncode:
            raise AssertionError(process.stderr[-1500:])
    async with async_playwright() as p:
        browser = await getattr(p, args.engine).launch(headless=True, **({'args':['--no-sandbox']} if args.engine == 'chromium' else {}))
        context = await browser.new_context(viewport={'width':1440, 'height':1050}, reduced_motion='reduce')
        page = await context.new_page()
        page.on('pageerror', lambda error: results['page_errors'].append(str(error)))
        def response_seen(response):
            path=urlsplit(response.url).path
            if response.status>=400 and path!='/favicon.ico':
                path=re.sub(r'/api/preview/[^/]+','/api/preview/[redacted]',path)
                results['request_errors'].append({'status':response.status,'path':path})
        page.on('response', response_seen)
        page.set_default_timeout(20000)
        await page.goto(base + '/studio/#setup=' + credentials['token'])
        await page.get_by_label('Username', exact=True).fill(credentials['username'])
        await page.get_by_label('Password', exact=True).fill(credentials['password'])
        assert await page.evaluate('location.hash') == ''
        await page.get_by_role('button', name='Create owner & sign in', exact=True).click()
        await page.get_by_role('heading', name='Overview', exact=True).wait_for()
        results['checks'].append('one_time_setup_and_token_removed')
        await page.get_by_label('Nama draft', exact=True).fill('Browser QA candidate')
        await page.get_by_role('button', name='Create draft', exact=True).click()
        await page.wait_for_function("() => document.querySelector('[aria-label=\"Pilih draft\"]').value !== ''")
        draft_id = await page.get_by_label('Pilih draft', exact=True).input_value()
        async def read(path):
            response = await context.request.get(base+'/api/studio/'+path)
            assert response.ok, await response.text()
            return await response.json()
        async def refresh():
            await page.get_by_role('button', name='Refresh', exact=True).click()
            await page.get_by_text('Workspace diperbarui.', exact=False).wait_for()
        async def save_validate():
            if not await page.get_by_role('button', name='Save draft', exact=True).is_disabled():
                await page.get_by_role('button', name='Save draft', exact=True).click()
                await page.get_by_text('Draft tersimpan.', exact=True).wait_for()
            await page.get_by_role('button', name='Validate', exact=True).click()
            await page.get_by_text('Validasi lulus.', exact=False).wait_for()
        await page.get_by_role('button', name='Betting & Auto', exact=True).click()
        await page.get_by_label('Saldo virtual awal', exact=True).fill('1500')
        await save_validate()
        saved = await read('drafts/'+draft_id)
        assert saved['config']['bet']['initial_balance'] == '1500'
        results['checks'].append('draft_save_validation')
        await page.get_by_role('button', name='Tile Studio', exact=True).click()
        assert await page.locator('.tile-card').count() == 17
        await page.locator('.tile-card img').first.wait_for()
        await page.wait_for_function("() => Array.from(document.querySelectorAll('.tile-card img')).every(i=>i.complete&&i.naturalWidth===218)")
        await page.locator('input[type=file]').set_input_files(args.web_root/'assets/portrait-v085/tiles/A-normal.webp')
        await page.get_by_text('Upload diterima.', exact=False).wait_for()
        await asyncio.to_thread(worker)
        await refresh()
        items = (await read('assets'))['assets']
        tile = next(x for x in items if x['is_derivative'] and x['kind']=='tile')
        assert tile['metadata']['width']==218 and tile['metadata']['height']==327
        await page.get_by_label('Gambar untuk normal', exact=True).select_option(tile['id'])
        await save_validate()
        results['checks'].append('tile_upload_ingest_binding')
        await page.screenshot(path=str(output/'tile-studio.png'), full_page=True, animations='disabled')
        await page.get_by_role('button', name='Scene & Controls', exact=True).click()
        await page.locator('input[type=file]').set_input_files(args.web_root/'assets/portrait-v085/tiles/A-normal.webp')
        await page.get_by_text('Upload diterima.', exact=False).wait_for()
        await asyncio.to_thread(worker)
        await refresh()
        assert any(x['is_derivative'] and x['kind']=='scene' for x in (await read('assets'))['assets'])
        results['checks'].append('scene_upload_ready')
        await page.get_by_role('button', name='Audio Studio', exact=True).click()
        async with page.expect_response(lambda response: response.url.endswith('/api/studio/assets') and response.request.method == 'POST') as upload_response:
            await page.locator('input[type=file][accept*=".m4a"]').set_input_files(args.web_root/'assets/audio/sfx/button.wav')
        accepted = await (await upload_response.value).json()
        assert 'job' in accepted and 'asset' in accepted, accepted
        uploaded_id = accepted['asset']['id']
        await page.locator(f'[data-asset-id="{uploaded_id}"]').wait_for()
        await asyncio.to_thread(worker)
        await refresh()
        items = (await read('assets'))['assets']
        assert any(item['kind']=='audio' and item['original_id']==uploaded_id and item['is_derivative'] and item['status']=='ready' for item in items)
        # The original remains in the library even after ingest changes it
        # from queued to Ready. Browser decoding of private originals is not a
        # prerequisite for the server's Render derivative action.
        original = next(x for x in items if x['id'] == uploaded_id)
        assert original['status'] == 'ready' and not original['is_derivative']
        await page.locator(f'[data-asset-id="{uploaded_id}"]').click()
        assert await page.get_by_role('button', name='Render derivative', exact=True).is_enabled()
        results['checks'].append('ready_original_remains_visible_and_can_render')
        baseline_music='/assets/approved-v082/audio/jade_serenity.m4a'
        await page.locator(f'[data-asset-id="{baseline_music}"]').click()
        assert await page.get_by_role('button', name='Import untuk editing', exact=True).is_enabled()
        results['checks'].append('audio_upload_and_processing_visible')
        await page.get_by_role('button', name='Import untuk editing', exact=True).click()
        await page.get_by_text('Baseline diimpor.', exact=False).wait_for()
        await asyncio.to_thread(worker)
        await refresh()
        items = (await read('assets'))['assets']
        audio = next(x for x in items if x['is_derivative'] and x['kind']=='audio')
        await page.locator(f'[data-asset-id="{audio["id"]}"]').click()
        await page.get_by_role('button', name='Play', exact=True).wait_for(state='visible')
        await page.get_by_label('Gain · dB', exact=True).fill('-6')
        await page.get_by_label('Trim akhir · s', exact=True).fill('0.1')
        await page.get_by_role('button', name='Play', exact=True).click()
        await page.get_by_role('button', name='Analisis clip', exact=True).click()
        assert await page.locator('canvas.spectrogram').count()==1
        await page.get_by_role('button', name='Render derivative', exact=True).click()
        await page.get_by_text('Render masuk antrean.', exact=False).wait_for()
        await asyncio.to_thread(worker)
        await refresh()
        items = (await read('assets'))['assets']
        rendered = next(x for x in items if x['is_derivative'] and x['kind']=='audio' and x['recipe'].get('gain_db')==-6)
        assert abs(rendered['metadata']['duration']-.1)<.0001
        await page.locator(f'[data-asset-id="{rendered["id"]}"]').click()
        await page.get_by_label('Clip tap', exact=True).select_option(rendered['id'])
        await save_validate()
        assert await page.locator('.rendered-audition audio').get_attribute('src') == rendered['url']
        results['checks'].append('audio_import_recipe_render_graph_binding')
        await page.get_by_role('button', name='Background music', exact=True).click()
        await page.get_by_label('Track', exact=True).first.select_option(rendered['id'])
        await page.get_by_role('button', name='Apply base background music', exact=True).click()
        await page.get_by_text('Background music base diterapkan ke draft', exact=False).wait_for()
        saved_music=(await read('drafts/'+draft_id))['config']['audio']['music']['base']
        assert saved_music['asset']==rendered['id'], saved_music
        assert saved_music['loop_start']==0 and saved_music['loop_end'] is None, saved_music
        assert await page.get_by_role('button', name='Publish', exact=True).is_enabled()
        results['checks'].append('background_music_apply_save_validate_and_publish_ready')
        await page.get_by_label('Track', exact=True).first.select_option('')
        await page.get_by_role('button', name='Apply base background music', exact=True).click()
        await page.get_by_text('Background music base diterapkan ke draft', exact=False).wait_for()
        assert (await read('drafts/'+draft_id))['config']['audio']['music']['base'] is None
        results['checks'].append('explicit_no_background_music')
        await page.evaluate('scrollTo(0,0)')
        await page.screenshot(path=str(output/'audio-studio.png'), full_page=True, animations='disabled')
        await page.set_viewport_size({'width':390,'height':844})
        await page.wait_for_timeout(250)
        await page.screenshot(path=str(output/'audio-studio-mobile.png'), full_page=True, animations='disabled')
        assert await page.evaluate('document.documentElement.scrollWidth===document.documentElement.clientWidth')
        results['checks'].append('mobile_no_horizontal_overflow')
        await page.set_viewport_size({'width':1440,'height':1050})
        await page.get_by_role('button', name='Math Lab', exact=True).click()
        await page.get_by_label('Paid rounds', exact=True).fill('100')
        await page.get_by_role('button', name='Queue simulation', exact=True).click()
        await page.get_by_text('Simulasi masuk antrean.', exact=False).wait_for()
        await asyncio.to_thread(worker)
        await refresh()
        await page.get_by_role('heading', name='Measured outcome', exact=True).wait_for()
        report = next(x for x in (await read('jobs'))['jobs'] if x['kind']=='simulate')['result']
        assert report['rounds']==100 and report['failures']==0 and len(report['rtp_ci95_percent'])==2
        results['checks'].append('math_lab_worker_report')
        await page.get_by_role('button', name='Preview', exact=True).click()
        frame = page.frame_locator('iframe[title="Draft game preview"]')
        await frame.locator('#spin-btn').wait_for()
        await page.wait_for_function("() => document.querySelector('iframe').contentWindow.MahjongStudioRuntime?.release")
        await page.locator('iframe').evaluate("e=>e.scrollIntoView({block:'center'})")
        await frame.locator('#soft-tech-continue').click()
        await frame.locator('#soft-tech-splash').wait_for(state='hidden')
        await frame.locator('#spin-btn').click()
        await page.wait_for_function("() => Number(document.querySelector('iframe').contentDocument.querySelector('#spin-count').textContent)>=1")
        results['checks'].append('isolated_real_renderer_spin')
        await page.get_by_role('button', name='Validate', exact=True).click()
        await page.get_by_text('Validasi lulus.', exact=False).wait_for()
        await page.get_by_role('button', name='Publish', exact=True).click()
        await page.get_by_label('Alasan perubahan', exact=True).fill('Disposable browser acceptance test')
        await page.get_by_role('button', name='Publish release', exact=True).click()
        await page.get_by_text('Rilis aktif diperbarui.', exact=False).wait_for()
        assert any(r['active'] and r['name']=='Browser QA candidate' for r in (await read('releases'))['releases'])
        await page.get_by_role('button', name='Releases & History', exact=True).click()
        await page.get_by_role('button', name='Activate', exact=True).last.click()
        await page.get_by_label('Alasan perubahan', exact=True).fill('Restore disposable baseline after QA')
        await page.get_by_role('button', name='Activate release', exact=True).click()
        await page.get_by_text('Rilis aktif diperbarui.', exact=False).wait_for()
        results['checks'].append('publish_and_rollback')
        await page.get_by_role('button', name='Overview', exact=True).click()
        await page.evaluate('scrollTo(0,0)')
        await page.screenshot(path=str(output/'overview.png'), full_page=True, animations='disabled')
        assert not results['page_errors'], results['page_errors']
        assert not results['request_errors'], results['request_errors']
        (output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        await context.close(); await browser.close()
    print(json.dumps(results))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--engine',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--output',type=Path,default=REPO/'qa/studio-v090/chromium')
    parser.add_argument('--web-root',type=Path,default=REPO/'web')
    parser.add_argument('--serve',action='store_true')
    args=parser.parse_args()
    if args.serve: server();return
    args.web_root=args.web_root.resolve()
    with tempfile.TemporaryDirectory(prefix='mahjong-studio-browser-') as tmp:
        with socket.socket() as port_socket:
            port_socket.bind(('127.0.0.1',0));port=port_socket.getsockname()[1]
        credentials={'token':secrets.token_urlsafe(32),'username':'qa_owner','password':secrets.token_urlsafe(32)}
        env=os.environ.copy()
        for key in list(env):
            if key in ('DATABASE_URL','STUDIO_PRODUCTION') or key.startswith('STUDIO_S3_'):
                env.pop(key,None)
        env.update(DJANGO_SETTINGS_MODULE='studio_server.settings',PYTHONPATH=str(REPO),
                   ALLOWED_HOSTS='localhost,127.0.0.1,testserver',CSRF_TRUSTED_ORIGINS='',
                   STUDIO_SQLITE_PATH=tmp+'/db.sqlite3',STUDIO_MEDIA_ROOT=tmp+'/media',
                   STUDIO_SETUP_TOKEN=credentials['token'],DJANGO_SECRET_KEY=secrets.token_urlsafe(48),
                   STUDIO_QA_PORT=str(port),STUDIO_QA_WEB_ROOT=str(args.web_root))
        for command in (['migrate','--noinput'],['bootstrap_studio']):
            subprocess.run([sys.executable,str(REPO/'manage.py'),*command],cwd=REPO,env=env,check=True,capture_output=True)
        with open(tmp+'/server.log','w') as log:
            process=subprocess.Popen([sys.executable,__file__,'--serve'],cwd=REPO,env=env,stdout=log,stderr=log)
            base=f'http://127.0.0.1:{port}'
            try:
                for _ in range(100):
                    try:
                        with urlopen(base+'/health',timeout=1) as response:
                            if response.status==200:break
                    except Exception:time.sleep(.1)
                else:raise AssertionError('Disposable Studio did not start')
                asyncio.run(verify(args,base,credentials,env))
            except BaseException as error:
                args.output.mkdir(parents=True,exist_ok=True)
                message=str(error)
                for secret in credentials.values():message=message.replace(secret,'[redacted]')
                (args.output/'failure.json').write_text(json.dumps({'type':type(error).__name__,'message':message[:4000]},indent=2))
                raise
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill()
if __name__=='__main__':main()
