/* Mahjong Legend: one gesture-unlocked graph, original gentle oriental score. */
(() => {
  'use strict';
  const get=(key,fallback)=>{try{return localStorage.getItem(key)??fallback;}catch{return fallback;}};
  const put=(key,value)=>{try{localStorage.setItem(key,String(value));}catch{}};
  const clamp=(v,fallback)=>Number.isFinite(Number(v))?Math.max(0,Math.min(1,Number(v))):fallback;
  let enabled=get('mw-sfx','on')!=='off',volume=clamp(get('mw-volume','.65'),.65);
  // Only missing preferences receive the new default; saved OFF is respected.
  let musicEnabled=get('mw-music','on')==='on',musicVolume=clamp(get('mw-music-volume','.22'),.22);
  let context=null,bus=null,analyser=null,musicGain=null,reelGain=null;
  let unlocked=false,gestureSeen=false,epoch=0,contextEpoch=0,resumePromise=null,resumeFailed=false;
  let musicSource=null,musicStarting=null,musicOffset=0,musicStartedAt=0,reelSource=null,reelWanted=false;
  let status='locked',lastError='',musicToken=0,reelToken=0;
  const sources=new Set(),buffers=new Map(),pending=new Map(),bytes=new Map(),played={},stamps=new Map();
  const base='/assets/audio/oriental-v082/';
  const names={spin:'spin',stop:'reel_stop',cascade:'cascade',crack:'crack',break:'tile_break',wild:'wild',multiplier:'multiplier',scatter:'scatter',bonus:'bonus',win:'win',tap:'button',bigwin:'bigwin'};
  const levels={spin:.85,stop:.66,cascade:.64,crack:.67,break:.88,wild:.7,multiplier:.69,scatter:.64,bonus:.69,win:.67,tap:.7,bigwin:.72};
  function request(name){
    if(!bytes.has(name))bytes.set(name,fetch(`${base}${name}.wav`).then(r=>{if(!r.ok)throw Error(`Audio HTTP ${r.status}`);return r.arrayBuffer();}).catch(()=>null));
    return bytes.get(name);
  }
  for(const name of [...new Set(Object.values(names)),'jade_garden_loop','reel_roll'])void request(name);
  function rms(){if(!analyser||context?.state!=='running')return 0;const data=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(data);return Math.sqrt(data.reduce((sum,v)=>sum+v*v,0)/data.length);}
  function state(){return{enabled,volume,musicEnabled,musicVolume,unlocked,context:context?.state??'not-created',loaded:buffers.size,voices:sources.size,musicPlaying:!!musicSource&&context?.state==='running',musicLoops:musicSource?1:0,reelPlaying:!!reelSource,status,lastError,levelRms:rms(),played:{...played}};}
  function notify(){window.dispatchEvent(new CustomEvent('mw-audio-state',{detail:state()}));}
  function fail(message){lastError=message;status='blocked';notify();}
  function graph(){
    const C=window.AudioContext||window.webkitAudioContext;
    if(!C){status='unavailable';lastError='Browser tidak mendukung Web Audio.';notify();return false;}
    try{
      context=new C({latencyHint:'interactive'});contextEpoch++;bus=context.createGain();bus.gain.value=.9;
      const limiter=context.createDynamicsCompressor();limiter.threshold.value=-9;limiter.knee.value=8;limiter.ratio.value=3;limiter.attack.value=.003;limiter.release.value=.12;
      analyser=context.createAnalyser();analyser.fftSize=1024;bus.connect(limiter).connect(analyser).connect(context.destination);
      musicGain=context.createGain();musicGain.gain.value=musicVolume;musicGain.connect(bus);
      reelGain=context.createGain();reelGain.gain.value=volume*.45;reelGain.connect(bus);
      context.onstatechange=()=>{unlocked=context.state==='running';status=unlocked?'ready':gestureSeen?'blocked':'locked';notify();};
      return true;
    }catch{status='unavailable';lastError='Audio belum dapat dimulai.';notify();return false;}
  }
  async function load(name){
    if(buffers.has(name))return buffers.get(name);
    if(!context)return null;
    if(!pending.has(name)){
      const decoder=context;
      pending.set(name,(async()=>{const data=await request(name);if(!data)return null;try{const buffer=await decoder.decodeAudioData(data.slice(0));buffers.set(name,buffer);return buffer;}catch{return null;}})());
    }
    const result=await pending.get(name);
    if(!result){pending.delete(name);bytes.delete(name);}
    return result;
  }
  function ramp(param,value,time=.045){if(!context)return;param.cancelScheduledValues(context.currentTime);param.setTargetAtTime(value,context.currentTime,time);}
  function pauseMusic(){
    musicToken++;
    if(musicSource){musicOffset=(musicOffset+Math.max(0,context.currentTime-musicStartedAt))%musicSource.buffer.duration;try{musicSource.stop();}catch{}musicSource.disconnect();musicSource=null;}
    notify();
  }
  function startMusic(){
    if(!enabled||!musicEnabled||musicVolume===0||document.hidden||context?.state!=='running'||musicSource)return Promise.resolve(false);
    if(musicStarting)return musicStarting;
    const token=musicToken,generation=contextEpoch;
    musicStarting=(async()=>{
      const buffer=await load('jade_garden_loop');
      if(token!==musicToken||generation!==contextEpoch||!enabled||!musicEnabled||document.hidden||context?.state!=='running')return false;
      if(!buffer){fail('Musik gagal dimuat. Ketuk Tes Suara untuk mencoba lagi.');return false;}
      const source=context.createBufferSource();source.buffer=buffer;source.loop=true;source.connect(musicGain);
      musicGain.gain.setValueAtTime(0,context.currentTime);ramp(musicGain.gain,musicVolume,.22);
      musicStartedAt=context.currentTime;musicSource=source;source.start(0,musicOffset%buffer.duration);lastError='';notify();return true;
    })().finally(()=>{
      musicStarting=null;
      // A quick hide/show or OFF/ON while decoding must not strand the loop.
      if(token!==musicToken&&enabled&&musicEnabled&&!document.hidden&&context?.state==='running')void startMusic();
    });
    return musicStarting;
  }
  function unlock(){
    gestureSeen=true;
    try{if(navigator.audioSession)navigator.audioSession.type='playback';}catch{}
    if(resumeFailed&&context?.state!=='running'){
      stop();pauseMusic();void context.close().catch(()=>{});context=null;resumePromise=null;resumeFailed=false;pending.clear();
    }
    if(!context&&!graph())return Promise.resolve(false);
    if(context.state==='running'){unlocked=true;status='ready';void startMusic();return Promise.resolve(true);}
    if(resumePromise)return resumePromise;
    const target=context;
    // Resume and silent pulse stay synchronous inside the real tap or key gesture.
    let resumed;
    try{resumed=target.resume();const pulse=target.createBufferSource();pulse.buffer=target.createBuffer(1,1,target.sampleRate);pulse.connect(bus);pulse.onended=()=>pulse.disconnect();pulse.start(0);}catch{resumed=Promise.reject(Error('resume'));}
    let timeout;
    resumePromise=Promise.race([Promise.resolve(resumed),new Promise((_,reject)=>{timeout=setTimeout(()=>reject(Error('timeout')),1200);})]).then(()=>{
      if(target!==context)return false;
      unlocked=target.state==='running';resumeFailed=!unlocked;status=unlocked?'ready':'blocked';
      if(unlocked){lastError='';for(const name of Object.values(names))void load(name);void startMusic();}
      else lastError='Ketuk Tes Suara untuk mengaktifkan audio.';
      notify();return unlocked;
    }).catch(()=>{resumeFailed=true;unlocked=false;fail('Ketuk Tes Suara untuk mengaktifkan audio.');return false;}).finally(()=>{clearTimeout(timeout);resumePromise=null;});
    return resumePromise;
  }
  async function play(type,variation=0){
    if(!enabled||volume===0||document.hidden||!gestureSeen)return false;
    const generation=epoch,requestedAt=performance.now();
    if(context?.state!=='running'&&!(await unlock()))return false;
    const key=names[type]||'button',buffer=await load(key);
    if(generation!==epoch||!enabled||document.hidden||context?.state!=='running'||performance.now()-requestedAt>1000)return false;
    if(!buffer){fail('Efek suara gagal dimuat. Ketuk Tes Suara untuk mencoba lagi.');return false;}
    if(sources.size>=16)return false;
    const previous=stamps.get(type)||-Infinity;
    if(performance.now()-previous<(type==='tap'?40:16))return false;
    stamps.set(type,performance.now());
    const source=context.createBufferSource(),gain=context.createGain();source.buffer=buffer;
    source.playbackRate.value=type==='stop'?1+Math.min(4,variation)*.022:1;
    gain.gain.value=volume*(levels[type]??.65);source.connect(gain).connect(bus);sources.add(source);
    source.onended=()=>{sources.delete(source);source.disconnect();gain.disconnect();};
    source.start();played[type]=(played[type]||0)+1;lastError='';status='ready';notify();return true;
  }
  async function startReel(){
    reelWanted=true;const token=++reelToken,generation=epoch;
    if(!enabled||!volume||document.hidden||!gestureSeen)return;
    if(context?.state!=='running'&&!(await unlock()))return;
    const buffer=await load('reel_roll');
    if(!buffer||!reelWanted||token!==reelToken||generation!==epoch||!enabled||document.hidden||reelSource)return;
    reelSource=context.createBufferSource();reelSource.buffer=buffer;reelSource.loop=true;reelSource.connect(reelGain);
    reelGain.gain.setValueAtTime(0,context.currentTime);ramp(reelGain.gain,volume*.45,.09);reelSource.start();notify();
  }
  function stopReel(){reelWanted=false;reelToken++;if(reelSource){const source=reelSource;reelSource=null;ramp(reelGain.gain,0,.035);try{source.stop(context.currentTime+.12);}catch{}source.onended=()=>source.disconnect();}notify();}
  function stop(){epoch++;stopReel();for(const source of sources){try{source.stop();}catch{}}sources.clear();}
  function setEnabled(value){enabled=!!value;put('mw-sfx',enabled?'on':'off');if(!enabled){stop();pauseMusic();}else{void unlock();void startMusic();}notify();}
  function setVolume(value){volume=clamp(value,volume);put('mw-volume',volume);if(reelGain)ramp(reelGain.gain,volume*.45);if(!volume)stop();notify();}
  function toggleMusic(){musicEnabled=!musicEnabled;put('mw-music',musicEnabled?'on':'off');if(musicEnabled){void unlock();void startMusic();}else pauseMusic();notify();return musicEnabled;}
  function setMusicVolume(value){musicVolume=clamp(value,musicVolume);put('mw-music-volume',musicVolume);if(musicGain)ramp(musicGain.gain,musicVolume);if(!musicVolume)pauseMusic();else void startMusic();notify();}
  async function test(){if(!enabled){lastError='Aktifkan Suara Game sebelum tes.';notify();return false;}if(!volume){lastError='Naikkan volume efek suara sebelum tes.';notify();return false;}if(!(await unlock()))return false;void startMusic();return play('win');}
  const gesture=e=>{if(e.isTrusted!==false&&!document.hidden)void unlock();};
  document.addEventListener('pointerdown',gesture,{passive:true,capture:true});
  document.addEventListener('touchend',gesture,{passive:true,capture:true});
  document.addEventListener('click',gesture,{capture:true});
  document.addEventListener('keydown',gesture,{capture:true});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){stop();pauseMusic();}else if(gestureSeen)void unlock();});
  window.addEventListener('pagehide',()=>{stop();pauseMusic();});
  window.addEventListener('pageshow',()=>{if(gestureSeen&&!document.hidden)void unlock();});
  window.MahjongWildAudio={play,unlock,stop,startReel,stopReel,setEnabled,setVolume,toggleMusic,setMusicVolume,test,get state(){return state();}};
})();
