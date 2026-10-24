/* Mahjong Wild UI 0.8.2. Presentation consumes server outcomes; it never draws gameplay RNG. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const assets='/assets/locked-v08/';
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  const format=(n,d=2)=>Number(n).toLocaleString('id-ID',{minimumFractionDigits:d,maximumFractionDigits:d});
  const node=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;};
  const audio=()=>window.MahjongWildAudio;
  const demo=[['M','D','G','O'],['B','L','M','D','E'],['D','W','N','W','E'],['G','E','M','L','O'],['D','G','B','M']].map(c=>c.map(symbol=>({symbol,enhanced:false})));
  let state=null,stake=1,options=[.2,.5,1,2,5,10],busy=false,skip=false,turbo=false,auto=0,autoTimer=null,last=null,history=[],displayWin=0,winFrame=0;
  const animations=new Set(),waiters=new Set();
  const duration=ms=>(skip||reduced.matches)?0:Math.round(ms*(turbo?.38:1));
  function wait(ms){return new Promise(resolve=>{const done=()=>{clearTimeout(id);waiters.delete(done);resolve();};const id=setTimeout(done,duration(ms));waiters.add(done);});}
  function motion(el,frames,ms,delay=0,easing='cubic-bezier(.22,.65,.32,1)'){
    if(skip||reduced.matches||!el.animate)return Promise.resolve();
    const a=el.animate(frames,{duration:duration(ms),delay:duration(delay),easing,fill:'both'});animations.add(a);
    return a.finished.catch(()=>{}).finally(()=>{animations.delete(a);a.cancel();});
  }
  function skipAnimation(){skip=true;stopDisc(true);for(const a of animations)a.cancel();for(const done of [...waiters])done();audio()?.stop();}
  function sfx(type,variant=0){if(!skip)void audio()?.play(type,variant);}
  function notice(text,win=false){$('stage-notice').textContent=text;$('stage-notice').parentElement.classList.toggle('winning',win);fitMeters();}
  function mult(bonus,index=0){
    const values=bonus?state?.rules.bonus_multipliers:state?.rules.base_multipliers;
    const root=$('mult-track');root.replaceChildren();
    (values||(bonus?[2,3,5,8]:[1,2,3,5])).forEach((v,i)=>{const el=node('span',`mult${i===Math.min(index,3)?' active':''}`,`x${v}`);root.append(el);});
    $('machine').classList.toggle('bonus-mode',bonus);
  }
  function tile(data,row){
    const el=node('div',`tile${data.enhanced?' enhanced':''}${data.symbol==='W'?' wild':''}${data.symbol==='S'?' scatter':''}`);
    el.dataset.symbol=data.symbol;el.dataset.row=String(row);el._tile={...data};
    const img=node('img','tile-image');img.src=`${assets}tiles/${data.symbol}-${data.enhanced?'gold':'normal'}.webp`;img.alt=data.symbol==='W'?'Wild':data.symbol==='S'?'Scatter':`Tile ${data.symbol}`;img.draggable=false;img.decoding='async';el.append(img);
    if(!['W','S'].includes(data.symbol)){const glow=node('img','symbol-emission');glow.src=`${assets}symbols/${data.symbol}.webp`;glow.alt='';glow.draggable=false;el.append(glow);}
    return el;
  }
  function reel(col,index){const e=node('div',`reel${col.length===4?' short':''}`);e.setAttribute('aria-label',`Reel ${index+1}`);col.forEach((t,row)=>e.append(tile(t,row)));return e;}
  function render(board){const root=$('board');root.replaceChildren();board.forEach((col,i)=>root.append(reel(col,i)));root.setAttribute('aria-label',board.map(c=>c.map(t=>t.symbol).join(' ')).join(' / '));}
  let discFrame=0,discAngle=0,discSpeed=0,discTarget=0,discLast=0;
  function driveDisc(on){
    discTarget=on&&!skip&&!reduced.matches?(turbo?680:430):0;
    if(discFrame||(!discTarget&&discSpeed<.5))return;
    discLast=performance.now();
    const tick=now=>{
      const dt=Math.min(.05,(now-discLast)/1000);discLast=now;
      discSpeed+=(discTarget-discSpeed)*(1-Math.exp(-dt/(discTarget?.19:.17)));
      discAngle=(discAngle+discSpeed*dt)%360;
      $('spin-btn').querySelector('.spin-disk').style.transform=`rotate(${discAngle.toFixed(3)}deg)`;
      if(discTarget||discSpeed>.5)discFrame=requestAnimationFrame(tick);else{discFrame=0;discSpeed=0;}
    };
    discFrame=requestAnimationFrame(tick);
  }
  function stopDisc(immediate=false){discTarget=0;if(immediate){cancelAnimationFrame(discFrame);discFrame=0;discSpeed=0;}}
  function fitMeters(){
    for(const el of document.querySelectorAll('.meter-value,#stage-notice')){
      el.style.fontSize='';
      const size=parseFloat(getComputedStyle(el).fontSize);
      if(el.scrollWidth>el.clientWidth&&el.clientWidth>0)el.style.fontSize=`${Math.max(8,size*el.clientWidth/el.scrollWidth*.97)}px`;
      el.title=el.textContent;
    }
  }
  function controls(){
    const ready=!!state&&Number(state.balance)>=stake;
    $('spin-btn').disabled=!busy&&!ready;$('spin-btn').classList.toggle('busy',busy);$('spin-btn').setAttribute('aria-label',busy?'Lewati animasi':'Spin');$('spin-btn').querySelector('.spin-label').textContent=busy?'SKIP':'SPIN';
    $('minus-btn').disabled=busy||auto>0||stake===options[0];$('plus-btn').disabled=busy||auto>0||stake===options.at(-1);$('bet-display-btn').disabled=busy||auto>0;
    $('auto-btn').disabled=busy&&!auto;$('auto-btn').classList.toggle('active',auto>0);$('auto-caption').textContent=auto?`STOP ${auto}`:'AUTO';
    $('turbo-btn').setAttribute('aria-pressed',String(turbo));$('setting-turbo').textContent=turbo?'ON':'OFF';$('bet-value').textContent=format(stake);$('setting-bet').textContent=format(stake);$('skip-btn').hidden=!busy;
    const a=audio()?.state||{enabled:true,volume:.65,musicEnabled:false,musicVolume:.2};
    driveDisc(busy);fitMeters();
    $('sound-btn').classList.toggle('sound-on',a.enabled);$('sound-btn').setAttribute('aria-label',a.enabled?'Matikan suara':'Aktifkan suara');$('setting-sound').textContent=a.enabled?'ON':'OFF';
    $('sfx-volume').value=Math.round(a.volume*100);$('sfx-value').textContent=`${Math.round(a.volume*100)}%`;$('setting-music').textContent=a.musicEnabled?'ON':'OFF';$('music-volume').value=Math.round(a.musicVolume*100);
    $('setting-sound').setAttribute('aria-pressed',String(a.enabled));$('setting-music').setAttribute('aria-pressed',String(a.musicEnabled));$('setting-turbo').setAttribute('aria-pressed',String(turbo));
  }
  function refresh(next){
    state=next;options=next.bet_options?.map(Number)||options;
    if(!options.includes(stake))stake=options[0];
    $('balance').textContent=format(next.balance);$('spin-count').textContent=next.spin_count;$('next-commit').textContent=next.next_seed_commitment_sha256;$('config-hash').textContent=next.config_sha256;
    controls();
  }
  async function req(path,payload){
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),20000);
    try{const response=await fetch(path,{signal:controller.signal,cache:'no-store',...(payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-ML-Request':'local-demo'},body:JSON.stringify(payload)})});const data=await response.json();if(!response.ok)throw Error(data.error||`HTTP ${response.status}`);return data;}
    finally{clearTimeout(timeout);}
  }
  function winCount(value){
    cancelAnimationFrame(winFrame);const start=displayWin,begin=performance.now(),ms=duration(290);
    const tick=now=>{const t=ms?Math.min(1,(now-begin)/ms):1;displayWin=start+(value-start)*(1-(1-t)**3);$('last-win').textContent=format(displayWin);fitMeters();if(t<1)winFrame=requestAnimationFrame(tick);};winFrame=requestAnimationFrame(tick);
  }
  // Smootherstep has zero velocity/acceleration at both ends. The full strip
  // moves downward: previous screen -> decorative tiles -> server result.
  function rollFrames(distance){
    return Array.from({length:61},(_,i)=>{const t=i/60,p=t*t*t*(t*(t*6-15)+10);return {offset:t,transform:`translate3d(0,${(-distance*(1-p)).toFixed(3)}px,0)`};});
  }
  async function spinReels(board){
    if(skip||reduced.matches){render(board);return;}
    const root=$('board');$('machine').classList.add('is-spinning');$('game-stage').dataset.motionPhase='roll';audio()?.startReel?.();
    const previous=[...root.children].map(el=>[...el.children].map(t=>t._tile).filter(Boolean));
    render(board);
    await Promise.all(board.map(async(col,i)=>{
      const finalReel=root.children[i],h=finalReel.getBoundingClientRect().height;
      const gap=parseFloat(getComputedStyle(finalReel).rowGap)||2,pitch=(h+gap)/col.length;
      const windowEl=node('div',`reel-window${col.length===4?' short':''}`),strip=node('div','reel-strip');
      windowEl.setAttribute('aria-label',`Reel ${i+1}`);windowEl.append(strip);
      const filler=Array.from({length:turbo?9:17},(_,j)=>demo[(i+j)%5][j%demo[(i+j)%5].length]);
      const old=previous[i]?.length===col.length?previous[i]:col;
      for(const t of [...col,...filler,...old]){const el=tile(t,0);el.style.height=`${pitch-gap}px`;el.style.flex=`0 0 ${pitch-gap}px`;strip.append(el);}
      strip.style.gap=`${gap}px`;
      const distance=(col.length+filler.length)*pitch;
      strip.style.transform=`translate3d(0,${-distance}px,0)`;
      root.replaceChild(windowEl,finalReel);
      await motion(strip,rollFrames(distance),1120+i*105,i*45,'linear');
      if(windowEl.isConnected)windowEl.replaceWith(reel(col,i));
      sfx('stop',i);
    }));
    audio()?.stopReel?.();$('machine').classList.remove('is-spinning');$('game-stage').dataset.motionPhase='settled';
  }
  // Irregular ceramic pieces retain the winning tile's symbol and a jade edge.
  // Geometry is decorative and deterministic; it never consumes gameplay RNG.
  const fractureMesh=[
    [[0,0],[.37,0],[.31,.29],[0,.37]],
    [[.37,0],[.7,0],[.74,.32],[.52,.43],[.31,.29]],
    [[.7,0],[1,0],[1,.39],[.74,.32]],
    [[0,.37],[.31,.29],[.43,.58],[.27,.7],[0,.65]],
    [[.31,.29],[.52,.43],[.74,.32],[.67,.67],[.43,.58]],
    [[.74,.32],[1,.39],[1,.73],[.67,.67]],
    [[0,.65],[.27,.7],[.34,1],[0,1]],
    [[.27,.7],[.43,.58],[.67,.67],[.73,1],[.34,1]],
    [[.67,.67],[1,.73],[1,1],[.73,1]]
  ];
  async function explode(tileEl,index){
    if(skip||reduced.matches)return;
    const box=tileEl.getBoundingClientRect(),layer=$('effects-layer'),area=layer.getBoundingClientRect();
    const image=tileEl.querySelector('.tile-image'),promises=[];
    const fx=(cls,w,h,x,y)=>{const e=node('div',cls);Object.assign(e.style,{left:`${x}px`,top:`${y}px`,width:`${w}px`,height:`${h}px`});layer.append(e);return e;};
    const x=box.left-area.left,y=box.top-area.top;
    const cx=x+box.width/2,cy=y+box.height/2;
    const ring=fx('shockwave',box.width,box.height,x,y);
    promises.push(motion(ring,[{transform:'scale(.4)',opacity:.8},{transform:'scale(1.6)',opacity:0}],560,0,'ease-out').then(()=>ring.remove()));
    // One local warm bloom per tile, without a full-screen white flash.
    const flash=fx('flash ceramic-flash',box.width*1.65,box.height*1.65,x-box.width*.325,y-box.height*.325);
    promises.push(motion(flash,[{offset:0,opacity:0,transform:'scale(.2)'},{offset:.12,opacity:.88,transform:'scale(.75)'},{offset:.55,opacity:.42,transform:'scale(1.05)'},{offset:1,opacity:0,transform:'scale(1.25)'}],580,0,'ease-out').then(()=>flash.remove()));
    const star=fx('impact-star',box.width*.9,box.width*.9,cx-box.width*.45,cy-box.width*.45);
    promises.push(motion(star,[{transform:'scale(.25) rotate(-15deg)',opacity:0},{offset:.18,transform:'scale(1) rotate(0deg)',opacity:1},{transform:'scale(.55) rotate(28deg)',opacity:0}],620,0,'ease-out').then(()=>star.remove()));
    for(let n=0;n<fractureMesh.length;n++){
      const points=fractureMesh[n],xs=points.map(p=>p[0]),ys=points.map(p=>p[1]);
      const l=Math.min(...xs),t=Math.min(...ys),w=Math.max(...xs)-l,h=Math.max(...ys)-t;
      const shard=fx('shard tile-fragment ceramic-fragment',w*box.width,h*box.height,x+l*box.width,y+t*box.height);
      const cut=`polygon(${points.map(p=>`${((p[0]-l)/w*100).toFixed(2)}% ${((p[1]-t)/h*100).toFixed(2)}%`).join(',')})`;
      shard.style.setProperty('--fragment-cut',cut);shard.style.setProperty('--fragment-depth',`${Math.max(2,box.width*.055).toFixed(2)}px`);
      const depth=node('i','fragment-depth'),face=node('i','fragment-face'),bevel=node('i','fragment-bevel');
      face.style.backgroundImage=`linear-gradient(135deg,#fff9,transparent 38%,#5a391922),url("${image.src}")`;
      face.style.backgroundSize=`100% 100%,${box.width}px ${box.height}px`;
      face.style.backgroundPosition=`0 0,${-l*box.width}px ${-t*box.height}px`;
      shard.append(depth,face,bevel);
      const px=l+w/2-.5,py=t+h/2-.5,dx=px*box.width*1.75+(index%2?2:-2),dy=py*box.height*1.15-box.height*.13;
      const angle=(n%2?1:-1)*(24+n*9),rx=(n%3-1)*38,ry=(n%2?1:-1)*(20+n*3);
      promises.push(motion(shard,[
        {offset:0,transform:'perspective(360px) translate3d(0,0,0) rotate(0deg)',opacity:1},
        {offset:.33,transform:`perspective(360px) translate3d(${dx*.65}px,${dy*.8}px,12px) rotateX(${rx*.6}deg) rotateY(${ry*.6}deg) rotateZ(${angle*.4}deg) scale(1.04)`,opacity:1},
        {offset:.68,transform:`perspective(360px) translate3d(${dx}px,${dy+box.height*.13}px,4px) rotateX(${rx}deg) rotateY(${ry}deg) rotateZ(${angle}deg) scale(.95)`,opacity:1},
        {offset:1,transform:`perspective(360px) translate3d(${dx*1.14}px,${dy+box.height*.67}px,-8px) rotateX(${rx*1.4}deg) rotateY(${ry*1.4}deg) rotateZ(${angle*1.4}deg) scale(.66)`,opacity:0}
      ],820,0,'linear').then(()=>shard.remove()));
    }
    // A bounded number of sparks keeps simultaneous cascades affordable on mobile.
    const sparkCount=index<8?10:6;
    for(let n=0;n<sparkCount;n++){
      const a=n*2.39996+index*.71,reach=box.width*(.46+(n%4)*.16),size=n%3===0?4:2;
      const spark=fx(`spark ember${n%4===0?' star-ember':''}`,size,size,cx-size/2,cy-size/2);
      const dx=Math.cos(a)*reach,dy=Math.sin(a)*reach*.78;
      promises.push(motion(spark,[{opacity:0,transform:'translate3d(0,0,0) scale(.5)'},{offset:.12,opacity:1,transform:`translate3d(${dx*.2}px,${dy*.2}px,0) scale(1.15)`},{offset:.58,opacity:.95,transform:`translate3d(${dx*.8}px,${dy*.8}px,0) scale(1)`},{opacity:0,transform:`translate3d(${dx}px,${dy+box.height*.27}px,0) scale(.15)`}],680+(n%3)*45,n%3*12,'ease-out').then(()=>spark.remove()));
    }
    tileEl.classList.add('removed');
    await Promise.all(promises);
  }
  async function fracture(event){
    if(skip||reduced.matches)return;
    $('game-stage').dataset.motionPhase='crack';
    const victims=[],gold=[];
    event.marked.forEach((rows,c)=>rows.forEach(r=>{
      const t=event.before[c][r],el=$('board').children[c].children[r];
      if(t.enhanced&&!['W','S'].includes(t.symbol)){gold.push(el);el.classList.add('morph-charge');}
      else{victims.push(el);const crack=node('img','crack');crack.src=assets+'effects/crack.webp';crack.alt='';el.append(crack);el.classList.add('cracked');}
    }));
    if(victims.length)sfx('crack');
    await wait(230);
    if(skip||reduced.matches)return;
    $('game-stage').dataset.motionPhase='shatter';if(victims.length)sfx('break');
    await Promise.all(victims.map(explode));
    gold.forEach(el=>el.classList.remove('morph-charge'));
  }
  async function drop(event){
    const board=$('board'),old=[...board.children].map(el=>({height:el.getBoundingClientRect().height,gap:parseFloat(getComputedStyle(el).rowGap)||2}));
    $('game-stage').dataset.motionPhase='drop';render(event.after);const promises=[];let transformed=false;
    event.after.forEach((col,c)=>{
      const marked=new Set(event.marked[c]),survivors=[];
      event.before[c].forEach((t,r)=>{if(!marked.has(r))survivors.push({row:r,morph:false});else if(t.enhanced&&!['W','S'].includes(t.symbol))survivors.push({row:r,morph:true});});
      const missing=col.length-survivors.length,pitch=(old[c].height+old[c].gap)/col.length;
      [...board.children[c].children].forEach((el,r)=>{
        const prev=r<missing?null:survivors[r-missing],offset=prev?(prev.row-r)*pitch:-(missing-r+1)*pitch;
        if(prev?.morph){transformed=true;el.classList.add('wild-pop');}
        if(Math.abs(offset)>.1||prev?.morph)promises.push(motion(el,[{offset:0,transform:`translateY(${offset}px)`,opacity:prev?1:0,easing:'cubic-bezier(.35,.03,.68,.7)'},{offset:.72,transform:'translateY(2px)',opacity:1,easing:'ease-out'},{offset:1,transform:'translateY(0)',opacity:1}],480,r*18+c*10,'linear'));
      });
    });
    if(transformed)sfx('wild');await Promise.all(promises);$('game-stage').dataset.motionPhase='settled';
  }
  async function banner(title,detail,ms=800){
    if(skip)return;const el=$('overlay-banner');el.replaceChildren(node('div','',title),node('small','',detail));el.classList.remove('hidden');await wait(ms);el.classList.add('hidden');
  }
  async function playback(record,totalWin){
    let cumulative=0;
    for(const event of record.events){
      if(event.type==='screen_start'){
        const bonus=event.phase==='bonus';$('phase-tag').textContent=bonus?`FREE ${event.number}/${record.free_spins_played}`:'BASE GAME';mult(bonus,0);notice(bonus?`FREE SPIN ${event.number}`:'BERPUTAR');await spinReels(event.board);
      }else if(event.type==='cascade'){
        mult(event.phase==='bonus',event.step-1);render(event.before);
        event.marked.forEach((rows,c)=>rows.forEach(r=>{$('board').children[c].children[r].classList.add('marked');$('board').children[c].children[r].append(node('span','win-border'));}));
        cumulative+=Number(event.awarded_x)*stake;winCount(cumulative);notice(`MENANG ${format(cumulative)}`,true);sfx(event.step>1?'multiplier':'win');await wait(280);
        if(event.after){
          await fracture(event);await drop(event);sfx('cascade');
        }
      }else if(event.type==='bonus_trigger'){sfx('bonus');await banner('FREE SPINS',`+${event.awarded_spins}`,1000);}
      else if(event.type==='bonus_retrigger'){sfx('bonus');await banner('EXTRA SPINS',`+${event.added_spins}`,700);}
      else if(event.type==='cap_reached'){sfx('bigwin');await banner('MAX WIN',`${event.cap_x}x`,1000);}
      else if(event.type==='round_end'){
        winCount(totalWin);notice(totalWin>0?`MENANG ${format(totalWin)}`:'COBA PUTARAN BERIKUTNYA',totalWin>0);
        if(Number(event.payout_x)>=20){sfx('bigwin');await banner(Number(event.payout_x)>=50?'LEGENDARY WIN':'BIG WIN',`${format(totalWin)} KREDIT`,1100);}
      }
    }
  }
  async function verifySeed(record,commitment){
    if(record.seed_commitment_sha256!==commitment)throw Error('Komitmen hasil berubah. Sesi disinkronkan ulang.');
    if(globalThis.crypto?.subtle){
      if(!/^[a-f0-9]{64}$/.test(record.seed_hex))throw Error('Invalid seed');
      const bytes=Uint8Array.from(record.seed_hex.match(/../g),x=>parseInt(x,16));
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
      if(digest!==commitment)throw Error('Verifikasi seed gagal');
    }
    if(record.config_sha256!==state.config_sha256)throw Error('Versi aturan berubah. Muat ulang game.');
  }
  function cancelAuto(){auto=0;clearTimeout(autoTimer);autoTimer=null;controls();}
  function storeHistory(data){
    history.unshift({round:data.round.round_id,spin:data.state.spin_count,stake:Number(data.stake_virtual_credits??stake),win:Number(data.win_virtual_credits)});history=history.slice(0,25);
    const root=$('history-list');root.replaceChildren();history.forEach(h=>{const e=node('div','history-entry');e.append(node('span','',`#${h.spin} | Bet ${format(h.stake)}`),node('strong','',`+${format(h.win)}`));root.append(e);});
  }
  async function spin(isAuto=false){
    if(busy){skipAnimation();return;}
    if(!state||Number(state.balance)<stake){cancelAuto();notice('KREDIT TIDAK CUKUP');return;}
    if(isAuto){if(!auto)return;auto--;}
    busy=true;skip=false;controls();audio()?.unlock();sfx('spin');notice('BERPUTAR');cancelAnimationFrame(winFrame);displayWin=0;$('last-win').textContent='0,00';$('effects-layer').replaceChildren();
    const commitment=state.next_seed_commitment_sha256;let accepted=null;
    $('balance').textContent=format(Number(state.balance)-stake);
    try{
      accepted=await req('/api/spin',{bet:String(stake)});await verifySeed(accepted.round,commitment);
      last=accepted.round;await playback(last,Number(accepted.win_virtual_credits));
      cancelAnimationFrame(winFrame);displayWin=Number(accepted.win_virtual_credits);$('last-win').textContent=format(displayWin);refresh(accepted.state);storeHistory(accepted);
      $('last-round-id').textContent=last.round_id;$('verify-btn').disabled=false;$('download-btn').disabled=false;$('verification-result').textContent='Hasil siap diverifikasi.';
    }catch(error){
      cancelAuto();notice(error.name==='AbortError'?'KONEKSI TERPUTUS. CEK HISTORY.':error.message);
      // Never retry a paid request automatically. Read back the server balance.
      try{refresh(await req('/api/state'));const recovered=await req('/api/last-round');last=recovered.round;$('last-round-id').textContent=last.round_id;$('verify-btn').disabled=false;$('download-btn').disabled=false;}catch{}
    }finally{
      audio()?.stopReel?.();for(const a of animations)a.cancel();$('effects-layer').replaceChildren();$('overlay-banner').classList.add('hidden');busy=false;skip=false;controls();$('phase-tag').textContent='BASE GAME';$('game-stage').dataset.motionPhase='idle';$('machine').classList.remove('is-spinning');
      if(auto&&!document.hidden&&Number(state?.balance)>=stake)autoTimer=setTimeout(()=>spin(true),turbo?180:550);else if(auto)cancelAuto();
    }
  }
  function panel(which='rules'){
    cancelAuto();document.querySelectorAll('.tab').forEach(b=>{const active=b.dataset.panel===which;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});document.querySelectorAll('.info-panel').forEach(p=>p.classList.toggle('hidden',p.id!==`panel-${which}`));
    const body=$('game-dialog').querySelector('.dialog-body');if(body)body.scrollTop=0;
    if(!$('game-dialog').open)$('game-dialog').showModal();
  }
  function step(direction){if(busy||auto)return;stake=options[Math.max(0,Math.min(options.length-1,options.indexOf(stake)+direction))];controls();}
  document.addEventListener('click',e=>{
    const button=e.target.closest('button');
    if(!button||button.disabled||['spin-btn','sound-btn','setting-sound'].includes(button.id))return;
    audio()?.unlock();sfx('tap');
  },true);
  $('sfx-volume').addEventListener('change',()=>sfx('tap'));
  $('spin-btn').addEventListener('click',()=>void spin());$('skip-btn').addEventListener('click',skipAnimation);
  $('minus-btn').addEventListener('click',()=>step(-1));$('plus-btn').addEventListener('click',()=>step(1));$('bet-display-btn').addEventListener('click',()=>step(1));
  function toggleTurbo(){turbo=!turbo;controls();}
  $('turbo-btn').addEventListener('click',toggleTurbo);$('setting-turbo').addEventListener('click',toggleTurbo);
  const sound=()=>{audio()?.setEnabled(!audio()?.state.enabled);controls();sfx('tap');};$('sound-btn').addEventListener('click',sound);$('setting-sound').addEventListener('click',sound);
  $('sfx-volume').addEventListener('input',e=>{audio()?.setVolume(Number(e.target.value)/100);$('sfx-value').textContent=`${e.target.value}%`;});
  $('setting-music').addEventListener('click',()=>{audio()?.toggleMusic();controls();});$('music-volume').addEventListener('input',e=>audio()?.setMusicVolume(Number(e.target.value)/100));
  $('menu-btn').addEventListener('click',()=>panel());$('info-shortcut').addEventListener('click',()=>panel('paytable'));$('history-shortcut').addEventListener('click',()=>panel('history'));
  $('close-dialog').addEventListener('click',()=>$('game-dialog').close());document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>panel(b.dataset.panel)));
  document.querySelector('.dialog-tabs').addEventListener('keydown',e=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
    const tabs=[...document.querySelectorAll('.tab')],current=tabs.indexOf(document.activeElement);if(current<0)return;
    const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(current+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
    e.preventDefault();panel(tabs[next].dataset.panel);tabs[next].focus();sfx('tap');
  });
  $('auto-btn').addEventListener('click',()=>{if(auto){cancelAuto();return;}if(!busy)$('auto-dialog').showModal();});
  for(const id of ['close-auto','auto-cancel'])$(id).addEventListener('click',()=>$('auto-dialog').close());
  document.querySelectorAll('[data-autospins]').forEach(b=>b.addEventListener('click',()=>{if(busy)return;auto=Number(b.dataset.autospins);$('auto-dialog').close();void spin(true);}));
  function closeReset(){if($('reset-dialog')?.open)$('reset-dialog').close();}
  $('reset-btn').addEventListener('click',()=>{if(busy)return;cancelAuto();$('reset-dialog')?.showModal();});
  for(const id of ['close-reset','reset-cancel'])$(id)?.addEventListener('click',closeReset);
  $('reset-confirm')?.addEventListener('click',async()=>{
    if(busy)return;const button=$('reset-confirm');button.disabled=true;
    try{cancelAuto();refresh(await req('/api/reset',{}));last=null;history=[];displayWin=0;cancelAnimationFrame(winFrame);$('last-win').textContent='0,00';$('history-list').replaceChildren(node('p','','Belum ada putaran.'));$('verify-btn').disabled=true;$('download-btn').disabled=true;render(demo);mult(false);notice('SIAP BERMAIN');closeReset();$('game-dialog').close();}
    catch(e){notice(e.message);if($('reset-status'))$('reset-status').textContent=e.message;}
    finally{button.disabled=false;}
  });
  $('verify-btn').addEventListener('click',async()=>{if(!last)return;$('verify-btn').disabled=true;try{const result=await req('/api/verify',{round:last});$('verification-result').textContent=`${result.valid?'PASS':'FAIL'}: ${result.reason}`;}catch(e){$('verification-result').textContent=e.message;}finally{$('verify-btn').disabled=false;}});
  $('download-btn').addEventListener('click',()=>{if(!last)return;const url=URL.createObjectURL(new Blob([JSON.stringify(last,null,2)],{type:'application/json'})),a=node('a');a.href=url;a.download=`mahjong-wild-${last.round_id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  document.addEventListener('keydown',e=>{if(e.code==='Space'&&!e.repeat&&!document.querySelector('dialog[open]')&&!['INPUT','BUTTON'].includes(document.activeElement?.tagName)){e.preventDefault();void spin();}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAuto();if(busy)skipAnimation();}});
  reduced.addEventListener?.('change',()=>{if(reduced.matches&&busy)skipAnimation();});
  window.addEventListener('pagehide',()=>{cancelAuto();if(busy)skipAnimation();else{stopDisc(true);audio()?.stop();}});
  window.addEventListener('pageshow',()=>{if(!busy)skip=false;controls();});
  new ResizeObserver(fitMeters).observe($('game-stage'));
  $('board').addEventListener('pointerdown',e=>{if(busy)return;const el=e.target.closest('.tile');if(el)void motion(el,[{transform:'scale(1)'},{transform:'scale(1.045)',offset:.4},{transform:'scale(1)'}],300);});
  const soundStatus=()=>{
    const a=audio()?.state;if(!$('audio-status')||!a)return;
    $('audio-status').textContent=!a.enabled?'Suara game dimatikan.':a.lastError||(!a.unlocked?'Ketuk Tes Suara untuk mengaktifkan audio.':a.musicPlaying?'Musik oriental lembut dan efek suara siap.':a.musicEnabled?'Musik sedang disiapkan. Efek suara siap.':'Efek suara siap. Musik dimatikan.');
  };
  window.addEventListener('mw-audio-state',soundStatus);
  $('test-sound-btn')?.addEventListener('click',async()=>{await audio()?.unlock();await audio()?.test?.();soundStatus();controls();});
  render(demo);mult(false);controls();soundStatus();$('last-win').textContent=format(0);notice('MEMUAT GAME');
  for(const file of ['effects/crack.webp']){const im=new Image();im.src=assets+file;}
  for(const id of 'ABCDEFGHIJKLMNOWS')for(const state of ['normal','gold']){const im=new Image();im.src=`${assets}tiles/${id}-${state}.webp`;}
  req('/api/state').then(next=>{refresh(next);mult(false);notice('SIAP BERMAIN');const root=$('paytable-list');root.replaceChildren();for(const[s,values]of Object.entries(next.rules.paytable)){const row=node('div','paytable-item');const label=node('span','symbol-label'),icon=node('img','paytable-tile');icon.src=`${assets}tiles/${s}-normal.webp`;icon.alt=`Tile ${s}`;label.append(icon,node('b','',s));row.append(label,...values.map(v=>node('span','',String(v))));root.append(row);}}).catch(e=>{notice('KONEKSI GAGAL. MUAT ULANG.');$('spin-btn').disabled=true;console.error(e.message);});
})();
