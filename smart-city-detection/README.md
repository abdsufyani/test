# كشف مخالفات المدينة من الصور — YOLO26n

جزء الذكاء الاصطناعي من مشروع **Secure Opportunistic IoT Crowd Sensing for Sustainable Smart Cities**.
الموديل يكتشف مخالفات المدينة في الصور، والجهاز المستهدف NVIDIA Jetson Orin Nano Super.

## الفئات

| الرقم | الفئة | الحالة |
|---|---|---|
| 0 | `illegal_dumping` (نفايات مرمية) | مفعّلة |
| 1 | `road_damage` (حفر وأضرار طرق) | مفعّلة |
| 2 | `abandoned_vehicle` (سيارات مهجورة) | مؤجلة لعدم توفر داتا |

## الطريقة

نبدأ من الأوزان الجاهزة **YOLO26n** من Ultralytics ونسوي لها Fine-tuning على داتا مدمجة من مصدرين (ما ندرّب من الصفر).

ليش نسوي Fine-tuning؟ اختبرنا قبل:
- YOLO26n الجاهز يكتشف الأشخاص والسيارات بثقة 85% وأكثر، لكن ما يعرف النفايات ولا الحفر.
- YOLOE-26 (فئات بالنص بدون تدريب) ما كشف كومة نفايات واضحة، وما فرّق بين السيارة المهجورة والعادية.

## الملفات

| الملف | وش فيه |
|---|---|
| `merge_datasets.py` | يدمج المصدرين، يوحّد أرقام الفئات **حسب الاسم** من `data.yaml` حق كل مصدر، يحذف الفئات غير المطلوبة، يتخطى الصور اللي صارت فاضية، يحذف الصور المكررة بين المصادر، يحوّل الـ polygons إلى مربعات، ويكتب `data.yaml` جديد مع إحصائية |
| `train_yolo26n_colab.ipynb` | نوتبوك Colab كامل: تنزيل، دمج، تدريب مع resume، تقييم، رسومات، تحليل أخطاء |

## خطوات التشغيل (كلها مجانية)

1. سوّ حساب مجاني في [Roboflow](https://roboflow.com) وخذ الـ API key من Settings ← API Keys.
2. افتح `train_yolo26n_colab.ipynb` في [Google Colab](https://colab.research.google.com) (File ← Upload notebook).
3. Runtime ← Change runtime type ← **T4 GPU**.
4. (اختياري) حط المفتاح في Colab Secrets باسم `ROBOFLOW_API_KEY`. لو ما حطيته، النوتبوك بيطلبه منك.
5. شغّل الخلايا بالترتيب (Runtime ← Run all).

### لو انقطع Colab
- الداتا الخام ونقاط التدريب كلها محفوظة في Drive تحت `MyDrive/smart_city_detection/`.
- أعد تشغيل كل الخلايا من الأول. التنزيل ينتخطى لأن الداتا موجودة، والدمج يتعاد (لأنه على القرص المحلي)، والتدريب يكمل من `last.pt` بـ `resume=True`.
- لو 100 epoch طويلة على الحد المجاني، غيّر `EPOCHS = 50` **قبل أول تشغيل**.

### المخرجات (في `MyDrive/smart_city_detection/deliverables/`)
- `best.pt`
- `results_table.csv`: Precision و Recall و mAP50 و mAP50-95 لكل فئة على valid و test
- `results.png`: منحنيات التدريب
- `test_confusion_matrix*.png` و `test_BoxPR_curve.png` وغيرها
- `examples_success.png` و `examples_errors.png`: 6 صور نجاح و6 صور أخطاء
- `test_per_image_errors.csv`: TP و FP و FN لكل صورة test
- `merge_stats.json`: إحصائية الدمج

### تشغيل سكربت الدمج لحاله
```bash
pip install pyyaml
python merge_datasets.py --smartathon path/to/smartathon --dumping path/to/dumping --out merged
```
كل مجلد لازم يكون تصدير YOLO من Roboflow (فيه `data.yaml` ومجلدات `train/` و `valid/` و `test/`).
لو اسم فئة في جدول `MAPPING` مو موجود في `data.yaml`، السكربت يوقف ويطبع الأسماء الموجودة بدل ما يدمج غلط.

## مصادر الداتا والاستشهاد

المصدرين كلهم مرخصين **CC BY 4.0**، يعني لازم نذكر المصدر.

1. **Visual Pollution (Smartathon)**: 7981 صورة من شوارع السعودية فيها 11 فئة. أخذنا `GARBAGE` وحطيناها في الفئة 0، وأخذنا `POTHOLES` وحطيناها في الفئة 1، والباقي حذفناه.
   https://universe.roboflow.com/smartathon-n3kfm/visual-pollution-iojfm
2. **Illegal Dumping Detection 2**: 8879 صورة فيها فئتين. أخذنا `garbage` وحطيناها في الفئة 0، وحذفنا `person`.
   https://universe.roboflow.com/bill-lhxqf/illegal-dumping-detection-2/dataset/1
3. داتا سدايا: بتنضاف لاحقاً.

> عدد الصور فوق منقول من صفحات الداتا. العدد الفعلي بعد الدمج يطلع في إحصائية السكربت.

صيغة BibTeX (الصيغة اللي يقترحها Roboflow Universe، تأكد من السنة والعنوان من زر "Cite" في صفحة كل داتا):
```bibtex
@misc{visual-pollution-iojfm_dataset,
  title        = {Visual Pollution Dataset},
  author       = {Smartathon},
  howpublished = {\url{https://universe.roboflow.com/smartathon-n3kfm/visual-pollution-iojfm}},
  publisher    = {Roboflow},
  note         = {visited on 2026-10-21},
}
@misc{illegal-dumping-detection-2_dataset,
  title        = {Illegal Dumping Detection 2 Dataset},
  author       = {bill},
  howpublished = {\url{https://universe.roboflow.com/bill-lhxqf/illegal-dumping-detection-2}},
  publisher    = {Roboflow},
  note         = {visited on 2026-10-21},
}
@software{yolo26_ultralytics,
  title  = {Ultralytics YOLO26},
  author = {Ultralytics},  % تأكد من صيغة الاستشهاد الرسمية في docs.ultralytics.com
  url    = {https://github.com/ultralytics/ultralytics},
  license = {AGPL-3.0},
}
```

## ملاحظات
- رخصة Ultralytics هي **AGPL-3.0**. للاستخدام الأكاديمي ما فيه مشكلة، لكن لو بيصير منتج تجاري لازم تراجعون الرخصة.
- لو تبون تشغّلون على Jetson لاحقاً: `YOLO('best.pt').export(format='engine', half=True)` على الجهاز نفسه.
