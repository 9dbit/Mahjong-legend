'use strict';
window.MahjongAgencyReady=(async()=>{
 const params=new URLSearchParams(location.hash.slice(1)),token=params.get('playground_launch');
 if(token){sessionStorage.setItem('mahjongAgencyLaunch',token);params.delete('playground_launch');history.replaceState(null,'',location.pathname+location.search+(params.size?'#'+params:''));}
 const pending=sessionStorage.getItem('mahjongAgencyLaunch');
 if(pending){
  const r=await fetch('/api/agency/launch',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-ML-Request':'local-demo'},body:JSON.stringify({token:pending})});
  const d=await r.json();if(!r.ok){if(r.status<500&&r.status!==429)sessionStorage.removeItem('mahjongAgencyLaunch');throw Error(d.error||'Launch gagal');}
  sessionStorage.removeItem('mahjongAgencyLaunch');
 }
})();
// The game awaits this promise and displays its error. Keep rejected launches
// from creating an unhandled rejection before deferred renderer scripts load.
window.MahjongAgencyReady.catch(()=>{});
