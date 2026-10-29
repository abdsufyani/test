# pi_detect.py
# يشتغل على Raspberry Pi 5: يصوّر بالكاميرا، يكتشف المخالفات بالموديل المدرَّب،
# ويرسلها للسيرفر بشكل آمن (HMAC + HTTPS)، ويقيس البيانات والزمن والطاقة.
#
# وضعين للمقارنة في الرسالة:
#   --mode opportunistic  (الافتراضي) يرسل اللقطات اللي فيها مخالفة بس
#   --mode fixed          يرسل كل لقطة (الطريقة التقليدية = baseline)
#
# أمثلة:
#   python pi_detect.py --model best_ncnn_model                         (بدون سيرفر: يحفظ محلياً)
#   python pi_detect.py --model best_ncnn_model --server https://192.168.1.20:8443
#   python pi_detect.py --model best_ncnn_model --server https://192.168.1.20:8443 --mode fixed --frames 100
#   python pi_detect.py --model best_ncnn_model --source test_images/   (تجربة على مجلد صور)

import argparse
import csv
import glob
import json
import os
import time
from datetime import datetime

import cv2
from ultralytics import YOLO

import energy

p = argparse.ArgumentParser()
p.add_argument("--model", default="best_ncnn_model", help="مجلد NCNN أو ملف .pt")
p.add_argument("--source", default="camera", help="camera أو مسار مجلد صور")
p.add_argument("--mode", choices=["opportunistic", "fixed"], default="opportunistic")
p.add_argument("--conf", type=float, default=0.40, help="أقل نسبة ثقة نقبلها")
p.add_argument("--interval", type=float, default=2.0, help="ثواني بين كل لقطة (الكاميرا فقط)")
p.add_argument("--frames", type=int, default=0, help="عدد اللقطات ثم يوقف (0 = بدون حد)")
p.add_argument("--out", default="detections", help="مجلد الحفظ المحلي والسجلات")
p.add_argument("--imgsz", type=int, default=640)
p.add_argument("--server", default="", help="رابط السيرفر، مثال: https://192.168.1.20:8443")
p.add_argument("--secret", default="secret.key", help="ملف المفتاح السري (نفس اللي على السيرفر)")
p.add_argument("--cert", default="cert.pem", help="شهادة السيرفر للتحقق من HTTPS")
p.add_argument("--device-id", default="pi5-01")
p.add_argument("--no-energy", action="store_true", help="إيقاف قياس الطاقة")
args = p.parse_args()

os.makedirs(args.out, exist_ok=True)
pending_dir = os.path.join(args.out, "pending")  # اللقطات اللي فشل إرسالها تنتظر هنا
os.makedirs(pending_dir, exist_ok=True)

# ===== الإرسال الآمن =====
session = secret = None
verify = True  # شهادة السيرفر (تنمرر مع كل طلب عشان ما تغطي عليها إعدادات النظام)
if args.server:
    import requests
    from secure_link import load_secret, sign
    secret = load_secret(args.secret)
    session = requests.Session()
    if args.server.startswith("https"):
        if not os.path.exists(args.cert):
            raise SystemExit(f"ما لقيت {args.cert} — انسخه من اللابتوب")
        verify = args.cert
    else:
        print("تنبيه: الاتصال بدون HTTPS (غير مشفّر)")

model = YOLO(args.model, task="detect")
print("الفئات:", model.names, "| الوضع:", args.mode, "| السيرفر:", args.server or "لا (حفظ محلي)")

meter = None
if not args.no_energy and energy.available():
    meter = energy.EnergyMeter()
    print("قياس الطاقة: شغال (PMIC تقريبي)")
else:
    print("قياس الطاقة: غير متاح على هذا الجهاز")

log_path = os.path.join(args.out, "log.csv")
new_log = not os.path.exists(log_path)
log_f = open(log_path, "a", newline="", encoding="utf-8")
log = csv.writer(log_f)
if new_log:
    log.writerow(["time", "mode", "frame", "detected", "sent", "classes", "confidences",
                  "inference_ms", "send_ms", "bytes", "watts", "image"])

