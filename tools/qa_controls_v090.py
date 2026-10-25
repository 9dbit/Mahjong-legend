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
from qa_fullframe_v086 import assert_layout, assert_control_hits, set_safe_area


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
                visual = page.evaluate('''() => {
                    const b = id => { const e = document.getElementById(id), r = e.getBoundingClientRect(), c = getComputedStyle(e);
                        return {id, width:r.width, height:r.height, background:c.backgroundImage, border:c.borderTopWidth}; };
                    return {buttons:['turbo-btn','minus-btn','spin-btn','plus-btn','auto-btn'].map(b),
                        oldSlicesPainted:[...document.querySelectorAll('.art-controls b')].some(e=>getComputedStyle(e).display!=='none'),
                        panel:getComputedStyle(document.querySelector('.art-controls')).backgroundImage};
                }''')
                assert not visual['oldSlicesPainted'], visual
                assert 'data:image/svg+xml' in visual['panel'], visual
                assert all(min(b['width'], b['height']) >= 44 for b in visual['buttons']), visual
                assert all(b['background'] != 'none' for b in visual['buttons']), visual
                spin = visual['buttons'][2]
                assert 80 <= spin['width'] <= 96.01, spin
                assert geometry['disk']['w'] >= spin['width'] - .5, geometry['disk']
                for button in [visual['buttons'][0], visual['buttons'][4]]:
                    assert button['width'] >= 52, button
                screenshot = f'{args.engine}-{width}x{height}-safe-{top}-{bottom}.png'
                page.screenshot(path=str(output / screenshot))
                receipt['layouts'].append({'viewport':[width,height], 'safe_area':[top,bottom],
                                          'buttons':visual['buttons'], 'screenshot':screenshot,
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
