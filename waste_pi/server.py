# server.py
# سيرفر المنصة (يشتغل على اللابتوب): يستقبل المخالفات من الرازبيري بشكل آمن ويعرضها
#
# أول مرة:   python server.py --init          (ينشئ المفتاح السري)
# التشغيل:   python server.py                 (HTTPS على المنفذ 8443)
# العرض:     افتح https://<IP-اللابتوب>:8443  في المتصفح

import argparse
import csv
import json
import os
import time
from datetime import datetime

from flask import Flask, abort, jsonify, request, send_from_directory

from secure_link import Verifier, create_secret, load_secret

p = argparse.ArgumentParser()
p.add_argument("--init", action="store_true", help="إنشاء مفتاح سري جديد")
p.add_argument("--port", type=int, default=8443)
p.add_argument("--data", default="received")
p.add_argument("--cert", default="cert.pem")
p.add_argument("--key", default="key.pem")
p.add_argument("--no-tls", action="store_true", help="بدون HTTPS (للتجربة فقط)")
args = p.parse_args()

if args.init:
    create_secret("secret.key")
    print("تم إنشاء secret.key — انسخه للرازبيري في مجلد waste_pi، ولا تشاركه مع أحد")
    raise SystemExit

os.makedirs(args.data, exist_ok=True)
verifier = Verifier(load_secret("secret.key"))
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # أقصى حجم للطلب 10MB

log_path = os.path.join(args.data, "server_log.csv")
if not os.path.exists(log_path):
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["time", "device", "accepted", "reason", "bytes", "classes", "image"])

stats = {"accepted": 0, "rejected": 0, "bytes": 0, "started": time.time()}


def write_log(*row):
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


@app.post("/upload")
def upload():
    image = request.files.get("image")
    meta_str = request.form.get("meta", "")
    if image is None:
        abort(400, "ما فيه صورة")
    image_bytes = image.read()
    size = len(image_bytes) + len(meta_str.encode())
    now = datetime.now().isoformat(timespec="seconds")

    ok, info = verifier.verify(request.headers, image_bytes, meta_str)
    if not ok:
        stats["rejected"] += 1
        write_log(now, request.headers.get("X-Device-ID", "?"), 0, info, size, "", "")
        print(f"مرفوض: {info}")
        return jsonify({"ok": False, "error": info}), 401

    device = info
    meta = json.loads(meta_str) if meta_str else {}
    name = f"{device}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    with open(os.path.join(args.data, name + ".jpg"), "wb") as f:
        f.write(image_bytes)
    with open(os.path.join(args.data, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    stats["accepted"] += 1
    stats["bytes"] += size
    classes = "|".join(d["class"] for d in meta.get("detections", []))
    write_log(now, device, 1, "", size, classes, name + ".jpg")
    print(f"مقبول من {device}: {classes or 'بدون اكتشاف'} ({size / 1024:.0f} KB)")
    return jsonify({"ok": True})


@app.get("/stats")
def get_stats():
    return jsonify(stats | {"uptime_s": round(time.time() - stats["started"])})


@app.get("/img/<path:name>")
def img(name):
    return send_from_directory(args.data, name)


@app.get("/")
def index():
    files = sorted((f for f in os.listdir(args.data) if f.endswith(".json")), reverse=True)[:30]
    cards = []
    for f in files:
        with open(os.path.join(args.data, f), encoding="utf-8") as fh:
            meta = json.load(fh)
        dets = ", ".join(f"{d['class']} {d['conf']}" for d in meta.get("detections", [])) or "بدون اكتشاف"
        cards.append(f'<div class="c"><img src="/img/{f[:-5]}.jpg"><p>{dets}<br><small>{f[:-5]}</small></p></div>')
    return f"""<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="5">
<title>المخالفات</title><style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#f5f5f5;color:#222}}
.s{{background:#fff;padding:12px;border-radius:8px;margin-bottom:16px}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}}
.c{{background:#fff;border-radius:8px;overflow:hidden}} .c img{{width:100%;display:block}}
.c p{{margin:8px}} small{{color:#777}}</style></head><body>
<h2>المخالفات المستلمة</h2>
<div class="s">مقبولة: <b>{stats['accepted']}</b> · مرفوضة: <b>{stats['rejected']}</b> ·
البيانات المستلمة: <b>{stats['bytes'] / 1e6:.2f} MB</b></div>
<div class="g">{''.join(cards) or '<p>ما وصل شي للحين</p>'}</div></body></html>"""


if __name__ == "__main__":
    ssl = None if args.no_tls else (args.cert, args.key)
    if ssl and not (os.path.exists(args.cert) and os.path.exists(args.key)):
        raise SystemExit("ما لقيت الشهادة. شغّل أول: python gen_cert.py <IP-اللابتوب>")
    print(f"السيرفر شغال على {'https' if ssl else 'http'}://0.0.0.0:{args.port}")
    app.run(host="0.0.0.0", port=args.port, ssl_context=ssl)
