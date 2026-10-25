/* UI 0.8.6. Width-first mobile geometry; no RNG, payment, or spin requests. */
(() => {
  'use strict';
  const stage = document.getElementById('game-stage');
  if (!stage) return;
  const root = document.documentElement;
  let pending = 0, warmTimer = 0, previous = '', lastBoardWidth = null;
  const px = value => `${Math.max(0, value).toFixed(3)}px`;
  const put = (key,value) => stage.style.setProperty(`--ff-${key}`,px(value));
  function update() {
    pending = 0;
    const view = window.visualViewport;
    // A pinch zoom must not be counteracted by a new application layout.
    if (view && Math.abs(view.scale - 1) > .02) return;
    const width = root.clientWidth;
    const height = Math.round(view?.height || innerHeight);
    const portrait = width <= height;
    const w = portrait ? width : Math.min(800,height*864/1859);
    const css = getComputedStyle(stage);
    const safeTop = parseFloat(css.getPropertyValue('--ff-safe-top')) || 0;
    const safeBottom = parseFloat(css.getPropertyValue('--ff-safe-bottom')) || 0;
    const h = Math.max(height,1), usable = Math.max(1,h-safeTop-safeBottom);
    const key = [w,h,safeTop,safeBottom].join(':');
    if (key === previous) return;
    previous = key;
    const fraction = Math.max(.62,Math.min(.728,.728-(1859/864-usable/w)*.17));
    const boardWidth = w*fraction;
    const boardHeight = 1.5*boardWidth-.0064*w;
    const spare = Math.max(0,usable-boardHeight);
    const header = spare*394/921, footer = spare-header;
    const rail = Math.min(header*.28,w*89/864);
    const crown = header-rail;
    const crownScale = Math.min(crown/305,w/864);
    const crownTop = safeTop+crown-305*crownScale;
    const footerTop = safeTop+header+boardHeight;
    const hud = Math.min(footer*.4,w*199/864);
    const controlsScale = Math.min((footer-hud)/328,w/864);
    // Retire transient textures on a real geometry change, not on every scroll.
    // This affects only animation; the accepted server round still settles once.
    if (lastBoardWidth !== null && Math.abs(boardWidth-lastBoardWidth)>.5) {
      window.MahjongReels?.finish();
    }
    lastBoardWidth=boardWidth;
    put('width',w);put('height',h);put('safe',safeTop);
    put('header',header);put('crown-height',305*crownScale);put('crown-top',crownTop);
    put('crown-left',(w-864*crownScale)/2);put('crown-width',864*crownScale);
    put('crown-edge',(w-840*crownScale)/2);
    put('rail-top',safeTop+crown);put('rail-height',rail);
    put('board-top',safeTop+header);put('board-width',boardWidth);
    put('board-left',(w-boardWidth)/2);put('board-height',boardHeight);
    put('footer-top',footerTop);put('hud-height',hud);
    put('controls-top',footerTop+hud);put('controls-height',328*controlsScale);
    put('controls-width',864*controlsScale);put('controls-left',(w-864*controlsScale)/2);
    put('controls-edge',(w-840*controlsScale)/2);
    put('control-unit',controlsScale);put('crown-unit',crownScale);
    stage.dataset.fullframe=portrait?'portrait':'landscape';
    // Chrome may emit many size events. Warm once after it settles, not once
    // per animation frame; the input handler can still prepare on demand.
    clearTimeout(warmTimer);
    warmTimer=setTimeout(()=>{
      if(document.querySelector('#spin-btn')?.getAttribute('aria-label')==='Spin')
        window.MahjongReels?.prewarm(document.getElementById('board'));
    },160);
  }
  const queue=()=>{if(!pending)pending=requestAnimationFrame(update);};
  update();
  addEventListener('resize',queue,{passive:true});addEventListener('pageshow',queue,{passive:true});
  window.visualViewport?.addEventListener('resize',queue,{passive:true});
  addEventListener('pagehide',()=>clearTimeout(warmTimer));
  window.MahjongViewport=Object.freeze({refresh:queue});
})();
