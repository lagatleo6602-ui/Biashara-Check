/* Biashara Check service worker: makes the app installable and keeps the screens available on a weak connection.
   Pages, styles and scripts: network first, the last copy when offline (so updates show at once).
   Fonts and icons: cache first.
   Data (/auth, /businesses, /admin, /payments ...) is never cached: figures always come fresh from the server. */
const VERSION = "bc-v7";
const SHELL = ["/static/app.css", "/static/app.js", "/static/charts.js", "/static/tour.js", "/static/i18n.js",
  "/static/login.js", "/static/account.js", "/static/how.js", "/static/assistant.js", "/static/install.js", "/static/icons/icon-192.png",
  "/static/fonts/bricolage-grotesque-latin-opsz-normal.woff2", "/static/fonts/public-sans-latin-wght-normal.woff2"];
const PAGES = ["/", "/login", "/account", "/how", "/install"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  const save = res => { if (res.ok) { const copy = res.clone(); caches.open(VERSION).then(c => c.put(e.request, copy)); } return res; };
  if (/^\/static\/(fonts|icons)\//.test(url.pathname)) {
    e.respondWith(caches.match(e.request).then(hit => hit || fetch(e.request).then(save)));
    return;
  }
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(fetch(e.request).then(save).catch(() => caches.match(e.request)));
    return;
  }
  if (PAGES.includes(url.pathname) && e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).then(res => {
      const copy = res.clone(); caches.open(VERSION).then(c => c.put(url.pathname, copy)); return res;
    }).catch(() => caches.match(url.pathname).then(hit => hit || new Response(
      "<!doctype html><meta name=viewport content='width=device-width'><title>Offline</title><body style='font-family:system-ui;padding:24px'>" +
      "<h1>You're offline</h1><p>Biashara Check needs the internet to load your figures. Check your data bundle or Wi-Fi and try again.</p>",
      { headers: { "Content-Type": "text/html" } }))));
  }
});
