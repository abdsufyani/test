// Service Worker: يستقبل الإشعار حتى لو الجوال مقفل والصفحة مسكّرة
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

function ack(orderId, event) {
  return fetch(`/api/orders/${orderId}/ack`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event }),
  }).catch(() => {});
}

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data.json(); } catch (_) { data = { title: 'طلبك جاهز', body: '' }; }

  event.waitUntil(
    Promise.all([
      self.registration.showNotification(data.title, {
        body: data.body,
        icon: '/icons/icon-192.png',
        badge: '/icons/icon-192.png',
        tag: `order-${data.orderId}`,
        renotify: true,
        requireInteraction: true,
        vibrate: [400, 150, 400, 150, 400],
        data: { url: data.url, orderId: data.orderId },
      }),
      data.orderId ? ack(data.orderId, 'delivered') : null,
    ])
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const { url, orderId } = event.notification.data || {};
  event.waitUntil(
    (async () => {
      if (orderId) await ack(orderId, 'seen');
      const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      const existing = all.find((c) => c.url.includes(url));
      if (existing) return existing.focus();
      return self.clients.openWindow(url || '/');
    })()
  );
});
