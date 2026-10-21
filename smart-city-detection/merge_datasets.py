#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سكربت دمج داتا سيتات YOLO من عدة مصادر في مجلد واحد بفئات موحدة.

الفكرة:
- لكل مصدر نقرأ data.yaml حقه ونطلع أسماء الفئات منه (ما نعتمد على أرقام ثابتة،
  لأن ترتيب الفئات يختلف من داتا لداتا).
- نربط اسم الفئة الأصلي بالفئة الموحدة حسب جدول MAPPING، وأي فئة مو في الجدول تنحذف.
- الصور اللي ما بقى فيها ولا box بعد الحذف نتخطاها.
- نحذف الصور المكررة (نفس المحتوى بالضبط) بين المصادر عشان ما يصير تسريب بين train و test.
- نكتب data.yaml جديد ونطبع إحصائية لكل split ولكل فئة.

الاستخدام:
    python merge_datasets.py --smartathon /content/smartathon --dumping /content/dumping --out /content/merged
"""

import argparse
import hashlib
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import yaml

# الفئات الموحدة النهائية (abandoned_vehicle مؤجلة لعدم توفر داتا)
FINAL_NAMES = {0: "illegal_dumping", 1: "road_damage"}

# جدول الربط: اسم الفئة في المصدر (بحروف صغيرة) ← رقم الفئة الموحدة
# أي اسم غير موجود هنا يُحذف
MAPPING = {
    "smartathon": {"garbage": 0, "potholes": 1},
    "dumping": {"garbage": 0},
}

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
# أسماء مجلدات الـ splits في تصدير Roboflow ← الاسم الموحد عندنا
SPLIT_ALIASES = {"train": "train", "valid": "valid", "val": "valid", "test": "test"}


def load_names(dataset_root: Path) -> list:
    """يقرأ أسماء الفئات من data.yaml (يدعم الصيغة list أو dict)."""
    yaml_path = dataset_root / "data.yaml"
    if not yaml_path.exists():
        sys.exit(f"[خطأ] ما لقيت data.yaml في {dataset_root}")
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    names = data.get("names")
    if isinstance(names, dict):  # صيغة {0: name, 1: name}
        names = [names[k] for k in sorted(names, key=int)]
    if not names:
        sys.exit(f"[خطأ] data.yaml في {dataset_root} ما فيه names")
    return [str(n) for n in names]


def build_id_map(source: str, names: list) -> dict:
    """يحوّل جدول الأسماء إلى جدول أرقام: رقم الفئة الأصلي ← رقم الفئة الموحد."""
    wanted = MAPPING[source]
    lower = [n.strip().lower() for n in names]
    id_map = {}
    for name, new_id in wanted.items():
        if name not in lower:
            # نوقف بدل ما نكمل بدمج غلط
            sys.exit(f"[خطأ] الفئة '{name}' مو موجودة في {source}. الفئات الموجودة: {names}")
        id_map[lower.index(name)] = new_id
    print(f"[{source}] الفئات الأصلية: {names}")
    for old, new in sorted(id_map.items()):
        print(f"    {old} ({names[old]}) ← {new} ({FINAL_NAMES[new]})")
    dropped = [n for i, n in enumerate(names) if i not in id_map]
    print(f"    محذوفة: {dropped}")
    return id_map


def find_splits(dataset_root: Path) -> dict:
    """يدور على مجلدات train/valid/test اللي فيها images و labels."""
    splits = {}
    for d in dataset_root.iterdir():
        if d.is_dir() and d.name.lower() in SPLIT_ALIASES and (d / "images").is_dir():
            splits[SPLIT_ALIASES[d.name.lower()]] = d
    if not splits:
        sys.exit(f"[خطأ] ما لقيت مجلدات train/valid/test في {dataset_root}")
    return splits


def convert_line(line: str, id_map: dict):
    """
    يحوّل سطر label واحد. يرجع None لو الفئة محذوفة أو السطر تالف.
    لو السطر polygon (segmentation) نحوله إلى bbox.
    """
    parts = line.split()
    if len(parts) < 5:
        return None
    try:
        cls = int(float(parts[0]))
        vals = [float(v) for v in parts[1:]]
    except ValueError:
        return None
    if cls not in id_map:
        return None
    if len(vals) == 4:
        x, y, w, h = vals
    elif len(vals) >= 6 and len(vals) % 2 == 0:  # polygon: x1 y1 x2 y2 ...
        xs, ys = vals[0::2], vals[1::2]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        x, y, w, h = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
    else:
        return None
    # نقص القيم داخل حدود الصورة ونتخطى المربعات الصفرية
    x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    w, h = min(max(w, 0.0), 1.0), min(max(h, 0.0), 1.0)
    if w <= 0 or h <= 0:
        return None
    return id_map[cls], f"{id_map[cls]} {x:.6f} {y:.6f} {w:.6f} {h:.6f}"


def file_hash(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def merge(sources: dict, out: Path):
    if out.exists():
        shutil.rmtree(out)
    for s in ("train", "valid", "test"):
        (out / s / "images").mkdir(parents=True, exist_ok=True)
        (out / s / "labels").mkdir(parents=True, exist_ok=True)

    # stats[split][class] = {"images": n, "boxes": n}
    stats = defaultdict(lambda: defaultdict(lambda: {"images": 0, "boxes": 0}))
    images_per_split = defaultdict(int)
    skipped_empty = defaultdict(int)
    skipped_dup = defaultdict(int)
    missing_label = defaultdict(int)
    seen_hashes = {}

    for source, root in sources.items():
        root = Path(root)
        id_map = build_id_map(source, load_names(root))
        for split, split_dir in sorted(find_splits(root).items()):
            for img in sorted((split_dir / "images").iterdir()):
                if img.suffix.lower() not in IMG_EXTS:
                    continue
                lbl = split_dir / "labels" / (img.stem + ".txt")
                if not lbl.exists():
                    missing_label[source] += 1
                    continue
                converted = []
                for line in lbl.read_text(encoding="utf-8", errors="ignore").splitlines():
                    r = convert_line(line, id_map)
                    if r:
                        converted.append(r)
                if not converted:  # ما بقى فيها شي بعد الحذف
                    skipped_empty[source] += 1
                    continue
                digest = file_hash(img)
                if digest in seen_hashes:  # صورة مكررة بنفس المحتوى
                    skipped_dup[source] += 1
                    continue
                seen_hashes[digest] = f"{source}/{split}/{img.name}"

                # بادئة باسم المصدر عشان ما تتعارض أسماء الملفات
                new_stem = f"{source}_{img.stem}"
                shutil.copy2(img, out / split / "images" / (new_stem + img.suffix.lower()))
                (out / split / "labels" / (new_stem + ".txt")).write_text(
                    "\n".join(l for _, l in converted) + "\n", encoding="utf-8")

                images_per_split[split] += 1
                for c in {c for c, _ in converted}:
                    stats[split][c]["images"] += 1
                for c, _ in converted:
                    stats[split][c]["boxes"] += 1

    # data.yaml الجديد
    data = {
        "path": str(out.resolve()),
        "train": "train/images",
        "val": "valid/images",
        "test": "test/images",
        "nc": len(FINAL_NAMES),
        "names": FINAL_NAMES,
    }
    with open(out / "data.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    # الإحصائية
    print("\n================ إحصائية الداتا المدمجة ================")
    print(f"{'split':<7}{'class':<18}{'images':>8}{'boxes':>8}")
    for split in ("train", "valid", "test"):
        for c, name in FINAL_NAMES.items():
            s = stats[split][c]
            print(f"{split:<7}{name:<18}{s['images']:>8}{s['boxes']:>8}")
        print(f"{split:<7}{'(كل الصور)':<18}{images_per_split[split]:>8}")
    print("--------------------------------------------------------")
    for source in sources:
        print(f"[{source}] صور تخطيناها لأنها فاضية بعد الحذف: {skipped_empty[source]} | "
              f"مكررة: {skipped_dup[source]} | بدون label: {missing_label[source]}")
    if images_per_split["test"] == 0:
        print("[تنبيه] ما فيه صور test. لازم تقسم جزء من train يدوياً.")

    # نحفظ الإحصائية كـ JSON عشان النوتبوك والتقرير
    summary = {
        "per_split": {sp: {FINAL_NAMES[c]: dict(v) for c, v in stats[sp].items()} for sp in ("train", "valid", "test")},
        "images_per_split": dict(images_per_split),
        "skipped_empty": dict(skipped_empty),
        "skipped_duplicates": dict(skipped_dup),
        "missing_label": dict(missing_label),
    }
    (out / "merge_stats.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nتم. data.yaml: {out / 'data.yaml'}")


def main():
    ap = argparse.ArgumentParser(description="دمج داتا Smartathon و Illegal Dumping بفئات موحدة")
    ap.add_argument("--smartathon", required=True, help="مجلد Smartathon (تصدير YOLO من Roboflow)")
    ap.add_argument("--dumping", required=True, help="مجلد Illegal Dumping Detection 2")
    ap.add_argument("--out", required=True, help="مجلد الإخراج")
    args = ap.parse_args()
    merge({"smartathon": args.smartathon, "dumping": args.dumping}, Path(args.out))


if __name__ == "__main__":
    main()
