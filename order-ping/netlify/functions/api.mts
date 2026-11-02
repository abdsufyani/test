// API رنّة على Netlify: نفس مسارات server.js لكن بالتخزين في Netlify Blobs
import type { Config, Context } from "@netlify/functions";
import { getStore } from "@netlify/blobs";
import webpush from "web-push";
import QRCode from "qrcode";
import { createHash, randomBytes } from "node:crypto";

const store = () => getStore({ name: "ranna", consistency: "strong" });

const env = (k: string, d = "") => Netlify.env.get(k) || d;
const PIN = () => env("CASHIER_PIN", "1234");

let vapidReady = false;
function setupVapid() {
  if (vapidReady) return;
  webpush.setVapidDetails(
    env("VAPID_SUBJECT", "mailto:you@example.com"),
    env("VAPID_PUBLIC_KEY"),
    env("VAPID_PRIVATE_KEY"),
  );
  vapidReady = true;
}

type Order = { id: string; number: string; status: "preparing" | "ready" | "done"; createdAt: number };

const json = (data: unknown, status = 200) => Response.json(data, { status, headers: { "cache-control": "no-store" } });
const err = (msg: string, status = 400) => json({ error: msg }, status);

const subKey = (id: string, endpoint: string) =>
  `subs/${id}/${createHash("sha1").update(endpoint).digest("hex")}`;

async function getOrder(id: string): Promise<Order | null> {
  return (await store().get(`orders/${id}`, { type: "json" })) as Order | null;
}

async function listSubs(id: string) {
  const s = store();
  const { blobs } = await s.list({ prefix: `subs/${id}/` });
  const subs = await Promise.all(blobs.map((b) => s.get(b.key, { type: "json" })));
  return blobs.map((b, i) => ({ key: b.key, sub: subs[i] as webpush.PushSubscription })).filter((x) => x.sub);
}

async function getEvents(id: string) {
  const s = store();
  const { blobs } = await s.list({ prefix: `events/${id}/` });
  const values = await Promise.all(blobs.map((b) => s.get(b.key)));
  const events: Record<string, number> = {};
  blobs.forEach((b, i) => { events[b.key.split("/").pop()!] = Number(values[i]); });
  return events;
}

async function publicOrder(o: Order) {
  const [events, subs] = await Promise.all([getEvents(o.id), store().list({ prefix: `subs/${o.id}/` })]);
  return {
    id: o.id,
    number: o.number,
    status: o.status,
    events,
    following: subs.blobs.length > 0 || !!events.opened,
    createdAt: o.createdAt,
  };
}

async function setEvent(id: string, ev: string, overwrite = false) {
  await store().set(`events/${id}/${ev}`, String(Date.now()), overwrite ? {} : { onlyIfNew: true });
}

async function clearPrefix(prefix: string) {
  const s = store();
  const { blobs } = await s.list({ prefix });
  await Promise.all(blobs.map((b) => s.delete(b.key)));
}

async function qrFor(origin: string, id: string) {
  const url = `${origin}/o/${id}`;
  return { url, qr: await QRCode.toDataURL(url, { margin: 1, width: 320 }) };
}

