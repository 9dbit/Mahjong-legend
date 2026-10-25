/* UI 0.8.6. Width-first mobile geometry; no RNG, payment, or spin requests. */
(() => {
  'use strict';
  const stage = document.getElementById('game-stage');
  if (!stage) return;
  const root = document.documentElement;
  const standaloneMedia = matchMedia('(display-mode: standalone)');
  let pending = 0, warmTimer = 0, previous = '', lastBoardWidth = null;
  const px = value => `${Math.max(0, value).toFixed(3)}px`;
  const put = (key,value) => stage.style.setProperty(`--ff-${key}`,px(value));
  function update() {
    pending = 0;
    const view = window.visualViewport;
    // A pinch zoom must not be counteracted by a new application layout.
    if (view && Math.abs(view.scale - 1) > .02) return;
    const standalone = standaloneMedia.matches || !!navigator.standalone;
    root.classList.toggle('standalone',standalone);
    const width = root.clientWidth;
    // Safari's visible viewport follows its toolbar. An installed app instead
    // paints the entire layout viewport, including beneath status/home areas.
    // Do not shrink its artwork to a transient, smaller visualViewport value.
    const height = Math.round(standalone
      ? Math.max(innerHeight,root.clientHeight,root.getBoundingClientRect().height,view?.height || 0)
      : (view?.height || innerHeight));
    const portrait = width <= height;
    const w = portrait ? width : Math.min(800,height*864/1859);
    const css = getComputedStyle(stage);
    const safeTop = parseFloat(css.getPropertyValue('--ff-safe-top')) || 0;
    const safeBottom = parseFloat(css.getPropertyValue('--ff-safe-bottom')) || 0;
    // Landscape centers the portrait artwork over a full-screen backdrop. Only
    // the part of a side inset that reaches this stage constrains live controls.
    const stageLeft = (width-w)/2;
    const safeLeft = Math.max(0,(parseFloat(css.getPropertyValue('--ff-safe-left')) || 0)-stageLeft);
    const safeRight = Math.max(0,(parseFloat(css.getPropertyValue('--ff-safe-right')) || 0)-stageLeft);
    const innerWidth = Math.max(1,w-safeLeft-safeRight);
    const center = safeLeft+innerWidth/2;
    const h = Math.max(height,1), usable = Math.max(1,h-safeTop-safeBottom);
    const key = [w,h,safeTop,safeBottom,safeLeft,safeRight,standalone].join(':');
    if (key === previous) return;
    previous = key;
    const fraction = Math.max(.62,Math.min(.728,.728-(1859/864-usable/innerWidth)*.17));
    // A square/split-screen viewport still needs room for the header and Spin.
    // Bound the board height before allocating those panels, preserving 2:3
    // tile geometry instead of allowing zero-height controls or cropping them.
    const minimumPanels = Math.min(usable*.55,Math.max(120,usable*.3));
    const boardHeight = Math.min(1.5*innerWidth*fraction-.0064*w,usable-minimumPanels);
    const boardWidth = (boardHeight+.0064*w)/1.5;
    const spare = Math.max(0,usable-boardHeight);
    const header = spare*394/921, footer = spare-header;
    const rail = Math.min(header*.28,w*89/864);
    const crown = header-rail;
    const crownScale = Math.min(crown/305,innerWidth/864);
    const crownTop = safeTop+crown-305*crownScale;
    const footerTop = safeTop+header+boardHeight;
    const hud = Math.min(footer*.4,w*199/864);
    const controlsScale = Math.min((footer-hud)/328,innerWidth/864);
    // Retire transient textures on a real geometry change, not on every scroll.
    // This affects only animation; the accepted server round still settles once.
    if (lastBoardWidth !== null && Math.abs(boardWidth-lastBoardWidth)>.5) {
      window.MahjongReels?.finish();
    }
    lastBoardWidth=boardWidth;
    put('width',w);put('height',h);put('safe',safeTop);
    put('header',header);put('crown-height',305*crownScale);put('crown-top',crownTop);
    put('crown-left',center-432*crownScale);put('crown-width',864*crownScale);
    put('crown-edge-left',center-420*crownScale);put('crown-edge-right',w-center-420*crownScale);
    put('rail-top',safeTop+crown);put('rail-height',rail);
    put('board-top',safeTop+header);put('board-width',boardWidth);
    put('board-left',center-boardWidth/2);put('board-height',boardHeight);
    put('footer-top',footerTop);put('hud-height',hud);
    put('controls-top',footerTop+hud);put('controls-height',328*controlsScale);
    put('controls-width',864*controlsScale);put('controls-left',center-432*controlsScale);
    put('controls-edge-left',center-420*controlsScale);put('controls-edge-right',w-center-420*controlsScale);
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
  addEventListener('orientationchange',queue,{passive:true});
  standaloneMedia.addEventListener('change',queue);
  window.visualViewport?.addEventListener('resize',queue,{passive:true});
  addEventListener('pagehide',()=>clearTimeout(warmTimer));
  window.MahjongViewport=Object.freeze({refresh:queue});
})();
