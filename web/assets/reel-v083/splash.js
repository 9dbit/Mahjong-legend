/* Soft Tech startup modeled on the owner's UNO LUCK launch flow.
 * Do not dismiss until the game assets and state are ready. Continue Play
 * performs AudioContext.resume() in the iOS user-gesture call stack.
 */
(() => {
  'use strict';
  const splash = document.getElementById('soft-tech-splash');
  const button = document.getElementById('soft-tech-continue');
  const progress = document.getElementById('soft-tech-progress');
  const status = document.getElementById('soft-tech-status');
  if (!splash || !button || !progress || !status) return;
  let released = false;
  let artReady = false;
  const logo = splash.querySelector('.soft-tech-logo-image');
  const fallback = splash.querySelector('.soft-tech-logo-fallback');
  if (logo) { const updateLogo = () => { const ok = logo.complete && logo.naturalWidth > 0; fallback.hidden = ok; logo.hidden = !ok; }; logo.addEventListener('load', updateLogo); logo.addEventListener('error', updateLogo); if (logo.complete) updateLogo(); }
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const started = performance.now();
  const notice = document.getElementById('stage-notice');
  const show = (value, message) => {
    progress.style.width = `${value}%`;
    if (message) status.textContent = message;
  };
  function check() {
    if (released) return;
    const ready = notice?.textContent?.trim() === 'SIAP BERMAIN';
    const failed = notice?.textContent?.includes('KONEKSI GAGAL');
    const waited = performance.now() - started > (reduced ? 450 : 1200);
    artReady = !!ready;
    if (ready && waited) {
      splash.classList.add('is-ready');
      show(100, 'SIAP BERMAIN');
      button.disabled = false;
    } else if (failed) {
      show(30, 'KONEKSI TERPUTUS. MUAT ULANG UNTUK MENCOBA LAGI.');
      button.disabled = true;
    } else {
      show(waited ? 80 : Math.round(20 + (performance.now() - started) / 22),
        'MENYIAPKAN GAME SYSTEM');
      setTimeout(check, 120);
    }
  }
  button.addEventListener('click', () => {
    if (released || !artReady) return;
    released = true;
    const audio = window.MahjongWildAudio;
    // Called synchronously, before any await or animation, to satisfy WebKit.
    try {
      const unlocked = audio?.unlock?.();
      if (unlocked) Promise.resolve(unlocked).then(() => audio?.play?.('tap')).catch(() => {});
    } catch (_) { /* No audio hardware must never block a game. */ }
    splash.classList.add('dismissed');
    document.dispatchEvent(new Event('mahjong:continue-play'));
    button.blur();
    setTimeout(() => { splash.hidden = true; }, reduced ? 50 : 350);
  });
  show(10, 'MENYIAPKAN GAME SYSTEM');
  setTimeout(check, 80);
})();
