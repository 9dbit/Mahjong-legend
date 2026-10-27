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


def assert_mobile_ornaments(page):
    """Six independent source-ratio sprites and zero obscured scored tiles."""
    data = page.evaluate(r'''async () => {
      const stage=document.querySelector('#game-stage');
      const reel=document.querySelector('.reel-theatre');
      const banner=document.querySelector('.announcement');
      const sb=getComputedStyle(stage);
      const val=n=>parseFloat(sb.getPropertyValue(n))||0;
      const board=reel.getBoundingClientRect();
      const tile=document.querySelector('#board .tile').getBoundingClientRect();
      const nodes=[...document.querySelectorAll('.art-board > .mobile-ornament')];
      const sprites=await Promise.all(nodes.map(async e=>{
        const box=e.getBoundingClientRect(),css=getComputedStyle(e);
        const match=css.backgroundImage.match(/url\(["']?([^"')]+)["']?\)/);
        const img=new Image();
        img.src=match?.[1]||'';
        try { await img.decode(); } catch (error) {}
        return {kind:e.className, left:box.left, right:box.right, top:box.top,
          width:box.width, height:box.height,display:css.display,
          pointerEvents:css.pointerEvents, fit:css.backgroundSize,
          transform:css.transform,
          url:img.src, natural:[img.naturalWidth,img.naturalHeight],
          decoded:img.complete&&img.naturalWidth>0};
      }));
      return {
        mode:stage.dataset.fullframe,tileWidth:tile.width,
        overlap:val('--ff-mobile-ornament-overlap'),
        board:{left:board.left,right:board.right},
        oldWings:val('--ff-wing-left')+val('--ff-wing-right'),
        oldSideOpacities:[...document.querySelectorAll('.art-board > b')]
          .filter((_,i)=>i!==1).map(e=>parseFloat(getComputedStyle(e).opacity)),
        oldTailDisplays:['::before','::after'].map(p=>getComputedStyle(reel,p).display),
        goldLine:parseFloat(getComputedStyle(reel.querySelector('.board-frame')).outlineWidth),
        sprites,
        shortReels:[...document.querySelectorAll('#board > .reel.short')].map(e=>{
          const first=e.querySelector('.tile'), fr=first.getBoundingClientRect();
          const board=document.querySelector('#board').getBoundingClientRect();
          const before=getComputedStyle(e,'::before'),after=getComputedStyle(e,'::after');
          return {top:fr.top-board.top,count:e.querySelectorAll('.tile').length,
            beforeDisplay:before.display,afterDisplay:after.display,
            afterImage:after.backgroundImage,
            afterTop:parseFloat(after.top),afterHeight:parseFloat(after.height),
            reelHeight:e.getBoundingClientRect().height,
            boardHeight:board.height,
            scoredTileCount:[...e.querySelectorAll('.tile')].filter(x=>!!x._tile).length};
        }),
        caps:['::before','::after'].map(p=>{
          const css=getComputedStyle(banner,p);
          return {w:parseFloat(css.width),h:parseFloat(css.height),
            image:css.backgroundImage};
        }),
        banner:getComputedStyle(banner).backgroundImage
      };
    }''')
    assert len(data['sprites']) == 6, data
    assert 0 < data['overlap'] <= data['tileWidth']*.10+.12, data
    assert abs(data['overlap']-data['tileWidth']*.08) < .18, data
    assert .5 <= data['goldLine'] <= 1.6, data
    assert data['oldWings'] == 0, data
    for cap, side in zip(data['caps'], ('left','right')):
        assert 'notice-'+side+'.webp' in cap['image'], cap
        assert abs(cap['w']/cap['h']-226/109)<.012, cap
    assert 'notice-center.webp' in data['banner'], data
    if data['mode'] == 'portrait':
        assert max(data['oldSideOpacities']) < .01, data
        assert data['oldTailDisplays'] == ['none','none'], data
    else:
        assert all(item['display']=='none' for item in data['sprites']), data
    seen=set()
    for asset in data['sprites']:
        kind=next((k for k in ('lantern','dragon','cloud')
                   if 'mobile-ornament--'+k+'-' in asset['kind']),None)
        side=next((x for x in ('left','right')
                   if asset['kind'].endswith('-'+x)),None)
        assert kind and side and (kind,side) not in seen, asset
        seen.add((kind,side))
        dimensions={'lantern':240,'dragon':505,'cloud':410}
        natural=(192 if kind=='cloud' else (118 if side=='left' else 117),dimensions[kind])
        assert asset['decoded'] and tuple(asset['natural'])==natural, asset
        path=('/assets/ornaments/approved-cloud-v097.svg'
              if kind=='cloud' else '/assets/fullframe-v086/mobile-'+kind+'-'+side+'.webp')
        assert path in asset['url'],asset
        if kind=='cloud' and data['mode']=='portrait':
            if side=='right':
                assert asset['transform'].startswith('matrix(-1,'),asset
            else:
                assert asset['transform']=='none',asset
        assert asset['pointerEvents']=='none' and asset['fit']=='contain',asset
        # Hidden assets have no layout box in landscape; only portrait paints them.
        if data['mode']!='portrait':
            continue
        # Width and height MUST derive from the SAME scale for all elements.
        xscale=asset['width']/natural[0]
        yscale=asset['height']/natural[1]
        assert xscale>0 and abs(xscale/yscale-1)<.012,asset
        if data['mode']=='portrait':
            assert asset['display']!='none',asset
            overlap=0 if kind=='lantern' else data['overlap']
            if side=='left':
                assert abs(asset['right']-data['board']['left']-overlap)<.5,asset
            else:
                assert abs(data['board']['right']-asset['left']-overlap)<.5,asset
    assert len(seen)==6,data
    # Both four-tile reels must start flush with the TOP of the first visible
    # row, not a motionless tile-shaped :before. The fifth slot is sealed by
    # a non-scoring ornament that begins after the last actual tile.
    assert len(data['shortReels'])==2,data
    for reel in data['shortReels']:
        assert reel['count']==reel['scoredTileCount']==4,reel
        assert abs(reel['top'])<=2.2,reel
        assert reel['beforeDisplay']=='none',reel
        assert reel['afterDisplay']!='none',reel
        assert 'reel-endcap-v097.svg' in reel['afterImage'],reel
        assert 0<=reel['afterTop']-reel['reelHeight']<=4.5,reel
        assert reel['afterHeight']>reel['boardHeight']*.15,reel
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
                ornament_geometry = assert_mobile_ornaments(page)
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
