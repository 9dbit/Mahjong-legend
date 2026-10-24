"""Observe real, unpaused reel frames over HTTP with the actual engine.

This test intentionally does not replace Element.animate, pause animation clocks,
or decode images on the application's behalf. Fixtures exist only in this process.
DOM coverage detects missing rows; unpaused screenshots add painted-pixel checks.
Neither headless browser timing nor these checks certify a physical iPhone's FPS.
"""
from pathlib import Path
import argparse
import asyncio
import io
import json
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mahjong_legend.engine import play_round, verify_round
from mahjong_legend.server import DemoSession, make_server
from PIL import Image
from playwright.async_api import async_playwright, expect

OUT = ROOT / 'qa' / 'spin-continuity'
SEEDS = (2, 3, 7, 9, 10, 13)


class FixtureSession(DemoSession):
    def __init__(self):
        super().__init__()
        self.reset()
        for seed in SEEDS:
            outcome = play_round(f'{seed:064x}', self.cfg)
            assert outcome['total_payout_x'] == '0' and not outcome['free_spins_played']

    def reset(self):
        super().reset()
        self.fixture_index = 0
        self.seed = f'{SEEDS[0]:064x}'
        return self.state()

    def spin(self, bet=None):
        result = super().spin(bet)
        self.fixture_index = (self.fixture_index + 1) % len(SEEDS)
        self.seed = f'{SEEDS[self.fixture_index]:064x}'
        result['state'] = self.state()
        return result


PROBE = r"""() => {
    const board = document.querySelector('#board');
    const p = window.qaContinuity = {
        active: true, frames: 0, violations: [], starts: [], stops: [],
        samples: [[], [], [], [], []], maxTiles: 0, maxFrameGap: 0,
        started: [false,false,false,false,false], rolling: [false,false,false,false,false],
        stopTimes: [null,null,null,null,null], lastTime: null
    };
    const fail = (kind, col, extra={}) => {
        if (p.violations.length < 15) p.violations.push({kind,col,...extra});
    };
    const tick = now => {
        if (!p.active) return;
        p.frames++;
        if (p.lastTime !== null) p.maxFrameGap = Math.max(p.maxFrameGap, now-p.lastTime);
        p.lastTime = now;
        const columns = [...board.children];
        p.maxTiles = Math.max(p.maxTiles, board.querySelectorAll('.tile').length);
        if (columns.length !== 5) fail('column-count', -1, {count:columns.length});
        columns.forEach((col,i) => {
            const isRolling = col.classList.contains('reel-window');
            if (isRolling && col.dataset.started === 'true') {
                if (!p.started[i]) { p.started[i]=true; p.starts.push(i); }
                const travel = Number(col.dataset.travel);
                if (Number.isFinite(travel)) p.samples[i].push([now,travel]);
            }
            if (p.rolling[i] && !isRolling) { p.stops.push(i); p.stopTimes[i]=now; }
            p.rolling[i] = isRolling;
            const box = col.getBoundingClientRect();
            if (box.width < 1 || box.height < 1) return fail('collapsed-column',i);
            const intervals = [];
            for (const img of col.querySelectorAll('.tile-image')) {
                const tile = img.closest('.tile');
                const r = img.getBoundingClientRect();
                const lo = Math.max(box.top,r.top), hi = Math.min(box.bottom,r.bottom);
                if (hi-lo < .5 || r.right <= box.left || r.left >= box.right) continue;
                const css = getComputedStyle(img), tc = getComputedStyle(tile);
                if (css.visibility === 'hidden' || tc.visibility === 'hidden' ||
                    Number(css.opacity) < .1 || Number(tc.opacity) < .1) continue;
                if (!img.complete || img.naturalWidth === 0) {
                    fail('undecoded-visible-image',i,{src:img.getAttribute('src')});
                    continue;
                }
                if (r.width < box.width*.85) continue;
                intervals.push([lo,hi]);
            }
            intervals.sort((a,b)=>a[0]-b[0]);
            let covered=0, end=box.top;
            for (const [lo,hi] of intervals) {
                covered += Math.max(0,hi-Math.max(lo,end)); end=Math.max(end,hi);
            }
            // Intentional 1px seams are allowed; a missing tile row is not.
            if (covered/box.height < .90) fail('uncovered-column',i,{coverage:covered/box.height});
        });
        requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
}"""

