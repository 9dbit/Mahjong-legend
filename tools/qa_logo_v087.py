"""UI 0.8.7 acceptance: continuous crown, round lanterns and animated rays.

The crown raster comparison uses the same browser to paint the untouched full
source as an independent reference. It catches visible panel/seam regressions
that viewport bounds alone cannot detect. Hardware iPhone testing is separate.
"""
from io import BytesIO
from pathlib import Path
import argparse
import json
import sys
import threading

from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from mahjong_legend.server import DemoSession, make_server
from qa_fullframe_v086 import (
    assert_background_images, assert_control_hits, assert_layout,
    install_viewport_fixture, set_safe_area,
)

OUT = ROOT / 'qa/logo-v087'


def previous_geometry(width, height, top=0, bottom=0, left=0, right=0):
    """Frozen v0.8.6 baseline, used only to measure the requested movement."""
    usable = height - top - bottom
    inner = width - left - right
    fraction = max(.62, min(.728, .728 - (1859 / 864 - usable / inner) * .17))
    panels = min(usable * .55, max(120, usable * .3))
    board = min(1.5 * inner * fraction - .0064 * width, usable - panels)
    board_width = (board + .0064 * width) / 1.5
    spare = usable - board
    header, footer = spare * 394 / 921, spare * 527 / 921
    hud = min(footer * .4, width * 199 / 864)
    control_unit = min((footer - hud) / 328, inner / 864)
    center = left + inner / 2
    return {
        'board_top': top + header,
        'controls_top': top + header + board + hud + .064 * control_unit,
        'lantern_deformation': [
            ((center - board_width / 2) / 118) / (board / 938),
            ((width - center - board_width / 2) / 117) / (board / 938),
        ],
    }


def crown_raster_comparison(page):
    """Compare the rendered crown with an independently sized source image.

    The temporary reference retains the same crest/ray/button overlays. The
    real reduced-motion preference holds them static, so only source sampling
    differs. Reference styles and the motion preference are restored afterwards.
    """
    frame = page.locator('.art-crown')
    geometry = frame.evaluate('''e=>{
      const r=e.getBoundingClientRect(),css=getComputedStyle(e),parts=[...e.children];
      return {x:r.x,y:r.y,width:r.width,height:r.height,
        imageWidth:r.width,imageHeight:1859*r.width/864,
        image:css.backgroundImage,size:css.backgroundSize,position:css.backgroundPosition,
        parts:parts.filter(p=>getComputedStyle(p).display!=='none').map(p=>{const b=p.getBoundingClientRect(),c=getComputedStyle(p);
          return {x:b.x,width:b.width,image:c.backgroundImage,size:c.backgroundSize,position:c.backgroundPosition};})};
    }''')
    assert abs(geometry['imageWidth'] - geometry['width']) < .05, geometry
    assert '/assets/portrait-v085/frame.webp' in geometry['image'], geometry
    assert not geometry['parts'], geometry
    assert geometry['position'] == '0px 0px', geometry
    size = [float(v.removesuffix('px')) for v in geometry['size'].split()]
    assert abs(size[0] - geometry['width']) < .01, geometry
    assert abs(size[1] - geometry['imageHeight']) < .01, geometry
    page.emulate_media(reduced_motion='reduce')
    page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    clip = {key: geometry[key] for key in ('x', 'y', 'width', 'height')}
    original_styles = frame.evaluate('e=>({self:e.style.cssText,parts:[...e.children].map(p=>p.style.cssText)})')
    try:
        actual = page.screenshot(clip=clip)
        frame.evaluate('''(e,g)=>{
          e.style.backgroundImage='url("/assets/portrait-v085/frame.webp")';
          e.style.backgroundSize=g.imageWidth+'px '+g.imageHeight+'px';
          e.style.backgroundPosition='0 0';
          for(const p of e.children)p.style.visibility='hidden';
        }''', geometry)
        page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        reference = page.screenshot(clip=clip)
    finally:
        frame.evaluate('''(e,s)=>{e.style.cssText=s.self;[...e.children].forEach((p,i)=>p.style.cssText=s.parts[i]);}''', original_styles)
        page.emulate_media(reduced_motion='no-preference')
    first, second = Image.open(BytesIO(actual)).convert('RGB'), Image.open(BytesIO(reference)).convert('RGB')
    assert first.size == second.size
    delta = ImageChops.difference(first, second)
    mean_error = sum(ImageStat.Stat(delta).mean) / 3
    if mean_error >= 1.0:
        engine = page.context.browser.browser_type.name
        (OUT / f'{engine}-crown-actual.png').write_bytes(actual)
        (OUT / f'{engine}-crown-continuous-reference.png').write_bytes(reference)
    # Allow tiny source-size rounding, not an inset or separately scaled panel.
    assert mean_error < 1.0, {'mean_channel_error': mean_error, 'geometry': geometry}
    return {'mean_channel_error_0_255': round(mean_error, 6), 'maximum_allowed': 1.0,
            'source': 'assets/portrait-v085/frame.webp', 'continuous_source_match': 'PASS',
            'geometry': geometry}


