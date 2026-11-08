// Kartei service worker: makes the app installable and lets it start offline.
// Data lives in IndexedDB (see src/lib/store.svelte.ts); /api is never cached here.
const CACHE = 'kartei-v1'
const SHARE = 'kartei-share'  // what another app shared (Web Share Target), until the /share page picks it up

self.addEventListener('install', () => self.skipWaiting())

self.addEventListener('activate', (e) =>
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== CACHE && k !== SHARE) await caches.delete(k)
    await self.clients.claim()
  })()))

self.addEventListener('fetch', (e) => {
  const req = e.request
  const url = new URL(req.url)
  if (req.method === 'POST' && url.origin === location.origin && url.pathname === '/share') {
    // shared from another app (installed app on Android): keep the text and files, then open the import page
    e.respondWith((async () => {
      const form = await req.formData()
      const files = await Promise.all(form.getAll('file').filter((f) => f instanceof File)
        .map(async (f) => ({ name: f.name, text: await f.text() })))
      const data = { title: form.get('title') || '', text: form.get('text') || '', url: form.get('url') || '', files }
      await (await caches.open(SHARE)).put('/share-data', new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } }))
      return Response.redirect('/share?received=1', 303)
    })())
    return
  }
  if (req.method !== 'GET' || url.origin !== location.origin) return
  if (url.pathname.startsWith('/static/assets/')) {
    // hashed file names never change: cache first
    // ponytail: old builds' assets stay in the cache; bump CACHE if it ever matters
    e.respondWith(caches.open(CACHE).then(async (c) => {
      const hit = await c.match(req)
      if (hit) return hit
      const res = await fetch(req)
      if (res.ok) c.put(req, res.clone())
      return res
    }))
  } else if (req.mode === 'navigate' && !/^\/(api|static|carddav|django-admin|\.well-known)(\/|$)/.test(url.pathname)) {
    // app shell (every SPA path serves the same index.html): network first (always the newest build), the cached copy when offline
    e.respondWith(fetch(req).then((res) => {
      if (res.ok && (res.headers.get('content-type') || '').startsWith('text/html')) {
        const copy = res.clone()
        caches.open(CACHE).then((c) => c.put('/', copy))
      }
      return res
    }).catch(async () => (await caches.match('/')) || Response.error()))
  }
})

// Web Push (see backend kartei/push.py): {title, body, tag, url}; only a count and a link, no contact data
self.addEventListener('push', (e) => {
  let d = {}
  try { d = e.data ? e.data.json() : {} } catch { /* not ours: show the default */ }
  e.waitUntil(self.registration.showNotification(d.title || 'Kartei', {
    body: d.body || '', tag: d.tag, data: { url: d.url || '/' }, icon: '/icon-192.png',
  }))
})

self.addEventListener('notificationclick', (e) => {
  e.notification.close()
  const url = new URL(e.notification.data?.url || '/', self.location.origin)
  if (url.origin !== self.location.origin) return
  e.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    if (open[0]) return (await open[0].focus()).navigate(url.href)
    return self.clients.openWindow(url.href)
  })())
})
