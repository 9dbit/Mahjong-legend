/* Full-bleed artwork; OS status bar and home indicator remain native. */
(() => {
  'use strict';
  const standalone=()=>matchMedia('(display-mode: standalone)').matches||!!navigator.standalone;
  function update(){document.documentElement.classList.toggle('standalone',standalone());const note=document.getElementById('connection-note');if(note)note.hidden=navigator.onLine;}
  update();addEventListener('online',update);addEventListener('offline',update);addEventListener('pageshow',update);
  if('serviceWorker' in navigator&&window.isSecureContext){window.addEventListener('load',()=>{navigator.serviceWorker.register('/sw.js').catch(error=>console.warn('PWA cache unavailable:',error.message));});}
})();
