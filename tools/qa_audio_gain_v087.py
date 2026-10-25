"""Render the actual mixer in Web Audio to verify the 30% presentation gain.

The source buffers use a deterministic low-level tone, so comparison does not
depend on codec output, hardware volume, or the timing of a real audio device.
Gesture unlocking and real asset decoding remain covered by qa_approved_v082.
"""
from pathlib import Path
import argparse
import json

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / 'web/assets/locked-v08/audio.js'
CASES = [
    {'name': 'effects_default', 'volume': .8, 'music_volume': .28, 'music': False, 'play': True},
    {'name': 'music_default', 'volume': .8, 'music_volume': .28, 'music': True, 'play': False},
    {'name': 'saved_custom_mix', 'volume': .37, 'music_volume': .19, 'music': True, 'play': True},
    {'name': 'saved_mute', 'volume': .37, 'music_volume': .19, 'music': True, 'play': True, 'enabled': False},
    {'name': 'mute_after_unlock', 'volume': .8, 'music_volume': .28, 'music': True, 'play': True, 'mute_after': True},
]

SETUP = r'''cfg => {
    localStorage.clear();
    localStorage.setItem('mw-volume', String(cfg.volume));
    localStorage.setItem('mw-music-volume', String(cfg.music_volume));
    localStorage.setItem('mw-sfx', cfg.enabled === false ? 'off' : 'on');
    localStorage.setItem('mw-music', cfg.music ? 'on' : 'off');
    const Offline = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    const actual = new Offline(1, 48000, 48000);
    const buffer = actual.createBuffer(1, 48000, 48000);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = .1 * Math.sin(2 * Math.PI * 440 * i / 48000);
    window.__audioQA = {actual, buffer, before: {...localStorage}};
    // Keep scheduling at time zero until all asynchronous source setup has
    // finished, then let the browser render the real AudioNode graph below.
    window.AudioContext = function () {
        return new Proxy(actual, {
            get(target, prop) {
                if (prop === 'state') return 'running';
                if (prop === 'resume') return async () => {};
                if (prop === 'decodeAudioData') return async () => buffer;
                const value = Reflect.get(target, prop, target);
                return typeof value === 'function' ? value.bind(target) : value;
            }
        });
    };
    window.fetch = async () => ({ok: true, arrayBuffer: async () => new ArrayBuffer(4)});
}'''

RENDER = r'''async cfg => {
    const audio = window.MahjongWildAudio;
    await audio.unlock();
    if (cfg.play) await audio.play('tap');
    if (cfg.music && cfg.enabled !== false) {
        for (let i = 0; i < 100 && !audio.state.musicPlaying; i++) await new Promise(r => setTimeout(r, 1));
        if (!audio.state.musicPlaying) throw new Error('Music did not enter the graph');
    }
    if (cfg.mute_after) audio.setEnabled(false);
    const state = audio.state;
    const after = {...localStorage};
    const out = (await __audioQA.actual.startRendering()).getChannelData(0);
    const input = __audioQA.buffer.getChannelData(0);
    const audible = cfg.enabled !== false && !cfg.mute_after;
    const originalGain = audible ? (cfg.play ? .8 * cfg.volume : 0) + (cfg.music ? cfg.music_volume : 0) : 0;
    let numerator = 0, denominator = 0, maximumError = 0, peak = 0;
    // Both buses are at their steady levels after the existing 650ms fade-in.
    for (let i = 38400; i < 45600; i++) {
        const reference = input[i] * originalGain;
        numerator += out[i] * reference;
        denominator += reference * reference;
        maximumError = Math.max(maximumError, Math.abs(out[i] - reference * 1.30));
    }
    for (const sample of out) peak = Math.max(peak, Math.abs(sample));
    return {name: cfg.name, amplitudeRatio: denominator ? numerator / denominator : null,
        maximumError, peak, state, before: __audioQA.before, after};
}'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=['chromium', 'webkit'], default='chromium')
    parser.add_argument('--browser')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    results = []
    with sync_playwright() as p:
        browser = getattr(p, args.engine).launch(
            headless=True, **({'executable_path': args.browser} if args.browser else {}))
        for cfg in CASES:
            page = browser.new_page()
            page.route('https://audio-qa.invalid/', lambda route: route.fulfill(
                status=200, content_type='text/html', body='<!doctype html><title>Audio gain QA</title>'))
            page.goto('https://audio-qa.invalid/')
            page.evaluate(SETUP, cfg)
            page.add_script_tag(content=AUDIO.read_text())
            result = page.evaluate(RENDER, cfg)
            assert result['maximumError'] < 1e-6, result
            if result['amplitudeRatio'] is not None:
                assert abs(result['amplitudeRatio'] - 1.30) < 1e-5, result
                assert result['peak'] > .001, result
            else:
                assert result['peak'] == 0, result
            assert result['state']['volume'] == cfg['volume'], result
            assert result['state']['musicVolume'] == cfg['music_volume'], result
            expected_after = {**result['before']}
            if cfg.get('mute_after'):
                expected_after['mw-sfx'] = 'off'
            assert result['after'] == expected_after, result
            assert not result['state']['lastError'], result
            results.append(result)
            page.close()
        browser.close()
    report = {'engine': args.engine, 'output_gain': 1.30, 'cases': results,
              'physical_audibility_tested': False}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