def lantern_geometry(page, baseline=None):
    result = page.evaluate('''async()=>{
      const all=[...document.querySelectorAll('.art-board > b')];
      return Promise.all([all[0],all[2]].map(async(e,i)=>{
        const box=e.getBoundingClientRect(),middle=getComputedStyle(e),
          top=getComputedStyle(e,'::before'),bottom=getComputedStyle(e,'::after');
        const height=c=>parseFloat(c.backgroundSize.split(/\\s+/)[1]);
        const match=top.backgroundImage.match(/url\\(["']?([^"')]+)["']?\\)/);
        const image=new Image();image.src=match?.[1]||'';let decoded=false;
        try{await image.decode();decoded=image.complete&&image.naturalWidth>0;}catch(_){}
        return {side:i?'right':'left',sourceWidth:i?117:118,
          width:box.width,height:box.height,topHeight:parseFloat(top.height),bottomHeight:parseFloat(bottom.height),
          topImageHeight:height(top),bottomImageHeight:height(bottom),middleImageHeight:height(middle),
          middleOffset:parseFloat(middle.backgroundPositionY),decoded,
          topImage:top.backgroundImage,bottomImage:bottom.backgroundImage,
          imageSize:[image.naturalWidth,image.naturalHeight]};
      }));
    }''')
    for i, side in enumerate(result):
        assert side['decoded'] and side['imageSize'] == [side['sourceWidth'], 938], side
        assert side['topImage'] == side['bottomImage'], side
        sy_top = side['topImageHeight'] / 938
        sy_middle = side['middleImageHeight'] / 938
        sy_bottom = side['bottomImageHeight'] / 938
        assert min(sy_top, sy_middle, sy_bottom) > 0, side
        assert side['topHeight'] + side['bottomHeight'] < side['height'], side
        joins = [side['topHeight'] / sy_top,
                 (side['topHeight'] - side['middleOffset']) / sy_middle,
                 (side['height'] - side['bottomHeight'] - side['middleOffset']) / sy_middle,
                 938 - side['bottomHeight'] / sy_bottom]
        # Browser layout rounds each CSS boundary to a subpixel. On extremely
        # short split-screen boards a tiny visible rounding becomes several
        # source-image rows; bound the actual seam in CSS pixels instead.
        # v0.9.2 keeps the dragon torso at natural horizontal/vertical scale.
        # On short boards its unneeded lower pixels are cropped behind the
        # intact bottom ornament instead of stretched to span the whole side.
        source_x_scale = side['width'] / side['sourceWidth']
        assert abs(sy_middle-source_x_scale) < .015, (side, sy_middle, source_x_scale)
        assert all(abs(value-wanted)*scale < .05 for value,wanted,scale in
                   zip((joins[0],joins[1],joins[3]),(256,256,849),(sy_top,sy_middle,sy_bottom))), (side,joins)
        deformation = (side['width'] / side['sourceWidth']) / sy_top
        side['source_join_rows'] = joins
        side['horizontal_to_vertical_scale'] = deformation
        if baseline:
            # Source lantern body is gently oval; 1.0 means no extra flattening.
            # The requested rounder presentation slightly increases its height.
            assert deformation <= 1.01, side
            assert deformation < baseline['lantern_deformation'][i] - .05, (side, baseline)
    return result


def light_state(page):
    return page.locator('.art-crown').evaluate('''e=>['::before','::after'].map(p=>{
      const c=getComputedStyle(e,p);return {pseudo:p,animation:c.animationName,
        playState:c.animationPlayState,opacity:Number(c.opacity),transform:c.transform,
        background:c.backgroundImage,pointerEvents:c.pointerEvents};
    })''')


