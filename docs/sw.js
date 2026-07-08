/* Service worker: app shell cached for offline; DATA is network-first so an
   open app always gets the freshest committed capture, falling back to cache. */
// Bump the version whenever the shell changes, or installed PWA users keep
// the old UI until the cache happens to expire.
const SHELL = "radar-shell-v6";
const ASSETS = ["./", "index.html", "app.js", "ask.js", "styles.css", "manifest.webmanifest", "icon.svg"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== SHELL).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  const isData = url.pathname.includes("/data/") || url.pathname.includes("/screenshots/");

  if (isData) {
    // network-first: fresh when online, cached when offline
    e.respondWith(
      fetch(e.request).then(res => {
        const copy = res.clone();
        caches.open(SHELL).then(c => c.put(e.request, copy));
        return res;
      }).catch(() => caches.match(e.request))
    );
  } else {
    // cache-first for the static shell
    e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
  }
});
