"""Render the release-configured audio graph and verify cancellation/voice bounds.

Uses real browser AudioNodes and deterministic tone buffers. Existing game QA
still covers codec decoding and gesture input; this probe isolates gain routing,
configuration, priority and mute semantics without hardware-volume assumptions.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import json
import sys

from playwright.sync_api import sync_playwright

import qa_audio_gain_v087 as legacy_qa

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from game_studio.domain import baseline_config

AUDIO = ROOT / "web/assets/studio-v090/audio.js"

RENDER_CONFIGURED = r'''async cfg => {
    const audio = window.MahjongWildAudio;
    await audio.configure(cfg.audio);
    await audio.unlock();
    if (cfg.phase) await audio.setPhase(cfg.phase);
    if (cfg.playEvent) await audio.play(cfg.playEvent);
    if (cfg.music && cfg.enabled !== false) {
        for (let i=0; i<100 && !audio.state.musicPlaying; i++) await new Promise(resolve=>setTimeout(resolve,1));
        if (!audio.state.musicPlaying) throw Error('Configured music did not start');
    }
    const state = audio.state, after = {...localStorage};
    const samples = (await __audioQA.actual.startRendering()).getChannelData(0);
    const input = __audioQA.buffer.getChannelData(0);
    let maximumError=0, peak=0;
    for (let i=38400; i<45600; i++) maximumError=Math.max(maximumError,Math.abs(samples[i]-input[i]*cfg.expectedGain));
    for (const sample of samples) peak=Math.max(peak,Math.abs(sample));
    return {name:cfg.name,maximumError,peak,state,before:__audioQA.before,after};
}'''

PRIORITY = r'''async () => {
    const audio=window.MahjongWildAudio;
    await audio.unlock();
    for (let i=0; i<16; i++) await audio.play('stop',i%5);
    const full=audio.state;
    const low=await audio.play('tap');
    const high=await audio.play('bigwin');
    const replaced=audio.state;
    audio.stop();
    const stopped=audio.state;
    return {full,low,high,replaced,stopped};
}'''

STALE = r'''async cfg => {
    const audio=window.MahjongWildAudio;
    const source=structuredClone(cfg);
    source.events.tap.asset='/media/delayed.wav';
    let resolveDelayed;
    const originalFetch=fetch;
    window.fetch=(url,...rest)=>String(url)==='/media/delayed.wav'
        ? new Promise(resolve=>{resolveDelayed=resolve;}) : originalFetch(url,...rest);
    await audio.configure(source); await audio.unlock();
    const waiting=audio.play('tap');
    for(let i=0;i<100&&!resolveDelayed;i++) await new Promise(resolve=>setTimeout(resolve,1));
    if(!resolveDelayed) throw Error('Delayed audio was not requested');
    const changed=structuredClone(source); changed.events.tap.enabled=false;
    await audio.configure(changed);
    resolveDelayed({ok:true,arrayBuffer:async()=>new ArrayBuffer(4)});
    const result=await waiting;
    const state=audio.state;
    const invalid=structuredClone(changed); invalid.events.spin.asset='https://outside.invalid/untrusted.wav';
    let rejected=false;
    try { await audio.configure(invalid); } catch { rejected=true; }
    return {result,state,rejected,after:audio.state,preferences:{...localStorage}};
}'''

NONBLOCKING = r'''async cfg => {
    const audio=window.MahjongWildAudio;
    await audio.unlock();
    const originalFetch=fetch;
    window.fetch=(url,...rest)=>String(url)==='/media/never-arrives.wav'
        ? new Promise(()=>{}) : originalFetch(url,...rest);
    const changed=structuredClone(cfg); changed.music.base.asset='/media/never-arrives.wav';
    const result=await Promise.race([
        audio.configure(changed).then(()=>true),
        new Promise(resolve=>setTimeout(()=>resolve(false),500))
    ]);
    await audio.configure(cfg);
    return {configurationApplied:result,state:audio.state};
}'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["chromium", "webkit"], default="chromium")
    parser.add_argument("--browser")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    baseline = baseline_config()["audio"]
    results = []
    with sync_playwright() as driver:
        browser = getattr(driver, args.engine).launch(headless=True,
            **({"executable_path": args.browser} if args.browser else {}))

        def page_for(settings):
            page = browser.new_page()
            page.route("https://audio-qa.invalid/", lambda route: route.fulfill(
                status=200, content_type="text/html", body="<!doctype html><title>Studio audio QA</title>"))
            page.goto("https://audio-qa.invalid/")
            page.evaluate(legacy_qa.SETUP, settings)
            page.add_script_tag(content=AUDIO.read_text())
            return page

        # Preserve the original 30% gain, preference storage and exact silence.
        for case in legacy_qa.CASES:
            page = page_for(case)
            result = page.evaluate(legacy_qa.RENDER, case)
            assert result["maximumError"] < 1e-6, result
            if result["amplitudeRatio"] is not None:
                assert abs(result["amplitudeRatio"] - 1.3) < 1e-5, result
            else:
                assert result["peak"] == 0, result
            expected = {**result["before"]}
            if case.get("mute_after"):
                expected["mw-sfx"] = "off"
            assert result["after"] == expected, result
            assert not result["state"]["lastError"], result
            results.append(result)
            page.close()

        custom = deepcopy(baseline)
        custom["output_gain"] = 1.1
        custom["buses"]["ui"] = 1.4
        custom["events"]["tap"].update(asset="/media/custom-button.wav", gain=.6)
        disabled = deepcopy(custom)
        disabled["events"]["tap"]["enabled"] = False
        music = deepcopy(baseline)
        music["buses"]["music"] = .75
        music["music"]["bonus"] = {"asset":"/media/bonus.wav", "gain":.3, "loop_start":.1, "loop_end":.95}
        configured = [
            {"name":"custom_event_bus_and_output", "audio":custom,"volume":.37,"music_volume":.19,"music":False,
             "playEvent":"tap","expectedGain":.37*.6*1.4*1.1},
            {"name":"explicit_no_sound", "audio":disabled,"volume":.37,"music_volume":.19,"music":False,
             "playEvent":"tap","expectedGain":0},
            {"name":"bonus_music_bus_and_clip", "audio":music,"volume":.37,"music_volume":.19,"music":True,
             "phase":"bonus","expectedGain":.19*.75*.3*1.3},
            {"name":"configured_saved_mute", "audio":custom,"volume":.37,"music_volume":.19,"music":True,
             "enabled":False,"playEvent":"tap","expectedGain":0},
        ]
        for case in configured:
            page = page_for(case)
            result = page.evaluate(RENDER_CONFIGURED, case)
            assert result["maximumError"] < 1e-6, result
            assert result["after"] == result["before"], result
            assert not result["state"]["lastError"], result
            if case["expectedGain"] == 0:
                assert result["peak"] == 0, result
            results.append(result)
            page.close()

        settings = {"volume":.8,"music_volume":.28,"music":False}
        page = page_for(settings)
        priority = page.evaluate(PRIORITY)
        assert priority["full"]["voices"] == 16, priority
        assert priority["low"] is False and priority["high"] is True, priority
        assert priority["replaced"]["voices"] == 16, priority
        assert priority["replaced"]["counts"].get("bigwin") == 1, priority
        assert priority["stopped"]["voices"] == 0, priority
        page.close()
        page = page_for(settings)
        stale = page.evaluate(STALE, baseline)
        assert stale["result"] is False, stale
        assert stale["state"]["voices"] == 0 and not stale["state"]["counts"].get("tap"), stale
        assert stale["rejected"] and stale["after"]["configRevision"] == stale["state"]["configRevision"], stale
        page.close()
        page = page_for({**settings,"music":True})
        nonblocking = page.evaluate(NONBLOCKING, baseline)
        assert nonblocking["configurationApplied"], nonblocking
        page.close()
        browser.close()
    report = {"engine":args.engine,"cases":results,"priority":priority,"stale_configuration":stale,
              "missing_music_nonblocking":nonblocking,
              "physical_listening_tested":False}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