# ===== عدادات الملخص =====
c = {"frames": 0, "detected": 0, "sent": 0, "failed": 0, "retried": 0,
     "bytes_all": 0, "bytes_sent": 0, "infer_ms": [], "send_ms": []}
started = time.time()


def send(image_bytes, meta):
    """يرسل لقطة للسيرفر بتوقيع HMAC. يرجع (نجح؟, الزمن ms)"""
    meta_str = json.dumps(meta, ensure_ascii=False)
    headers = sign(secret, args.device_id, image_bytes, meta_str)
    t = time.time()
    try:
        r = session.post(f"{args.server}/upload", headers=headers, timeout=10, verify=verify,
                         files={"image": ("frame.jpg", image_bytes, "image/jpeg")},
                         data={"meta": meta_str})
        ok = r.status_code == 200
        if not ok:
            print(f"   السيرفر رفض: {r.status_code} {r.text[:100]}")
    except Exception as e:  # انقطاع شبكة وغيره
        print(f"   فشل الإرسال: {e.__class__.__name__}")
        ok = False
    return ok, (time.time() - t) * 1000


def retry_pending(limit=3):
    """يعيد إرسال اللقطات المعلّقة لما ترجع الشبكة"""
    for jpg in sorted(glob.glob(os.path.join(pending_dir, "*.jpg")))[:limit]:
        js = jpg[:-4] + ".json"
        with open(jpg, "rb") as f:
            img = f.read()
        with open(js, encoding="utf-8") as f:
            meta = json.load(f)
        meta["retried"] = True
        ok, _ = send(img, meta)
        if not ok:
            return
        os.remove(jpg)
        os.remove(js)
        c["retried"] += 1  # تنحسب لحالها عشان ما تخرب مقارنة هذا التشغيل
        print(f"   انرسلت لقطة معلّقة: {os.path.basename(jpg)}")


