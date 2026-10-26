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
    expected['announcement'] = '/assets/fullframe-v086/notice-center.webp'
    for element in ['meter-0', 'meter-1', 'meter-2',
                    'turbo-btn', 'minus-btn', 'plus-btn', 'auto-btn']:
        expected[element] = '/assets/approved-v082/frame.webp'
    for element, path in expected.items():
        pseudo = '::after' if element in {'turbo-btn', 'auto-btn'} else None
        actual = [asset['path'] for asset in decoded if asset['element'] == element and asset['pseudo'] == pseudo]
        assert actual == [path], {'element':element, 'expected':path, 'actual':actual}
    caps = {'::before':'/assets/fullframe-v086/notice-left.webp',
            '::after':'/assets/fullframe-v086/notice-right.webp'}
    for pseudo, name in caps.items():
        matches = [item for item in decoded
                   if item['element'] == 'announcement' and item['pseudo'] == pseudo]
        assert len(matches) == 1 and matches[0]['path'] == name, matches
        assert (matches[0]['width'],matches[0]['height']) == (226,109), matches
    return decoded


def assert_source_proportional_ornaments(page):
    """One thin gold edge and actual scaled alpha cutouts, never side inlays."""
    data = page.evaluate('''() => {
        const stage=document.querySelector('#game-stage');
        const scene=document.querySelector('.reel-theatre');
        const banner=document.querySelector('.announcement');
        const sb=getComputedStyle(stage);
        const val=n=>parseFloat(sb.getPropertyValue(n))||0;
        const left=getComputedStyle(scene,'::before');
        const right=getComputedStyle(scene,'::after');
        const capLeft=getComputedStyle(banner,'::before');
        const capRight=getComputedStyle(banner,'::after');
        const tile=document.querySelector('#board .tile').getBoundingClientRect();
        const box=c=>({width:parseFloat(c.width),height:parseFloat(c.height),
             image:c.backgroundImage,visible:c.display!=='none'});
        return {
          boardHeight:val('--ff-board-height'),tileWidth:tile.width,
          overlap:val('--ff-tail-overlap'),oldWings:val('--ff-wing-left')+val('--ff-wing-right'),
          tailLeft:{...box(left),edge:parseFloat(left.left)+parseFloat(left.width)},
          tailRight:{...box(right),edge:parseFloat(right.right)+parseFloat(right.width)},
          goldLine:parseFloat(getComputedStyle(scene.querySelector('.board-frame')).outlineWidth),
          capLeft:box(capLeft),capRight:box(capRight),
          centerBanner:getComputedStyle(banner).backgroundImage
        };
    }''')
    assert data['oldWings'] == 0, data
    assert 0 < data['overlap'] <= data['tileWidth'] * .10 + .2, data
    assert abs(data['overlap']-data['tileWidth']*.08) < .35, data
    assert .5 <= data['goldLine'] <= 1.6, data
    expected_h = (938-525)*data['boardHeight']/938*1.42
    for side, natural_w in [('Left',118),('Right',117)]:
        obj=data['tail'+side]
        assert obj['visible'] and 'tail-'+side.lower()+'.webp' in obj['image'], obj
        assert obj['image'].count('url(') == 1 and 'gradient' not in obj['image'], obj
        expected_w=natural_w*data['boardHeight']/938*1.42
        assert abs(obj['width']-expected_w)<.12 and abs(obj['height']-expected_h)<.12, obj
        assert abs(obj['edge']-data['overlap'])<.12, obj
        assert abs((obj['width']/natural_w)/(obj['height']/413)-1)<.012, obj
    for side in ('Left','Right'):
        cap=data['cap'+side]
        assert cap['visible'] and 'notice-'+side.lower()+'.webp' in cap['image'], cap
        assert abs(cap['width']/cap['height']-226/109)<.012, cap
    assert 'notice-center.webp' in data['centerBanner'], data
    return data


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
                ornament_geometry = assert_source_proportional_ornaments(page)
                screenshot = f'{args.engine}-{width}x{height}-safe-{top}-{bottom}.png'
                page.screenshot(path=str(output / screenshot))
                receipt['layouts'].append({'viewport':[width,height], 'safe_area':[top,bottom],
                                          'buttons':visual['buttons'], 'screenshot':screenshot,
                                          'decoded_scene_assets':scene_assets, 'decoded_footer_assets':footer_assets,
                                          'stage':geometry['stage'], 'board':geometry['board'],
                                          'ornaments':ornament_geometry})
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
