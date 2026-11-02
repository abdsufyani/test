// سيرفر نظام تنبيه الطلبات
const fs = require('fs');
const path = require('path');
const http = require('http');
const express = require('express');
const { WebSocketServer } = require('ws');
const webpush = require('web-push');
const QRCode = require('qrcode');
const store = require('./store');

// ---------- قراءة .env بدون مكتبات ----------
const envPath = path.join(__dirname, '.env');
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z_]+)\s*=\s*(.*)\s*$/);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
  }
}

const PORT = process.env.PORT || 3000;
const PIN = process.env.CASHIER_PIN || '1234';
const { VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY } = process.env;
const VAPID_SUBJECT = process.env.VAPID_SUBJECT || 'mailto:you@example.com';
const BASE_URL = process.env.BASE_URL || ''; // مثال: https://ping.example.com

if (!VAPID_PUBLIC_KEY || !VAPID_PRIVATE_KEY) {
  console.error('ما فيه مفاتيح VAPID. شغّل: npm run vapid');
  process.exit(1);
}
webpush.setVapidDetails(VAPID_SUBJECT, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY);

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// ---------- WebSocket ----------
const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/ws' });

wss.on('connection', (ws, req) => {
  const url = new URL(req.url, 'http://x');
  if (url.searchParams.get('role') === 'cashier') {
    if (url.searchParams.get('pin') !== PIN) return ws.close(4001, 'pin');
    ws.role = 'cashier';
  } else {
    ws.orderId = url.searchParams.get('order');
  }
});

function broadcast(order) {
  const msg = JSON.stringify({ type: 'order', order: store.publicOrder(order) });
  for (const c of wss.clients) {
    if (c.readyState !== 1) continue;
    if (c.role === 'cashier' || c.orderId === order.id) c.send(msg);
  }
}

// ---------- حماية لوحة الكاشير ----------
function cashierOnly(req, res, next) {
  if (req.get('x-pin') !== PIN) return res.status(401).json({ error: 'PIN غلط' });
  next();
}

function orderUrl(req, id) {
  const base = BASE_URL || `${req.protocol}://${req.get('host')}`;
  return `${base}/o/${id}`;
}

// ---------- API ----------
app.get('/api/vapid-public-key', (req, res) => res.json({ key: VAPID_PUBLIC_KEY }));

app.post('/api/login', (req, res) => {
  if (req.body.pin === PIN) return res.json({ ok: true });
  res.status(401).json({ error: 'PIN غلط' });
});

app.get('/api/orders', cashierOnly, (req, res) => {
  res.json(store.listOrders().map(store.publicOrder));
});

app.post('/api/orders', cashierOnly, async (req, res) => {
  const number = String(req.body.number || '').trim();
  if (!number) return res.status(400).json({ error: 'رقم الطلب مطلوب' });
  const order = store.createOrder(number);
  const url = orderUrl(req, order.id);
  const qr = await QRCode.toDataURL(url, { margin: 1, width: 320 });
  broadcast(order);
  res.json({ order: store.publicOrder(order), url, qr });
});

app.get('/api/orders/:id/qr', cashierOnly, async (req, res) => {
  const order = store.getOrder(req.params.id);
  if (!order) return res.status(404).end();
  const url = orderUrl(req, order.id);
  res.json({ url, qr: await QRCode.toDataURL(url, { margin: 1, width: 320 }) });
});

// صفحة العميل تقرأ الطلب
app.get('/api/orders/:id', (req, res) => {
  const order = store.getOrder(req.params.id);
  if (!order) return res.status(404).json({ error: 'الطلب غير موجود' });
  res.json(store.publicOrder(order));
});

// العميل يشترك في الإشعارات
app.post('/api/orders/:id/subscribe', (req, res) => {
  const sub = req.body.subscription;
  if (!sub || !sub.endpoint) return res.status(400).json({ error: 'اشتراك غير صالح' });
  const order = store.updateOrder(req.params.id, (o) => {
    if (!o.subscriptions.some((s) => s.endpoint === sub.endpoint)) o.subscriptions.push(sub);
  });
  if (!order) return res.status(404).end();
  broadcast(order);
  res.json({ ok: true });
});

// أحداث التتبع من العميل: opened / delivered / seen / coming
const ALLOWED_EVENTS = ['opened', 'delivered', 'seen', 'coming'];
app.post('/api/orders/:id/ack', (req, res) => {
  const ev = req.body.event;
  if (!ALLOWED_EVENTS.includes(ev)) return res.status(400).end();
  const order = store.updateOrder(req.params.id, (o) => {
    if (!o.events[ev]) o.events[ev] = Date.now();
    // "شافه" تعني ضمنياً إنه "وصل"
    if ((ev === 'seen' || ev === 'coming') && o.status === 'ready' && !o.events.delivered) {
      o.events.delivered = Date.now();
    }
  });
  if (!order) return res.status(404).end();
  broadcast(order);
  res.json({ ok: true });
});

// الكاشير يضغط "جاهز"
app.post('/api/orders/:id/ready', cashierOnly, async (req, res) => {
  const order = store.getOrder(req.params.id);
  if (!order) return res.status(404).end();

  store.updateOrder(order.id, (o) => {
    o.status = 'ready';
    o.events.readyAt = Date.now();
  });

  const payload = JSON.stringify({
    orderId: order.id,
    title: `طلبك جاهز ✅ رقم ${order.number}`,
    body: 'تفضل استلمه من الكاونتر',
    url: `/o/${order.id}`,
  });

  const dead = [];
  let sent = 0;
  await Promise.all(
    order.subscriptions.map((sub) =>
      webpush
        .sendNotification(sub, payload, { TTL: 3600, urgency: 'high' })
        .then(() => sent++)
        .catch((err) => {
          // 404/410 = الاشتراك انتهى
          if (err.statusCode === 404 || err.statusCode === 410) dead.push(sub.endpoint);
          else console.error('push error', err.statusCode || '', err.body || err.message);
        })
    )
  );

  const updated = store.updateOrder(order.id, (o) => {
    o.subscriptions = o.subscriptions.filter((s) => !dead.includes(s.endpoint));
    if (sent > 0) o.events.sent = Date.now();
  });
  broadcast(updated);
  res.json({ ok: true, sent, order: store.publicOrder(updated) });
});

// تسليم الطلب وإغلاقه
app.post('/api/orders/:id/done', cashierOnly, (req, res) => {
  const order = store.updateOrder(req.params.id, (o) => {
    o.status = 'done';
    o.subscriptions = [];
  });
  if (!order) return res.status(404).end();
  broadcast(order);
  res.json({ ok: true });
});

// ---------- الصفحات ----------
app.get('/o/:id', (req, res) => res.sendFile(path.join(__dirname, 'public', 'order.html')));
app.get('/', (req, res) => res.redirect('/cashier.html'));

server.listen(PORT, () => {
  console.log(`شغال على http://localhost:${PORT}  (لوحة الكاشير: /cashier.html)`);
});