BOARD = """() => [...document.querySelector('#board').children].map(c =>
    [...c.querySelectorAll(':scope > .tile')].map(t =>
        ({symbol:t.dataset.symbol, enhanced:t.classList.contains('enhanced')})))"""


async def wait_for_initial_pixels(page):
    # Poll readiness without calling decode(), which could hide an application bug.
    for _ in range(100):
        if await page.locator('#board').evaluate("""b => {
            const imgs=[...b.querySelectorAll('.tile-image')];
            return imgs.length===23 && imgs.every(i=>i.complete && i.naturalWidth>0);
        }"""):
            return
        await asyncio.sleep(.04)
    raise AssertionError('Initial board pixels never became available')


def check_painted_columns(data):
    image = Image.open(io.BytesIO(data)).convert('RGB')
    w, h = image.size
    fractions = []
    for col in range(5):
        # Stay inside each reel and the shared vertical area of short/tall columns.
        crop = image.crop((int((col+.2)*w/5), int(h*.14),
                           int((col+.8)*w/5), int(h*.86)))
        pixels = list(crop.getdata())
        bright = sum(r>135 and g>105 and b>35 for r,g,b in pixels)/len(pixels)
        fractions.append(bright)
        assert bright > .15, ('Unpainted/blank reel screenshot', col, bright)
    return fractions


def speed_profile(samples, end_time):
    assert len(samples) >= 12, ('Insufficient live motion frames', len(samples))
    first = samples[0][0]
    length = end_time-first
    assert length > 250
    def at(fraction):
        target = first + length*fraction
        for a,b in zip(samples,samples[1:]):
            if a[0] <= target <= b[0]:
                return a[1]+(b[1]-a[1])*(target-a[0])/(b[0]-a[0])
        return samples[-1][1] if target >= samples[-1][0] else samples[0][1]
    speeds = {
        'start': (at(.15)-at(.02))/.13,
        'middle': (at(.60)-at(.40))/.20,
        'end': (at(.98)-at(.85))/.13,
    }
    assert speeds['middle'] > speeds['start']*2, speeds
    assert speeds['middle'] > speeds['end']*2, speeds
    assert all(b[1] >= a[1]-.05 for a,b in zip(samples,samples[1:])), 'Reel reversed or jumped backwards'
    return speeds


