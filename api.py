#!/usr/bin/env python3
"""api.py — FY114 推論橋接伺服器

本服務作為 Raspberry Pi 展示機的推論橋接，將 /analyse 請求轉發至
FY115 平台的 Segment API 與 Encoder API。

Endpoint:
    POST /analyse     影像辨識（multipart form: image=<file>）
    GET  /healthz     健康檢查

啟動:
    python api.py \\
        --segment-url http://192.168.50.1:8001 \\
        --encoder-url http://192.168.50.1:8002
"""

import argparse
import io
import time

import cv2
import numpy as np
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# 由 __main__ 透過 argparse 設定
_SEGMENT_URL: str = "http://192.168.50.1:8001"
_ENCODER_URL: str = "http://192.168.50.1:8002"
_TIMEOUT: int = 30


# ── Endpoints ──

@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"})


@app.route("/analyse", methods=["POST"])
def analyse():
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

    # Step 1: Segment
    print("[api] calling Segment API...", flush=True)
    try:
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        seg_resp = requests.post(
            f"{_SEGMENT_URL}/v1/segment/predict",
            files={"file": ("frame.jpg", io.BytesIO(buf.tobytes()), "image/jpeg")},
            data={"confidence": "0.25"},
            timeout=_TIMEOUT,
        )
        seg_resp.raise_for_status()
        seg_data = seg_resp.json()
    except requests.exceptions.RequestException as e:
        print(f"[api] Segment API error: {e}", flush=True)
        return jsonify({"error": f"Segment API unreachable: {e}"}), 503

    raw_dets = seg_data.get("detections", [])
    print(f"[api] Segment done  pills={len(raw_dets)}  ({time.time()-t0:.2f}s)", flush=True)

    pills = []
    for i, det in enumerate(raw_dets):
        x1, y1, x2, y2 = det["bbox"]
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        print(f"[api]   [{i+1}/{len(raw_dets)}] encoding  bbox={det['bbox']}", flush=True)

        # Step 2: Encode crop
        try:
            _, cbuf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
            enc_resp = requests.post(
                f"{_ENCODER_URL}/v1/encoder/encode",
                files={"file": ("crop.jpg", io.BytesIO(cbuf.tobytes()), "image/jpeg")},
                timeout=_TIMEOUT,
            )
            enc_resp.raise_for_status()
            enc_data = enc_resp.json()
        except requests.exceptions.RequestException as e:
            print(f"[api]   [{i+1}] Encoder API error: {e}", flush=True)
            continue

        results = enc_data.get("results", [])
        if not results:
            continue

        top1 = results[0]
        lic   = top1.get("許可證字號", "")
        name  = top1.get("中文品名", "未識別")
        score = float(top1.get("score", 0.0))
        print(f"[api]   [{i+1}/{len(raw_dets)}] → {lic}  {name}  score={score:.4f}", flush=True)

        pills.append({
            "bbox":           det["bbox"],
            "mask_b64":       "",  # 遮罩未請求（UI 自動忽略）
            "confidence":     round(float(det["confidence"]), 4),
            "class_id":       int(det["class_id"]),
            "license_number": lic,
            "name":           name,
            "side":           0,
            "score":          round(score, 4),
            "drug_info": {
                "name_zh":   top1.get("中文品名", ""),
                "name_en":   top1.get("英文品名", ""),
                "shape":     top1.get("形狀", ""),
                "color":     top1.get("顏色", ""),
                "size":      top1.get("外觀尺寸", ""),
                "mark1":     top1.get("標註一", ""),
                "mark2":     top1.get("標註二", ""),
                "image_url": top1.get("外觀圖檔連結", ""),
            },
        })

    print(f"[api] done  total={time.time()-t0:.2f}s  matched={len(pills)}", flush=True)
    return jsonify({"status": "ok", "pills": pills})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="FY114 推論橋接伺服器",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--segment-url", default="http://192.168.50.1:8001",
        help="Segment API 位址",
    )
    parser.add_argument(
        "--encoder-url", default="http://192.168.50.1:8002",
        help="Encoder API 位址",
    )
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="HTTP 請求逾時秒數",
    )
    parser.add_argument(
        "--port", type=int, default=5000,
        help="本機監聽埠",
    )
    args = parser.parse_args()

    _SEGMENT_URL = args.segment_url
    _ENCODER_URL = args.encoder_url
    _TIMEOUT = args.timeout

    print(f"[api] Segment URL : {_SEGMENT_URL}", flush=True)
    print(f"[api] Encoder URL : {_ENCODER_URL}", flush=True)
    print(f"[api] Timeout     : {_TIMEOUT}s", flush=True)
    print(f"[api] Listening on port {args.port}", flush=True)

    app.run(host="0.0.0.0", port=args.port)
