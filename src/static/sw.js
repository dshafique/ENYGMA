/* ENYGMA service worker.
 *
 * Deliberately small, and deliberately not a cache of the app.
 *
 * Everything this app renders is private: transcripts, summaries, who said what.
 * A service worker that caches pages leaves that on the device's disk, outside
 * the database whose permissions are the whole isolation story, and serves it
 * back after a logout. So: HTML and anything under /api, /auth, /upload or
 * /meetings is never cached, never served from cache, and never touched here.
 *
 * What is cached is the immutable stuff: /static/... always carries ?v=<build>,
 * so a URL's contents can never change. Those are safe to keep forever and are
 * what makes the app open instantly on a phone.
 */
const BUILD = new URL(self.location).searchParams.get("v") || "dev";
const SHELL = `enygma-static-${BUILD}`;

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // A new build means a new cache name; the old ones are dead weight.
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((n) => n !== SHELL).map((n) => caches.delete(n)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Private by default. Only versioned static assets are eligible.
  const cacheable = url.pathname.startsWith("/static/") && url.searchParams.has("v");
  if (!cacheable) return;                       // straight to the network

  event.respondWith((async () => {
    const cache = await caches.open(SHELL);
    const hit = await cache.match(request);
    if (hit) return hit;
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  })());
});
