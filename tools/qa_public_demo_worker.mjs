/** Exercise the real worker: document navigation must stay outside its cache. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const origin = 'https://mahjong.xd-play.com';
const source = readFileSync(new URL('../web/sw.js', import.meta.url), 'utf8');

function createWorker({offline = false, cached = new Map()} = {}) {
  const listeners = new Map();
  const activity = {fetches: [], reads: [], writes: []};
  vm.runInNewContext(source, {
    URL,
    Response,
    self: {
      location: {origin},
      addEventListener: (type, callback) => listeners.set(type, callback),
    },
    fetch: async request => {
      activity.fetches.push(request.url);
      if (offline) throw new Error('Offline test fixture');
      return new Response('network asset', {status: 200});
    },
    caches: {
      open: async () => ({put: async (request, response) => {
        activity.writes.push(request.url);
        cached.set(request.url, response);
      }}),
      match: async request => {
        activity.reads.push(request.url);
        return cached.get(request.url)?.clone();
      },
    },
  });
  assert.equal(typeof listeners.get('fetch'), 'function');
  return {
    activity,
    cached,
    async dispatch(path, {method = 'GET', mode = 'navigate', destination = 'document'} = {}) {
      const request = {url: new URL(path, origin).href, method, mode, destination};
      const pending = [];
      let intercepted = false;
      let response;
      listeners.get('fetch')({
        request,
        respondWith(value) {intercepted = true; response = Promise.resolve(value);},
        waitUntil(value) {pending.push(Promise.resolve(value));},
      });
      const result = response ? await response : undefined;
      await Promise.all(pending);
      return {intercepted, response: result};
    },
  };
}

// Deliberately seed HTML with XFO DENY. Neither online nor offline navigation
// may read it, including a reload after the root-scoped worker takes control.
const documents = ['/', '/?mode=pwa', '/index.html', '/play/',
  '/play/?gamelang=en&cur=USD', '/studio/', '/api/state', '/media/example/image'];
for (const offline of [false, true]) {
  const cached = new Map(documents.map(path => [new URL(path, origin).href,
    new Response('<html>stale direct-play shell</html>', {
      headers: {'Content-Type': 'text/html', 'X-Frame-Options': 'DENY'},
    })]));
  const worker = createWorker({offline, cached});
  for (const path of documents) {
    assert.equal((await worker.dispatch(path)).intercepted, false, `${path}: offline=${offline}`);
  }
  assert.deepEqual(worker.activity, {fetches: [], reads: [], writes: []});
}

// Preserve the existing presentation cache: network first, then exact-URL
// offline fallback. A different version must not receive a stale asset or HTML.
const asset = '/assets/approved-v082/pwa.js?v=082';
const online = createWorker();
const loaded = await online.dispatch(asset, {mode: 'same-origin', destination: 'script'});
assert.equal(loaded.intercepted, true);
assert.equal(await loaded.response.text(), 'network asset');
assert.deepEqual(online.activity.writes, [origin + asset]);
const offline = createWorker({offline: true, cached: online.cached});
const recovered = await offline.dispatch(asset, {mode: 'same-origin', destination: 'script'});
assert.equal(await recovered.response.text(), 'network asset');
const missing = await offline.dispatch(asset.replace('?v=082', '?v=new'), {mode: 'same-origin', destination: 'script'});
assert.equal(missing.response.type, 'error');
assert.equal((await online.dispatch('/assets/example.js', {method: 'POST'})).intercepted, false);
assert.equal((await online.dispatch('https://xd-play.com/assets/example.js')).intercepted, false);

console.log('PASS: root, PWA, and /play/ documents never use worker cache; asset cache behavior is preserved.');