export default async (req: Request, context: Context) => {
  const url = new URL(req.url);
  const parts = url.pathname.replace(/^\/api\/?/, "").split("/").filter(Boolean);
  const method = req.method;
  const body = method === "POST" ? await req.json().catch(() => ({})) : {};
  const isCashier = req.headers.get("x-pin") === PIN();

  try {
    // GET /api/vapid-public-key
    if (parts[0] === "vapid-public-key") return json({ key: env("VAPID_PUBLIC_KEY") });

    // POST /api/login
    if (parts[0] === "login" && method === "POST") {
      return body.pin === PIN() ? json({ ok: true }) : err("PIN غلط", 401);
    }

    if (parts[0] !== "orders") return err("غير موجود", 404);
    const id = parts[1];
    const action = parts[2];

    // GET /api/orders  (الكاشير)
    if (!id && method === "GET") {
      if (!isCashier) return err("PIN غلط", 401);
      const s = store();
      const { blobs } = await s.list({ prefix: "orders/" });
      const orders = (await Promise.all(blobs.map((b) => s.get(b.key, { type: "json" })))) as (Order | null)[];
      const active = orders.filter((o): o is Order => !!o && o.status !== "done").sort((a, b) => a.createdAt - b.createdAt);
      return json(await Promise.all(active.map(publicOrder)));
    }

    // POST /api/orders  (طلب جديد)
    if (!id && method === "POST") {
      if (!isCashier) return err("PIN غلط", 401);
      const number = String(body.number || "").trim().slice(0, 6);
      if (!number) return err("رقم الطلب مطلوب");
      const order: Order = { id: randomBytes(6).toString("base64url"), number, status: "preparing", createdAt: Date.now() };
      await store().setJSON(`orders/${order.id}`, order);
      return json({ order: await publicOrder(order), ...(await qrFor(url.origin, order.id)) });
    }

    const order = id ? await getOrder(id) : null;
    if (!order) return err("الطلب غير موجود", 404);

    // GET /api/orders/:id
    if (!action && method === "GET") return json(await publicOrder(order));

    // GET /api/orders/:id/qr
    if (action === "qr") {
      if (!isCashier) return err("PIN غلط", 401);
      return json(await qrFor(url.origin, order.id));
    }

    if (method !== "POST") return err("غير مسموح", 405);

    // POST /api/orders/:id/subscribe
    if (action === "subscribe") {
      const sub = body.subscription;
      if (!sub?.endpoint || !sub?.keys) return err("اشتراك غير صالح");
      await store().setJSON(subKey(order.id, sub.endpoint), sub);
      return json({ ok: true });
    }

    // POST /api/orders/:id/ack
    if (action === "ack") {
      const ev = body.event;
      if (!["opened", "delivered", "seen", "coming"].includes(ev)) return err("حدث غير معروف");
      await setEvent(order.id, ev);
      if ((ev === "seen" || ev === "coming") && order.status === "ready") await setEvent(order.id, "delivered");
      return json({ ok: true });
    }

    // POST /api/orders/:id/ready
    if (action === "ready") {
      if (!isCashier) return err("PIN غلط", 401);
      setupVapid();
      order.status = "ready";
      await store().setJSON(`orders/${order.id}`, order);
      // رنّة ثانية: نصفّر أحداث المتابعة ونخلي "جاي"
      await Promise.all(["sent", "delivered", "seen"].map((e) => store().delete(`events/${order.id}/${e}`)));

      const payload = JSON.stringify({
        orderId: order.id,
        title: `طلبك جاهز ✅ رقم ${order.number}`,
        body: "تفضل استلمه من الكاونتر",
        url: `/o/${order.id}`,
      });
      let sent = 0;
      const subs = await listSubs(order.id);
      await Promise.all(
        subs.map(({ key, sub }) =>
          webpush
            .sendNotification(sub, payload, { TTL: 3600, urgency: "high" })
            .then(() => { sent++; })
            .catch(async (e: any) => {
              if (e.statusCode === 404 || e.statusCode === 410) await store().delete(key);
              else console.error("push error", e.statusCode || "", e.body || e.message);
            }),
        ),
      );
      if (sent > 0) await setEvent(order.id, "sent", true);
      return json({ ok: true, sent, order: await publicOrder(order) });
    }

    // POST /api/orders/:id/done
    if (action === "done") {
      if (!isCashier) return err("PIN غلط", 401);
      order.status = "done";
      await store().setJSON(`orders/${order.id}`, order);
      await clearPrefix(`subs/${order.id}/`);
      return json({ ok: true });
    }

    return err("غير موجود", 404);
  } catch (e: any) {
    console.error(e);
    return err("خطأ في السيرفر", 500);
  }
};

export const config: Config = { path: "/api/*" };
