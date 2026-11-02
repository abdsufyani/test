// منطق صفحة العميل
const orderId = location.pathname.split('/').pop();
const $ = (id) => document.getElementById(id);
const show = (id, on = true) => $(id).classList.toggle('hidden', !on);

const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const isStandalone = matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const pushSupported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

let order = null;
let wasReady = false;

function api(path, body) {
  return fetch(`/api/orders/${orderId}${path}`, {
    method: body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
}

// تنبيه صوتي واهتزاز لو الصفحة مفتوحة
function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [0, 0.35, 0.7].forEach((t) => {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.frequency.value = 880;
      g.gain.setValueAtTime(0.25, ctx.currentTime + t);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.3);
      o.connect(g).connect(ctx.destination);
      o.start(ctx.currentTime + t);
      o.stop(ctx.currentTime + t + 0.3);
    });
  } catch (_) {}
  if (navigator.vibrate) navigator.vibrate([400, 150, 400, 150, 400]);
}

function render() {
  if (!order) return;
  document.title = `طلب ${order.number}`;
  renderDots($('num'), order.number);
  const ready = order.status === 'ready';
  const done = order.status === 'done';
  $('ticket').classList.toggle('ready', ready);

  if (done) {
    $('status').textContent = 'تم استلام الطلب';
    $('sub').textContent = 'بالعافية عليك 🤍';
  } else if (ready) {
    $('status').textContent = 'طلبك جاهز ✅';
    $('sub').textContent = 'تفضل استلمه من الكاونتر';
  } else {
    $('status').textContent = 'طلبك قيد التحضير';
    $('sub').textContent = 'جوالك يرن أول ما يجهز';
  }
  show('pulse', !ready && !done);

  const coming = !!order.events.coming;
  show('comingBtn', ready && !coming);
  show('comingPill', ready && coming);
  if (ready || done) { show('notifyBtn', false); show('iosNote', false); }

  if (ready && !wasReady) {
    beep();
    api('/ack', { event: 'seen' });
  }
  wasReady = ready;
}

async function load() {
  const r = await api('');
  if (!r.ok) {
    $('status').textContent = 'الطلب غير موجود';
    $('sub').textContent = '';
    show('pulse', false);
    return false;
  }
  order = await r.json();
  render();
  return true;
}

// تحديث الحالة كل ثانيتين (يوقف لما الصفحة مخفية)
let pollTimer = null;
function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(() => { if (!document.hidden) load(); }, 2000);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });

function urlBase64ToUint8Array(base64) {
  const pad = '='.repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function subscribe() {
  $('notifyBtn').disabled = true;
  try {
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') throw new Error('ما سمحت بالإشعارات. فعّلها من إعدادات المتصفح.');
    const reg = await navigator.serviceWorker.ready;
    const { key } = await (await fetch('/api/vapid-public-key')).json();
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
    }
    const r = await api('/subscribe', { subscription: sub.toJSON() });
    if (!r.ok) throw new Error('صار خطأ في الاشتراك');
    localStorageSet(`sub-${orderId}`, '1');
    show('notifyBtn', false);
    show('notifyOk', true);
  } catch (err) {
    const msg = /[؀-ۿ]/.test(err.message)
      ? err.message
      : 'ما قدرنا نفعّل الإشعارات على هذا المتصفح. خلّ الصفحة مفتوحة وبتنبهك بصوت لما يجهز.';
    $('errBox').textContent = msg;
    show('errBox', true);
    $('notifyBtn').disabled = false;
  }
}

function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch (_) {} }
function localStorageGet(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }

async function init() {
  const ok = await load();
  if (!ok) return;
  startPolling();
  api('/ack', { event: 'opened' });

  if (order.status !== 'preparing') return;

  if (pushSupported) {
    await navigator.serviceWorker.register('/sw.js');
    if (Notification.permission === 'granted' && localStorageGet(`sub-${orderId}`)) {
      show('notifyOk', true);
    } else {
      show('notifyBtn', true);
    }
  } else if (isIOS && !isStandalone) {
    show('iosNote', true);
  } else {
    show('unsupported', true);
  }
}

$('notifyBtn').addEventListener('click', subscribe);
$('comingBtn').addEventListener('click', async () => {
  $('comingBtn').disabled = true;
  await api('/ack', { event: 'coming' });
});

init();