def handle(frame, name):
    t0 = time.time()
    r = model(frame, conf=args.conf, imgsz=args.imgsz, verbose=False)[0]
    infer_ms = (time.time() - t0) * 1000
    c["infer_ms"].append(infer_ms)
    c["frames"] += 1

    classes = [model.names[int(b.cls)] for b in r.boxes]
    confs = [round(float(b.conf), 2) for b in r.boxes]
    boxes = [[round(v) for v in b.xyxy[0].tolist()] for b in r.boxes]
    detected = bool(classes)
    c["detected"] += detected

    ok_enc, buf = cv2.imencode(".jpg", r.orig_img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    image_bytes = buf.tobytes() if ok_enc else b""
    c["bytes_all"] += len(image_bytes)  # حجم اللقطة لو انرسلت (للمقارنة)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    meta = {"time": stamp, "frame": name, "mode": args.mode, "device": args.device_id,
            "detections": [{"class": k, "conf": s, "box": bx} for k, s, bx in zip(classes, confs, boxes)]}

    should_send = detected or args.mode == "fixed"
    sent, send_ms, img_path = False, 0, ""

    if detected:  # نحفظ نسخة محلية عليها المربعات
        img_path = os.path.join(args.out, f"{stamp}.jpg")
        r.save(filename=img_path)
        with open(img_path[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)

    if should_send and session:
        sent, send_ms = send(image_bytes, meta)
        if sent:
            c["sent"] += 1
            c["bytes_sent"] += len(image_bytes)
            c["send_ms"].append(send_ms)
            retry_pending()
        else:
            c["failed"] += 1
            with open(os.path.join(pending_dir, f"{stamp}.jpg"), "wb") as f:
                f.write(image_bytes)
            with open(os.path.join(pending_dir, f"{stamp}.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)
    elif should_send:  # بدون سيرفر: نحسبها كأنها انرسلت (للمقارنة)
        c["sent"] += 1
        c["bytes_sent"] += len(image_bytes)

    watts = meter.sample(time.time()) if meter else None
    log.writerow([datetime.now().isoformat(timespec="seconds"), args.mode, name, int(detected),
                  int(sent), "|".join(classes), "|".join(map(str, confs)), round(infer_ms),
                  round(send_ms), len(image_bytes) if should_send else 0,
                  round(watts, 3) if watts else "", img_path])
    log_f.flush()

    found = ", ".join(f"{k} {s}" for k, s in zip(classes, confs)) or "لا شي"
    status = ("مرسلة" if sent else "فشل/معلّقة") if (should_send and session) else ("محفوظة" if detected else "")
    print(f"[{c['frames']}] {name}: {found}  ({infer_ms:.0f} ms) {status}"
          + (f"  {watts:.2f}W" if watts else ""))


try:
    if meter:
        meter.sample(time.time())
    if args.source == "camera":
        from picamera2 import Picamera2
        cam = Picamera2()
        cam.configure(cam.create_still_configuration(main={"size": (1280, 960), "format": "RGB888"}))
        cam.start()
        time.sleep(2)  # وقت لضبط الإضاءة
        i = 0
        while args.frames == 0 or i < args.frames:
            frame = cam.capture_array()  # صيغة BGR جاهزة للموديل
            handle(frame, f"cam_{i}")
            i += 1
            time.sleep(args.interval)
    else:
        files = sorted(f for e in ("jpg", "jpeg", "png", "JPG", "JPEG", "PNG")
                       for f in glob.glob(os.path.join(args.source, f"*.{e}")))
        for f in files[: args.frames or None]:
            handle(f, os.path.basename(f))
except KeyboardInterrupt:
    pass
finally:
    log_f.close()
    if c["frames"]:
        warm = c["infer_ms"][1:] or c["infer_ms"]
        s = {
            "mode": args.mode,
            "frames": c["frames"],
            "detected": c["detected"],
            "sent": c["sent"],
            "failed_pending": c["failed"],
            "retried_from_before": c["retried"],
            "mb_if_all_sent": round(c["bytes_all"] / 1e6, 3),
            "mb_sent": round(c["bytes_sent"] / 1e6, 3),
            "data_reduction_pct": round(100 * (1 - c["bytes_sent"] / c["bytes_all"]), 1) if c["bytes_all"] else None,
            "avg_inference_ms": round(sum(warm) / len(warm)),
            "avg_send_ms": round(sum(c["send_ms"]) / len(c["send_ms"])) if c["send_ms"] else None,
            "duration_s": round(time.time() - started, 1),
        }
        es = meter.summary() if meter else None
        if es:
            s |= {"avg_watts": round(es["avg_watts"], 3), "energy_joules": round(es["energy_j"], 1),
                  "joules_per_frame": round(es["energy_j"] / c["frames"], 2)}

        print("\n===== ملخص =====")
        print(f"الوضع: {s['mode']} | لقطات: {s['frames']} | فيها مخالفة: {s['detected']} | "
              f"مرسلة: {s['sent']} | معلّقة: {s['failed_pending']}")
        print(f"البيانات المرسلة: {s['mb_sent']} MB من {s['mb_if_all_sent']} MB "
              f"(تقليل {s['data_reduction_pct']}%)")
        print(f"متوسط زمن التحليل: {s['avg_inference_ms']} ms"
              + (f" | متوسط زمن الإرسال: {s['avg_send_ms']} ms" if s['avg_send_ms'] else ""))
        if es:
            print(f"الطاقة: متوسط {s['avg_watts']} W | الكلي {s['energy_joules']} J | "
                  f"{s['joules_per_frame']} J لكل لقطة")
        summary_path = os.path.join(args.out, f"summary_{args.mode}_{datetime.now():%Y%m%d_%H%M%S}.json")
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
        print(f"الملخص: {summary_path} | السجل: {log_path}")
