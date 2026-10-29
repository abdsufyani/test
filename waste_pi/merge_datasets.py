# merge_datasets.py
# يدمج عدة داتا سيتات بصيغة YOLO في داتا وحدة بفئات موحدة:
#   0 = illegal_dumping   1 = road_damage   2 = abandoned_vehicle
#
# - أسماء الفئات تنقرأ من data.yaml حق كل داتا، والربط بالاسم بالضبط (مو بالرقم ولا بجزء من الكلمة)
#   لو اسم مطلوب ما لقيناه، السكربت يوقف ويطبع الأسماء الموجودة بدل ما يدمج غلط
# - الفئات غير المطلوبة (person, graffiti, ...) تنحذف، والصور اللي ما بقى فيها شي تتخطى
# - الصور المكررة بنفس المحتوى بين المصادر تنحذف (عشان ما يصير تسريب بين train و test)
# - الـ polygons (لو الداتا segmentation) تتحول لمربعات
# - لو مصدر السيارات المهجورة مو موجود، الداتا تطلع بفئتين بس (0 و 1)
#
# الاستخدام:
#   python merge_datasets.py output_dir smart=path1 dump=path2 dead=path3

import hashlib
import json
import os
import shutil
import sys
from collections import defaultdict

import yaml

ALL_CLASSES = {0: "illegal_dumping", 1: "road_damage", 2: "abandoned_vehicle"}

# جدول الربط لكل مصدر: رقم الفئة الموحد <- الأسماء المقبولة (بحروف صغيرة، مطابقة كاملة)
MAPPING = {
    "smart": {0: ["garbage"], 1: ["potholes", "pothole"]},
    "dump": {0: ["garbage"]},
    "dead": {2: ["deadvehicle", "dead vehicle", "dead_vehicle", "dead-vehicle",
                 "abandoned vehicle", "abandoned_vehicle", "abandoned-vehicle"]},
}
# مصادر لو فيها فئة وحدة بس، تنربط بهالفئة تلقائياً حتى لو اسمها مختلف
SINGLE_CLASS_DEFAULT = {"dead": 2}

SPLITS = {"train": "train", "valid": "valid", "val": "valid", "test": "test"}
IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def read_names(dataset_dir):
    """يقرأ أسماء الفئات من data.yaml (قائمة أو قاموس)"""
    path = os.path.join(dataset_dir, "data.yaml")
    if not os.path.exists(path):
        sys.exit(f"[خطأ] ما لقيت data.yaml في {dataset_dir}")
    with open(path, encoding="utf-8") as f:
        names = yaml.safe_load(f).get("names")
    if isinstance(names, dict):
        names = [names[k] for k in sorted(names, key=int)]
    if not names:
        sys.exit(f"[خطأ] data.yaml في {dataset_dir} ما فيه names")
    return [str(n) for n in names]


def build_mapping(short, names):
    """يطلع جدول تحويل: رقم الفئة القديم -> الرقم الموحد. الفئات اللي مو فيه تنحذف"""
    if short not in MAPPING:
        sys.exit(f"[خطأ] المصدر '{short}' مو معروف. المصادر المعروفة: {list(MAPPING)}")
    lower = [n.strip().lower() for n in names]
    mapping = {}
    if len(names) == 1 and short in SINGLE_CLASS_DEFAULT:
        mapping[0] = SINGLE_CLASS_DEFAULT[short]
    else:
        for new_id, accepted in MAPPING[short].items():
            found = [i for i, n in enumerate(lower) if n in accepted]
            if not found:
                sys.exit(f"[خطأ] في '{short}' ما لقيت فئة {ALL_CLASSES[new_id]} "
                         f"(الأسماء المقبولة: {accepted}).\n"
                         f"       الفئات الموجودة: {names}\n"
                         f"       أضف الاسم الصحيح في MAPPING داخل merge_datasets.py")
            for i in found:
                mapping[i] = new_id

    print(f"\n[{short}] الفئات الأصلية والتحويل:")
    for i, n in enumerate(names):
        print(f"   {i}: {n:<25} -> {ALL_CLASSES[mapping[i]] if i in mapping else 'حذف'}")
    return mapping


def find_splits(dataset_dir):
    """يدور على مجلدات train/valid/test اللي فيها images"""
    splits = {}
    for d in sorted(os.listdir(dataset_dir)):
        full = os.path.join(dataset_dir, d)
        if d.lower() in SPLITS and os.path.isdir(os.path.join(full, "images")):
            splits[SPLITS[d.lower()]] = full
    if not splits:
        sys.exit(f"[خطأ] ما لقيت مجلدات train/valid/test في {dataset_dir}")
    return splits


