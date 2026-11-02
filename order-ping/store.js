// تخزين بسيط في ملف JSON (كافي للنسخة الأولى)
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const FILE = path.join(__dirname, 'data.json');
let db = { orders: {} };

try {
  db = JSON.parse(fs.readFileSync(FILE, 'utf8'));
} catch (_) { /* أول تشغيل */ }

let saveTimer = null;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => fs.writeFile(FILE, JSON.stringify(db, null, 2), () => {}), 200);
}

// الحالات: preparing → ready → done
// أحداث التتبع: sent, delivered, seen, coming
function createOrder(number) {
  const id = crypto.randomBytes(6).toString('base64url');
  const order = {
    id,
    number: String(number),
    status: 'preparing',
    subscriptions: [],
    events: {},
    createdAt: Date.now(),
  };
  db.orders[id] = order;
  save();
  return order;
}

function getOrder(id) {
  return db.orders[id] || null;
}

function listOrders() {
  return Object.values(db.orders)
    .filter((o) => o.status !== 'done')
    .sort((a, b) => a.createdAt - b.createdAt);
}

function updateOrder(id, fn) {
  const o = db.orders[id];
  if (!o) return null;
  fn(o);
  save();
  return o;
}

// نسخة آمنة للإرسال للواجهة (بدون بيانات الاشتراك)
function publicOrder(o) {
  return {
    id: o.id,
    number: o.number,
    status: o.status,
    events: o.events,
    following: o.subscriptions.length > 0 || !!o.events.opened,
    createdAt: o.createdAt,
  };
}

module.exports = { createOrder, getOrder, listOrders, updateOrder, publicOrder };
