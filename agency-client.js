'use strict';
window.SoftTechNavigation.enable();
window.MahjongAgencyReady=(async()=>{
 const params=new URLSearchParams(location.hash.slice(1)),token=params.get('softtech_launch');
 if(token){sessionStorage.setItem('mahjongAgencyLaunch',token);params.delete('softtech_launch');history.replaceState(null,'',location.pathname+location.search+(params.size?'#'+params:''));}
 const pending=sessionStorage.getItem('mahjongAgencyLaunch');
 if(pending){
  const r=await fetch('/api/agency/launch',{method:'POST',signal:AbortSignal.timeout(15000),credentials:'same-origin',headers:{'Content-Type':'application/json','X-ML-Request':'local-demo'},body:JSON.stringify({token:pending})});
  const d=await r.json();if(!r.ok){if(r.status<500&&r.status!==429)sessionStorage.removeItem('mahjongAgencyLaunch');const e=Error(d.error||'Launch gagal');e.status=r.status;throw e;}
  window.SoftTechNavigation.update(d);
  sessionStorage.removeItem('mahjongAgencyLaunch');
 }
 const response=await fetch('/api/agency/context',{signal:AbortSignal.timeout(15000),credentials:'same-origin',cache:'no-store'});
 const context=await response.json();if(!response.ok){const e=Error(context.error||'Buka game melalui website agen');e.status=response.status;throw e;}window.SoftTechNavigation.update(context);
})();
// The game awaits this promise and displays its error. Keep rejected launches
// from creating an unhandled rejection before deferred renderer scripts load.
window.MahjongAgencyReady.catch(e=>window.SoftTechNavigation.error(e));
