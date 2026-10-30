# secure_link.py
# طبقة الأمان المشتركة بين الرازبيري والسيرفر:
# كل رسالة تنوقّع بـ HMAC-SHA256 بمفتاح سري مشترك + وقت الإرسال + رقم عشوائي (nonce)
# السيرفر يرفض: التوقيع الغلط، الرسالة المعدّلة، الرسالة القديمة، والرسالة المكررة

import hashlib
import hmac
import os
import secrets
import time

MAX_AGE_SEC = 60  # أقصى عمر للرسالة بالثواني


def load_secret(path="secret.key"):
    with open(path, "r", encoding="utf-8") as f:
        key = f.read().strip()
    if len(key) < 32:
        raise ValueError("المفتاح السري قصير أو فاضي")
    return key.encode()


def create_secret(path="secret.key"):
    """ينشئ مفتاح سري جديد (مرة وحدة على السيرفر، وبعدين ينسخ للرازبيري)"""
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _message(device, ts, nonce, image_bytes, meta_str):
    return "|".join([
        device, str(ts), nonce,
        hashlib.sha256(image_bytes).hexdigest(),
        hashlib.sha256(meta_str.encode()).hexdigest(),
    ]).encode()


def sign(secret, device, image_bytes, meta_str):
    """يرجع الهيدرز اللي تنرسل مع الطلب"""
    ts = int(time.time())
    nonce = secrets.token_hex(12)
    sig = hmac.new(secret, _message(device, ts, nonce, image_bytes, meta_str), hashlib.sha256).hexdigest()
    return {"X-Device-ID": device, "X-Timestamp": str(ts), "X-Nonce": nonce, "X-Signature": sig}


class Verifier:
    """يستخدمه السيرفر للتحقق من كل رسالة"""

    def __init__(self, secret):
        self.secret = secret
        self.seen = {}  # nonce -> وقت الاستلام (لمنع إعادة الإرسال)

    def verify(self, headers, image_bytes, meta_str):
        try:
            device = headers["X-Device-ID"]
            ts = int(headers["X-Timestamp"])
            nonce = headers["X-Nonce"]
            sig = headers["X-Signature"]
        except (KeyError, ValueError):
            return False, "هيدرز ناقصة"

        now = time.time()
        if abs(now - ts) > MAX_AGE_SEC:
            return False, "رسالة قديمة أو ساعة الجهاز غلط"

        # تنظيف الـ nonces القديمة
        for n, t in list(self.seen.items()):
            if now - t > MAX_AGE_SEC * 2:
                del self.seen[n]
        if nonce in self.seen:
            return False, "رسالة مكررة (replay)"

        expected = hmac.new(self.secret, _message(device, ts, nonce, image_bytes, meta_str),
                            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return False, "توقيع غلط أو البيانات تعدّلت"

        self.seen[nonce] = now
        return True, device
