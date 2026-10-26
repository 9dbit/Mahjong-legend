"""Verify the visible, full-size console and actual game button interactions."""
from pathlib import Path
import argparse
import json
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from mahjong_legend.server import DemoSession, make_server
from playwright.sync_api import sync_playwright, expect
from qa_fullframe_v086 import assert_layout, assert_control_hits, assert_background_images, set_safe_area


def assert_footer_assets(page):
    """Decode the real painted controls and require the approved artwork sources."""
    decoded = page.evaluate(r'''async () => {
        const entries = [
            ['panel', document.querySelector('.art-controls')],
            ['announcement', document.querySelector('.announcement')],
            ...[...document.querySelectorAll('.credits-strip .meter')].map((e, i) => ['meter-' + i, e]),
            ...['turbo-btn','minus-btn','spin-btn','plus-btn','auto-btn'].map(id => [id, document.getElementById(id)])
        ];
        const jobs = [];
        const decode = async (element, pseudo, src) => {
            const url = new URL(src, location.href), image = new Image();
            image.src = url.href;
            try {
                await image.decode();
                return {element, pseudo, path:url.pathname, url:url.href,
                    ok:image.complete && image.naturalWidth > 0 && image.naturalHeight > 0,
                    width:image.naturalWidth, height:image.naturalHeight};
            } catch (error) {
                return {element, pseudo, path:url.pathname, url:url.href, ok:false, error:String(error)};
            }
        };
        for (const [label, element] of entries) {
            for (const pseudo of [null, '::before', '::after']) {
                const value = getComputedStyle(element, pseudo).backgroundImage;
                for (const match of value.matchAll(/url\((?:"([^"]+)"|'([^']+)'|([^)]*))\)/g)) {
                    jobs.push(decode(label, pseudo, match[1] || match[2] || match[3]));
                }
            }
        }
        const disk = document.querySelector('#spin-btn .spin-disk');
        jobs.push(decode('spin-disk', null, disk.currentSrc || disk.src));
        return Promise.all(jobs);
    }''')
    assert decoded and all(asset['ok'] for asset in decoded), decoded
    expected = {'panel':'/assets/control-panel-v091/stage-clean.webp',
                'spin-disk':'/assets/approved-v082/spin-disc.webp'}
    for element in ['announcement', 'meter-0', 'meter-1', 'meter-2',
                    'turbo-btn', 'minus-btn', 'plus-btn', 'auto-btn']:
        expected[element] = '/assets/approved-v082/frame.webp'
    for element, path in expected.items():
        pseudo = '::after' if element in {'turbo-btn', 'auto-btn'} else None
        actual = [asset['path'] for asset in decoded if asset['element'] == element and asset['pseudo'] == pseudo]
        assert actual == [path], {'element':element, 'expected':path, 'actual':actual}
    return decoded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=['chromium', 'webkit'], default='chromium')
    args = parser.parse_args()
    output = ROOT / 'qa/controls-v090'
    output.mkdir(parents=True, exist_ok=True)
    session = DemoSession()
    session.seed = f'{2:064x}'
    server = make_server(port=0, session=session)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    receipt = {'engine': args.engine, 'layouts': [], 'page_errors': [], 'physical_device_tested': False}
    try:
        with sync_playwright() as playwright:
            browser = getattr(playwright, args.engine).launch(headless=True)
            for width, height, top, bottom in [(320,568,0,0), (360,640,0,0), (390,690,0,0),
                                                (390,844,59,34), (430,932,59,34), (844,390,0,0)]:
                page = browser.new_page(viewport={'width': width, 'height': height},
                                        is_mobile=True, has_touch=True, device_scale_factor=2)
                page.on('pageerror', lambda error: receipt['page_errors'].append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='networkidle')
                expect(page.locator('#soft-tech-continue')).to_be_enabled(timeout=20000)
                page.locator('#soft-tech-continue').click()
                expect(page.locator('#soft-tech-splash')).to_be_hidden()
                set_safe_area(page, top, bottom)
                geometry = assert_layout(page, width, height, top, bottom)
                assert_control_hits(page)
                scene_assets = assert_background_images(page)
                footer_assets = assert_footer_assets(page)
                visual = page.evaluate('''() => {
                    const b = id => { const e = document.getElementById(id), r = e.getBoundingClientRect(), c = getComputedStyle(e);
                        const overlay = getComputedStyle(e, '::after');
                        return {id, width:r.width, height:r.height, background:c.backgroundImage !== 'none' ? c.backgroundImage : overlay.backgroundImage, border:c.borderTopWidth}; };
                    return {buttons:['turbo-btn','minus-btn','spin-btn','plus-btn','auto-btn'].map(b),
                        oldSlicesPainted:[...document.querySelectorAll('.art-controls b')].some(e=>getComputedStyle(e).display!=='none'),
                        panel:getComputedStyle(document.querySelector('.art-controls')).backgroundImage};
                }''')
                assert not visual['oldSlicesPainted'], visual
                assert all(min(b['width'], b['height']) >= 44 for b in visual['buttons']), visual
                assert all(b['background'] != 'none' for b in visual['buttons']), visual
                spin = visual['buttons'][2]
                assert 63.99 <= spin['width'] <= 76.81, spin
                old_spin = max(80,min(96,80+(geometry['controls']['w']-320)*16/70))
                assert abs(spin['width']-.8*old_spin) < .65, (spin,old_spin)
                assert geometry['disk']['w'] >= spin['width'] - .5, geometry['disk']
                for button in [visual['buttons'][0], visual['buttons'][4]]:
                    assert button['width'] >= 52, button
                # Inlays must meet untouched dragon pixels and real reel edges.
                wings = page.evaluate('''() => {
                    const stage=document.querySelector('#game-stage');
                    const theatre=document.querySelector('.reel-theatre');
                    const outer=document.querySelector('.art-board').getBoundingClientRect();
                    const inner=theatre.getBoundingClientRect();
                    const st=getComputedStyle(stage),left=getComputedStyle(theatre,'::before'),right=getComputedStyle(theatre,'::after');
                    const val=n=>parseFloat(st.getPropertyValue(n))||0;
                    return {mode:stage.dataset.fullframe,left:val('--ff-wing-left'),right:val('--ff-wing-right'),
                      dragonLeft:val('--ff-left-base-width'),dragonRight:val('--ff-right-base-width'),
                      gapLeft:inner.left-outer.left,gapRight:outer.right-inner.right,
                      leftPaint:left.backgroundImage!=='none'&&left.display!=='none',
                      rightPaint:right.backgroundImage!=='none'&&right.display!=='none'};
                }''')
                if wings['mode'] != 'landscape':
                    assert wings['left'] > 0 and wings['right'] > 0, wings
                    assert abs(wings['left']+wings['dragonLeft']-wings['gapLeft']) < .8, wings
                    assert abs(wings['right']+wings['dragonRight']-wings['gapRight']) < .8, wings
                    assert wings['leftPaint'] and wings['rightPaint'], wings
                screenshot = f'{args.engine}-{width}x{height}-safe-{top}-{bottom}.png'
                page.screenshot(path=str(output / screenshot))
                receipt['layouts'].append({'viewport':[width,height], 'safe_area':[top,bottom],
                                          'buttons':visual['buttons'], 'screenshot':screenshot,
                                          'decoded_scene_assets':scene_assets, 'decoded_footer_assets':footer_assets,
                                          'stage':geometry['stage'], 'board':geometry['board']})
                page.close()

            # These are the original live buttons: one action still makes one
            # accepted round. The geometry layer never sends game requests.
            page = browser.new_page(viewport={'width':390,'height':690}, is_mobile=True, has_touch=True)
            page.on('pageerror', lambda error: receipt['page_errors'].append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='networkidle')
            expect(page.locator('#soft-tech-continue')).to_be_enabled(timeout=20000)
            page.locator('#soft-tech-continue').click()
            expect(page.locator('#soft-tech-splash')).to_be_hidden()
            requests = []
            page.on('request', lambda request: requests.append(request.url) if '/api/spin' in request.url else None)
            page.locator('#turbo-btn').click()
            expect(page.locator('#turbo-btn')).to_have_attribute('aria-pressed', 'true')
            start = session.spins
            page.locator('#spin-btn').click()
            expect(page.locator('#spin-btn')).to_have_attribute('aria-label', 'Lewati animasi')
            expect(page.locator('#spin-btn')).to_have_attribute('aria-label', 'Spin', timeout=60000)
            assert len(requests) == 1 and session.spins == start + 1, (requests, session.spins)
            page.locator('#auto-btn').click()
            expect(page.locator('#auto-dialog')).to_be_visible()
            page.locator('[data-autospins="10"]').click()
            expect(page.locator('#auto-btn')).to_have_class('secondary-control auto-control active')
            page.locator('#auto-btn').click()
            expect(page.locator('#auto-caption')).to_have_text('AUTO')
            expect(page.locator('#spin-btn')).to_have_attribute('aria-label', 'Spin', timeout=60000)
            assert len(requests) == 2 and session.spins == start + 2, (requests, session.spins)
            receipt['interactions'] = {'spin_requests':len(requests), 'accepted_rounds':session.spins-start,
                                       'turbo_toggle':'PASS', 'auto_start_stop':'PASS'}
            assert not receipt['page_errors'], receipt['page_errors']
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    (output / f'{args.engine}.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'result':'PASS', 'engine':args.engine, 'layouts':len(receipt['layouts']),
                      'interactions':receipt['interactions']}))


if __name__ == '__main__':
    main()
