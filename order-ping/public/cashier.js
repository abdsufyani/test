// منطق لوحة الكاشير
const $ = (id) => document.getElementById(id);
const show = (id, on = true) => $(id).classList.toggle('hidden', !on);

let pin = sessionGet('pin') || '';
const orders = new Map();

function sessionGet(k) { try { return sessionStorage.getItem(k); } catch (_) { return null; } }
function sessionSet(k, v) { try { sessionStorage.setItem(k, v); } catch (_) {} }

function api(path, body) {
  return fetch(`/api${path}`, {
    method: body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', 'x-pin': pin },
    body: body ? JSON.stringify(body) : undefined,
  });
}

// ---------- الدخول ----------
$('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  pin = $('pinInput').value.trim();
  const r = await api('/login', { pin });
  if (!r.ok) { $('loginErr').textContent = 'PIN غلط'; return; }
  sessionSet('pin', pin);
  start();
});

async function start() {
  const r = await api('/orders');
  if (!r.ok) { show('loginView', true); show('boardView', false); return; }
  show('loginView', false);
  show('boardView', true);
  setOrders(await r.json());
  startPolling();
}

// تحديث اللوحة كل ثانيتين (يوقف لما الصفحة مخفية)
let pollTimer = null;
let lastJson = '';
function setOrders(list) {
  const j = JSON.stringify(list);
  if (j === lastJson) return; // ما تغير شي، لا نعيد الرسم
  lastJson = j;
  orders.clear();
  for (const o of list) orders.set(o.id, o);
  renderAll();
}
async function refresh() {
  try {
    const r = await api('/orders');
    if (r.ok) setOrders(await r.json());
  } catch (_) {}
}
function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(() => { if (!document.hidden) refresh(); }, 2000);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && pin) refresh(); });

// ---------- الرسم ----------
const STATUS_TEXT = { preparing: 'قيد التحضير', ready: 'جاهز' };

function renderAll() {
  const grid = $('grid');
  grid.innerHTML = '';
  show('empty', orders.size === 0);
  for (const o of orders.values()) grid.appendChild(card(o));
}

function card(o) {
  const el = document.createElement('div');
  el.className = 'card';
  el.dataset.id = o.id;
  el.innerHTML = `
    <div class="card-head">
      <div class="num"></div>
      <div>
        <div class="st">${STATUS_TEXT[o.status] || o.status}</div>
        <div class="follow">${o.following ? '📱 العميل متابع من جواله' : '⏳ العميل ما مسح الكود بعد'}</div>
      </div>
    </div>
    <div class="steps-wrap"></div>
    <div class="card-actions"></div>`;
  renderDots(el.querySelector('.num'), o.number);
  if (o.status === 'ready') el.querySelector('.num').classList.add('ready');

  const actions = el.querySelector('.card-actions');
  if (o.status === 'preparing') {
    actions.append(
      button('جاهز', 'btn-primary', () => api(`/orders/${o.id}/ready`, {})),
      button('QR', 'btn-ghost', () => showQR(o)),
    );
    actions.firstChild.style.flex = '3';
  } else {
    const ev = o.events || {};
    const steps = document.createElement('div');
    steps.className = 'steps';
    steps.innerHTML = [
      ['sent', '✓ انرسل'],
      ['delivered', '✓✓ وصل'],
      ['seen', '👁 شافه'],
      ['coming', '🚶 جاي'],
    ].map(([k, t]) => `<span class="step ${k} ${ev[k] ? 'on' : ''}">${t}</span>`).join('');
    el.querySelector('.steps-wrap').appendChild(steps);
    actions.append(
      button('تم التسليم', 'btn-dark', () => api(`/orders/${o.id}/done`, {})),
      button('إعادة الرنّة', 'btn-ghost', () => api(`/orders/${o.id}/ready`, {})),
    );
  }
  return el;
}

function button(text, cls, onClick) {
  const b = document.createElement('button');
  b.className = `btn ${cls}`;
  b.textContent = text;
  b.addEventListener('click', async () => { b.disabled = true; await onClick(); await refresh(); b.disabled = false; });
  return b;
}

// ---------- طلب جديد + QR ----------
$('newForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const number = $('newNum').value.trim();
  if (!number) return;
  const r = await api('/orders', { number });
  if (!r.ok) return alert('ما قدرت أضيف الطلب');
  const data = await r.json();
  $('newNum').value = '';
  refresh();
  openQR(data.order.number, data.qr, data.url);
});

async function showQR(o) {
  const r = await api(`/orders/${o.id}/qr`);
  const data = await r.json();
  openQR(o.number, data.qr, data.url);
}

function openQR(number, qr, url) {
  $('qrTitle').textContent = `طلب رقم ${number}`;
  $('qrImg').src = qr;
  $('qrUrl').textContent = url;
  show('qrModal', true);
}
$('qrClose').addEventListener('click', () => show('qrModal', false));

if (pin) start();
