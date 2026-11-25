const CACHE='janbos-werkbon-shell-v1';
const SHELL=['/werkbonnen/glaszetter','/werkbonnen/kantoor','/werkbonnen/static/app.css','/werkbonnen/static/app.js','/werkbonnen/static/janbos-logo.png','/werkbonnen/static/icon-192.png','/werkbonnen/static/icon-512.png'];
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)));self.skipWaiting();});
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('janbos-werkbon-shell-')&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{const url=new URL(event.request.url);if(event.request.method!=='GET'||url.origin!==location.origin||!SHELL.includes(url.pathname))return;event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)));});
