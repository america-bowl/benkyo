const CACHE_VERSION = 'benkyo-v1';
const APP_CACHE = `${CACHE_VERSION}-app`;
const IMAGE_CACHE = `${CACHE_VERSION}-images`;

const IMAGE_HOSTS = new Set([
  'upload.wikimedia.org',
  'commons.wikimedia.org'
]);

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(APP_CACHE);

    try {
      const response = await fetch('./', { cache: 'reload' });
      if (response.ok) {
        await cache.put('./', response.clone());
      }
    } catch (error) {
      // The navigation handler caches the page on its first visit.
    }

    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();

    await Promise.all(
      keys
        .filter(
          (key) =>
            key.startsWith('benkyo-') &&
            ![APP_CACHE, IMAGE_CACHE].includes(key)
        )
        .map((key) => caches.delete(key))
    );

    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (event) => {
  const request = event.request;

  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Cache Wikimedia images after their first successful load.
  if (
    url.protocol === 'https:' &&
    IMAGE_HOSTS.has(url.hostname) &&
    request.destination === 'image'
  ) {
    event.respondWith((async () => {
      const cache = await caches.open(IMAGE_CACHE);
      const cached = await cache.match(request, {
        ignoreVary: true
      });

      if (cached) return cached;

      try {
        const response = await fetch(request);

        if (response.ok || response.type === 'opaque') {
          await cache.put(request, response.clone());
        }

        return response;
      } catch (error) {
        const fallback = await cache.match(request, {
          ignoreVary: true
        });

        return fallback ||
          new Response('', {
            status: 504,
            statusText: 'Image unavailable offline'
          });
      }
    })());

    return;
  }

  // Cache the application and its local resources.
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith((async () => {
      const cache = await caches.open(APP_CACHE);

      try {
        const response = await fetch(request);

        if (response.ok) {
          await cache.put(request, response.clone());
        }

        return response;
      } catch (error) {
        return (
          await cache.match(request) ||
          await cache.match('./') ||
          new Response('Offline. Please open this page online first.', {
            status: 503,
            headers: {
              'Content-Type': 'text/plain; charset=utf-8'
            }
          })
        );
      }
    })());

    return;
  }

  event.respondWith((async () => {
    const cache = await caches.open(APP_CACHE);
    const cached = await cache.match(request);

    if (cached) return cached;

    try {
      const response = await fetch(request);

      if (response.ok) {
        await cache.put(request, response.clone());
      }

      return response;
    } catch (error) {
      return new Response('', {
        status: 504,
        statusText: 'Resource unavailable offline'
      });
    }
  })());
});
