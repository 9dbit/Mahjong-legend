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
  // Sound is enabled for gameplay by default, but a browser gesture is required to unlock audio.
  // Only lightweight synthesized original effects are used (no third-party assets).
  let sound = true;
  let audio = null;
  let volume = 0.65;
  try {
    const savedSound = localStorage.getItem('mahjong-legend-sfx');
    sound = savedSound !== 'off';
    const savedVolume = Number(localStorage.getItem('mahjong-legend-volume'));
    if (Number.isFinite(savedVolume) && savedVolume >= 0 && savedVolume <= 1 && localStorage.getItem('mahjong-legend-volume') !== null) volume = savedVolume;
  } catch (_) { /* Privacy mode may disable storage. */ }
  let lastRecord = null;
  let latestWin = 0;
  let selectedBet = 1;
  let betOptions = [0.2,0.5,1,2,5,10];
  let autoRemaining = 0;
  let autoTimer = null;
  let recentRounds = [];
  let animatedWin = 0;
  let winAnimation = 0;

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const reduced = () => reduceMotion.matches;
  const motionMs = ms => (skip || reduced()) ? 0 : Math.max(28, Math.round(ms * (turbo ? .36 : 1)));
  const delay = ms => new Promise(resolve => setTimeout(resolve, motionMs(ms)));
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
  function makeTile(tile, opts={}) {
    const el=create('div',`tile ${classFor(tile.symbol)}${tile.enhanced?' enhanced':''}${opts.marked?' marked':''}${opts.falling?' falling':''}`);
    el.title=tile.symbol==='W'?'Wild':tile.symbol==='S'?'Scatter':`Mahjong Wild symbol ${tile.symbol}`;
    el.dataset.symbol=tile.symbol;
    const sprite=create('img','tile-image');
    sprite.src=`/assets/tiles/tile_${tile.symbol}.webp`;
    sprite.alt=''; sprite.draggable=false;sprite.decoding='async';
    el.appendChild(sprite);
    if (opts.row !== undefined) el.style.setProperty('--row', String(opts.row));
    return el;
  }
  function makeReel(col,reelIndex,opts={}) {
    const reel=create('div',`reel${col.length===4?' short':''}`);
    reel.setAttribute('aria-label',`Reel ${reelIndex+1}`);
    col.forEach((tile,index)=>reel.appendChild(makeTile(tile,{
      row:index, marked:opts.marked?.includes(index), falling:opts.falling
    })));
    return reel;
  }
  function renderBoard(board,opts={}) {
    const root=$('board');root.replaceChildren();
    board.forEach((col,reelIndex)=>root.appendChild(makeReel(col,reelIndex,{
      marked:opts.marked?.[reelIndex],falling:opts.falling
    })));
    root.setAttribute('aria-label','Reels: '+board.map(col=>col.map(tile=>tile.symbol).join('')).join(' / '));
  }
  // Spin preview is strictly decorative. Its tiles never feed the RNG or payout.
  async function spinReels(finalBoard) {
    if(skip||reduced()) {renderBoard(finalBoard);return;}
    const preview=finalBoard.map((col,i)=>col.map((_,row)=>({
      ...col[(row+i+2)%col.length], enhanced:col[(row+i+2)%col.length].enhanced
    })));
    renderBoard(preview);
    const board=$('board');
    board.classList.add('rolling-board');
    [...board.children].forEach((reel,i)=>{
      reel.classList.add('rolling');
      reel.style.setProperty('--reel-lag',`${i*-37}ms`);
    });
    await delay(290);
    for(let i=0;i<finalBoard.length;i++) {
      if(skip){renderBoard(finalBoard);break;}
      const finished=makeReel(finalBoard[i],i);
      finished.classList.add('settled');
      board.replaceChild(finished,board.children[i]);
      playSound('stop',i);
      await delay(93);
    }
    board.classList.remove('rolling-board');
    board.setAttribute('aria-label','Reels: '+finalBoard.map(col=>col.map(tile=>tile.symbol).join('')).join(' / '));
    await delay(120);
  }
  // Match each surviving tile to its previous row so falling tiles actually move
  // from their old position. Winning gold tiles become Wild in the same motion.
  function cascadeDrop(event) {
    const board=$('board');
    const oldHeights=[...board.children].map((el,i)=>el.getBoundingClientRect().height/event.before[i].length);
    board.replaceChildren();
    let morphCount=0;
    event.after.forEach((col,reelIndex)=>{
      const marked=new Set(event.marked[reelIndex]);
      const survivors=[];
      event.before[reelIndex].forEach((tile,idx)=>{
        if(!marked.has(idx))survivors.push({row:idx,morph:false});
        else if(tile.enhanced && tile.symbol!=='W' && tile.symbol!=='S')survivors.push({row:idx,morph:true});
      });
      const missing=col.length-survivors.length;
      const reel=makeReel(col,reelIndex);
      [...reel.children].forEach((tile,targetRow)=>{
        const isNew=targetRow<missing;
        const survivor=isNew?null:survivors[targetRow-missing];
        const pitch=oldHeights[reelIndex] || 70;
        const from=isNew?-(missing-targetRow+1.5)*pitch:(survivor.row-targetRow)*pitch;
        tile.style.setProperty('--enter-from',`${from.toFixed(1)}px`);
        tile.style.setProperty('--drop-delay',`${Math.round((isNew ? targetRow : targetRow-missing)*38)}ms`);
        tile.classList.add(isNew?'new-drop':'tile-drop');
        if(survivor?.morph){tile.classList.add('morphed-wild');morphCount++;}
      });
      board.appendChild(reel);
    });
    board.setAttribute('aria-label','Reels: '+event.after.map(col=>col.map(tile=>tile.symbol).join('')).join(' / '));
    if(morphCount)playSound('wild',morphCount);
  }
  function burstWin(text,tier='regular') {
    if(skip||reduced())return;
    const fx=$('effects-layer');
    const floating=create('div',`win-floating ${tier}`,text);
    fx.replaceChildren(floating);
    floating.addEventListener('animationend',()=>floating.remove(),{once:true});
  }
  function animateWinValue(value,ms=310) {
    cancelAnimationFrame(winAnimation);
    const start=animatedWin,end=Number(value);
    if(reduced()||skip||Math.abs(end-start)<.00001){
      animatedWin=end;$('last-win').textContent=format(end);return;
    }
    const duration=motionMs(ms),startTime=performance.now();
    function tick(now){
      const t=Math.min(1,(now-startTime)/Math.max(1,duration));
      const eased=1-(1-t)**3;
      animatedWin=start+(end-start)*eased;
      $('last-win').textContent=format(animatedWin);
      if(t<1)winAnimation=requestAnimationFrame(tick);else animatedWin=end;
    }
    winAnimation=requestAnimationFrame(tick);
    $('last-win').closest('.meter').classList.remove('meter-flash');
    void $('last-win').offsetWidth;
    $('last-win').closest('.meter').classList.add('meter-flash');
  }
  function updateMult(isBonus,index=0) {
    const values=(isBonus?state?.rules?.bonus_multipliers:state?.rules?.base_multipliers) || (isBonus?[2,3,5,8]:[1,2,3,4]);
    const track=$('mult-track');track.replaceChildren();
    values.forEach((v,i)=>track.appendChild(create('span',`mult${i===Math.min(index,3)?' active mult-glow':''}`,`x${v}`)));
    $('machine').classList.toggle('bonus-mode',isBonus);
  }
  function showBanner(text,detail) {
    const el=$('overlay-banner');el.replaceChildren();
    el.appendChild(create('div','',text));el.appendChild(create('small','',detail));
    el.className='overlay-banner '+(Number(detail?.match?.(/\d+/)?.[0])>=30?'major':'');
  }
  function hideBanner(){$('overlay-banner').classList.add('hidden');}
  function status(message){$('stage-notice').textContent=message;}
  function phase(text){$('phase-tag').textContent=text;}
  // Original procedural effects, authored for Mahjong Wild.
  // AudioContext is unlocked from direct user interactions, as iOS Safari requires.
  function playSound(type,variation=0) {
    if(!sound||skip||volume<=0)return;
    if(window.MahjongWildAudio?.playSfx){window.MahjongWildAudio.playSfx(type,variation,sound,volume);return;}
    try {
      const AudioContextClass=window.AudioContext||window.webkitAudioContext;
      if(!AudioContextClass)return;
      const ctx=audio||(audio=new AudioContextClass());
      if(ctx.state==='suspended')void ctx.resume();
      const start=ctx.currentTime+0.005;
      const master=Math.min(1,volume);
      const tone=(pitch,duration=.14,at=0,gain=.035,shape='sine',endPitch=pitch)=>{
        const osc=ctx.createOscillator(),amp=ctx.createGain();
        osc.type=shape;
        osc.frequency.setValueAtTime(Math.max(30,pitch),start+at);
        osc.frequency.exponentialRampToValueAtTime(Math.max(30,endPitch),start+at+duration);
        amp.gain.setValueAtTime(.0001,start+at);
        amp.gain.exponentialRampToValueAtTime(Math.max(.0002,master*gain),start+at+.012);
        amp.gain.exponentialRampToValueAtTime(.0001,start+at+duration);
        osc.connect(amp).connect(ctx.destination);
        osc.start(start+at);osc.stop(start+at+duration+.012);
      };
      const clack=(duration=.065,at=0,gain=.027,frequency=1450)=>{
        const frames=Math.max(64,Math.floor(ctx.sampleRate*duration));
        const buffer=ctx.createBuffer(1,frames,ctx.sampleRate);
        const data=buffer.getChannelData(0);
        for(let i=0;i<frames;i++)data[i]=(Math.random()*2-1)*Math.pow(1-i/frames,1.75);
        const source=ctx.createBufferSource(),filter=ctx.createBiquadFilter(),amp=ctx.createGain();
        source.buffer=buffer;filter.type='bandpass';filter.frequency.value=frequency;
        filter.Q.value=.75;amp.gain.setValueAtTime(master*gain,start+at);
        amp.gain.exponentialRampToValueAtTime(.0001,start+at+duration);
        source.connect(filter).connect(amp).connect(ctx.destination);
        source.start(start+at);source.stop(start+at+duration);
      };
      switch(type){
        case 'tap': tone(490,.07,0,.012,'triangle',425); break;
        case 'spin':
          clack(.14,0,.022,480);tone(170,.23,0,.027,'sawtooth',420);
          tone(280,.27,.04,.017,'triangle',540);break;
        case 'stop':
          clack(.072,0,.039,900+variation*160);
          tone(220+variation*16,.09,0,.021,'triangle',160);break;
        case 'win':
          clack(.085,0,.025,1870);tone(540,.22,.005,.030,'sine',700);
          tone(800,.28,.065,.022,'sine',910);break;
        case 'cascade':
          clack(.13,0,.03,2450);tone(400,.22,0,.025,'triangle',600);break;
        case 'multiplier':
          tone(780,.14,0,.024,'sine',1040);tone(1180,.22,.07,.018,'sine',1400);break;
        case 'wild':
          tone(640,.28,0,.027,'sine',1000);tone(1040,.32,.05,.020,'triangle',1570);
          clack(.11,.03,.015,3650);break;
        case 'bonus':
          [392,523,659,784].forEach((v,i)=>{tone(v,.31,i*.11,.036,'triangle',v*1.06);tone(v*2,.22,i*.11,.012,'sine');});break;
        case 'bigwin':
          [392,494,587,784,988].forEach((v,i)=>tone(v,.44,i*.075,.032,'sine',v*1.025));
          clack(.13,.08,.025,3200);break;
        default: tone(330,.07,0,.012,'triangle',270);
      }
    }catch(_){/* Sound may be blocked by browser settings. Gameplay still works. */}
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
    $('sfx-volume').value=String(Math.round(volume*100));
    $('sfx-value').textContent=`${Math.round(volume*100)}%`;
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
    updateControls();updateMult(false,0);renderPaytable();
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
  function toggleTurbo(){turbo=!turbo;updateControls();playSound('tap');}
  function toggleSound(){
    sound=!sound;
    try{localStorage.setItem('mahjong-legend-sfx',sound?'on':'off');}catch(_){}
    updateControls();playSound('tap');
  }
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
    let cumulative=0;
    for(const evt of round.events){
      if(evt.type==='screen_start'){
        const bonus=evt.phase==='bonus';
        phase(bonus?`FREE SPIN ${evt.number} / ${round.free_spins_played}`:'BASE GAME');
        updateMult(bonus,0);
        status(bonus?`FREE SPIN ${evt.number}`:'SPINNING...');
        await spinReels(evt.board);
      }else if(evt.type==='cascade'){
        const phaseBonus=evt.phase==='bonus';
        updateMult(phaseBonus,evt.step-1);
        renderBoard(evt.before,{marked:evt.marked});
        const credit=Number(evt.awarded_x)*selectedBet;
        cumulative+=credit;
        status(`CASCADE ${evt.step}  /  x${evt.multiplier}  /  +${format(credit)}`);
        burstWin(`+${format(credit)}`);
        playSound(evt.step>1?'multiplier':'win');
        animateWinValue(cumulative);
        await delay(355);
        if(evt.after){
          for(const [reelIndex,indices] of evt.marked.entries()){
            const reel=$('board').children[reelIndex];
            indices.forEach(row=>{
              const tile=reel?.children[row];
              if(tile)tile.classList.add(tile.classList.contains('enhanced')?'gold-burst':'dissolving');
            });
          }
          playSound('cascade');
          await delay(160);
          cascadeDrop(evt);
          await delay(455);
        }
      }else if(evt.type==='bonus_trigger'){
        showBanner('FREE SPINS',`+${evt.awarded_spins} SPINS`);
        playSound('bonus');await delay(1000);hideBanner();
      }else if(evt.type==='bonus_retrigger'){
        showBanner('EXTRA SPINS',`+${evt.added_spins} SPINS`);
        playSound('bonus');await delay(760);hideBanner();
      }else if(evt.type==='cap_reached'){
        showBanner('LEGENDARY WIN',`MAX ${evt.cap_x}x BET`);
        playSound('bigwin');await delay(1200);hideBanner();
      }else if(evt.type==='round_end'){
        animateWinValue(creditWin,180);
        if(Number(evt.payout_x)>0){
          const amount=Number(evt.payout_x);
          const tier=amount>=50?'LEGENDARY WIN':amount>=20?'BIG WIN':'TOTAL WIN';
          showBanner(tier,`${format(creditWin)} CREDITS`);
          playSound(amount>=20?'bigwin':'win');
          await delay(amount>=20?1050:580);hideBanner();
        }
        phase('BASE GAME');
        status(Number(evt.payout_x)>0?`TOTAL WIN  ${format(creditWin)} CREDITS`:'GOLD TILES TRANSFORM INTO WILD');
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
    status('SPINNING...');cancelAnimationFrame(winAnimation);animatedWin=0;latestWin=0;
    $('last-win').textContent='0.00';$('effects-layer').replaceChildren();
    if(state)$('balance').textContent=format(Number(state.balance)-selectedBet);
    $('board').classList.add('spinning');playSound('spin');
    try{
      const promised=state?.next_seed_commitment_sha256;
      const [data]=await Promise.all([req('/api/spin',{bet:String(selectedBet)}),delay(290)]);
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
    }catch(err){status(`ERROR: ${err.message}`);cancelAuto();if(state)$('balance').textContent=format(state.balance);}
    finally{
      hideBanner();$('board').classList.remove('spinning','rolling-board');busy=false;updateControls();
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
      cancelAnimationFrame(winAnimation);animatedWin=0;$('effects-layer').replaceChildren();
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
  $('sfx-volume').addEventListener('input',e=>{
    volume=Math.min(1,Math.max(0,Number(e.target.value)/100));
    $('sfx-value').textContent=`${Math.round(volume*100)}%`;
    try{localStorage.setItem('mahjong-legend-volume',String(volume));}catch(_){}
  });
  $('sfx-volume').addEventListener('change',()=>playSound('tap'));
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
