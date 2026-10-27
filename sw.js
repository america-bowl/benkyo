const VERSION = 'benkyo-v2';
const APP_CACHE = `${VERSION}-app`;
const IMAGE_CACHE = `${VERSION}-portraits`;
const SHELL = ['./', './index.html', './portraits.json', './manifest.webmanifest', './icons/app.svg'];
const MANIFEST_URL = new URL('./portraits.json', self.registration.scope).href;

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(APP_CACHE);
    for (const path of SHELL) {
      try { await cache.add(new Request(new URL(path, self.registration.scope), {cache:'reload'})); }
      catch (_) { /* navigation request below can cache the shell on first visit */ }
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k.startsWith('benkyo-') && ![APP_CACHE,IMAGE_CACHE].includes(k)).map(k=>caches.delete(k)));
    await self.clients.claim();
  })());
});

async function cachePortraits(client) {
  const send = data => { try { client?.postMessage(data); } catch (_) {} };
  try {
    const mres = await fetch(MANIFEST_URL, {cache:'no-store'});
    if (!mres.ok) throw new Error('portraits.json could not be loaded');
    const manifest = await mres.json();
    const urls = [...new Set((manifest.portraits||[]).map(p=>p.src).filter(Boolean))];
    const cache = await caches.open(IMAGE_CACHE);
    let done=0, saved=0, failed=0, cursor=0;
    const workers = Array.from({length:5}, async()=>{
      while (cursor<urls.length) {
        const url=urls[cursor++];
        try {
          const already=await cache.match(url,{ignoreVary:true});
          if (already) { saved++; }
          else {
            const req=new Request(url,{mode:'no-cors',credentials:'omit',cache:'reload'});
            const response=await fetch(req);
            if (response && (response.ok || response.type==='opaque')) { await cache.put(url,response.clone()); saved++; }
            else failed++;
          }
        } catch (_) { failed++; }
        done++; send({type:'WARM_PROGRESS',done,total:urls.length,saved,failed});
      }
    });
    await Promise.all(workers);
    send({type:'WARM_DONE',done,total:urls.length,saved,failed});
  } catch (error) { send({type:'WARM_ERROR',message:String(error)}); }
}

self.addEventListener('message', event => {
  if (event.data?.type==='WARM_PORTRAITS') event.waitUntil(cachePortraits(event.source));
});

self.addEventListener('fetch', event => {
  const req=event.request;
  if (req.method!=='GET') return;
  const url=new URL(req.url);
  if (req.destination==='image' && url.protocol==='https:' && (url.hostname==='upload.wikimedia.org'||url.hostname==='commons.wikimedia.org')) {
    event.respondWith((async()=>{
      const cache=await caches.open(IMAGE_CACHE);
      const hit=await cache.match(req,{ignoreVary:true});
      if(hit) return hit;
      try {
        const response=await fetch(req);
        if(response && (response.ok||response.type==='opaque')) { try { await cache.put(req,response.clone()); } catch(_){} }
        return response;
      } catch(_) {
        return await cache.match(req,{ignoreVary:true}) || new Response('',{status:504,statusText:'Portrait not cached yet'});
      }
    })());
    return;
  }
  if(url.origin!==self.location.origin) return;
  if(req.mode==='navigate') {
    event.respondWith((async()=>{
      const cache=await caches.open(APP_CACHE);
      try { const response=await fetch(req); if(response.ok) { try { await cache.put(req,response.clone()); } catch(_){} } return response; }
      catch(_) {
        return await cache.match(req) || await cache.match(new URL('./',self.registration.scope).href) || await cache.match(new URL('./index.html',self.registration.scope).href) || new Response('オフラインです。オンラインで一度ページを開いてください。',{status:503,headers:{'Content-Type':'text/plain; charset=utf-8'}});
      }
    })());
    return;
  }
  event.respondWith((async()=>{
    const cache=await caches.open(APP_CACHE), hit=await cache.match(req);
    if(hit)return hit;
    try { const response=await fetch(req); if(response.ok) {try{await cache.put(req,response.clone())}catch(_){}} return response; }
    catch(_){return new Response('',{status:504,statusText:'Resource unavailable offline'});}
  })());
});
