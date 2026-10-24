/* Original, existing sound files. One WebAudio context unlocked by a real gesture. */
(() => {
  'use strict';
  const get=(key,fallback)=>{try{return localStorage.getItem(key)??fallback;}catch{return fallback;}};
  const put=(key,value)=>{try{localStorage.setItem(key,String(value));}catch{}};
  let enabled=get('mw-sfx','on')!=='off';
  let volume=Math.max(0,Math.min(1,Number(get('mw-volume','.65'))||0));
  let musicEnabled=get('mw-music','off')==='on';
  let musicVolume=Math.max(0,Math.min(1,Number(get('mw-music-volume','.2'))||0));
  let context=null,unlocked=false,epoch=0;
  const buffers=new Map(),sources=new Set(),pending=new Map();
  const names={spin:'spin',stop:'reel_stop',cascade:'cascade',break:'tile_break',wild:'wild',multiplier:'multiplier',scatter:'scatter',bonus:'bonus',win:'win',tap:'button',bigwin:'win'};
  const music=new Audio('/assets/audio/music/ambient_jade_loop.m4a');
  music.loop=true;music.preload='none';music.volume=musicVolume;
  const bytes=new Map();
  for(const name of new Set(Object.values(names))){
    const request=fetch(`/assets/audio/sfx/${name}.wav`).then(r=>{if(!r.ok)throw Error('audio');return r.arrayBuffer();}).catch(()=>null);
    bytes.set(name,request);
  }
  async function load(name){
    if(buffers.has(name))return buffers.get(name);
    if(!context)return null;
    if(!pending.has(name))pending.set(name,(async()=>{
      const data=await bytes.get(name);if(!data)return null;
      try{const b=await context.decodeAudioData(data.slice(0));buffers.set(name,b);return b;}catch{return null;}
    })());
    return pending.get(name);
  }
  function startMusic(){if(unlocked&&enabled&&musicEnabled&&!document.hidden){music.volume=musicVolume;void music.play().catch(()=>{});}}
  async function unlock(){
    if(!context){const C=window.AudioContext||window.webkitAudioContext;if(C)context=new C();}
    if(context?.state==='suspended'){try{await context.resume();}catch{}}
    unlocked=true;
    for(const name of bytes.keys())void load(name);
    startMusic();
  }
  async function play(type,variation=0){
    if(!enabled||volume===0||document.hidden||!unlocked||!context)return;
    const generation=epoch;
    const buffer=await load(names[type]||'button');
    if(generation!==epoch||!buffer||!enabled||document.hidden||sources.size>=12||context.state!=='running')return;
    const source=context.createBufferSource(),gain=context.createGain();
    source.buffer=buffer;source.playbackRate.value=type==='stop'?1+Math.min(4,variation)*.025:1;
    gain.gain.value=volume*.55;source.connect(gain).connect(context.destination);sources.add(source);
    source.onended=()=>{sources.delete(source);source.disconnect();gain.disconnect();};source.start();
  }
  function stop(){epoch++;for(const s of sources){try{s.stop();}catch{}}sources.clear();}
  function setEnabled(value){enabled=!!value;put('mw-sfx',enabled?'on':'off');if(!enabled){stop();music.pause();}else startMusic();}
  function setVolume(value){volume=Math.max(0,Math.min(1,value));put('mw-volume',volume);}
  function toggleMusic(){musicEnabled=!musicEnabled;put('mw-music',musicEnabled?'on':'off');if(musicEnabled)startMusic();else music.pause();return musicEnabled;}
  function setMusicVolume(value){musicVolume=Math.max(0,Math.min(1,value));music.volume=musicVolume;put('mw-music-volume',musicVolume);}
  document.addEventListener('pointerdown',()=>void unlock(),{passive:true});
  document.addEventListener('keydown',()=>void unlock());
  document.addEventListener('visibilitychange',()=>{if(document.hidden){stop();music.pause();}else startMusic();});
  window.MahjongWildAudio={play,unlock,stop,setEnabled,setVolume,toggleMusic,setMusicVolume,get state(){return{enabled,volume,musicEnabled,musicVolume,unlocked,context:context?.state??'not-created',loaded:buffers.size,voices:sources.size};}};
})();