def check_light(page):
    page.emulate_media(reduced_motion='no-preference')
    samples = []
    for _ in range(4):
        samples.append(light_state(page))
        page.wait_for_timeout(420)
    assert [s['animation'] for s in samples[0]] == ['crown-glow', 'crown-rays'], samples
    for i in range(2):
        assert all(s[i]['playState'] == 'running' and s[i]['pointerEvents'] == 'none' for s in samples), samples
        assert max(s[i]['opacity'] for s in samples) - min(s[i]['opacity'] for s in samples) > .025, samples
        assert len({s[i]['transform'] for s in samples}) > 1, samples
    page.evaluate("document.documentElement.classList.add('reels-running')")
    paused = light_state(page)
    assert all(s['playState'] == 'paused' for s in paused), paused
    page.evaluate("document.documentElement.classList.remove('reels-running')")
    page.emulate_media(reduced_motion='reduce')
    static_before = light_state(page)
    page.wait_for_timeout(420)
    static_after = light_state(page)
    assert static_before == static_after, (static_before, static_after)
    assert all(s['animation'] == 'none' and 0 < s['opacity'] < .3 and s['transform'] == 'none' for s in static_after), static_after
    page.emulate_media(reduced_motion='no-preference')
    return {'animated_samples': samples, 'reel_pause': paused,
            'reduced_motion': static_after, 'result': 'PASS'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', choices=['chromium', 'webkit'], default='chromium')
    ap.add_argument('--browser')
    ap.add_argument('--offline', action='store_true')
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    session = DemoSession()
    session.seed = f'{2:064x}'
    server = None
    report = {'ui': '0.8.7', 'engine': args.engine,
              'physical_iphone_tested': False, 'cases': [], 'page_errors': []}
    if not args.offline:
        server = make_server(port=0, session=session)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = getattr(p, args.engine).launch(headless=True, **({'executable_path': args.browser} if args.browser else {}))
            cases = [
                {'name': 'browser-390x690', 'size': (390, 690), 'safe': (0, 0, 0, 0)},
                {'name': 'browser-390x844', 'size': (390, 844), 'safe': (0, 0, 0, 0)},
                {'name': 'standalone-390x844', 'size': (390, 844), 'safe': (59, 34, 0, 0), 'standalone': True},
                {'name': 'standalone-asymmetric', 'size': (390, 844), 'safe': (59, 34, 24, 12), 'standalone': True},
                {'name': 'compact-360x360', 'size': (360, 360), 'safe': (0, 0, 0, 0), 'compact': True},
            ]
            for case in cases:
                print('LOGO', args.engine, case['name'], flush=True)
                width, height = case['size']
                top, bottom, left, right = case['safe']
                page = browser.new_page(viewport={'width': width, 'height': height}, is_mobile=True,
                                        has_touch=True, device_scale_factor=2)
                page.on('pageerror', lambda error: report['page_errors'].append(str(error)))
                if case.get('standalone'):
                    install_viewport_fixture(page, True, 751, offline=args.offline)
                if args.offline:
                    from local_preview import offline
                    offline(page, seed=2)
                else:
                    session.reset()
                    session.seed = f'{2:064x}'
                    page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='networkidle')
                expect(page.locator('#soft-tech-continue')).to_be_enabled(timeout=20000)
                page.locator('#soft-tech-continue').click()
                expect(page.locator('#soft-tech-splash')).to_be_hidden()
                set_safe_area(page, top, bottom, left, right)
                geometry = assert_layout(page, width, height, top, bottom, left, right)
                assert_background_images(page)
                assert_control_hits(page)
                baseline = previous_geometry(width, height, top, bottom, left, right)
                movement = {'board_pixels_down': geometry['board']['y'] - baseline['board_top'],
                            'controls_pixels_down': geometry['controls']['y'] - baseline['controls_top']}
                if not case.get('compact'):
                    assert movement['board_pixels_down'] > 5, movement
                    # Native controls now reserve their own height. Their top
                    # may move up to fit a larger visible Spin while the crown
                    # and board retain the improved v087 placement.
                    assert geometry['controls']['h'] >= 108, geometry['controls']
                    assert geometry['disk']['w'] >= 80, geometry['disk']
                    assert all(min(button['w'],button['h']) >= 44 for button in geometry['buttons'][2:]), geometry['buttons']
                result = {'name': case['name'], 'viewport': case['size'], 'safe': case['safe'],
                          'movement_from_v086': movement, 'crown': crown_raster_comparison(page),
                          'lanterns': lantern_geometry(page, None if case.get('compact') else baseline)}
                if case['name'] == 'browser-390x690':
                    result['light'] = check_light(page)
                page.screenshot(path=str(OUT / f'{args.engine}-{case["name"]}.png'))
                assert not report['page_errors'], report['page_errors']
                report['cases'].append(result)
                page.close()
            browser.close()
        report['result'] = 'PASS'
    finally:
        if server:
            server.shutdown()
            server.server_close()
        (OUT / f'report-{args.engine}.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
