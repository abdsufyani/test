# energy.py
# قياس تقريبي لاستهلاك Raspberry Pi 5 من شريحة الطاقة (PMIC) بدون أي جهاز إضافي
# يجمع (الجهد × التيار) لكل خطوط الطاقة اللي يقرأها الأمر: vcgencmd pmic_read_adc
# ملاحظة: قياس تقريبي للمقارنة بين الأوضاع، مش بديل عن جهاز قياس USB-C

import re
import shutil
import subprocess

_CUR = re.compile(r"(\S+)_A\s+current\(\d+\)=([\d.]+)A")
_VOLT = re.compile(r"(\S+)_V\s+volt\(\d+\)=([\d.]+)V")


def available():
    return shutil.which("vcgencmd") is not None


def read_watts():
    """يرجع الاستهلاك الحالي بالواط، أو None لو ما يقدر يقرأ"""
    try:
        out = subprocess.run(["vcgencmd", "pmic_read_adc"], capture_output=True,
                             text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    amps = {n: float(v) for n, v in _CUR.findall(out)}
    volts = {n: float(v) for n, v in _VOLT.findall(out)}
    common = amps.keys() & volts.keys()
    if not common:
        return None
    return sum(amps[n] * volts[n] for n in common)


class EnergyMeter:
    """يسجل قراءات الطاقة على طول التشغيل ويحسب المتوسط والطاقة الكلية"""

    def __init__(self):
        self.samples = []  # (الوقت, الواط)

    def sample(self, t):
        w = read_watts()
        if w is not None:
            self.samples.append((t, w))
        return w

    def summary(self):
        if len(self.samples) < 2:
            return None
        avg_w = sum(w for _, w in self.samples) / len(self.samples)
        dur = self.samples[-1][0] - self.samples[0][0]
        return {"avg_watts": avg_w, "duration_s": dur, "energy_j": avg_w * dur}
