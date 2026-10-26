// Gør appen installerbar og lader den åbne uden net (viser så de sidst hentede priser).
const CACHE = "tank-klar-v15";
const FILER = ["./", "index.html", "manifest.webmanifest", "ikoner/ikon-192.png", "ikoner/ikon-512.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(FILER))); self.skipWaiting(); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(k => Promise.all(k.filter(n => n !== CACHE).map(n => caches.delete(n)))));
  self.clients.claim();
});
// Net først (så priserne altid er friske), cache som reserve.
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET" || new URL(e.request.url).origin !== location.origin) return;
  const nøgle = e.request.url.split("?")[0];
  e.respondWith(
    fetch(e.request).then(svar => {
      const kopi = svar.clone();
      caches.open(CACHE).then(c => c.put(nøgle, kopi));
      return svar;
    }).catch(() => caches.match(nøgle))
  );
});