async def run(args):
    OUT.mkdir(parents=True, exist_ok=True)
    session = FixtureSession()
    server = make_server(port=0, session=session)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report = {'engine':args.engine, 'transport':'HTTP + CSP', 'cases':[]}
    try:
        async with async_playwright() as p:
            browser = await getattr(p,args.engine).launch(headless=True,
                **({'executable_path':args.browser} if args.browser else {}))

            async def exercise(name, repeats=1, turbo=False, skip=False,
                               asset_delay=False, api_delay=False):
                session.reset()
                context = await browser.new_context(viewport={'width':390,'height':844},
                    device_scale_factor=2, is_mobile=True, has_touch=True,
                    service_workers='block')
                page = await context.new_page()
                errors, requests = [], []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: requests.append(r.url)
                        if r.method=='POST' and r.url.endswith('/api/spin') else None)
                gate, intercepted = asyncio.Event(), asyncio.Event()
                async def held(route):
                    intercepted.set()
                    await gate.wait()
                    await route.continue_()
                if asset_delay:
                    # Seed 2 settles to J-gold, which is absent from the initial board.
                    await page.route('**/assets/approved-v082/tiles/J-gold.webp', held)
                if api_delay:
                    await page.route('**/api/spin', held)
                try:
                    await page.goto(f'http://127.0.0.1:{server.server_port}',
                                    wait_until='domcontentloaded')
                    await wait_for_initial_pixels(page)
                    if not asset_delay:
                        await expect(page.locator('#stage-notice')).to_have_text('SIAP BERMAIN')
                    if turbo:
                        await page.locator('#turbo-btn').click()
                    for turn in range(repeats):
                        await page.evaluate(PROBE)
                        initial = await page.evaluate(BOARD)
                        click = asyncio.create_task(page.locator('#spin-btn').click(timeout=7000))
                        if asset_delay or api_delay:
                            await asyncio.wait_for(intercepted.wait(), timeout=5)
                            await asyncio.sleep(.45)
                            assert await page.evaluate(BOARD) == initial, 'Pending response/asset discarded visible board'
                            assert not await page.evaluate('qaContinuity.violations')
                            gate.set()
                        await click
                        await expect(page.locator('.reel-window').first).to_be_visible(timeout=7000)
                        if skip:
                            # Multiple skip taps while busy must not debit another spin.
                            await page.evaluate("""() => {
                                const b=document.querySelector('#spin-btn'); b.click(); b.click();
                            }""")
                        painted = None
                        if name == 'normal-repeat' and turn == 0:
                            await asyncio.sleep(.48)
                            shot = await page.locator('#board').screenshot(
                                path=str(OUT/f'{args.engine}-unpaused-spin.png'), animations='allow')
                            painted = check_painted_columns(shot)
                        await expect(page.locator('#spin-count')).to_have_text(str(turn+1), timeout=12000)
                        await expect(page.locator('#spin-btn')).to_have_attribute('aria-label','Spin')
                        await asyncio.sleep(.08)
                        result = await page.evaluate('() => { qaContinuity.active=false; return qaContinuity; }')
                        assert result['frames'] >= 3, result
                        assert not result['violations'], result['violations']
                        assert result['maxTiles'] <= 33, ('Unbounded rolling tile allocation', result['maxTiles'])
                        if not skip:
                            assert result['starts'] == [0,1,2,3,4], result['starts']
                            assert result['stops'] == [0,1,2,3,4], result['stops']
                        speeds = None
                        if not turbo and not skip:
                            speeds = [speed_profile(s,t) for s,t in zip(result['samples'], result['stopTimes'])]
                        expected = [e['board'] for e in session.last_round['events'] if e['type']=='screen_end'][-1]
                        assert await page.evaluate(BOARD) == expected, 'Visual board differs from server result'
                        assert session.spins == turn+1 == len(requests), 'Duplicate or missing paid spin'
                        assert verify_round(session.last_round, session.cfg)['valid']
                        assert not errors, errors
                        report['cases'].append({'case':name,'turn':turn+1,
                            'sampled_frames':result['frames'],'max_tiles':result['maxTiles'],
                            'start_order':result['starts'],'stop_order':result['stops'],
                            'speed':speeds,'painted_bright_fractions':painted,
                            'max_frame_gap_ms':result['maxFrameGap'],
                            'visible_coverage':'PASS','server_board':'PASS','one_request':'PASS'})
                finally:
                    gate.set()
                    await context.close()

            await exercise('normal-repeat', repeats=2)
            await exercise('turbo', turbo=True)
            await exercise('skip', skip=True)
            await exercise('cold-delayed-result-image', asset_delay=True)
            await exercise('delayed-spin-response', api_delay=True)
            await browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        (OUT/f'report-{args.engine}.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'engine':args.engine,'cases':len(report['cases']),
                      'unpaused_coverage':'PASS','server_result':'PASS'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine',choices=['chromium','webkit'],default='chromium')
    parser.add_argument('--browser')
    asyncio.run(run(parser.parse_args()))
