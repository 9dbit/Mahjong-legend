/* Shared native-game navigation. Only metadata returned by the game server is
 * accepted; launch fragments and referrers never choose a return destination. */
(() => {
 'use strict';
 let enabled=false,ui=null,destination=null,label='website agen',expired=false,lastError=null;
 const validURL=value=>{try{const u=new URL(value);if(u.username||u.password||u.search||u.hash||!(u.protocol==='https:'||u.protocol==='http:'&&['localhost','127.0.0.1'].includes(u.hostname)))return null;return u.href;}catch{return null;}};
 function link(id){const a=document.createElement('a');if(id)a.id=id;a.dataset.agencyReturn='';a.className='pg-return';a.setAttribute('aria-label','Kembali ke website agen');a.addEventListener('click',()=>window.dispatchEvent(new Event('playground:leave')));return a;}
 function apply(){
  if(!ui)return;
  for(const a of document.querySelectorAll('[data-agency-return]')){a.hidden=!destination;if(destination){a.href=destination;a.textContent=a.id==='agency-return'?'‹':'‹ Kembali ke '+label;a.title='Kembali ke '+label;a.setAttribute('aria-label','Kembali ke '+label);}}
  ui.panel.hidden=!lastError;
  if(lastError){ui.title.textContent=expired?'Sesi game berakhir':'Game belum dapat dilanjutkan';ui.message.textContent=expired?'Kembali ke website agen lalu buka game lagi. Hasil ronde yang sudah diterima tetap diproses oleh Soft Tech.':lastError;ui.retry.hidden=expired;}
 }
 function mount(){
  if(!enabled||ui||!document.body)return;
  const style=document.createElement('style');style.textContent=`.pg-return{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:8px 14px;box-sizing:border-box;border:1px solid #e4def7;border-radius:999px;background:#fff;color:#5637ad;font:600 13px/1.25 system-ui,sans-serif;text-decoration:none;box-shadow:0 2px 10px #0002;max-width:min(280px,90vw);text-align:center}.pg-return:focus-visible{outline:3px solid #aa88ff;outline-offset:3px}#agency-return{position:fixed;z-index:2147483001;top:calc(env(safe-area-inset-top,0px) + 8px);right:8px;width:40px;height:40px;padding:0;font-size:30px;line-height:1}#agency-session-notice{position:fixed;inset:0;z-index:2147483000;display:grid;place-items:center;padding:70px 20px 30px;background:#171221ba;font-family:system-ui,sans-serif}#agency-session-notice .pg-card{background:#fff;color:#282435;border-radius:22px;padding:24px;max-width:380px;box-shadow:0 12px 50px #0004}#agency-session-notice h2{font-size:22px;line-height:1.3;margin:0 0 12px}#agency-session-notice p{font-size:15px;line-height:1.6;margin:0 0 20px}#agency-session-notice .pg-actions{display:flex;gap:12px;flex-wrap:wrap}#agency-session-notice button{min-height:40px;padding:8px 16px;border:0;border-radius:999px;background:#ece7f8;color:#5637ad;font:600 14px system-ui;cursor:pointer}.pg-return[hidden],#agency-session-notice[hidden],#agency-session-notice button[hidden]{display:none!important}.pg-menu-return{margin:10px 0}`;
  document.head.append(style);
  const back=link('agency-return');document.body.append(back);
  const panel=document.createElement('section');panel.id='agency-session-notice';panel.hidden=true;panel.setAttribute('role','alert');
  const card=document.createElement('div');card.className='pg-card';
  const title=document.createElement('h2'),message=document.createElement('p'),actions=document.createElement('div');actions.className='pg-actions';
  const retry=document.createElement('button');retry.type='button';retry.textContent='Coba lagi';retry.addEventListener('click',()=>location.reload());actions.append(link(),retry);card.append(title,message,actions);panel.append(card);document.body.append(panel);
  const menu=document.querySelector('#game-dialog .dialog-body, #menuDialog .dialog-body');if(menu){const a=link();a.classList.add('pg-menu-return');menu.prepend(a);}
  ui={panel,title,message,retry};apply();
 }
 function enable(){enabled=true;mount();}
 function update(data={}){
  enable();const nav=data.navigation;if(nav){destination=validURL(nav.home_url);label=String(nav.label||'website agen').slice(0,80);}
  if(typeof data.session_expired==='boolean'){expired=data.session_expired;if(expired)lastError='Sesi game berakhir';else lastError=null;}
  apply();
 }
 function error(e){enable();if(e?.status===401&&destination)expired=true;lastError=['AbortError','TimeoutError','TypeError'].includes(e?.name)?'Koneksi terputus. Pilih Coba lagi untuk memulihkan status ronde.':String(e?.message||'Game belum tersedia. Coba lagi.');apply();}
 window.SoftTechNavigation={enable,update,error,canStart:()=>!expired};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount);
})();
