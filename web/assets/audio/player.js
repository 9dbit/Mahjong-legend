/* Mahjong Wild original audio asset engine. Audio starts only on explicit input. */
(() => {
  'use strict';
  const root='/assets/audio/';
  const map={spin:'spin',stop:'reel_stop',reel_stop:'reel_stop',cascade:'cascade',break:'tile_break',tile_break:'tile_break',wild:'wild',mult:'multiplier',multiplier:'multiplier',scatter:'scatter',bonus:'bonus',win:'win',tick:'button',tap:'button',bigwin:'win',button:'button'};
  const music=new Audio(root+'music/ambient_jade_loop.m4a');
  music.preload='none';music.loop=true;music.volume=.24;
  const cues=new Map();let enabled=true;let musicEnabled=false;let musicLevel=.24;
  const safeGet=(k)=>{try{return localStorage.getItem(k);}catch{return null;}};
  const safeSet=(k,v)=>{try{localStorage.setItem(k,v);}catch{}};
  musicEnabled=safeGet('mahjong-wild-music')==='on';
  const cached=(name)=>{if(!cues.has(name)){const a=new Audio(root+'sfx/'+name+'.wav');a.preload='auto';cues.set(name,a);}return cues.get(name);};
  const api={
    playSfx(key,variant=0,on=true,level=.65){
      enabled=on!==false;
      if(!enabled)return;
      const name=map[key]||'button';
      try{const src=cached(name);const sound=src.cloneNode();sound.volume=Math.min(.95,Math.max(0,level*.8));sound.play().catch(()=>{});}catch{}
    },
    setEnabled(on){enabled=on;if(!on)music.pause();else if(musicEnabled)api.startMusic();},
    startMusic(){if(!enabled||!musicEnabled)return;music.volume=musicLevel;music.play().catch(()=>{});},
    toggleMusic(){musicEnabled=!musicEnabled;safeSet('mahjong-wild-music',musicEnabled?'on':'off');if(musicEnabled)api.startMusic();else music.pause();return musicEnabled;},
    setMusicVolume(n){musicLevel=Math.min(1,Math.max(0,n));music.volume=musicLevel;},
  };
  window.MahjongWildAudio=api;
  document.addEventListener('DOMContentLoaded',()=>{
    const spin=document.getElementById('spin-btn');
    if(spin)spin.addEventListener('click',()=>api.startMusic(),{passive:true});
    const btn=document.getElementById('sound-btn');
    if(btn)btn.addEventListener('click',()=>{setTimeout(()=>api.setEnabled(btn.classList.contains('sound-on')),0);});
    const settings=document.getElementById('panel-settings');
    if(settings){
      const row=document.createElement('div');row.className='setting-row';
      const label=document.createElement('span');label.textContent='Ambient music';
      const button=document.createElement('button');button.type='button';button.id='setting-music';button.textContent=musicEnabled?'ON':'OFF';
      button.addEventListener('click',()=>button.textContent=api.toggleMusic()?'ON':'OFF');
      row.append(label,button);settings.appendChild(row);
    }
  });
})();