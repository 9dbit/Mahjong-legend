"""Adapt the reviewed full-frame renderer to versioned Studio manifests.

Run after build_fullframe_ui.py. Frozen game and math sources remain unchanged.
The new derivative is distinct from all legacy game.js assets.
"""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'web/assets/studio-v090'

def replace(source,old,new,count=1):
    if source.count(old)!=count: raise ValueError(f'Review Studio runtime integration anchor: {old[:100]} ({source.count(old)} vs {count})')
    return source.replace(old,new)

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    text=(ROOT/'web/assets/portrait-v085/game.js').read_text()
    text=replace(text,'UI 0.8.7','UI 0.9.2')
    text=replace(text,"  const tileAssets='/assets/portrait-v085/';", """  const tileAssets='/assets/portrait-v085/';
  const apiBase=document.querySelector('meta[name="studio-api-base"]')?.content||'/api';
  let activeManifest=null;
  const tileUrl=t=>activeManifest?.tiles?.[t.symbol]?.[t.enhanced?'gold':'normal']||`${tileAssets}tiles/${t.symbol}-${t.enhanced?'gold':'normal'}.webp`;
  const pendingKey='mw-pending:'+apiBase;
  let pendingSpin=null;
  try{pendingSpin=JSON.parse(sessionStorage.getItem(pendingKey)||'null');}catch{}
  function savePending(value){pendingSpin=value;try{value?sessionStorage.setItem(pendingKey,JSON.stringify(value)):sessionStorage.removeItem(pendingKey);}catch{}}
  async function applyManifest(next){
    const m=next?.manifest;if(!m||m.release_sha256===activeManifest?.release_sha256)return;
    await window.MahjongReels.prepare(Object.values(m.tiles).flatMap(x=>[x.normal,x.gold]));
    const board=[...$('board').children].map(col=>[...col.children].filter(e=>e._tile).map(e=>e._tile));
    activeManifest=m;
    await audio()?.configure?.(m.audio);
    const scene=m.scene||{};
    const bg=scene.background?`url("${scene.background}")`:'';
    $('game-stage').style.backgroundImage=bg;document.documentElement.style.backgroundImage=bg;
    const crown=document.querySelector('.art-crown');
    if(crown){crown.style.backgroundImage=scene.crown?`url("${scene.crown}")`:'';crown.style.backgroundSize=scene.crown?'100% 100%':'';crown.style.backgroundPosition=scene.crown?'center':'';}
    const center=document.querySelector('.art-board b:nth-child(2)');if(center)center.style.backgroundImage=scene.board?`url("${scene.board}")`:'';
    scene.footer?$('game-stage').style.setProperty('--ff-console-art',`url("${scene.footer}")`):$('game-stage').style.removeProperty('--ff-console-art');
    if(board.length===5&&board.every(c=>c.length)){ $('board').replaceChildren();render(board); }
    const autoRoot=document.querySelector('.auto-options');if(autoRoot){autoRoot.replaceChildren(...m.bet.auto_counts.map(n=>{const b=node('button','',String(n));b.type='button';b.dataset.autospins=String(n);return b;}));}
    window.MahjongStudioRuntime={release:m.release_id,manifest:m,preview:apiBase!=='/api'};
  }""")
    text=replace(text,'Math.round(ms*(turbo?.38:1))','Math.round(ms*(turbo?.38:1)/(activeManifest?.presentation.animation_speed||1))')
    text=replace(text,"`${tileAssets}tiles/${data.symbol}-${data.enhanced?'gold':'normal'}.webp`",'tileUrl(data)')
    text=replace(text,"`${tileAssets}tiles/${t.symbol}-${t.enhanced?'gold':'normal'}.webp`",'tileUrl(t)',3)
    # The previous replacement also sees the fallback in our inserted helper.
    text=text.replace('||tileUrl(t);','||`${tileAssets}tiles/${t.symbol}-${t.enhanced?\'gold\':\'normal\'}.webp`;')
    text=replace(text,"if(!['W','S'].includes(data.symbol)){const glow", "if(!['W','S'].includes(data.symbol)&&tileUrl(data).startsWith(tileAssets)){const glow")
    # The corner cap is a non-interactive pseudo-element, never a winning tile node.
    old_reel="function reel(col,index){const e=node('div',`reel${col.length===4?' short':''}`);"
    new_reel=old_reel+"if(col.length===4){const cap=col[col.length-1];e.style.setProperty('--corner-cap-image',`url(\"${tileUrl(cap)}\")`);}"
    text=replace(text,old_reel,new_reel)
    text=replace(text,'  function refresh(next){\n    state=next;options=next.bet_options?.map(Number)||options;', '''  async function refresh(next){
    await applyManifest(next);
    if(!state)stake=String(next.spin_price);
    state=next;options=next.bet_options?[...next.bet_options]:options;
    if(pendingSpin&&pendingSpin.ticket_id!==next.ticket?.id)savePending(null);
    if(next.ticket?.status==='pending')stake=String(next.ticket.stake||pendingSpin?.bet||stake);
    if(next.migration_notice){const p=node('p','studio-migration-notice',next.migration_notice);p.setAttribute('role','status');$('panel-rules').prepend(p);notice('SESI PERMANEN AKTIF');}
    const root=$('paytable-list');root.replaceChildren();for(const[s,values]of Object.entries(next.rules.paytable)){const row=node('div','paytable-item');const label=node('span','symbol-label'),icon=node('img','paytable-tile');icon.src=tileUrl({symbol:s,enhanced:false});icon.alt=`Tile ${s}`;label.append(icon,node('b','',s));row.append(label,...values.map(v=>node('span','',String(v))));root.append(row);}
    const summary=$('studio-rules-summary');if(summary)summary.textContent=`Multiplier base: ${next.rules.base_multipliers.join(' → ')}. Bonus: ${next.rules.bonus_multipliers.join(' → ')}. Free spins untuk 3 scatter: ${next.rules.free_spins_for_3_scatters}, +${next.rules.extra_free_spins} per scatter tambahan. Batas seluruh ronde: ${next.max_payout_x}×.`;
    for(const[id,value]of Object.entries({'rule-base':next.rules.base_multipliers.map(v=>'x'+v).join(' / '),'rule-bonus':next.rules.bonus_multipliers.map(v=>'x'+v).join(' / '),'rule-free':next.rules.free_spins_for_3_scatters+' FREE SPINS','rule-extra':'+'+next.rules.extra_free_spins+' FREE SPINS','rule-cap':next.max_payout_x+'x BET'})){if($(id))$(id).textContent=value;}
    mult(false);''')
    text=replace(text,'fetch(path,{signal:',"fetch(path.startsWith('/api/')?apiBase+path.slice(4):path,{signal:")
    text=text.replace('disabled=busy||auto>0',"disabled=busy||auto>0||state?.ticket?.status==='pending'")
    text=replace(text,"$('auto-btn').disabled=busy&&!auto;", "$('auto-btn').disabled=(busy&&!auto)||state?.ticket?.status==='pending';")
    text=replace(text,"const bonus=event.phase==='bonus';$('phase-tag')", "const bonus=event.phase==='bonus';audio()?.setPhase?.(bonus?'bonus':'base');$('phase-tag')")
    text=replace(text,'await spinReels(event.board);','await spinReels(event.board);if(event.scatters>0)sfx(\'scatter\');')
    text=replace(text,'Number(event.payout_x)>=20','Number(event.payout_x)>=(activeManifest?.presentation.big_win_x??20)')
    text=replace(text,'Number(event.payout_x)>=50','Number(event.payout_x)>=(activeManifest?.presentation.mega_win_x??50)')
    text=replace(text,"accepted=await req('/api/spin',{bet:String(stake)});await verifySeed(accepted.round,commitment);", """if(state.ticket){
        if(!pendingSpin||pendingSpin.ticket_id!==state.ticket.id)savePending({bet:String(stake),ticket_id:state.ticket.id,idempotency_key:crypto.randomUUID()});
        accepted=await req('/api/spin',pendingSpin);
      }else accepted=await req('/api/spin',{bet:String(stake)});
      await verifySeed(accepted.round,commitment);
      if(accepted.round_manifest&&activeManifest&&accepted.round_manifest.release_sha256!==activeManifest.release_sha256)throw Error('Manifest ronde tidak sesuai tiket. Hasil tersimpan, sinkronkan ulang.');
      savePending(null);""")
    text=replace(text,'refresh(accepted.state);storeHistory(accepted);',"""const policy=activeManifest?.bet;
      if(auto&&((policy?.auto_stop_on_bonus&&accepted.round.free_spins_played>0)||(policy?.auto_stop_on_win_x!=null&&Number(accepted.round.total_payout_x)>=policy.auto_stop_on_win_x)))auto=0;
      let latest=accepted.state;try{latest=await req('/api/state');}catch{}
      await refresh(latest);storeHistory(accepted);""")
    text=replace(text,"try{refresh(await req('/api/state'));", "try{await refresh(await req('/api/state'));")
    text=replace(text,"cancelAuto();refresh(await req('/api/reset',{}));", "cancelAuto();await refresh(await req('/api/reset',{}));")
    text=replace(text,"$('phase-tag').textContent='BASE GAME';$('game-stage').dataset.motionPhase='idle';", "$('phase-tag').textContent='BASE GAME';audio()?.setPhase?.('base');$('game-stage').dataset.motionPhase='idle';")
    old="document.querySelectorAll('[data-autospins]').forEach(b=>b.addEventListener('click',()=>{if(busy)return;auto=Number(b.dataset.autospins);$('auto-dialog').close();void spin(true);}));"
    new="document.querySelector('.auto-options').addEventListener('click',e=>{const b=e.target.closest('[data-autospins]');if(!b||busy)return;auto=Number(b.dataset.autospins);$('auto-dialog').close();void spin(true);});"
    text=replace(text,old,new)
    # The startup now preloads exactly the ticket's manifest, then renders it.
    lines=text.splitlines()
    startup=next(i for i,line in enumerate(lines) if "Promise.all([req('/api/state')" in line)
    lines[startup]="  req('/api/state').then(async next=>{await refresh(next);mult(false);window.MahjongReels.prewarm($('board'));notice(next.migration_notice?'SESI BARU · CEK INFO':'SIAP BERMAIN');}).catch(e=>{notice('KONEKSI GAGAL. MUAT ULANG.');$('spin-btn').disabled=true;console.error(e.message);});"
    (OUT/'game.js').write_text('\n'.join(lines)+'\n')
    html=(ROOT/'web/index.html').read_text().replace('/assets/portrait-v085/game.js','/assets/studio-v090/game.js').replace('/assets/locked-v08/audio.js','/assets/studio-v090/audio.js').replace('?v=087','?v=092').replace('0.8.7','0.9.2')
    html=html.replace('<section id="panel-rules"', '<section id="panel-rules"')
    for label,ident in [('BASE MULTIPLIERS','rule-base'),('FREE SPIN MULTIPLIERS','rule-bonus'),('3 SCATTER','rule-free'),('SCATTER TAMBAHAN','rule-extra'),('MAKSIMUM PER PUTARAN','rule-cap')]:
        html=html.replace('<span>'+label+'</span><b>','<span>'+label+'</span><b id="'+ident+'">')
    html=html.replace('Saldo sesi dapat direset saat server diperbarui.','Saldo sesi tersimpan permanen dan hanya direset melalui tombol Reset Demo.')
    # Replace fixed baseline rule wording with a live snapshot summary.
    marker='<p class="small-note">RTP belum divalidasi ulang'
    start=html.find(marker)
    if start>=0:
        end=html.index('</p>',start)+4
        html=html[:start]+'<p id="studio-rules-summary" class="small-note"></p><p class="small-note">Kredit virtual. RTP adalah estimasi statistik per versi aturan; hasil setiap ronde dapat diverifikasi.</p>'+html[end:]
    (ROOT/'web/index.html').write_text(html)
    sw=ROOT/'web/sw.js'
    worker=sw.read_text().replace('presentation-087','presentation-092')
    if "url.pathname.startsWith('/studio')" not in worker:
        worker=worker.replace("url.pathname.startsWith('/api/')","(url.pathname.startsWith('/api/')||url.pathname.startsWith('/studio')||url.pathname.startsWith('/media/'))")
    sw.write_text(worker)
    release={'release':'0.9.2','math_version':'0.8.0','studio':True,'schema_version':1,'virtual_credits_only':True}
    (OUT/'release.json').write_text(json.dumps(release)+'\n')
    print('Studio 0.9.2 runtime compiled; math engine unchanged')

if __name__=='__main__': build()
