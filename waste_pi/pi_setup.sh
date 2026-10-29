#!/bin/bash
# pi_setup.sh — تجهيز Raspberry Pi 5 لتشغيل موديل كشف المخالفات
# يشتغل على Raspberry Pi OS (64-bit). التشغيل:  bash pi_setup.sh
set -e

echo "== 1) تحديث النظام =="
sudo apt update && sudo apt full-upgrade -y

echo "== 2) مكتبات الكاميرا والنظام =="
sudo apt install -y python3-picamera2 python3-venv python3-pip libgl1 rpicam-apps || \
sudo apt install -y python3-picamera2 python3-venv python3-pip libgl1 libcamera-apps

echo "== 3) بيئة بايثون (تشوف مكتبة الكاميرا من النظام) =="
python3 -m venv --system-site-packages ~/waste_env
source ~/waste_env/bin/activate
pip install --upgrade pip
pip install ultralytics ncnn requests

echo "== 4) فحص الكاميرا =="
if command -v rpicam-hello >/dev/null; then rpicam-hello --list-cameras; else libcamera-hello --list-cameras; fi

echo
echo "تم. كل مرة تفتح الجهاز فعّل البيئة بـ:"
echo "   source ~/waste_env/bin/activate"
