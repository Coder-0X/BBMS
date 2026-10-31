/**
 * BloodBank LIS — Bedside PWA Service Worker
 *
 * Strategy: network-first for API calls (patient safety — always want fresh data),
 * cache-first for static assets. If offline and no cached API response, show
 * a clear error message rather than stale data.
 *
 * CACHE_NAME should be bumped on every deploy to invalidate old assets.
 */

const CACHE_NAME = 'bloodbank-bedside-v1';
const STATIC_ASSETS = [
  '/bedside/',
  '/static/manifest.json',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API calls: network-first, no cache fallback (patient safety)
  if (url.pathname.startsWith('/api/v1/bedside/')) {
    event.respondWith(
      fetch(event.request).catch(() =>
        new Response(
          JSON.stringify({ error: 'offline', message: 'No network connection. Cannot verify patient identity offline.' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        )
      )
    );
    return;
  }

  // Static assets: cache-first
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