def convert_line(line, mapping):
    """يحوّل سطر label واحد. يرجع (الفئة, السطر) أو None لو الفئة محذوفة أو السطر تالف"""
    parts = line.split()
    if len(parts) < 5:
        return None
    try:
        cls = int(float(parts[0]))
        vals = [float(v) for v in parts[1:]]
    except ValueError:
        return None
    if cls not in mapping:
        return None
    if len(vals) == 4:
        x, y, w, h = vals
    elif len(vals) >= 6 and len(vals) % 2 == 0:  # polygon: x1 y1 x2 y2 ...
        xs, ys = vals[0::2], vals[1::2]
        x, y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        w, h = max(xs) - min(xs), max(ys) - min(ys)
    else:
        return None
    # نقص القيم داخل حدود الصورة ونتخطى المربعات الصفرية
    x, y, w, h = (min(max(v, 0.0), 1.0) for v in (x, y, w, h))
    if w <= 0 or h <= 0:
        return None
    new = mapping[cls]
    return new, f"{new} {x:.6f} {y:.6f} {w:.6f} {h:.6f}"


def file_hash(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def merge(sources, output):
    """sources: قائمة (اسم_مختصر, مسار_المجلد). يرجع الإحصائية"""
    # نقرأ كل الجداول أول، عشان لو فيه خطأ يوقف قبل ما ينسخ أي شي
    mappings = {short: build_mapping(short, read_names(path)) for short, path in sources}
    used = sorted({c for m in mappings.values() for c in m.values()})
    if used != list(range(len(used))):
        sys.exit(f"[خطأ] أرقام الفئات المستخدمة لازم تكون متتالية من 0، والموجود: {used}")
    final = {c: ALL_CLASSES[c] for c in used}

    if os.path.exists(output):
        shutil.rmtree(output)
    for s in ("train", "valid", "test"):
        os.makedirs(os.path.join(output, s, "images"))
        os.makedirs(os.path.join(output, s, "labels"))

    # stats[split][class] = {"images": n, "boxes": n}
    stats = {s: {n: {"images": 0, "boxes": 0} for n in final.values()} for s in ("train", "valid", "test")}
    images = defaultdict(int)
    skipped = {short: {"empty": 0, "duplicate": 0, "no_label": 0} for short, _ in sources}
    seen = set()

    for short, path in sources:
        mapping = mappings[short]
        for split, split_dir in find_splits(path).items():
            img_dir = os.path.join(split_dir, "images")
            for img_name in sorted(os.listdir(img_dir)):
                base, ext = os.path.splitext(img_name)
                if ext.lower() not in IMG_EXTS:
                    continue
                lbl = os.path.join(split_dir, "labels", base + ".txt")
                if not os.path.exists(lbl):
                    skipped[short]["no_label"] += 1
                    continue
                with open(lbl, encoding="utf-8", errors="ignore") as f:
                    lines = [r for r in (convert_line(l, mapping) for l in f) if r]
                if not lines:  # ما بقى فيها شي من فئاتنا
                    skipped[short]["empty"] += 1
                    continue
                img_path = os.path.join(img_dir, img_name)
                digest = file_hash(img_path)
                if digest in seen:  # نفس الصورة موجودة من قبل
                    skipped[short]["duplicate"] += 1
                    continue
                seen.add(digest)

                new_base = f"{short}_{base}"
                shutil.copy(img_path, os.path.join(output, split, "images", new_base + ext.lower()))
                with open(os.path.join(output, split, "labels", new_base + ".txt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(l for _, l in lines) + "\n")

                images[split] += 1
                for c in {c for c, _ in lines}:
                    stats[split][final[c]]["images"] += 1
                for c, _ in lines:
                    stats[split][final[c]]["boxes"] += 1

    data = {
        "path": os.path.abspath(output),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "nc": len(final),
        "names": final,
    }
    with open(os.path.join(output, "data.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    print("\n===== الإحصائية (عدد الصور / عدد المربعات لكل فئة) =====")
    print(f"{'split':<7}{'class':<20}{'images':>8}{'boxes':>8}")
    for s in ("train", "valid", "test"):
        for n in final.values():
            print(f"{s:<7}{n:<20}{stats[s][n]['images']:>8}{stats[s][n]['boxes']:>8}")
        print(f"{s:<7}{'(كل الصور)':<20}{images[s]:>8}")
    print("-" * 43)
    for short, d in skipped.items():
        print(f"[{short}] تخطينا: فاضية بعد الحذف {d['empty']} | مكررة {d['duplicate']} | بدون label {d['no_label']}")
    for n in final.values():
        if stats["train"][n]["boxes"] == 0:
            print(f"تنبيه: الفئة {n} ما لها أي صورة في train")
    if images["test"] == 0:
        print("تنبيه: ما فيه صور test، التقييم بيكون على valid")
    if 2 not in final:
        print("تنبيه: ما فيه داتا سيارات مهجورة، الموديل بيتدرب على فئتين بس")

    summary = {"classes": final, "per_split": stats, "images_per_split": dict(images), "skipped": skipped}
    with open(os.path.join(output, "merge_stats.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nتم. data.yaml: {os.path.join(output, 'data.yaml')}")
    return summary


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("الاستخدام: python merge_datasets.py output_dir smart=path1 dump=path2 [dead=path3]")
    srcs = [tuple(a.split("=", 1)) for a in sys.argv[2:]]
    merge(srcs, sys.argv[1])
