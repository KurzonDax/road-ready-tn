// The service worker: lets the app open with no connection after one visit online.
// build.py copies this to dist/sw.js and writes in the build version and the files to keep.
//
// - The page (/ and /index.html) and questions.json: network first. Wait up to 3 seconds;
//   use the network's answer and keep a copy in rrtn-pages, else use the kept copy.
// - Fonts, icons and the manifest (STATIC_FILES, as build.py lists them): cache first, in
//   rrtn-static-<version>.
// - Everything else, every /api/ request among it, goes to the network and is never kept.
const VERSION = '86811447b565';
const STATIC_FILES = ["apple-touch-icon.png", "fonts/atkinson-hyperlegible/atkinson-hyperlegible-400.woff2", "fonts/atkinson-hyperlegible/atkinson-hyperlegible-700.woff2", "fonts/overpass/overpass-variable.woff2", "icon-192.png", "icon-512.png", "manifest.webmanifest"];
const PAGES = 'rrtn-pages';
const STATIC = 'rrtn-static-' + VERSION;
const WAIT_MS = 3000;

const STATIC_PATHS = new Set(STATIC_FILES.map(name => '/' + name));

// The copy is kept under one name for each: the page as /, whichever URL opened it.
function pageKey(request) {
  const url = new URL(request.url);
  if (request.mode === 'navigate' && (url.pathname === '/' || url.pathname === '/index.html')) return '/';
  if (url.pathname === '/questions.json') return '/questions.json';
  return null;
}

// Keep a copy of a good answer. A 401 (signed out) or any other error is never kept.
function keep(key, response) {
  if (!response.ok) return Promise.resolve();
  const copy = response.clone();
  return caches.open(PAGES).then(c => c.put(key, copy));
}

// Network first. A server error (5xx, e.g. a proxy with the Instance down) counts as no answer.
function networkFirst(event, key) {
  let saving = Promise.resolve();
  const network = fetch(event.request).then(r => { saving = keep(key, r); return r; });
  event.waitUntil(network.then(() => saving).catch(() => {}));
  const answered = network.then(r => (r.status >= 500 ? Promise.reject(r) : r));
  const timeout = new Promise((resolve, reject) => setTimeout(reject, WAIT_MS));
  return Promise.race([answered, timeout]).catch(async () => {
    const cached = await caches.match(key, { cacheName: PAGES });
    return cached || network;
  });
}

async function cacheFirst(request) {
  const cache = await caches.open(STATIC);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(caches.open(STATIC).then(c => c.addAll(STATIC_FILES)));
});

// The page that registered this worker loaded before it did, so its copy wasn't kept. Keep it if
// it is missing, so the next open works with no connection. questions.json is never fetched here:
// that would ask for it signed out (#20). The page fetches it again once this worker controls it.
async function keepPage() {
  if (await caches.match('/', { cacheName: PAGES })) return;
  await keep('/', await fetch('/', { cache: 'no-cache' }));
}

self.addEventListener('activate', event => {
  const ready = (async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(n => n.startsWith('rrtn-static-') && n !== STATIC).map(n => caches.delete(n)));
    await self.clients.claim();
  })();
  event.waitUntil(ready);
  // Not part of activating: requests wait until activating ends.
  ready.then(keepPage).catch(() => {});
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || request.method !== 'GET' || url.pathname.startsWith('/api/')) return;
  const key = pageKey(request);
  if (key) return event.respondWith(networkFirst(event, key));
  if (STATIC_PATHS.has(url.pathname)) return event.respondWith(cacheFirst(request));
});
