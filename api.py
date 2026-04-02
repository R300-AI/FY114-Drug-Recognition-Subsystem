#!/usr/bin/env python3
"""api.py — FY114 藥物辨識推論伺服器

Endpoint:
    POST /analyse     影像辨識（multipart form: image=<file>）

啟動:
    python api.py
"""

import base64
import csv

import cv2
import numpy as np
from flask import Flask, jsonify, request

# ── 檢測 DirectML (Ryzen iGPU) ──
import torch

_device = "cpu"
try:
    import torch_directml
    _device = torch_directml.device()
    print(f"[api] 🚀 DirectML GPU detected")
except ImportError:
    print("[api] torch-directml not installed, using CPU")
    print("[api] Install: pip install torch-directml")
except Exception as e:
    print(f"[api] DirectML unavailable ({e}), using CPU")

from utils.models import YOLODetector, ResNet34Encoder, Top1Matcher
from utils.gallery import Gallery

# ── 固定路徑 ──
_MODEL_PATH   = "src/best.pt"
_GALLERY_PATH = "src/gallery"
_DRUG_DB_PATH = "DrugTW2025.csv"

app = Flask(__name__)

# ── 啟動時載入（模組層級，gunicorn 每 worker 各載一次）──
def _load_drug_db() -> dict[str, dict]:
    db: dict[str, dict] = {}
    try:
        with open(_DRUG_DB_PATH, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                lic = row.get("許可證字號", "").strip()
                if lic:
                    db[lic] = {
                        "name_zh":   row.get("中文品名", ""),
                        "name_en":   row.get("英文品名", ""),
                        "shape":     row.get("形狀", ""),
                        "color":     row.get("顏色", ""),
                        "size":      row.get("外觀尺寸", ""),
                        "mark1":     row.get("標註一", ""),
                        "mark2":     row.get("標註二", ""),
                        "image_url": row.get("外觀圖檔連結", ""),
                    }
        print(f"[api] DrugTW2025: {len(db)} entries")
    except Exception as e:
        print(f"[api] Warning: DrugTW2025 load failed: {e}")
    return db

_drug_db = _load_drug_db()

_gallery = Gallery(_GALLERY_PATH)
_gallery.load()
print(f"[api] Gallery: {_gallery.size} entries")

_detector = YOLODetector(_MODEL_PATH, device=_device)
_encoder  = ResNet34Encoder()
_matcher  = Top1Matcher(_gallery)
print("[api] Ready")


# ── 輔助 ──
def _mask_to_b64(mask: np.ndarray | None) -> str:
    if mask is None:
        return ""
    _, buf = cv2.imencode(".png", (mask * 255).astype(np.uint8))
    return base64.b64encode(buf.tobytes()).decode("ascii")


# ── Endpoint ──
@app.route("/analyse", methods=["POST"])
def analyse():
    import time
    t0 = time.time()

    if "image" not in request.files:
        return jsonify({"error": "No image field"}), 400

    frame = cv2.imdecode(
        np.frombuffer(request.files["image"].read(), np.uint8),
        cv2.IMREAD_COLOR,
    )
    if frame is None:
        return jsonify({"error": "Cannot decode image"}), 400

    print(f"[api] image received  shape={frame.shape}", flush=True)

    print("[api] running YOLO detection...", flush=True)
    detections = list(_detector(frame))
    print(f"[api] YOLO done  pills={len(detections)}  "
          f"({time.time()-t0:.2f}s)", flush=True)

    pills = []
    for i, det in enumerate(detections):
        x1, y1, x2, y2 = det.bbox
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        print(f"[api]   [{i+1}/{len(detections)}] encoding+matching  "
              f"conf={det.confidence:.2f}  bbox={det.bbox}", flush=True)
        result = _matcher(_encoder(crop))

        # ── DEBUG: 輪流選擇 00008 和 00009 測試多類別功能 ──
        _debug_drug_list = [
            "衛署罕藥製字第000008號",
            "衛署罕藥製字第000009號",
        ]
        lic = _debug_drug_list[i % len(_debug_drug_list)]
        info  = _drug_db.get(lic, {})
        name  = info.get("name_zh", "未識別")
        score = 1.0
        print(f"[api]   [{i+1}/{len(detections)}] → {lic}  {name}  score={score}  [DEBUG alternate]", flush=True)

        pills.append({
            "bbox":           list(det.bbox),
            "mask_b64":       _mask_to_b64(det.mask),
            "confidence":     round(float(det.confidence), 4),
            "class_id":       int(det.class_id),
            "license_number": lic,
            "name":           name,
            "side":           0,
            "score":          score,
            "drug_info":      info,
        })

    print(f"[api] done  total={time.time()-t0:.2f}s  matched={len(pills)}", flush=True)
    return jsonify({"status": "ok", "pills": pills})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
