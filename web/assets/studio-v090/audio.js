/* Mahjong Wild 0.9.0: immutable release audio, gesture unlock and bounded voices. */
(() => {
  'use strict';
  const MAX_VOICES = 16, MAX_BUFFERS = 24, MAX_DECODED_BYTES = 48 * 1024 * 1024;
  const MAX_FILE_BYTES = 32 * 1024 * 1024;
  const files = {spin:'spin',stop:'reel_stop',cascade:'cascade',break:'tile_break',wild:'wild',
    multiplier:'multiplier',scatter:'scatter',bonus:'bonus',win:'win',tap:'button',bigwin:'win'};
  const priorities = {tap:10,spin:40,stop:50,break:45,cascade:45,scatter:65,wild:70,multiplier:70,win:90,bigwin:100,bonus:100};
  const cooldowns = {tap:24,break:12,cascade:12};
  const baselineMusic = '/assets/approved-v082/audio/jade_serenity.m4a';
  const get = (key, fallback) => {try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }};
  const put = (key, value) => {try { localStorage.setItem(key, String(value)); } catch {}};
  const clamp = (value, fallback=.5) => Number.isFinite(Number(value)) ? Math.max(0, Math.min(1, Number(value))) : fallback;
  let enabled = get('mw-sfx', 'on') !== 'off', volume = clamp(get('mw-volume', '.8'));
  let musicEnabled = get('mw-music', 'on') === 'on', musicVolume = clamp(get('mw-music-volume', '.28'));
  let config = {
    output_gain:1.30, buses:{music:1,reels:1,wins:1,ui:1},
    events:Object.fromEntries(Object.entries(files).map(([event, file]) => [event, {
      asset:`/assets/audio/sfx/${file}.wav`, gain:event==='tap'?.8:event==='break'?.85:.7,
      bus:event==='tap'?'ui':['win','bigwin','bonus'].includes(event)?'wins':'reels', enabled:true
    }])),
    music:{base:{asset:baselineMusic,gain:1,loop_start:0,loop_end:null},bonus:null}
  };
  let context = null, unlocked = false, epoch = 0, configRevision = 0, phase = 'base';
  let sfxBus = null, musicBus = null, duckBus = null, outputBus = null, analyser = null;
  let musicSource = null, musicTask = null, musicEpoch = 0, unlockPending = null;
  let lastError = '', droppedVoices = 0, activeLoads = 0;
  const buses = {}, buffers = new Map(), pending = new Map(), queue = [], voices = new Set();
  const counts = {}, lastPlayed = new Map();

  function finite(value, low, high, name) {
    if (typeof value === 'boolean' || value === null || value === '' || !Number.isFinite(Number(value)) || Number(value) < low || Number(value) > high)
      throw new Error(`Invalid audio ${name}`);
    return Number(value);
  }
  function asset(value) {
    if (typeof value !== 'string' || value.length > 600) throw new Error('Invalid audio asset');
    const parsed = new URL(value, location.href);
    if (parsed.origin !== location.origin || !['http:','https:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.hash)
      throw new Error('Audio assets must use this site');
    return parsed.pathname + parsed.search;
  }
  function normalize(input) {
    if (!input || !input.buses || !input.events || !input.music) throw new Error('Incomplete audio configuration');
    const next = {output_gain:finite(input.output_gain,0,2,'output gain'),buses:{},events:{},music:{}};
    for (const key of ['music','reels','wins','ui']) next.buses[key] = finite(input.buses[key],0,2,`${key} bus`);
    for (const name of Object.keys(files)) {
      const event = input.events[name];
      if (!event || typeof event.enabled !== 'boolean' || !['reels','wins','ui'].includes(event.bus))
        throw new Error(`Invalid audio event ${name}`);
      next.events[name] = {asset:event.enabled?asset(event.asset):null,
        gain:finite(event.gain,0,2,`${name} gain`),bus:event.bus,enabled:event.enabled};
    }
    for (const name of ['base','bonus']) {
      const music = input.music[name];
      if (music == null) { next.music[name] = null; continue; }
      const start = finite(music.loop_start ?? 0,0,120,'loop start');
      const end = music.loop_end == null ? null : finite(music.loop_end,0,120,'loop end');
      if (end !== null && end <= start) throw new Error('Audio loop end must follow start');
      next.music[name] = {asset:asset(music.asset),gain:finite(music.gain,0,2,'music gain'),loop_start:start,loop_end:end};
    }
    return next;
  }
  function applyLevels() {
    if (!context) return;
    const now = context.currentTime;
    sfxBus.gain.cancelScheduledValues(now); sfxBus.gain.setValueAtTime(enabled?volume:0, now);
    musicBus.gain.cancelScheduledValues(now); musicBus.gain.setValueAtTime(enabled?musicVolume*config.buses.music:0, now);
    outputBus.gain.value = config.output_gain; // The v0.8.7 1.30 boost appears exactly once.
    for (const name of ['reels','wins','ui']) buses[name].gain.value = config.buses[name];
  }
  function ensureContext() {
    if (context) return true;
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) { lastError = 'Audio tidak didukung'; return false; }
    context = new Audio();
    sfxBus = context.createGain(); musicBus = context.createGain(); duckBus = context.createGain();
    outputBus = context.createGain(); analyser = context.createAnalyser(); analyser.fftSize = 256;
    for (const name of ['reels','wins','ui']) { buses[name] = context.createGain(); buses[name].connect(sfxBus); }
    sfxBus.connect(outputBus); musicBus.connect(duckBus); duckBus.connect(outputBus);
    outputBus.connect(analyser); analyser.connect(context.destination); applyLevels();
    return true;
  }
  function activeURLs() {
    const urls = new Set([...voices].map(voice => voice.url));
    if (musicSource) urls.add(musicSource.url);
    return urls;
  }
  function decodedBytes() { return [...buffers.values()].reduce((total, entry) => total + entry.bytes, 0); }
  function cache(url, buffer) {
    const bytes = buffer.length * buffer.numberOfChannels * 4;
    if (bytes > MAX_DECODED_BYTES) throw new Error('Audio asset exceeds decoded memory budget');
    buffers.delete(url); buffers.set(url, {buffer,bytes});
    const protectedURLs = activeURLs();
    for (const key of [...buffers.keys()]) {
      if (buffers.size <= MAX_BUFFERS && decodedBytes() <= MAX_DECODED_BYTES) break;
      if (!protectedURLs.has(key)) buffers.delete(key);
    }
    if (!buffers.has(url)) throw new Error('Audio cache is full; active sounds were preserved');
    return buffer;
  }
  async function readBytes(response) {
    const size = Number(response.headers?.get('Content-Length') || 0);
    if (size > MAX_FILE_BYTES) throw new Error('Audio file exceeds upload limit');
    if (!response.body?.getReader) {
      const bytes = await response.arrayBuffer();
      if (bytes.byteLength > MAX_FILE_BYTES) throw new Error('Audio file exceeds upload limit');
      return bytes;
    }
    const reader = response.body.getReader(), chunks = []; let total = 0;
    try {
      while (true) {
        const {done,value} = await reader.read(); if (done) break;
        total += value.byteLength;
        if (total > MAX_FILE_BYTES) throw new Error('Audio file exceeds upload limit');
        chunks.push(value);
      }
    } catch (error) { await reader.cancel().catch(()=>{}); throw error; }
    finally { reader.releaseLock(); }
    const bytes = new Uint8Array(total); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return bytes.buffer;
  }
  function pump() {
    while (activeLoads < 2 && queue.length) {
      const task = queue.shift(); activeLoads++;
      void task().finally(() => { activeLoads--; pump(); });
    }
  }
  function load(url, reportError=true) {
    if (!context) return Promise.resolve(null);
    if (buffers.has(url)) { const hit = buffers.get(url); buffers.delete(url); buffers.set(url, hit); return Promise.resolve(hit.buffer); }
    if (pending.has(url)) return pending.get(url).promise;
    const revision = configRevision, controller = new AbortController();
    let finish;
    const promise = new Promise(resolve => { finish = resolve; });
    const entry = {controller,promise}; pending.set(url, entry);
    queue.push(async () => {
      let result = null, deadline = null, timedOut = false, cancel = null;
      try {
        if (revision !== configRevision || controller.signal.aborted) return;
        const aborted = new Promise((_, reject) => {
          cancel = () => reject(new DOMException('Audio load cancelled', 'AbortError'));
          controller.signal.addEventListener('abort', cancel, {once:true});
        });
        deadline = setTimeout(() => { timedOut = true; controller.abort(); }, 8000);
        const response = await Promise.race([fetch(url, {signal:controller.signal, credentials:'same-origin'}), aborted]);
        if (!response.ok) throw new Error(`Audio ${response.status}`);
        const data = await Promise.race([readBytes(response), aborted]);
        if (revision !== configRevision || controller.signal.aborted) return;
        const buffer = await Promise.race([context.decodeAudioData(data), aborted]);
        if (revision !== configRevision || controller.signal.aborted) return;
        result = cache(url, buffer);
      } catch (error) {
        if (reportError && revision === configRevision && (error.name !== 'AbortError' || timedOut))
          lastError = timedOut?'Audio load timed out':error.message;
      } finally {
        if (deadline !== null) clearTimeout(deadline);
        if (cancel) controller.signal.removeEventListener('abort', cancel);
        if (pending.get(url) === entry) pending.delete(url);
        finish(result);
      }
    });
    pump(); return promise;
  }
  function preload() {
    // Only this release's game effects. Studio's entire library is never loaded.
    if (!context || !enabled || !unlocked) return;
    for (const url of new Set(Object.values(config.events).filter(event => event.enabled).map(event => event.asset))) void load(url);
  }
  function releaseVoice(voice) {
    voices.delete(voice);
    try { voice.source.stop(); } catch {}
    try { voice.source.disconnect(); voice.gain.disconnect(); } catch {}
  }
  function stop() {
    epoch++;
    for (const voice of [...voices]) releaseVoice(voice);
    lastPlayed.clear();
    if (duckBus) { duckBus.gain.cancelScheduledValues(context.currentTime); duckBus.gain.value = 1; }
  }
  function pauseMusic() {
    musicEpoch++; musicTask = null;
    if (musicSource) {
      const old = musicSource; musicSource = null;
      try { old.source.stop(); } catch {}
      old.source.disconnect(); old.gain.disconnect();
    }
  }
  function selectedMusic() { return config.music[phase] || config.music.base; }
  function musicKey(track) { return track ? JSON.stringify(track) : ''; }
  function startMusic() {
    const track = selectedMusic(), key = musicKey(track);
    if (!track || !unlocked || !enabled || !musicEnabled || document.hidden || context?.state !== 'running') return Promise.resolve(false);
    if (musicSource?.key === key) return Promise.resolve(true);
    if (musicTask?.key === key) return musicTask.promise;
    const generation = musicEpoch, revision = configRevision;
    const task = {key,promise:null};
    task.promise = (async () => {
      let url = track.asset;
      let buffer = await load(url, url !== baselineMusic);
      if (!buffer && url === baselineMusic) { url = baselineMusic.replace('.m4a','.ogg'); buffer = await load(url); }
      if (!buffer || generation !== musicEpoch || revision !== configRevision || musicKey(selectedMusic()) !== key ||
          !enabled || !musicEnabled || !unlocked || document.hidden || context.state !== 'running') return false;
      const end = track.loop_end ?? buffer.duration;
      if (track.loop_start >= end || end > buffer.duration + .001) { lastError = 'Music loop exceeds clip duration'; return false; }
      // Keep the old track while the replacement loads, then replace it once.
      if (musicSource) {
        const old = musicSource; musicSource = null;
        try { old.source.stop(); } catch {}
        old.source.disconnect(); old.gain.disconnect();
      }
      const source = context.createBufferSource(), gain = context.createGain();
      source.buffer = buffer; source.loop = true; source.loopStart = track.loop_start; source.loopEnd = end;
      source.connect(gain); gain.connect(musicBus);
      const now = context.currentTime; gain.gain.setValueAtTime(0, now); gain.gain.linearRampToValueAtTime(track.gain, now + .65);
      const record = {source,gain,url,key}; musicSource = record;
      source.onended = () => { if (musicSource === record) musicSource = null; source.disconnect(); gain.disconnect(); };
      source.start(); return true;
    })().finally(() => { if (musicTask === task) musicTask = null; });
    musicTask = task; return task.promise;
  }
  function unlock() {
    if (!ensureContext()) return Promise.resolve(false);
    // Resume synchronously in the pointer/key handler, before any fetch await.
    const resume = context.state === 'running' ? Promise.resolve() : context.resume();
    if (!unlockPending) unlockPending = Promise.resolve(resume).then(() => {
      unlocked = context.state === 'running'; preload(); void startMusic(); return unlocked;
    }).catch(error => { lastError = error.message; return false; }).finally(() => { unlockPending = null; });
    return unlockPending;
  }
  function duckMusic() {
    if (!duckBus || !musicSource) return;
    const now = context.currentTime;
    duckBus.gain.cancelScheduledValues(now); duckBus.gain.setValueAtTime(duckBus.gain.value, now);
    duckBus.gain.linearRampToValueAtTime(.7, now+.025);
    duckBus.gain.setValueAtTime(.7, now+.18); duckBus.gain.linearRampToValueAtTime(1, now+.55);
  }
  async function play(type, variation=0) {
    const event = config.events[type];
    if (!event?.enabled || !enabled || volume === 0 || document.hidden || !context) return false;
    const generation = epoch, revision = configRevision;
    if (unlockPending) await unlockPending;
    const buffer = await load(event.asset);
    if (generation !== epoch || revision !== configRevision || !buffer || !enabled || volume === 0 ||
        document.hidden || context.state !== 'running') return false;
    const now = context.currentTime, previous = lastPlayed.get(type);
    if (previous !== undefined && (now - previous) * 1000 < (cooldowns[type] || 0)) return false;
    const priority = priorities[type] || 40;
    if (voices.size >= MAX_VOICES) {
      const victim = [...voices].sort((a,b) => a.priority-b.priority || a.started-b.started)[0];
      if (victim.priority >= priority) { droppedVoices++; return false; }
      releaseVoice(victim); droppedVoices++;
    }
    const source = context.createBufferSource(), gain = context.createGain(); source.buffer = buffer;
    source.playbackRate.value = type === 'stop' ? 1 + Math.max(0, Math.min(4, Number(variation) || 0)) * .025 : 1;
    gain.gain.value = event.gain; source.connect(gain); gain.connect(buses[event.bus]);
    const voice = {source,gain,url:event.asset,priority,started:now}; voices.add(voice);
    counts[type] = (counts[type] || 0) + 1; lastPlayed.set(type, now);
    source.onended = () => { voices.delete(voice); source.disconnect(); gain.disconnect(); };
    if (priority >= 90) duckMusic();
    source.start(); return true;
  }
  async function configure(input) {
    const next = normalize(input); // An invalid config leaves the working mixer intact.
    if (JSON.stringify(next) === JSON.stringify(config)) return true;
    stop(); pauseMusic(); configRevision++;
    for (const entry of pending.values()) entry.controller.abort();
    pending.clear(); buffers.clear(); config = next; lastError = ''; applyLevels();
    // Applying a release must never wait for an audio download to finish a round.
    preload(); void startMusic(); return true;
  }
  async function setPhase(value) {
    if (!['base','bonus'].includes(value)) return false;
    if (phase === value) return startMusic();
    const oldKey = musicKey(selectedMusic()); phase = value;
    if (!selectedMusic()) { pauseMusic(); return false; }
    if (oldKey !== musicKey(selectedMusic())) { musicEpoch++; musicTask = null; }
    return startMusic();
  }
  function setEnabled(value) {
    enabled = !!value; put('mw-sfx', enabled?'on':'off'); applyLevels();
    if (!enabled) { stop(); pauseMusic(); } else void unlock();
  }
  function setVolume(value) { volume = clamp(value); put('mw-volume', volume); applyLevels(); }
  function toggleMusic() {
    musicEnabled = !musicEnabled; put('mw-music', musicEnabled?'on':'off');
    if (musicEnabled) void unlock(); else pauseMusic(); return musicEnabled;
  }
  function setMusicVolume(value) { musicVolume = clamp(value); put('mw-music-volume', musicVolume); applyLevels(); }
  function level() {
    if (!analyser) return 0;
    const data = new Float32Array(analyser.fftSize); analyser.getFloatTimeDomainData(data);
    return Math.sqrt(data.reduce((total,sample) => total+sample*sample,0)/data.length);
  }
  document.addEventListener('pointerdown', () => void unlock(), {passive:true});
  document.addEventListener('keydown', () => void unlock());
  document.addEventListener('visibilitychange', () => {if (document.hidden) { stop(); pauseMusic(); } else if (unlocked) void unlock();});
  window.addEventListener('pagehide', () => { stop(); pauseMusic(); });
  window.MahjongWildAudio = {play,unlock,stop,configure,setPhase,setEnabled,setVolume,toggleMusic,setMusicVolume,
    get state() { return {enabled,volume,musicEnabled,musicVolume,outputGain:config.output_gain,unlocked,
      context:context?.state??'not-created',loaded:buffers.size,voices:voices.size,musicPlaying:!!musicSource,
      level:level(),counts:{...counts},lastError,phase,configRevision,decodedBytes:decodedBytes(),droppedVoices,
      musicAsset:musicSource?.url??null,buses:{...config.buses}}; }};
})();
