/* Mahjong Wild 0.8.2: gesture-unlocked shared mixer. Original music + local SFX. */
(() => {
  'use strict';
  const get=(key,fallback)=>{try{return localStorage.getItem(key)??fallback;}catch{return fallback;}};
  const put=(key,value)=>{try{localStorage.setItem(key,String(value));}catch{}};
  const clamp=(v,f=.5)=>Number.isFinite(Number(v))?Math.max(0,Math.min(1,Number(v))):f;
  let enabled=get('mw-sfx','on')!=='off',volume=clamp(get('mw-volume','.8'));
  let musicEnabled=get('mw-music','on')==='on',musicVolume=clamp(get('mw-music-volume','.28'));
  let context=null,unlocked=false,epoch=0,musicSource=null,musicPending=null,unlockPending=null,sfxBus=null,musicBus=null,analyser=null,lastError='';
  const buffers=new Map(),sources=new Set(),pending=new Map(),bytes=new Map();
  const names={spin:'spin',stop:'reel_stop',cascade:'cascade',break:'tile_break',wild:'wild',multiplier:'multiplier',scatter:'scatter',bonus:'bonus',win:'win',tap:'button',bigwin:'win'};
  const counts={};
  for(const name of new Set(Object.values(names))){
    bytes.set(name,fetch(`/assets/audio/sfx/${name}.wav`).then(r=>{if(!r.ok)throw Error('SFX '+r.status);return r.arrayBuffer();}).catch(e=>{lastError=e.message;return null;}));
  }
  function ensureContext(){
    if(context)return true;
    const C=window.AudioContext||window.webkitAudioContext;if(!C){lastError='Audio tidak didukung';return false;}
    context=new C();sfxBus=context.createGain();musicBus=context.createGain();analyser=context.createAnalyser();analyser.fftSize=256;
    sfxBus.gain.value=enabled?volume:0;musicBus.gain.value=enabled?musicVolume:0;
    sfxBus.connect(analyser);musicBus.connect(analyser);analyser.connect(context.destination);
    return true;
  }
  async function load(name){
    if(buffers.has(name))return buffers.get(name);if(!context)return null;
    if(!pending.has(name))pending.set(name,(async()=>{try{const data=await bytes.get(name);if(!data)return null;const b=await context.decodeAudioData(data.slice(0));buffers.set(name,b);return b;}catch(e){lastError=e.message;return null;}})());
    return pending.get(name);
  }
  async function musicBuffer(){
    if(!musicPending)musicPending=(async()=>{
      for(const ext of ['m4a','ogg'])try{const r=await fetch('/assets/approved-v082/audio/jade_serenity.'+ext);if(!r.ok)continue;return await context.decodeAudioData(await r.arrayBuffer());}catch(e){lastError=e.message;}
      musicPending=null;return null;
    })();return musicPending;
  }
  function pauseMusic(){if(musicSource){try{musicSource.stop();}catch{}musicSource.disconnect();musicSource=null;}}
  async function startMusic(){
    if(!unlocked||!enabled||!musicEnabled||document.hidden||musicSource)return;
    const b=await musicBuffer();if(!b||!unlocked||!enabled||!musicEnabled||document.hidden||musicSource||context?.state!=='running')return;
    const src=context.createBufferSource();src.buffer=b;src.loop=true;src.connect(musicBus);musicSource=src;
    musicBus.gain.cancelScheduledValues(context.currentTime);musicBus.gain.setValueAtTime(0,context.currentTime);musicBus.gain.linearRampToValueAtTime(musicVolume,context.currentTime+.65);src.start();
  }
  function unlock(){
    if(!ensureContext())return Promise.resolve(false);
    // resume is called synchronously inside the user gesture, not after fetch/decode.
    const resume=context.state==='running'?Promise.resolve():context.resume();
    if(!unlockPending)unlockPending=Promise.resolve(resume).then(()=>{
      unlocked=context.state==='running';for(const name of bytes.keys())void load(name);void startMusic();return unlocked;
    }).catch(e=>{lastError=e.message;return false;}).finally(()=>{unlockPending=null;});
    return unlockPending;
  }
  async function play(type,variation=0){
    if(!enabled||volume===0||document.hidden||!context)return;
    const generation=epoch;if(unlockPending)await unlockPending;
    const buffer=await load(names[type]||'button');
    if(generation!==epoch||!buffer||!enabled||document.hidden||sources.size>=16||context.state!=='running')return;
    const source=context.createBufferSource(),gain=context.createGain();source.buffer=buffer;
    source.playbackRate.value=type==='stop'?1+Math.min(4,variation)*.025:1;
    gain.gain.value=type==='tap'?.8:type==='break'?.85:.7;
    source.connect(gain).connect(sfxBus);sources.add(source);counts[type]=(counts[type]||0)+1;
    source.onended=()=>{sources.delete(source);source.disconnect();gain.disconnect();};source.start();
  }
  function stop(){epoch++;for(const s of sources){try{s.stop();}catch{}}sources.clear();}
  function setEnabled(value){enabled=!!value;put('mw-sfx',enabled?'on':'off');if(sfxBus)sfxBus.gain.value=enabled?volume:0;if(musicBus)musicBus.gain.value=enabled?musicVolume:0;if(!enabled){stop();pauseMusic();}else void unlock();}
  function setVolume(value){volume=clamp(value);put('mw-volume',volume);if(sfxBus)sfxBus.gain.value=enabled?volume:0;}
  function toggleMusic(){musicEnabled=!musicEnabled;put('mw-music',musicEnabled?'on':'off');if(musicEnabled)void unlock();else pauseMusic();return musicEnabled;}
  function setMusicVolume(value){musicVolume=clamp(value);put('mw-music-volume',musicVolume);if(musicBus)musicBus.gain.setTargetAtTime(enabled?musicVolume:0,context.currentTime,.08);}
  function level(){if(!analyser)return 0;const data=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(data);return Math.sqrt(data.reduce((sum,x)=>sum+x*x,0)/data.length);}
  document.addEventListener('pointerdown',()=>void unlock(),{passive:true});document.addEventListener('keydown',()=>void unlock());
  document.addEventListener('visibilitychange',()=>{if(document.hidden){stop();pauseMusic();}else if(unlocked)void unlock();});
  window.addEventListener('pagehide',()=>{stop();pauseMusic();});
  window.MahjongWildAudio={play,unlock,stop,setEnabled,setVolume,toggleMusic,setMusicVolume,get state(){return{enabled,volume,musicEnabled,musicVolume,unlocked,context:context?.state??'not-created',loaded:buffers.size,voices:sources.size,musicPlaying:!!musicSource,level:level(),counts:{...counts},lastError};}};
})();
