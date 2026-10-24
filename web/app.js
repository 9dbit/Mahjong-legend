(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const demoBoard = [
    ['I','E','M','B'],
    ['A','J','F','N','C'],
    ['O','G','W','K','D'],
    ['H','I','M','L','B'],
    ['C','N','E','A'],
  ].map(col => col.map(symbol => ({symbol, enhanced:false})));
  const dotTiles = {A:2,B:3,C:4,D:6};
  const bambooTiles = {E:2,F:3,G:4,H:6};
  const charTiles = {
    I:['\u4e00','\u842c'],J:['\u4e8c','\u842c'],
    K:['\u4e94','\u842c'],L:['\u516b','\u842c'],
  };
  const dragonTiles = {M:'\u4e2d',N:'\u767c',O:'\u767d'};
  let state = null;
  let busy = false;
  let skip = false;
  let turbo = false;
  let sound = false;
  let audio = null;
  let lastRecord = null;
  let latestWin = 0;
  let selectedBet = 1;
  let betOptions = [0.2,0.5,1,2,5,10];
  let autoRemaining = 0;
  let autoTimer = null;
  let recentRounds = [];

  const delay = ms => new Promise(resolve => setTimeout(resolve, (skip || window.matchMedia('(prefers-reduced-motion: reduce)').matches) ? 0 : Math.max(45,Math.round(ms*(turbo?.32:1)))));
  const format = (v,d=2) => Number.isFinite(Number(v)) ? Number(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}) : '0.00';
  const create = (tag,className,textContent) => {
    const el=document.createElement(tag);
    if(className)el.className=className;
    if(textContent!==undefined)el.textContent=textContent;
    return el;
  };
  function svgEl(tag,attrs={}) {
    const node=document.createElementNS(SVG_NS,tag);
    for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));
    return node;
  }
  function svgCanvas(){return svgEl('svg',{viewBox:'0 0 70 86',class:'tile-svg','aria-hidden':'true'});}

  function makeDotArt(count) {
    const svg=svgCanvas();
    const positions = count===2?[[24,27],[46,60]]
      :count===3?[[18,24],[35,43],[52,62]]
      :count===4?[[22,25],[48,25],[22,58],[48,58]]
      :[[18,20],[35,20],[52,20],[18,59],[35,59],[52,59]];
    positions.forEach(([x,y],i)=>{
      const color=['#3a699b','#33845e','#ae4138','#397b9a','#b54c3f','#3c8a5c'][i];
      svg.appendChild(svgEl('circle',{cx:x,cy:y,r:count===6?9:11,fill:'#e7f1e1',stroke:color,'stroke-width':2.4}));
      svg.appendChild(svgEl('circle',{cx:x,cy:y,r:count===6?5.8:7.3,fill:color,opacity:.95}));
      svg.appendChild(svgEl('circle',{cx:x-2,cy:y-2,r:count===6?2:2.6,fill:'#def7e2'}));
    });
    return svg;
  }
  function makeBambooArt(count) {
    const svg=svgCanvas();
    const positions=count===2?[[24,39],[46,39]]:count===3?[[14,28],[35,45],[56,61]]
      :count===4?[[21,29],[48,29],[21,57],[48,57]]
      :[[16,23],[35,23],[54,23],[16,62],[35,62],[54,62]];
    positions.forEach(([x,y],i)=>{
      const color=i%3===1?'#b4493d':'#277e60';
      svg.appendChild(svgEl('rect',{x:x-4,y:y-13,width:8,height:27,rx:3,fill:color}));
      svg.appendChild(svgEl('rect',{x:x-2,y:y-10,width:4,height:21,rx:2,fill:'#b6d9a7'}));
      svg.appendChild(svgEl('path',{d:`M${x-5} ${y-4}h10 M${x-5} ${y+5}h10`,stroke:'#f5ede0','stroke-width':2.5}));
      svg.appendChild(svgEl('path',{d:`M${x-5} ${y-10}l-5 -4 M${x+5} ${y+9}l5 4`,stroke:color,'stroke-width':2,'stroke-linecap':'round'}));
    });
    return svg;
  }
  function makeIngot(){
    const art=create('div','wild-art');
    art.appendChild(create('span','wild-word','WILD'));
    const svg=svgEl('svg',{viewBox:'0 0 92 65',class:'ingot-svg','aria-hidden':'true'});
    const defs=svgEl('defs');
    const grad=svgEl('linearGradient',{id:'gold-ingot',x1:'0',y1:'0',x2:'0',y2:'1'});
    [['0%','#fff6ab'],['45%','#edb834'],['85%','#b8711d'],['100%','#e6a32c']].forEach(([offset,color])=>grad.appendChild(svgEl('stop',{offset,'stop-color':color})));
    defs.appendChild(grad);svg.appendChild(defs);
    svg.appendChild(svgEl('path',{d:'M10 23 Q16 12 31 22 L61 22 Q79 11 84 23 L75 49 Q46 61 17 49Z',fill:'url(#gold-ingot)',stroke:'#9c5519','stroke-width':3}));
    svg.appendChild(svgEl('ellipse',{cx:46,cy:24,rx:28,ry:10,fill:'#fff6a4',stroke:'#ad7422','stroke-width':2}));
    svg.appendChild(svgEl('ellipse',{cx:46,cy:23,rx:20,ry:5.5,fill:'#c88417'}));
    svg.appendChild(svgEl('path',{d:'M24 38 Q46 49 68 38',stroke:'#fff3a9',fill:'none','stroke-width':3,opacity:.7}));
    art.appendChild(svg);return art;
  }
  function tileFace(symbol) {
    const art=create('span','tile-art');
    if(dotTiles[symbol])art.appendChild(makeDotArt(dotTiles[symbol]));
    else if(bambooTiles[symbol])art.appendChild(makeBambooArt(bambooTiles[symbol]));
    else if(charTiles[symbol]){
      const wrap=create('span','mahjong-char');
      wrap.appendChild(create('span','char-number',charTiles[symbol][0]));
      wrap.appendChild(create('span','char-suit',charTiles[symbol][1]));
      art.appendChild(wrap);
    }else if(dragonTiles[symbol])art.appendChild(create('span','char-ruby',dragonTiles[symbol]));
    else if(symbol==='W')art.appendChild(makeIngot());
    else if(symbol==='S')art.appendChild(create('span','scatter-art','\u798f'));
    return art;
  }
  function classFor(symbol) {
    if(symbol==='W')return 'wild';
    if(symbol==='S')return 'scatter';
    if('IKM'.includes(symbol))return 'char-red';
    if('JLN'.includes(symbol))return 'char-jade';
    if(symbol==='O')return 'char-indigo';
    return '';
  }
  function renderBoard(board,opts={}) {
    const root=$('board');root.replaceChildren();
    board.forEach((col,reelIndex)=>{
      const reel=create('div',`reel${col.length===4?' short':''}`);
      reel.setAttribute('aria-label',`Reel ${reelIndex+1}`);
      col.forEach((tile,index)=>{
        const marked=opts.marked?.[reelIndex]?.includes(index);
        const el=create('div',`tile ${classFor(tile.symbol)}${tile.enhanced?' enhanced':''}${marked?' marked':''}${opts.falling?' falling':''}`);
        el.title=tile.symbol==='W'?'Wild':tile.symbol==='S'?'Scatter':`Mahjong Legend symbol ${tile.symbol}`;
        el.appendChild(tileFace(tile.symbol));
        reel.appendChild(el);
      });
      root.appendChild(reel);
    });
    root.setAttribute('aria-label','Reels: '+board.map(col=>col.map(tile=>tile.symbol).join('')).join(' / '));
  }
  function updateMult(isBonus,index=0) {
    const values=isBonus?[2,3,5,8]:[1,2,3,4];
    const track=$('mult-track');track.replaceChildren();
    values.forEach((v,i)=>track.appendChild(create('span',`mult${i===Math.min(index,3)?' active':''}`,`x${v}`)));
  }
  function showBanner(text,detail) {
    const el=$('overlay-banner');el.replaceChildren();
    el.appendChild(create('div','',text));el.appendChild(create('small','',detail));
    el.classList.remove('hidden');
  }
  function hideBanner(){$('overlay-banner').classList.add('hidden');}
  function status(message){$('stage-notice').textContent=message;}
  function phase(text){$('phase-tag').textContent=text;}
  function playSound(tone) {
    if(!sound)return;
    try {
      const ctx=audio||(audio=new (window.AudioContext||window.webkitAudioContext)());
      if(ctx.state==='suspended')ctx.resume();
      const osc=ctx.createOscillator();const gain=ctx.createGain();
      osc.type=tone==='win'?'sine':'triangle';
      osc.frequency.setValueAtTime(tone==='win'?540:tone==='bonus'?750:280,ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(tone==='win'?750:tone==='bonus'?1020:220,ctx.currentTime+.13);
      gain.gain.setValueAtTime(.0001,ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(.055,ctx.currentTime+.018);
      gain.gain.exponentialRampToValueAtTime(.0001,ctx.currentTime+.19);
      osc.connect(gain);gain.connect(ctx.destination);osc.start();osc.stop(ctx.currentTime+.2);
    }catch(e){/* Audio is optional and can be unavailable in locked-down contexts. */}
  }
  async function req(path,payload){
    const options=payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-ML-Request':'local-demo'},body:JSON.stringify(payload)};
    const response=await fetch(path,options);const data=await response.json();
    if(!response.ok)throw Error(data.error||`HTTP ${response.status}`);
    return data;
  }
  function betAffordable(){return state && Number(state.balance)>=selectedBet;}
  function updateControls(){
    $('bet-value').textContent=format(selectedBet);
    $('setting-bet').textContent=format(selectedBet);
    $('minus-btn').disabled=busy||selectedBet===betOptions[0];
    $('plus-btn').disabled=busy||selectedBet===betOptions[betOptions.length-1];
    $('bet-display-btn').disabled=busy;
    $('spin-btn').disabled=!busy&&!betAffordable();
    $('spin-btn').classList.toggle('busy',busy);
    $('spin-btn').setAttribute('aria-label',busy?'Skip spin animation':'Spin');
    $('spin-btn').title=busy?'Skip animation':'Spin (Space)';
    $('spin-btn').querySelector('.spin-label').textContent=busy?'SKIP':'SPIN';
    $('auto-btn').classList.toggle('active',autoRemaining>0);
    $('auto-caption').textContent=autoRemaining>0?`STOP ${autoRemaining}`:'AUTO';
    $('auto-btn').setAttribute('aria-label',autoRemaining>0?'Stop auto spin after current round':'Auto spin options');
    $('auto-btn').disabled=busy&&autoRemaining===0;
    $('turbo-btn').setAttribute('aria-pressed',String(turbo));
    $('setting-turbo').textContent=turbo?'ON':'OFF';
    $('setting-sound').textContent=sound?'ON':'OFF';
    $('sound-btn').setAttribute('aria-label',sound?'Turn sound off':'Turn sound on');
    $('sound-btn').title=sound?'Sound on':'Sound off';
    $('sound-btn').classList.toggle('sound-on',sound);
    $('sound-btn').querySelector('path').setAttribute('d',sound?'M4 9v6h4l5 4V5L8 9H4z M16 8q5 4 0 8 M18 5q8 7 0 14':'M4 9v6h4l5 4V5L8 9H4z M17 9l4 6m0-6l-4 6');
    $('skip-btn').hidden=!busy;
  }
  function refresh(next){
    state=next;
    if(Array.isArray(next.bet_options)&&next.bet_options.length)betOptions=next.bet_options.map(Number);
    $('balance').textContent=format(next.balance);
    $('spin-count').textContent=String(next.spin_count);
    $('next-commit').textContent=next.next_seed_commitment_sha256;
    $('config-hash').textContent=next.config_sha256;
    updateControls();renderPaytable();
  }
  function renderPaytable(){
    if(!state?.rules?.paytable)return;
    const root=$('paytable-list');root.replaceChildren();
    Object.entries(state.rules.paytable).forEach(([sym,values])=>{
      const row=create('div','paytable-item');
      row.appendChild(create('span','',` ${sym}  ${sym==='A'?'(Dots)':sym==='E'?'(Bamboo)':sym==='I'?'(Character)':''}`));
      values.forEach(x=>row.appendChild(create('span','',String(x))));root.appendChild(row);
    });
  }
  function setBet(index){
    if(busy||autoRemaining)return;
    const idx=Math.max(0,Math.min(index,betOptions.length-1));selectedBet=betOptions[idx];updateControls();
  }
  function stepBet(direction){setBet(betOptions.indexOf(selectedBet)+direction);}
  function toggleTurbo(){turbo=!turbo;updateControls();playSound('tick');}
  function toggleSound(){sound=!sound;updateControls();playSound('tick');}
  function cancelAuto(){
    autoRemaining=0;
    if(autoTimer){clearTimeout(autoTimer);autoTimer=null;}
    updateControls();
  }
  async function validateCommitment(record,previous) {
    if(previous && record.seed_commitment_sha256!==previous)throw Error('Seed commitment mismatch');
    if(globalThis.crypto?.subtle){
      const hex=record.seed_hex;
      if(!/^[0-9a-f]{64}$/.test(hex))throw Error('Invalid seed format');
      const buffer=Uint8Array.from(hex.match(/../g),s=>parseInt(s,16));
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',buffer)),b=>b.toString(16).padStart(2,'0')).join('');
      if(hash!==record.seed_commitment_sha256)throw Error('Browser seed verification failed');
    }
  }
  async function animateRound(round,creditWin){
    for(const evt of round.events){
      if(evt.type==='screen_start'){
        const bonus=evt.phase==='bonus';
        phase(bonus?`FREE SPIN ${evt.number}`:'BASE GAME');
        updateMult(bonus,0);
        status(bonus?`FREE SPIN ${evt.number}`:'SPINNING...');
        renderBoard(evt.board,{falling:!skip});
        playSound('spin');await delay(bonus?135:220);
      }else if(evt.type==='cascade'){
        updateMult(evt.phase==='bonus',evt.step-1);
        renderBoard(evt.before,{marked:evt.marked});
        status(`CASCADE ${evt.step}  /  x${evt.multiplier}  /  +${format(Number(evt.awarded_x)*selectedBet)}`);
        playSound('win');await delay(330);
        if(evt.after){renderBoard(evt.after,{falling:!skip});await delay(275);}
      }else if(evt.type==='bonus_trigger'){
        showBanner('FREE SPINS',`+${evt.awarded_spins} SPINS`);
        playSound('bonus');await delay(970);hideBanner();
      }else if(evt.type==='bonus_retrigger'){
        showBanner('EXTRA SPINS',`+${evt.added_spins} SPINS`);
        playSound('bonus');await delay(730);hideBanner();
      }else if(evt.type==='cap_reached'){
        showBanner('LEGENDARY WIN',`MAX  ${evt.cap_x}x BET`);
        await delay(1100);hideBanner();
      }else if(evt.type==='round_end'){
        if(Number(evt.payout_x)>0){
          showBanner(Number(evt.payout_x)>=25?'BIG WIN':'YOU WIN',`${format(creditWin)} CREDITS`);
          playSound('win');await delay(Number(evt.payout_x)>=25?1000:560);hideBanner();
        }
        phase('BASE GAME');status(Number(evt.payout_x)>0?`TOTAL WIN  ${format(creditWin)} CREDIT`:'GOLD TILES TRANSFORM INTO WILD');
        updateMult(false,0);
      }
    }
  }
  function recordHistory(entry){
    recentRounds.unshift(entry);recentRounds=recentRounds.slice(0,25);
    const list=$('history-list');list.replaceChildren();
    for(const item of recentRounds){
      const row=create('div','history-entry');
      const col=create('div','');
      col.append(create('strong','',`ROUND ${item.number}`),create('br'),create('small','',`Bet ${format(item.bet)} credits  /  ${item.id}`));
      row.append(col,create('strong','',`+${format(item.win)}`));list.appendChild(row);
    }
  }
  async function spin(fromAuto=false){
    if(busy){skip=true;return;}
    if(!betAffordable()){status('NOT ENOUGH VIRTUAL CREDITS');cancelAuto();return;}
    if(fromAuto){if(autoRemaining<=0)return;autoRemaining--;}
    busy=true;skip=false;updateControls();
    status('SPINNING...');$('last-win').textContent='0.00';latestWin=0;
    $('board').classList.add('spinning');playSound('spin');
    try{
      const promised=state?.next_seed_commitment_sha256;
      const [data]=await Promise.all([req('/api/spin',{bet:String(selectedBet)}),delay(380)]);
      $('board').classList.remove('spinning');
      lastRecord=data.round;
      await validateCommitment(lastRecord,promised);
      const win=Number(data.win_virtual_credits ?? Number(lastRecord.total_payout_x)*selectedBet);
      await animateRound(lastRecord,win);
      latestWin=win;$('last-win').textContent=format(win);
      $('last-round-id').textContent=lastRecord.round_id;
      $('verify-btn').disabled=false;$('download-btn').disabled=false;
      $('verification-result').textContent='Round is ready to replay and verify.';
      $('verification-result').className='verification-result';
      recordHistory({number:data.state.spin_count,bet:Number(data.stake_virtual_credits ?? selectedBet),win,id:lastRecord.round_id.slice(0,8)});
      refresh(data.state);
    }catch(err){status(`ERROR: ${err.message}`);cancelAuto();}
    finally{
      hideBanner();$('board').classList.remove('spinning');busy=false;updateControls();
      if(autoRemaining>0){
        if(!betAffordable()){status('AUTO STOP: INSUFFICIENT CREDITS');cancelAuto();}
        else autoTimer=setTimeout(()=>{autoTimer=null;spin(true);},turbo?95:380);
      }
    }
  }
  function openPanel(panel='rules'){
    cancelAuto();
    selectPanel(panel);
    if(!$('game-dialog').open)$('game-dialog').showModal();
  }
  function selectPanel(panel){
    document.querySelectorAll('.tab').forEach(btn=>{
      const active=btn.dataset.panel===panel;
      btn.classList.toggle('active',active);
      if(active)btn.setAttribute('aria-current','page');else btn.removeAttribute('aria-current');
    });
    document.querySelectorAll('.info-panel').forEach(p=>p.classList.toggle('hidden',p.id!==`panel-${panel}`));
  }
  function startAuto(count){
    if(busy)return;
    if($('auto-dialog').open)$('auto-dialog').close();
    autoRemaining=count;
    updateControls();spin(true);
  }
  function openAuto(){
    if(autoRemaining>0){cancelAuto();status('AUTO SPIN STOPPED');return;}
    if(!busy)$('auto-dialog').showModal();
  }
  async function reset(){
    if(busy)return;
    if(!window.confirm('Reset local virtual credits and erase the current spin history?'))return;
    try{
      cancelAuto();const next=await req('/api/reset',{});
      lastRecord=null;recentRounds=[];latestWin=0;
      $('history-list').replaceChildren(create('p','','No rounds in this browser session yet.'));
      $('last-win').textContent='0.00';$('last-round-id').textContent='No completed round';
      $('verify-btn').disabled=true;$('download-btn').disabled=true;
      $('verification-result').textContent='No completed spin to verify.';
      $('verification-result').className='verification-result';
      renderBoard(demoBoard);updateMult(false,0);phase('BASE GAME');status('GOLD TILES TRANSFORM INTO WILD');
      refresh(next);$('game-dialog').close();
    }catch(e){status(`ERROR: ${e.message}`);}
  }
  async function verify(){
    if(!lastRecord)return;
    $('verify-btn').disabled=true;
    try{
      const result=await req('/api/verify',{round:lastRecord});
      $('verification-result').className=`verification-result ${result.valid?'pass':'fail'}`;
      $('verification-result').textContent=result.valid?`PASS: ${result.reason}`:`FAIL: ${result.reason}`;
    }catch(e){$('verification-result').className='verification-result fail';$('verification-result').textContent=e.message;}
    finally{$('verify-btn').disabled=!lastRecord;}
  }
  function download(){
    if(!lastRecord)return;
    const blob=new Blob([JSON.stringify(lastRecord,null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob);const link=document.createElement('a');
    link.href=url;link.download=`mahjong-legend-round-${lastRecord.round_id}.json`;
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  $('spin-btn').addEventListener('click',()=>spin());
  $('minus-btn').addEventListener('click',()=>stepBet(-1));
  $('plus-btn').addEventListener('click',()=>stepBet(1));
  $('bet-display-btn').addEventListener('click',()=>stepBet(1));
  $('turbo-btn').addEventListener('click',toggleTurbo);
  $('sound-btn').addEventListener('click',toggleSound);
  $('auto-btn').addEventListener('click',openAuto);
  $('menu-btn').addEventListener('click',()=>openPanel('rules'));
  $('info-shortcut').addEventListener('click',()=>openPanel('paytable'));
  $('history-shortcut').addEventListener('click',()=>openPanel('history'));
  $('close-dialog').addEventListener('click',()=>$('game-dialog').close());
  $('close-auto').addEventListener('click',()=>$('auto-dialog').close());
  $('auto-cancel').addEventListener('click',()=>$('auto-dialog').close());
  $('skip-btn').addEventListener('click',()=>{skip=true;$('skip-btn').hidden=true;});
  $('reset-btn').addEventListener('click',reset);
  $('verify-btn').addEventListener('click',verify);
  $('download-btn').addEventListener('click',download);
  $('setting-turbo').addEventListener('click',toggleTurbo);
  $('setting-sound').addEventListener('click',toggleSound);
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>selectPanel(btn.dataset.panel)));
  document.querySelectorAll('[data-autospins]').forEach(btn=>btn.addEventListener('click',()=>startAuto(Number(btn.dataset.autospins))));
  window.addEventListener('keydown',e=>{
    if(e.code!=='Space'||e.repeat)return;
    if($('game-dialog').open||$('auto-dialog').open||['INPUT','BUTTON','TEXTAREA'].includes(document.activeElement?.tagName))return;
    e.preventDefault();spin();
  });
  renderBoard(demoBoard);updateMult(false,0);updateControls();
  req('/api/state').then(refresh).catch(err=>{status(`SERVER NOT CONNECTED: ${err.message}`);$('spin-btn').disabled=true;});
})();
