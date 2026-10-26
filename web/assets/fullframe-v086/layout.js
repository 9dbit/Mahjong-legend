/* UI 0.8.7. Full-width scene and independent touch controls; no game requests. */
(() => {
  'use strict';
  const stage = document.getElementById('game-stage');
  if (!stage) return;
  const root = document.documentElement;
  const standaloneMedia = matchMedia('(display-mode: standalone)');
  let pending = 0, warmTimer = 0, previous = '', lastBoardWidth = null;
  const px = value => `${Math.max(0, value).toFixed(6)}px`;
  const put = (key,value) => stage.style.setProperty(`--ff-${key}`,px(value));
  function update() {
    pending = 0;
    const view = window.visualViewport;
    // A pinch zoom must not be counteracted by a new application layout.
    if (view && Math.abs(view.scale - 1) > .02) return;
    const standalone = standaloneMedia.matches || !!navigator.standalone;
    root.classList.toggle('standalone',standalone);
    const viewportWidth = root.clientWidth;
    // Safari's visible viewport follows its toolbar. An installed app instead
    // paints the entire layout viewport, including beneath status/home areas.
    // Do not shrink its artwork to a transient, smaller visualViewport value.
    const height = Math.round(standalone
      ? Math.max(innerHeight,root.clientHeight,root.getBoundingClientRect().height,view?.height || 0)
      : (view?.height || innerHeight));
    // Large monitors use one complete, height-fitted cabinet. The former
    // landscape split scaled the crown to 70% of a wide monitor while leaving
    // a tiny detached reel board and a separate right-hand Spin panel.
    // Keep short landscape phones/tablets in their existing split-console mode.
    const desktop = viewportWidth >= 1000 && height >= 620;
    root.classList.toggle('desktop-layout',desktop);
    const w = desktop
      ? Math.min(viewportWidth - 36, 580, Math.max(350, Math.round(height * .50)))
      : viewportWidth;
    const portrait = desktop || viewportWidth <= height || viewportWidth < 540;
    // Landscape has a scene beside a full-size console. A portrait column
    // squeezed to 180px cannot fit five accessible controls.
    const panelWidth = portrait ? w : Math.min(460,Math.max(320,w*.52));
    const sceneWidth = portrait ? w : w-panelWidth;
    const panelLeft = portrait ? 0 : sceneWidth;
    const css = getComputedStyle(stage);
    const safeTop = parseFloat(css.getPropertyValue('--ff-safe-top')) || 0;
    const safeBottom = parseFloat(css.getPropertyValue('--ff-safe-bottom')) || 0;
    // Landscape centers the portrait artwork over a full-screen backdrop. Only
    // the part of a side inset that reaches this stage constrains live controls.
    const safeLeft = Math.max(0,parseFloat(css.getPropertyValue('--ff-safe-left')) || 0);
    const safeRight = Math.max(0,parseFloat(css.getPropertyValue('--ff-safe-right')) || 0);
    const innerWidth = Math.max(1,sceneWidth-safeLeft-(portrait?safeRight:0));
    const center = safeLeft+innerWidth/2;
    const controlsSafeLeft = portrait ? safeLeft : 0;
    const controlsWidth = Math.max(1,panelWidth-controlsSafeLeft-safeRight);
    const h = Math.max(height,1), usable = Math.max(1,h-safeTop-safeBottom);
    const key = [viewportWidth,w,h,safeTop,safeBottom,safeLeft,safeRight,standalone,desktop].join(':');
    if (key === previous) return;
    previous = key;
    const fraction = Math.max(.62,Math.min(.728,.728-(1859/864-usable/innerWidth)*.17));
    // A square/split-screen viewport still needs room for the header and Spin.
    // Bound the board height before allocating those panels, preserving 2:3
    // tile geometry instead of allowing zero-height controls or cropping them.
    const minimumPanels = Math.min(usable*.55,Math.max(120,usable*.3));
    const preferredBoard = Math.min(1.5*innerWidth*fraction-.0064*w,usable-minimumPanels);
    // Reserve the entire original-width crown before sizing the reels. The
    // former height-first budget shrank it into a narrow, visibly separate box.
    const crownScale = sceneWidth/864;
    const rail = 89*crownScale;
    const minimumHeader = 305*crownScale+rail;
    // Visible buttons determine the console budget, not a scaled staircase
    // illustration. Phone hit targets never shrink below 44 CSS pixels.
    // User-requested visual face is 20% smaller, still a 64px+ touch target.
    const spin = .8*Math.max(80,Math.min(96,80+(controlsWidth-320)*16/70));
    const secondary = Math.max(52,Math.min(60,52+(controlsWidth-320)*8/110));
    const controlHeight = Math.max(108,spin+24);
    // The approved banner gets its full row on phones. Very short/square
    // windows retain the previous compact budget so extra decoration cannot
    // consume the board or reduce the full-size control targets.
    const compactHud = portrait && usable-minimumHeader-controlHeight < 142;
    // Reclaim decorative HUD height for actual 2:3 scoring tiles.
    const hud = compactHud ? 58 : 66;
    const footer = hud+controlHeight;
    const boardHeight = Math.max(1,Math.min(preferredBoard,usable-minimumHeader-(portrait?footer:0)));
    const boardWidth = (boardHeight+.0064*w)/1.5;
    const header = portrait ? usable-boardHeight-footer : minimumHeader;
    const crown = header-rail;
    const crownTop = safeTop+crown-305*crownScale;
    const footerTop = portrait ? safeTop+header+boardHeight : safeTop+Math.max(0,(usable-footer)/2);
    // Retire transient textures on a real geometry change, not on every scroll.
    // This affects only animation; the accepted server round still settles once.
    if (lastBoardWidth !== null && Math.abs(boardWidth-lastBoardWidth)>.5) {
      window.MahjongReels?.finish();
    }
    lastBoardWidth=boardWidth;
    put('width',w);put('height',h);put('safe',safeTop);
    put('header',header);put('crown-height',305*crownScale);put('crown-top',crownTop);
    put('crown-left',0);put('crown-width',sceneWidth);put('scene-width',sceneWidth);
    put('crown-edge-left',12*crownScale);put('crown-edge-right',12*crownScale);
    put('header-inset-left',safeLeft);put('header-inset-right',portrait?safeRight:0);
    put('rail-top',safeTop+crown);put('rail-height',rail);
    put('board-top',safeTop+header);put('board-width',boardWidth);
    put('board-left',center-boardWidth/2);put('board-height',boardHeight);
    // Each side is the complete 118/117x938 portrait source, painted once.
    // The native image aspect is preserved with no independent top/middle/
    // bottom stretch and no double lantern or duplicated golden scroll.
    const leftDragon=118*boardHeight/938, rightDragon=117*boardHeight/938;
    for(const [side,sourceWidth] of [['left',118],['right',117]]) {
      put(side+'-base-width',sourceWidth*boardHeight/938);
    }
    // Fill the excess side gutters with ornamental inlays, never skew tiles.
    // On short landscape, intact dragon columns already hug the board.
    put('wing-left',portrait?Math.max(0,center-boardWidth/2-leftDragon):0);
    put('wing-right',portrait?Math.max(0,sceneWidth-center-boardWidth/2-rightDragon):0);
    put('footer-top',footerTop);put('hud-height',hud);
    // A 66px HUD has two non-overlapping lanes: 30px notice + 32px meters.
    // Preserve the tighter 58px fallback in short/safe-area viewports.
    put('notice-height',compactHud?22:30);put('meter-offset',compactHud?24:32);
    put('meter-height',32);put('meter-padding',2);
    put('panel-left',panelLeft);put('panel-width',panelWidth);
    put('footer-art-top',portrait?footerTop:0);put('footer-art-height',portrait?h-footerTop:h);
    put('controls-top',footerTop+hud);put('controls-height',controlHeight);
    put('controls-width',controlsWidth);put('controls-left',panelLeft+controlsSafeLeft);
    put('spin-size',spin);put('secondary-size',secondary);
    put('crown-unit',crownScale);
    stage.dataset.fullframe=desktop?'desktop':portrait?'portrait':'landscape';
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
