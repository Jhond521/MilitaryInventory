// Minimal app-shell service worker for SIGA (RF-17 / T-06 will expand this
// once the mobile-first operator screens exist). Scope is the whole origin —
// served at /sw.js, not under /static/, so it can control every route.
const CACHE_NAME = "siga-shell-v4";
const APP_SHELL = ["/manifest.json", "/static/icons/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
