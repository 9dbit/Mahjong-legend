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

PAGE_LIFECYCLE = r'''async fixture => {
    const audio=window.MahjongWildAudio;
    const originalFetch=fetch, requests=[], aborted=[];
    const earlyListeners=new Set(), add=window.addEventListener, remove=window.removeEventListener;
    window.addEventListener=function(type,listener,...options){
        if(type==='beforeunload') earlyListeners.add(listener);
        return add.call(this,type,listener,...options);
    };
    window.removeEventListener=function(type,listener,...options){
        if(type==='beforeunload') earlyListeners.delete(listener);
        return remove.call(this,type,listener,...options);
    };
    window.fetch=(url,options={})=>{
        requests.push(String(url));
        return new Promise((resolve,reject)=>{
            options.signal?.addEventListener('abort',()=>{
                aborted.push(String(url)); reject(new DOMException('Fixture cancelled','AbortError'));
            },{once:true});
        });
    };
    await audio.configure(fixture.audio); await audio.unlock();
    const pendingMusic=audio.setPhase('base');
    // Two requests are active; the remaining effects and music are queued.
    if(requests.length!==2) throw Error('Fixture did not fill the two-load queue');
    const listenersWhilePending=earlyListeners.size;
    if(fixture.event==='visibilitychange') {
        Object.defineProperty(document,'hidden',{configurable:true,value:true});
        document.dispatchEvent(new Event('visibilitychange'));
    } else dispatchEvent(fixture.event==='pagehide'
        ? new PageTransitionEvent('pagehide',{persisted:true}) : new Event('beforeunload'));
    const settled=await Promise.race([pendingMusic.then(()=>true),new Promise(resolve=>setTimeout(()=>resolve(false),200))]);
    const whileHidden={unlock:await audio.unlock(),play:await audio.play('tap'),music:await audio.setPhase('base')};
    await new Promise(resolve=>setTimeout(resolve,10));
    const hidden={requests:[...requests],aborted:[...aborted],state:audio.state,settled,whileHidden,
        earlyListeners:earlyListeners.size};
    window.fetch=originalFetch;
    // A BFCache restoration keeps preferences and may restart from cached or
    // newly fetched buffers. No synthetic user click is needed for this fixture.
    if(fixture.event==='visibilitychange') {
        delete document.hidden; document.dispatchEvent(new Event('visibilitychange'));
    } else dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}));
    for(let i=0;i<100&&!audio.state.musicPlaying;i++) await new Promise(resolve=>setTimeout(resolve,1));
    const restored=audio.state;
    // Once all loads finish, the temporary early-navigation listener must be
    // removed. An idle beforeunload alone must no longer suspend this mixer.
    dispatchEvent(new Event('beforeunload'));
    return {event:fixture.event,hidden,restored,listenersWhilePending,listenersAfterDrain:earlyListeners.size,
        early_listener_removed:audio.state.musicPlaying,
        before:__audioQA.before,preferences:{...localStorage},simulated_bfcache:true};
}'''

STALE_MUSIC = r'''async cfg => {
    const audio=window.MahjongWildAudio;
    const isolated=structuredClone(cfg);
    for(const event of Object.values(isolated.events)) event.enabled=false;
    const originalFetch=fetch, requests=[];
    window.fetch=(url,options={})=>{
        requests.push(String(url));
        return String(url).endsWith('jade_serenity.m4a')
            ? new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('Fixture cancelled','AbortError')),{once:true}))
            : originalFetch(url,options);
    };
    await audio.configure(isolated); await audio.unlock();
    const waiting=audio.setPhase('base');
    const replacement=structuredClone(isolated); replacement.music.base=null;
    await audio.configure(replacement);
    const result=await waiting;
    await new Promise(resolve=>setTimeout(resolve,10));
    return {result,requests,state:audio.state};
}'''

BASELINE_FALLBACK = r'''async cfg => {
    const audio=window.MahjongWildAudio;
    const isolated=structuredClone(cfg);
    for(const event of Object.values(isolated.events)) event.enabled=false;
    const originalFetch=fetch, requests=[];
    window.fetch=(url,...options)=>{
        requests.push(String(url));
        return String(url).endsWith('jade_serenity.m4a')
            ? Promise.resolve({ok:false,status:415}) : originalFetch(url,...options);
    };
    await audio.configure(isolated); await audio.unlock();
    const result=await audio.setPhase('base');
    return {result,requests,state:audio.state};
}'''


