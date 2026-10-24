/* Mahjong Wild UI 0.8.4: compositor-driven atlases, backed by the ORIGINAL
 * DOM reels. Outcome, balance and RNG remain exclusively server-controlled.
 * The fallback reels remain painted throughout every transition, including
 * Safari GPU loss, slow decoding, page backgrounding and Skip.
 */
(() => {
  'use strict';
  const VERSION = '0.8.4';
  const ease = t => t * t * t * (t * (t * 6 - 15) + 10);
  const MAX_LOGS = 30;
  const imageCache = new Map();
  let active = null;
  let receipt = null;
  const now = () => performance.now();
  const clone = object => JSON.parse(JSON.stringify(object));
  const stored = (key, fallback) => { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } };
  const optedIn = () => stored('mw-diagnostics-optin', 'off') === 'on';

  function load(url) {
    if (imageCache.has(url)) return imageCache.get(url);
    const promise = new Promise((resolve, reject) => {
      const image = new Image();
      let ended = false;
      const end = error => {
        if (ended) return;
        ended = true;
        clearTimeout(timeout);
        image.onload = image.onerror = null;
        if (error) { imageCache.delete(url); reject(error); }
        else resolve(image);
      };
      const timeout = setTimeout(() => end(Error('Tile asset timeout')), 11000);
      image.decoding = 'async';
      image.onload = async () => {
        try {
          if (typeof image.decode === 'function') await image.decode();
          if (!image.naturalWidth) throw Error('Empty tile asset');
          end();
        } catch (error) { end(error); }
      };
      image.onerror = () => end(Error('Tile asset unavailable'));
      image.src = url;
    });
    imageCache.set(url, promise);
    return promise;
  }

  const prepare = urls => Promise.all([...new Set(urls)].map(load));
  async function ready(element) {
    await Promise.all([...element.querySelectorAll('img')].map(async image => {
      await load(image.src);
      // Decode the actual final DOM node before the atomic replacement.
      if (image.decode) await image.decode();
      if (!image.complete || !image.naturalWidth) throw Error('Final tile decode failed');
    }));
  }
  function signal(phase, column) {
    document.dispatchEvent(new CustomEvent('mahjong:reel', {detail: {phase, column, at: now()}}));
  }
  function finishLog(log) {
    if (!log || log.reported) return;
    log.reported = true;
    const safe = clone(log);
    delete safe.reported;
    try {
      const history = JSON.parse(stored('mw_spin_logs', '[]'));
      history.push(safe);
      localStorage.setItem('mw_spin_logs', JSON.stringify(history.slice(-MAX_LOGS)));
    } catch (_) { /* Storage is optional, never block gameplay. */ }
    document.dispatchEvent(new CustomEvent('mahjong:spin-log', {detail: safe}));
    if (optedIn()) {
      // Anonymous, opt-in summary only. No cookies, IP, balance or seed in payload.
      const summary = {
        version: safe.version, mode: safe.mode, completed: safe.completed,
        cancelled: safe.cancelled, starts: safe.starts, stops: safe.stops,
        durationMs: safe.durationMs, prepareMs: safe.prepareMs,
        maxFrameGapMs: safe.maxFrameGapMs, slowFrames: safe.slowFrames,
        samples: safe.samples, atlasPixels: safe.atlasPixels,
        errors: safe.errors.slice(0, 3), device: safe.device
      };
      void fetch('/api/diagnostics/spin', {
        method: 'POST', credentials: 'omit', cache: 'no-store', keepalive: true,
        headers: {'Content-Type': 'application/json', 'X-ML-Request': 'local-demo'},
        body: JSON.stringify(summary)
      }).catch(() => {});
    }
  }
  function reportFailure(phase, error) {
    const log = {version: VERSION, mode: 'fallback', completed: false,
      cancelled: false, durationMs: 0, prepareMs: 0, maxFrameGapMs: 0,
      slowFrames: 0, samples: 0, starts: [], stops: [], atlasPixels: 0,
      errors: [`${phase}: ${String(error).slice(0, 150)}`], device: {dpr: 1, width: innerWidth, height: innerHeight}};
    receipt = log;
    finishLog(log);
  }

  async function run({root, board, buildReel, urlFor, filler, shouldSkip, onStop, turbo}) {
    if (active) active.finish();
    const oldNodes = [...root.children];
    if (oldNodes.length !== 5) throw Error('Expected 5 visible reels');
    const prior = oldNodes.map(reel => [...reel.children].map(tile => tile._tile).filter(Boolean));
    const finals = board.map((col, index) => buildReel(col, index));
    const startedPreparing = now();
    const sequences = board.map((col, i) => {
      const earlier = prior[i]?.length === col.length ? prior[i] : col;
      const interim = Array.from({length: turbo ? 6 : 8}, (_, j) => filler(i, j));
      return {col, all: [...col, ...interim, ...earlier], steps: col.length + interim.length};
    });
    const urls = [...new Set(sequences.flatMap(c => c.all.map(urlFor)))];
    // Never touch the visible DOM while fetching and decoding tile artwork.
    const decoded = await prepare(urls);
    const lookup = new Map(urls.map((url, i) => [url, decoded[i]]));
    await Promise.all(finals.map(ready));
    const preparationMs = Math.round(now() - startedPreparing);
    if (shouldSkip()) { root.replaceChildren(...finals); return; }

    const duration = turbo ? 680 : 1570;
    const stagger = turbo ? 70 : 135;
    const totalHeight = sequences.map((item, i) => {
      const node = oldNodes[i];
      const h = node.getBoundingClientRect().height;
      const gap = parseFloat(getComputedStyle(node).rowGap) || 0;
      return ((h + gap) / item.col.length) * item.all.length;
    });
    const maxHeight = Math.max(...totalHeight);
    const dpr = Math.max(.8, Math.min(1.5, window.devicePixelRatio || 1, 3900 / maxHeight));
    const columns = sequences.map((seq, i) => {
      const original = oldNodes[i];
      const box = original.getBoundingClientRect();
      if (box.width < 1 || box.height < 1) throw Error('Reel surface has zero dimensions');
      const gap = parseFloat(getComputedStyle(original).rowGap) || 0;
      const pitch = (box.height + gap) / seq.col.length;
      const fullHeight = seq.all.length * pitch;
      const canvas = document.createElement('canvas');
      canvas.className = 'reel-strip reel-canvas';
      canvas.setAttribute('aria-hidden', 'true');
      canvas.width = Math.ceil(box.width * dpr);
      canvas.height = Math.ceil(fullHeight * dpr);
      canvas.style.height = `${fullHeight}px`;
      canvas.style.width = `${box.width}px`;
      const context = canvas.getContext('2d', {alpha: true});
      if (!context) throw Error('Canvas context unavailable');
      context.setTransform(canvas.width / box.width, 0, 0, canvas.height / fullHeight, 0, 0);
      context.imageSmoothingEnabled = true;
      context.imageSmoothingQuality = 'medium';
      // Draw the entire strip ONCE, then let the GPU compositor scroll it.
      // Keep undrawn pixels transparent so the intact DOM tiles remain visible
      // if iOS WebKit temporarily evicts a composited canvas texture.
      context.clearRect(0, 0, box.width, fullHeight);
      seq.all.forEach((tile, j) => {
        const image = lookup.get(urlFor(tile));
        if (!image?.naturalWidth) throw Error('Decoded tile missing from atlas');
        context.drawImage(image, 0, j * pitch, box.width, pitch - gap);
      });
      const surface = document.createElement('div');
      surface.className = 'reel-surface';
      surface.setAttribute('aria-hidden', 'true');
      surface.append(canvas);
      // The original 4/5 tiles REMAIN underneath as a fail-safe layer.
      return {original, final: finals[i], surface, canvas, i, distance: seq.steps * pitch,
        started: false, stopped: false, animation: null};
    });

    const log = {
      version: VERSION, mode: 'gpu-composited-atlas', completed: false, cancelled: false,
      starts: [], stops: [], durationMs: 0, prepareMs: preparationMs,
      maxFrameGapMs: 0, slowFrames: 0, samples: 0,
      atlasPixels: columns.reduce((v, c) => v + c.canvas.width * c.canvas.height, 0),
      errors: [], device: {dpr: Number(dpr.toFixed(2)), width: innerWidth, height: innerHeight}
    };
    receipt = log;
    const startedAt = now();
    return new Promise(resolve => {
      const timers = new Set();
      let frameId = 0, lastFrame = null, done = false;
      function sampleFrame(t) {
        if (done) return;
        if (lastFrame !== null) {
          const gap = t - lastFrame;
          log.maxFrameGapMs = Math.max(log.maxFrameGapMs, Math.round(gap));
          if (gap > 34) log.slowFrames++;
        }
        lastFrame = t; log.samples++;
        frameId = requestAnimationFrame(sampleFrame);
      }
      function settle(c) {
        if (c.stopped) return;
        c.stopped = true;
        try { c.animation?.cancel(); } catch (_) {}
        c.surface.remove();
        if (c.original.isConnected) c.original.replaceWith(c.final);
        log.stops.push(c.i + 1);
        signal('stop', c.i + 1);
        if (!shouldSkip()) onStop?.(c.i);
        // A disconnected canvas is released after the DOM has its final tiles.
        c.canvas.width = c.canvas.height = 1;
        if (columns.every(column => column.stopped)) finish(false);
      }
      function finish(cancelled) {
        if (done) return;
        done = true;
        for (const timer of timers) clearTimeout(timer);
        timers.clear();
        cancelAnimationFrame(frameId);
        for (const c of columns) if (!c.stopped) {
          c.stopped = true;
          try { c.animation?.cancel(); } catch (_) {}
          c.surface.remove();
          if (c.original.isConnected) c.original.replaceWith(c.final);
          log.stops.push(c.i + 1); signal('stop', c.i + 1);
          c.canvas.width = c.canvas.height = 1;
        }
        log.cancelled = cancelled;
        log.completed = true;
        log.durationMs = Math.round(now() - startedAt);
        document.documentElement.classList.remove('reels-running');
        active = null;
        finishLog(log);
        resolve();
      }
      function begin(c) {
        if (done) return;
        if (shouldSkip() || document.hidden) { finish(true); return; }
        try {
          const from = `translate3d(0,${-c.distance.toFixed(2)}px,0)`;
          c.canvas.style.transform = from;
          c.original.append(c.surface);
          c.started = true;
          log.starts.push(c.i + 1);
          signal('start', c.i + 1);
          c.animation = c.canvas.animate([
            {transform: from}, {transform: 'translate3d(0,0px,0)'}
          ], {duration, easing: 'cubic-bezier(.72,0,.28,1)', fill: 'both'});
          c.animation.finished.then(() => {
            if (!done) settle(c);
          }).catch(() => {});
        } catch (error) {
          log.errors.push(String(error).slice(0, 150));
          finish(true);
        }
      }
      active = {finish: () => finish(true)};
      document.documentElement.classList.add('reels-running');
      frameId = requestAnimationFrame(sampleFrame);
      columns.forEach((c, i) => timers.add(setTimeout(() => begin(c), stagger * i)));
      // Engine already calls finish() if tab becomes hidden; this is a safety net.
      timers.add(setTimeout(() => finish(true), duration + stagger * 5 + 1800));
    });
  }

  function setShareDiagnostics(value) {
    try { localStorage.setItem('mw-diagnostics-optin', value ? 'on' : 'off'); } catch (_) {}
    return optedIn();
  }
  function logs() {
    try { const result = JSON.parse(stored('mw_spin_logs', '[]')); return Array.isArray(result) ? result.slice(-MAX_LOGS) : []; }
    catch { return []; }
  }
  const diagnosticButton = document.getElementById('setting-diagnostics');
  const exportButton = document.getElementById('export-spin-logs');
  const status = document.getElementById('diagnostics-status');
  function updateDiagnosticButton() {
    if (!diagnosticButton) return;
    const allowed = optedIn();
    diagnosticButton.textContent = allowed ? 'ON' : 'OFF';
    diagnosticButton.setAttribute('aria-pressed', String(allowed));
  }
  diagnosticButton?.addEventListener('click', () => {
    setShareDiagnostics(!optedIn());
    updateDiagnosticButton();
    if (status) status.textContent = optedIn()
      ? 'Log performa anonim akan dikirim ke developer setelah tiap Spin.'
      : 'Hanya log lokal. Developer tidak menerima data Spin.';
  });
  exportButton?.addEventListener('click', () => {
    const data = JSON.stringify({game: 'Mahjong Wild', release: VERSION, logs: logs()}, null, 2);
    const url = URL.createObjectURL(new Blob([data], {type: 'application/json'}));
    const link = document.createElement('a');
    link.download = 'mahjong-wild-spin-diagnostics.json';
    link.href = url;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 500);
    if (status) status.textContent = `${logs().length} log Spin siap diunduh.`;
  });
  updateDiagnosticButton();
  window.MahjongReels = Object.freeze({
    prepare, ready, run, ease, finish: () => active?.finish(),
    diagnostics: () => receipt ? clone(receipt) : null,
    logs, setShareDiagnostics, get shareDiagnostics() { return optedIn(); },
    recordError: reportFailure,
    exportLogs: () => JSON.stringify({game: 'Mahjong Wild', release: VERSION, logs: logs()}, null, 2)
  });
})();
