"""Adapt the reviewed full-frame renderer to versioned Studio manifests.

Run after build_fullframe_ui.py. Frozen game and math sources remain unchanged.
The new derivative is distinct from all legacy game.js assets.
"""
from pathlib import Path
import json
import re

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
  let liveAudioSha=null,liveAudioRelease=null,liveAudioTask=null,liveAudioError=null;
  // Audio follows the active published release; spin tiles and payouts remain
  // bound to the immutable ticket release. This request is read-only.
  async function syncLiveAudio(){
    if(liveAudioTask)return liveAudioTask;
    const task=(async()=>{
      const controller=new AbortController();
      // A broken /audio-live connection must not stall game initialization.
      const deadline=setTimeout(()=>controller.abort(),4500);
      try{
        const res=await fetch(apiBase+'/audio-live',{method:'GET',
          credentials:'same-origin',cache:'no-store',signal:controller.signal,
          headers:{'Accept':'application/json'}});
        if(!res.ok)throw Error('Live audio '+res.status);
        const data=await res.json();
        if(!data?.release_sha256||!data.audio?.music)throw Error('Invalid live audio release');
        if(data.release_sha256!==liveAudioSha){
          await audio()?.configure?.(data.audio);
          liveAudioSha=data.release_sha256;
        }
        liveAudioRelease=data.release_id;
        liveAudioError=null;
        if(window.MahjongStudioRuntime){
          window.MahjongStudioRuntime.liveAudioRelease=data.release_id;
          window.MahjongStudioRuntime.liveAudioError=null;
        }
        return true;
      }catch(error){
        liveAudioError=String(error?.message||error);
        if(window.MahjongStudioRuntime)window.MahjongStudioRuntime.liveAudioError=liveAudioError;
        return false; // Never block a spin or modify ticket state for sound.
      }finally{clearTimeout(deadline);}
    })();
    liveAudioTask=task;
    try{return await task;}finally{if(liveAudioTask===task)liveAudioTask=null;}
  }
  const tileUrl=t=>activeManifest?.tiles?.[t.symbol]?.[t.enhanced?'gold':'normal']||`${tileAssets}tiles/${t.symbol}-${t.enhanced?'gold':'normal'}.webp`;
  const pendingKey='mw-pending:'+apiBase;
  let pendingSpin=null;
  try{pendingSpin=JSON.parse(sessionStorage.getItem(pendingKey)||'null');}catch{}
  function savePending(value){pendingSpin=value;try{value?sessionStorage.setItem(pendingKey,JSON.stringify(value)):sessionStorage.removeItem(pendingKey);}catch{}}
  async function applyManifest(next){
    const m=next?.manifest;if(!m||m.release_sha256===activeManifest?.release_sha256)return;
    // Fetch the published soundtrack in PARALLEL with preparing the tiles.
    // Do not defer this request until the splash is already dismissible.
    const firstManifest=!activeManifest;
    const initialAudioSync=firstManifest?syncLiveAudio():Promise.resolve(!!liveAudioSha);
    await window.MahjongReels.prepare(Object.values(m.tiles).flatMap(x=>[x.normal,x.gold]));
    const board=[...$('board').children].map(col=>[...col.children].filter(e=>e._tile).map(e=>e._tile));
    activeManifest=m;
    // The old spin ticket may pin old music for 24 hours. Fall back to its
    // soundtrack ONLY if the live-audio endpoint was unreachable.
    const activeAudioFound=await initialAudioSync;
    if(firstManifest&&!activeAudioFound&&!liveAudioSha)await audio()?.configure?.(m.audio);
    const scene=m.scene||{};
    const bg=scene.background?`url("${scene.background}")`:'';
    $('game-stage').style.backgroundImage=bg;document.documentElement.style.backgroundImage=bg;
    const crown=document.querySelector('.art-crown');
    if(crown){crown.style.backgroundImage=scene.crown?`url("${scene.crown}")`:'';crown.style.backgroundSize=scene.crown?'100% 100%':'';crown.style.backgroundPosition=scene.crown?'center':'';}
    const center=document.querySelector('.art-board b:nth-child(2)');if(center)center.style.backgroundImage=scene.board?`url("${scene.board}")`:'';
    scene.footer?$('game-stage').style.setProperty('--ff-console-art',`url("${scene.footer}")`):$('game-stage').style.removeProperty('--ff-console-art');
    if(board.length===5&&board.every(c=>c.length)){ $('board').replaceChildren();render(board); }
    const autoRoot=document.querySelector('.auto-options');if(autoRoot){autoRoot.replaceChildren(...m.bet.auto_counts.map(n=>{const b=node('button','',String(n));b.type='button';b.dataset.autospins=String(n);return b;}));}
    window.MahjongStudioRuntime={...window.MahjongStudioRuntime,release:m.release_id,manifest:m,preview:apiBase!=='/api',liveAudioRelease,liveAudioError};
  }""")
    text=replace(text,'Math.round(ms*(turbo?.38:1))','Math.round(ms*(turbo?.38:1)/(activeManifest?.presentation.animation_speed||1))')
    text=replace(text,"`${tileAssets}tiles/${data.symbol}-${data.enhanced?'gold':'normal'}.webp`",'tileUrl(data)')
    text=replace(text,"`${tileAssets}tiles/${t.symbol}-${t.enhanced?'gold':'normal'}.webp`",'tileUrl(t)',3)
    # The previous replacement also sees the fallback in our inserted helper.
    text=text.replace('||tileUrl(t);','||`${tileAssets}tiles/${t.symbol}-${t.enhanced?\'gold\':\'normal\'}.webp`;')
    text=replace(text,"if(!['W','S'].includes(data.symbol)){const glow", "if(!['W','S'].includes(data.symbol)&&tileUrl(data).startsWith(tileAssets)){const glow")
    # The short outside reels start with their FIRST scored tile at the
    # visible top boundary. Their lower one-tile space is an ornamental SVG,
    # not a fake, permanently frozen duplicate of a scoring tile.
    if text.count("function reel(col,index){const e=node('div',`reel${col.length===4?' short':''}`);") != 1:
        raise ValueError("Unexpected reel builder; review first-row animation")
    # Six visual positions can still contain exactly four scored cells.
    # Neither decorative corner receives a _tile payload or a scoring row.
    old_reel = """function reel(col,index){const e=node('div',`reel${col.length===4?' short':''}`);e.setAttribute('aria-label',`Reel ${index+1}`);col.forEach((t,row)=>e.append(tile(t,row)));return e;}"""
    new_reel = """  const cornerTile=(index,col,edge='bottom')=>{
    const names='ABCDEFGHIJKLMNO';
    const signature=(col||[]).reduce((sum,t,n)=>sum+(names.indexOf(t.symbol)+1)*(n+3),index*11+(edge==='top'?19:37));
    return {symbol:names[((signature%names.length)+names.length)%names.length],enhanced:false};
  };
  function reel(col,index){
    const e=node('div',`reel${col.length===4?' short':''}`);
    e.setAttribute('aria-label',`Reel ${index+1}`);
    const visual=(edge)=>{
      const ghost=node('div','corner-visual');ghost.dataset.scoring='false';ghost.dataset.corner=edge;
      ghost.setAttribute('aria-hidden','true');
      const image=node('img','corner-visual-image');image.src=tileUrl(cornerTile(index,col,edge));
      image.alt='';image.draggable=false;image.decoding='async';ghost.append(image);
      return ghost;
    };
    if(col.length===4)e.append(visual('top'));
    col.forEach((t,row)=>e.append(tile(t,row)));
    if(col.length===4)e.append(visual('bottom'));
    return e;
  }"""
    text=replace(text,old_reel,new_reel)
    text=replace(text,'root.children[c].children.length===col.length',"root.children[c].querySelectorAll(':scope > .tile').length===col.length")
    # Scoring rows are independent of the top/bottom visual-only tile nodes.
    text=replace(text,'root.children[c].children[r]._tile',"root.children[c].querySelectorAll(':scope > .tile')[r]?._tile")
    text=replace(text,"filler:(i,j)=>demo[(i+j)%5][j%demo[(i+j)%5].length],","filler:(i,j)=>demo[(i+j)%5][j%demo[(i+j)%5].length],visualFiller:cornerTile,")
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
    mult(false);void syncLiveAudio();''')
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
    # Insert INSIDE the existing game IIFE, before its closing brace.
    closing=next(i for i in range(len(lines)-1,-1,-1) if lines[i].strip()=='})();')
    lines[closing:closing]=[
      "  setInterval(()=>{if(!document.hidden)void syncLiveAudio();},12000);",
      "  document.addEventListener('visibilitychange',()=>{if(!document.hidden)void syncLiveAudio();});",
      "  window.addEventListener('pageshow',()=>{void syncLiveAudio();});",
      "  window.addEventListener('focus',()=>{if(!document.hidden)void syncLiveAudio();});",
    ]
    (OUT/'game.js').write_text('\n'.join(lines)+'\n')

    # Patch the COMPILED reel runtime after immutable v085 hash-checked edits
    # have applied. The original v083 script is intentionally untouched.
    # The fifth visible corner tile is decorative and excluded from scoring.
    compiled=ROOT/'web/assets/portrait-v085/reels.js'
    reel_text=compiled.read_text()
    reel_text=replace(reel_text,
      '  async function run({root, board, buildReel, urlFor, filler, shouldSkip, onStop, turbo}) {',
      '  async function run({root, board, buildReel, urlFor, filler, visualFiller, shouldSkip, onStop, turbo}) {')
    reel_text=replace(reel_text,
      '      const tiles = [...original.children].filter(t => t._tile);',
      "      const tiles = [...original.children].filter(t => t._tile || t.classList.contains('corner-visual'));")
    reel_text=replace(reel_text,
      "        const im = tile.querySelector('.tile-image');",
      "        const im = tile.querySelector('.tile-image, .corner-visual-image');")
    reel_text=replace(reel_text,
      '''      const earlier = prior[i]?.length === col.length ? prior[i] : col;
      const interim = Array.from({length: turbo ? 3 : 4}, (_, j) => filler(i, j));
      return {col, all: [...col, ...interim, ...earlier], steps: col.length + interim.length};''',
      '''      const earlier = prior[i]?.length === col.length ? prior[i] : col;
      const visual = visualFiller && col.length === 4 ? [visualFiller(i, col, 'top'), ...col, visualFiller(i, col, 'bottom')] : col;
      const priorVisual = visualFiller && col.length === 4
        ? [visualFiller(i, earlier, 'top'), ...earlier, visualFiller(i, earlier, 'bottom')] : earlier;
      const interim = Array.from({length: turbo ? 3 : 4}, (_, j) => filler(i, j));
      return {col, visibleCount:visual.length, all:[...visual,...interim,...priorVisual],
        steps:visual.length+interim.length};''')
    reel_text=replace(reel_text,
      '((h + gap) / item.col.length) * item.all.length',
      '((h + gap) / item.visibleCount) * item.all.length')
    reel_text=replace(reel_text,
      'const pitch = (box.height + gap) / seq.col.length;',
      'const pitch = (box.height + gap) / seq.visibleCount;')
    compiled.write_text(reel_text)

    html=(ROOT/'web/index.html').read_text().replace('/assets/portrait-v085/game.js','/assets/studio-v090/game.js').replace('/assets/locked-v08/audio.js','/assets/studio-v090/audio.js').replace('?v=087','?v=098').replace('0.8.7','0.9.2')
    # Explicitly rev both audio and splash script URLs for installed iPhone
    # PWAs. The underlying source remains immutable until this final compiler.
    html=html.replace('/assets/studio-v090/audio.js?v=082',
        '/assets/studio-v090/audio.js?v=099')
    html=html.replace('/assets/reel-v083/splash.js?v=084',
        '/assets/reel-v083/splash.js?v=099')
    html=replace(html,
      '<div id="effects-layer" class="effects-layer" aria-hidden="true"></div>',
      '<span class="jade-cloud-foreground jade-cloud-foreground--left" aria-hidden="true"></span>'
      '<span class="jade-cloud-foreground jade-cloud-foreground--right" aria-hidden="true"></span>'
      '<div id="effects-layer" class="effects-layer" aria-hidden="true"></div>')
    # Only the final Studio game renders the visual-only fifth tiles.
    # Legacy locked UI QA deliberately continues to test its original 4-row outer reels.
    html=replace(html,'<main class="game-stage" id="game-stage"',
                 '<main class="game-stage" id="game-stage" data-corner-reels="animated"')
    # Cache keys must change for an installed iOS PWA as well as Safari.
    html=replace(html,'/assets/portrait-v085/reels.js?v=098','/assets/portrait-v085/reels.js?v=102')
    html=replace(html,'/assets/fullframe-v086/layout.css?v=100','/assets/fullframe-v086/layout.css?v=102')
    # Only mutate the FINAL compiled game HTML; responsive builder verifies
    # that the locked upstream source remains byte-identical until this stage.
    source_touch='<link rel="apple-touch-icon" href="/assets/approved-v082/icon-180.png">'
    assert html.count(source_touch)==1, 'Locked PWA touch link changed'
    html=html.replace(source_touch,
        '<link rel="apple-touch-icon" sizes="180x180" href="/assets/approved-v082/icon-180.png?v=mahjong-gold-20261026">'
        '\n  <link rel="icon" type="image/png" sizes="192x192" href="/assets/approved-v082/icon-192.png?v=mahjong-gold-20261026">')
    # Give iOS LinkPresentation a full-size preview, rather than only a favicon.
    # A new path also avoids persistent Safari touch-icon caches keyed by URL.
    icon_name='assets/branding/mahjong-wild-fullframe-20261027-512.png'
    touch_name='assets/branding/mahjong-wild-fullframe-20261027-180.png'
    for name,size in ((icon_name,512),(touch_name,180)):
        (ROOT/'web'/name).write_bytes((ROOT/f'web/assets/approved-v082/icon-{size}.png').read_bytes())
    html=html.replace('/assets/approved-v082/icon-180.png?v=mahjong-gold-20261026', '/'+touch_name)
    origin='https://mahjong-legend-web-production.up.railway.app'
    social=(
        '<meta property="og:title" content="Mahjong Wild">\n'
        '  <meta property="og:type" content="website">\n'
        f'  <meta property="og:image" content="{origin}/{icon_name}">\n'
        '  <meta property="og:image:width" content="512">\n'
        '  <meta property="og:image:height" content="512">\n'
        '  <meta property="og:image:alt" content="Mahjong Wild">\n'
    )
    html=html.replace('</head>',social+'</head>')
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
    worker=sw.read_text()
    worker,changed=re.subn(r"const CACHE='mahjong-wild-presentation-[0-9]+'",
        "const CACHE='mahjong-wild-presentation-102'",worker)
    if changed!=1: raise ValueError("PWA cache version anchor missing")
    if "url.pathname.startsWith('/studio')" not in worker:
        worker=worker.replace("url.pathname.startsWith('/api/')","(url.pathname.startsWith('/api/')||url.pathname.startsWith('/studio')||url.pathname.startsWith('/media/'))")
    sw.write_text(worker)
    release={'release':'0.9.2','math_version':'0.8.0','studio':True,'schema_version':1,'virtual_credits_only':True}
    (OUT/'release.json').write_text(json.dumps(release)+'\n')
    print('Studio 0.9.2 runtime compiled; math engine unchanged')

if __name__=='__main__': build()
