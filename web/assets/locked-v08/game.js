/* Mahjong Wild UI 0.8.3. Presentation consumes server outcomes; it never draws gameplay RNG. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const assets='/assets/approved-v082/';
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  const format=(n,d=2)=>Number(n).toLocaleString('id-ID',{minimumFractionDigits:d,maximumFractionDigits:d});
  const node=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;};
  const audio=()=>window.MahjongWildAudio;
  const demo=[['M','D','G','O'],['B','L','M','D','E'],['D','W','N','W','E'],['G','E','M','L','O'],['D','G','B','M']].map((c,ci)=>c.map((symbol,r)=>({symbol,enhanced:ci>=1&&ci<=3&&r===2})));
  let state=null,stake=1,options=[.2,.5,1,2,5,10],busy=false,skip=false,turbo=false,auto=0,autoTimer=null,last=null,history=[],displayWin=0,winFrame=0;
  const animations=new Set(),waiters=new Set();
  const duration=ms=>(skip||reduced.matches)?0:Math.round(ms*(turbo?.38:1));
  function wait(ms){return new Promise(resolve=>{const done=()=>{clearTimeout(id);waiters.delete(done);resolve();};const id=setTimeout(done,duration(ms));waiters.add(done);});}
  function motion(el,frames,ms,delay=0,easing='cubic-bezier(.22,.65,.32,1)'){
    if(skip||reduced.matches||!el.animate)return Promise.resolve();
    const a=el.animate(frames,{duration:duration(ms),delay:duration(delay),easing,fill:'both'});animations.add(a);
    return a.finished.catch(()=>{}).finally(()=>{animations.delete(a);a.cancel();});
  }
  function skipAnimation(){skip=true;window.MahjongReels.finish();stopDisc(true);for(const a of animations)a.cancel();for(const done of [...waiters])done();audio()?.stop();}
  function sfx(type,variant=0){if(!skip)void audio()?.play(type,variant);}
  function notice(text,win=false){const e=$('stage-notice');e.replaceChildren();if(win&&text.startsWith('MENANG ')){e.append(document.createTextNode('MENANG '),node('strong','win-amount',text.slice(7)));}else e.textContent=text;e.parentElement.classList.toggle('winning',win);fitMeters();}
  function mult(bonus,index=0){
    const values=bonus?state?.rules.bonus_multipliers:state?.rules.base_multipliers;
    const root=$('mult-track');root.replaceChildren();
    (values||(bonus?[2,3,5,8]:[1,2,3,5])).forEach((v,i)=>{const el=node('span',`mult${i===Math.min(index,3)?' active':''}`,`x${v}`);el.dataset.value=String(v);if([1,2,3,5].includes(v)){const im=node('img','mult-glyph');im.alt='';im.src=`${assets}multiplier/${v}-${i===Math.min(index,3)?'active':'idle'}.webp`;el.append(im);el.classList.add('art-mult');}root.append(el);});
    $('machine').classList.toggle('bonus-mode',bonus);
  }
  function tile(data,row){
    const el=node('div',`tile${data.enhanced?' enhanced':''}${data.symbol==='W'?' wild':''}${data.symbol==='S'?' scatter':''}`);
    el.dataset.symbol=data.symbol;el.dataset.row=String(row);el._tile={...data};
    const img=node('img','tile-image');img.src=`${assets}tiles/${data.symbol}-${data.enhanced?'gold':'normal'}.webp`;img.alt=data.symbol==='W'?'Wild':data.symbol==='S'?'Scatter':`Tile ${data.symbol}`;img.draggable=false;img.decoding='sync';el.append(img);
    if(!['W','S'].includes(data.symbol)){const glow=node('img','symbol-emission');glow.src=`${assets}symbols/${data.symbol}.webp`;glow.alt='';glow.draggable=false;el.append(glow);}
    return el;
  }
  function reel(col,index){const e=node('div',`reel${col.length===4?' short':''}`);e.setAttribute('aria-label',`Reel ${index+1}`);col.forEach((t,row)=>e.append(tile(t,row)));return e;}
  function render(board){
    const root=$('board');
    const same=root.children.length===board.length&&board.every((col,c)=>root.children[c].classList.contains('reel')&&root.children[c].children.length===col.length&&col.every((t,r)=>{const old=root.children[c].children[r]._tile;return old?.symbol===t.symbol&&!!old.enhanced===!!t.enhanced;}));
    if(same){for(const el of root.querySelectorAll('.tile')){el.classList.remove('marked','removed','cracked','wild-pop','morph-charge');el.querySelectorAll('.crack,.win-border').forEach(n=>n.remove());}}
    else root.replaceChildren(...board.map(reel));
    root.setAttribute('aria-label',board.map(c=>c.map(t=>t.symbol).join(' ')).join(' / '));
  }
  async function preparedRender(board){const reels=board.map(reel);await Promise.all(reels.map(window.MahjongReels.ready));$('board').replaceChildren(...reels);$('board').setAttribute('aria-label',board.map(c=>c.map(t=>t.symbol).join(' ')).join(' / '));}
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
    const ready=!!state&&navigator.onLine&&Number(state.balance)>=stake;
    $('spin-btn').disabled=!busy&&!ready;$('spin-btn').classList.toggle('busy',busy);$('spin-btn').setAttribute('aria-label',busy?'Lewati animasi':'Spin');$('spin-btn').querySelector('.spin-label').textContent=busy?'SKIP':'SPIN';
    $('minus-btn').disabled=busy||auto>0||stake===options[0];$('plus-btn').disabled=busy||auto>0||stake===options.at(-1);$('bet-display-btn').disabled=busy||auto>0;
    $('auto-btn').disabled=busy&&!auto;$('auto-btn').classList.toggle('active',auto>0);$('auto-caption').textContent=auto?`STOP ${auto}`:'AUTO';
    $('turbo-btn').setAttribute('aria-pressed',String(turbo));$('setting-turbo').textContent=turbo?'ON':'OFF';$('bet-value').textContent=format(stake);$('setting-bet').textContent=format(stake);$('skip-btn').hidden=!busy;
    const a=audio()?.state||{enabled:true,volume:.65,musicEnabled:false,musicVolume:.2};
    driveDisc(busy);fitMeters();
    $('sound-btn').classList.toggle('sound-on',a.enabled);$('sound-btn').setAttribute('aria-label',a.enabled?'Matikan suara':'Aktifkan suara');$('setting-sound').textContent=a.enabled?'ON':'OFF';
    $('sfx-volume').value=Math.round(a.volume*100);$('sfx-value').textContent=`${Math.round(a.volume*100)}%`;$('setting-music').textContent=a.musicEnabled?'ON':'OFF';$('music-volume').value=Math.round(a.musicVolume*100);
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
  async function spinReels(board){
    $('game-stage').dataset.motionPhase='preparing';
    try {
      await window.MahjongReels.run({
        root:$('board'),board,buildReel:reel,
        urlFor:t=>`${assets}tiles/${t.symbol}-${t.enhanced?'gold':'normal'}.webp`,
        filler:(i,j)=>demo[(i+j)%5][j%demo[(i+j)%5].length],
        turbo,shouldSkip:()=>skip||reduced.matches,
        onStop:i=>sfx('stop',i)
      });
      $('board').setAttribute('aria-label',board.map(c=>c.map(t=>t.symbol).join(' ')).join(' / '));
    } catch (error) {
      window.MahjongReels.recordError('spin-reel',error);
      try { await preparedRender(board); } catch (_) { render(board); }
    } finally {
      $('machine').classList.remove('is-spinning');
      $('game-stage').dataset.motionPhase='settled';
    }
  }
  document.addEventListener('mahjong:reel',e=>{
    if(e.detail.phase==='start'){
      if(e.detail.column===1)sfx('spin');
      $('machine').classList.add('is-spinning');
      $('game-stage').dataset.motionPhase='roll';
    }
  });
  async function readyBoard(board){
    await window.MahjongReels.prepare(board.flat().map(t=>`${assets}tiles/${t.symbol}-${t.enhanced?'gold':'normal'}.webp`));
  }
  // Fragments contain the actual winning tile pixels, including its symbol.
  // All work is awaited/cancellable; refill cannot hide the break after 200ms.
  async function explode(tileEl,index){
    if(skip||reduced.matches)return;
    const box=tileEl.getBoundingClientRect(),layer=$('effects-layer'),area=layer.getBoundingClientRect();
    const image=tileEl.querySelector('.tile-image'),promises=[];
    const fx=(cls,w,h,x,y)=>{const e=node('div',cls);Object.assign(e.style,{left:`${x}px`,top:`${y}px`,width:`${w}px`,height:`${h}px`});layer.append(e);return e;};
    const x=box.left-area.left,y=box.top-area.top;
    const ring=fx('shockwave',box.width,box.height,x,y);
    promises.push(motion(ring,[{transform:'scale(.6)',opacity:.7},{transform:'scale(1.7)',opacity:0}],520,0,'ease-out').then(()=>ring.remove()));
    const flash=fx('flash',box.width*1.65,box.height*1.65,x-box.width*.325,y-box.height*.325);
    promises.push(motion(flash,[{opacity:.9,transform:'scale(.45)'},{opacity:.35,transform:'scale(1)',offset:.3},{opacity:0,transform:'scale(1.3)'}],510).then(()=>flash.remove()));
    // Irregular ceramic faces with a visible jade/ivory thickness, not rectangles.
    const shapes=['polygon(3% 12%,72% 0,100% 34%,84% 96%,8% 84%)','polygon(15% 0,100% 12%,85% 82%,38% 100%,0 51%)','polygon(0 25%,66% 0,100% 52%,60% 100%,5% 80%)'];
    for(let n=0;n<9;n++){
      const c=n%3,r=Math.floor(n/3),w=box.width/3,h=box.height/3;
      const shard=fx('shard tile-fragment',w+2,h+2,x+c*w,y+r*h),side=node('span','fragment-side'),face=node('span','fragment-face');
      const clip=shapes[n%3];side.style.clipPath=clip;face.style.clipPath=clip;
      face.style.backgroundImage=`url("${image.src}")`;face.style.backgroundSize=`${box.width}px ${box.height}px`;face.style.backgroundPosition=`${-c*w}px ${-r*h}px`;
      shard.append(side,face);
      const dx=(c-1)*box.width*.9+(index%2?6:-6),dy=(r-1)*box.height*.52-8,angle=(n%2?1:-1)*(32+n*11);
      promises.push(motion(shard,[
        {offset:0,transform:'translate3d(0,0,0) rotate(0deg) scale(1)',opacity:1},
        {offset:.32,transform:`translate3d(${dx*.62}px,${dy}px,0) rotate(${angle*.38}deg) scale(.97)`,opacity:1},
        {offset:.72,transform:`translate3d(${dx}px,${dy+14}px,0) rotate(${angle}deg) scale(.86)`,opacity:1},
        {offset:1,transform:`translate3d(${dx*1.15}px,${dy+box.height*.85}px,0) rotate(${angle*1.4}deg) scale(.62)`,opacity:0}
      ],720,0,'linear').then(()=>shard.remove()));
    }
    for(let n=0;n<(turbo?5:10);n++){
      const star=n%3===0,size=star?box.width*.14:3;
      const spark=fx(star?'spark star':'spark',size,size,x+box.width/2-size/2,y+box.height/2-size/2),a=n*2.399+index*.2,travel=box.width*(.55+n%3*.22);
      promises.push(motion(spark,[{opacity:0,transform:'translate(0,0) scale(.4)'},{opacity:1,offset:.14,transform:`translate(${Math.cos(a)*travel*.2}px,${Math.sin(a)*travel*.2}px) scale(1)`},{opacity:.85,offset:.6,transform:`translate(${Math.cos(a)*travel*.75}px,${Math.sin(a)*travel*.8}px) scale(.8)`},{opacity:0,transform:`translate(${Math.cos(a)*travel}px,${Math.sin(a)*travel+box.height*.2}px) scale(.2)`}],760,0,'ease-out').then(()=>spark.remove()));
    }
    tileEl.classList.add('removed');await Promise.all(promises);
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
    await wait(185);
    if(skip||reduced.matches)return;
    $('game-stage').dataset.motionPhase='shatter';if(victims.length)sfx('break');
    await Promise.all(victims.map(explode));
    gold.forEach(el=>el.classList.remove('morph-charge'));
  }
  async function drop(event){
    const board=$('board'),old=[...board.children].map(el=>({height:el.getBoundingClientRect().height,gap:parseFloat(getComputedStyle(el).rowGap)||2}));
    await readyBoard(event.after);$('game-stage').dataset.motionPhase='drop';await preparedRender(event.after);const promises=[];let transformed=false;
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
        mult(event.phase==='bonus',event.step-1);await readyBoard(event.before);await preparedRender(event.before);
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
    if(!navigator.onLine){notice('OFFLINE. SAMBUNGKAN INTERNET.');return;}
    if(!state||Number(state.balance)<stake){cancelAuto();notice('KREDIT TIDAK CUKUP');return;}
    if(isAuto){if(!auto)return;auto--;}
    busy=true;skip=false;controls();audio()?.unlock();notice('BERPUTAR');cancelAnimationFrame(winFrame);displayWin=0;$('last-win').textContent='0,00';$('effects-layer').replaceChildren();
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
      for(const a of animations)a.cancel();$('effects-layer').replaceChildren();$('overlay-banner').classList.add('hidden');busy=false;skip=false;controls();$('phase-tag').textContent='BASE GAME';$('game-stage').dataset.motionPhase='idle';$('machine').classList.remove('is-spinning');
      if(auto&&!document.hidden&&Number(state?.balance)>=stake)autoTimer=setTimeout(()=>spin(true),turbo?180:550);else if(auto)cancelAuto();
    }
  }
  function panel(which='rules'){
    cancelAuto();document.querySelectorAll('.tab').forEach(b=>(b.classList.toggle('active',b.dataset.panel===which),b.setAttribute('aria-selected',String(b.dataset.panel===which))));document.querySelectorAll('.info-panel').forEach(p=>p.classList.toggle('hidden',p.id!==`panel-${which}`));if(!$('game-dialog').open)$('game-dialog').showModal();
  }
  function step(direction){if(busy||auto)return;stake=options[Math.max(0,Math.min(options.length-1,options.indexOf(stake)+direction))];controls();}
  $('spin-btn').addEventListener('click',()=>void spin());$('skip-btn').addEventListener('click',skipAnimation);
  $('minus-btn').addEventListener('click',()=>step(-1));$('plus-btn').addEventListener('click',()=>step(1));$('bet-display-btn').addEventListener('click',()=>step(1));
  $('turbo-btn').addEventListener('click',()=>{turbo=!turbo;controls();});$('setting-turbo').addEventListener('click',()=>{$('turbo-btn').click();});
  const sound=()=>{audio()?.setEnabled(!audio()?.state.enabled);controls();};$('sound-btn').addEventListener('click',sound);$('setting-sound').addEventListener('click',sound);
  $('sfx-volume').addEventListener('input',e=>{audio()?.setVolume(Number(e.target.value)/100);$('sfx-value').textContent=`${e.target.value}%`;});
  $('setting-music').addEventListener('click',()=>{audio()?.toggleMusic();controls();});$('music-volume').addEventListener('input',e=>audio()?.setMusicVolume(Number(e.target.value)/100));
  $('menu-btn').addEventListener('click',()=>panel());$('info-shortcut').addEventListener('click',()=>panel('paytable'));$('history-shortcut').addEventListener('click',()=>panel('history'));
  $('close-dialog').addEventListener('click',()=>$('game-dialog').close());document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>panel(b.dataset.panel)));
  $('auto-btn').addEventListener('click',()=>{if(auto){cancelAuto();return;}if(!busy)$('auto-dialog').showModal();});
  for(const id of ['close-auto','auto-cancel'])$(id).addEventListener('click',()=>$('auto-dialog').close());
  document.querySelectorAll('[data-autospins]').forEach(b=>b.addEventListener('click',()=>{if(busy)return;auto=Number(b.dataset.autospins);$('auto-dialog').close();void spin(true);}));
  $('reset-btn').addEventListener('click',async()=>{if(busy)return;if(!$('reset-dialog').open){$('reset-dialog').showModal();return;}$('reset-dialog').close();try{cancelAuto();refresh(await req('/api/reset',{}));last=null;history=[];displayWin=0;cancelAnimationFrame(winFrame);$('last-win').textContent='0,00';$('history-list').replaceChildren(node('p','','Belum ada putaran.'));$('verify-btn').disabled=true;$('download-btn').disabled=true;render(demo);mult(false);notice('SIAP BERMAIN');$('game-dialog').close();}catch(e){notice(e.message);}});
  $('reset-cancel').addEventListener('click',()=>$('reset-dialog').close());
  $('reset-confirm').addEventListener('click',()=>$('reset-btn').click());
  $('test-audio-btn').addEventListener('click',async()=>{await audio()?.unlock();await audio()?.play('win');const a=audio()?.state;$('audio-status').textContent=!a?.enabled?'Suara dimatikan. Aktifkan Sound effects.':a?.context==='running'?'Audio aktif. Naikkan volume media HP bila belum terdengar.':'Audio belum aktif. Sentuh TES SUARA lagi.';});
  document.addEventListener('click',e=>{if(e.isTrusted&&e.target.closest('button:not(:disabled)')){void audio()?.unlock();void audio()?.play('tap');}},{capture:true});
  window.addEventListener('offline',()=>{cancelAuto();controls();});
  window.addEventListener('online',()=>{req('/api/state').then(refresh).catch(()=>{});});
  $('verify-btn').addEventListener('click',async()=>{if(!last)return;$('verify-btn').disabled=true;try{const result=await req('/api/verify',{round:last});$('verification-result').textContent=`${result.valid?'PASS':'FAIL'}: ${result.reason}`;}catch(e){$('verification-result').textContent=e.message;}finally{$('verify-btn').disabled=false;}});
  $('download-btn').addEventListener('click',()=>{if(!last)return;const url=URL.createObjectURL(new Blob([JSON.stringify(last,null,2)],{type:'application/json'})),a=node('a');a.href=url;a.download=`mahjong-wild-${last.round_id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  document.addEventListener('keydown',e=>{if(e.code==='Space'&&!e.repeat&&!$('game-dialog').open&&!$('auto-dialog').open&&!$('reset-dialog').open&&!['INPUT','BUTTON'].includes(document.activeElement?.tagName)){e.preventDefault();void spin();}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){cancelAuto();if(busy)skipAnimation();}});
  reduced.addEventListener?.('change',()=>{if(reduced.matches&&busy)skipAnimation();});
  window.addEventListener('pagehide',()=>{cancelAuto();skipAnimation();});
  new ResizeObserver(fitMeters).observe($('game-stage'));
  window.addEventListener('resize',fitMeters);
  $('board').addEventListener('pointerdown',e=>{if(busy)return;const el=e.target.closest('.tile');if(el)void motion(el,[{transform:'scale(1)'},{transform:'scale(1.045)',offset:.4},{transform:'scale(1)'}],300);});
  render(demo);mult(false);controls();$('last-win').textContent=format(0);notice('MEMUAT GAME');
  for(const file of ['effects/crack.webp']){const im=new Image();im.src=assets+file;}
  Promise.all([req('/api/state'),window.MahjongReels.prepare(Array.from('ABCDEFGHIJKLMNOWS').flatMap(id=>['normal','gold'].map(s=>`${assets}tiles/${id}-${s}.webp`)))]).then(([next])=>{refresh(next);mult(false);notice('SIAP BERMAIN');const root=$('paytable-list');root.replaceChildren();for(const[s,values]of Object.entries(next.rules.paytable)){const row=node('div','paytable-item');const label=node('span','symbol-label'),icon=node('img','paytable-tile');icon.src=`${assets}tiles/${s}-normal.webp`;icon.alt=`Tile ${s}`;label.append(icon,node('b','',s));row.append(label,...values.map(v=>node('span','',String(v))));root.append(row);}}).catch(e=>{notice('KONEKSI GAGAL. MUAT ULANG.');$('spin-btn').disabled=true;console.error(e.message);});
})();