INSTANT_FIRST_CLICK = r'''async config => {
    const audio=window.MahjongWildAudio;
    await audio.configure(config);
    const warmed=await audio.warmMusic();
    const before=audio.state;
    if(!warmed || !before.musicPrepared)throw Error('BGM was not predecoded');
    if(before.unlocked || before.musicPlaying)throw Error('Autoplay before user gesture');
    await audio.unlock();
    await audio.setPhase('base');
    const after=audio.state;
    if(!after.musicPlaying)throw Error('Continue did not schedule music');
    const samples=(await __audioQA.actual.startRendering()).getChannelData(0);
    const rms=(a,b)=>{
      let sum=0,count=0;
      for(let i=Math.floor(a*48000);i<Math.floor(b*48000);i++){
        sum+=samples[i]*samples[i];count++;
      }
      return Math.sqrt(sum/count);
    };
    const first=rms(.03,.07),settled=rms(.55,.65);
    return {before,after,first,settled,ratio:first/Math.max(settled,1e-9)};
}'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["chromium", "webkit"], default="chromium")
    parser.add_argument("--browser")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    baseline = baseline_config()["audio"]
    results = []
    page_errors = []
    with sync_playwright() as driver:
        browser = getattr(driver, args.engine).launch(headless=True,
            **({"executable_path": args.browser} if args.browser else {}))

        def page_for(settings):
            page = browser.new_page()
            page.on("pageerror", lambda error: page_errors.append(str(error)))
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
        lifecycles = []
        for event in ["pagehide","beforeunload","visibilitychange"]:
            page = page_for({**settings,"music":True})
            lifecycle = page.evaluate(PAGE_LIFECYCLE, {"audio":baseline,"event":event})
            hidden = lifecycle["hidden"]
            assert hidden["settled"] and len(hidden["requests"]) == len(hidden["aborted"]) == 2, lifecycle
            assert lifecycle["listenersWhilePending"] == 1 and hidden["earlyListeners"] == lifecycle["listenersAfterDrain"] == 0, lifecycle
            assert not any(hidden["whileHidden"].values()), lifecycle
            assert hidden["state"]["loaded"] == hidden["state"]["voices"] == 0, lifecycle
            assert not hidden["state"]["musicPlaying"] and not hidden["state"]["lastError"], lifecycle
            assert lifecycle["restored"]["unlocked"] and lifecycle["restored"]["musicPlaying"], lifecycle
            assert lifecycle["early_listener_removed"], lifecycle
            assert not lifecycle["restored"]["lastError"], lifecycle
            assert lifecycle["preferences"] == lifecycle["before"], lifecycle
            lifecycles.append(lifecycle)
            page.close()
        page = page_for({**settings,"music":True})
        stale_music = page.evaluate(STALE_MUSIC, baseline)
        assert stale_music["result"] is False and len(stale_music["requests"]) == 1, stale_music
        assert stale_music["requests"][0].endswith("jade_serenity.m4a"), stale_music
        assert not stale_music["state"]["musicPlaying"] and not stale_music["state"]["lastError"], stale_music
        page.close()
        page = page_for({**settings,"music":True})
        fallback = page.evaluate(BASELINE_FALLBACK, baseline)
        assert fallback["result"] and fallback["state"]["musicPlaying"], fallback
        assert [Path(url).suffix for url in fallback["requests"]] == [".m4a",".ogg"], fallback
        assert not fallback["state"]["lastError"], fallback
        page.close()
        # With a decoded buffer, music begins at full audible gain during
        # the FIRST 30-70ms, rather than ramping in over the old 650ms.
        page = page_for({**settings,"music":True})
        instant = page.evaluate(INSTANT_FIRST_CLICK, baseline)
        assert instant["before"]["musicPrepared"] and not instant["before"]["unlocked"], instant
        assert not instant["before"]["musicPlaying"] and instant["after"]["musicPlaying"], instant
        assert instant["ratio"] > .9, instant
        assert instant["after"]["musicStartedAt"] is not None, instant
        page.close()
        assert not page_errors, page_errors
        browser.close()
    report = {"engine":args.engine,"cases":results,"instant_continue":instant,"priority":priority,"stale_configuration":stale,
              "missing_music_nonblocking":nonblocking,
              "page_lifecycle":lifecycles,"stale_music_no_fallback":stale_music,
              "baseline_fallback":fallback,"page_errors":page_errors,
              "physical_listening_tested":False}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
