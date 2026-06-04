"""utils/analyser.py — AI 推論管線

將相機幀直接送至 AI Search Platform 的 Segment API 與 Encoder API，
回傳結構化的辨識結果。由 ui.py 的 _call_api() 呼叫，不需要本機 Flask 橋接服務。

主要函式：
    analyse(frame, segment_url, encoder_url, timeout)  → dict
    check_reachable(segment_url, encoder_url, timeout)  → None（失敗時 raise）
"""

import base64
import io
import time

import cv2
import numpy as np
import requests


# ── mask 工具 ─────────────────────────────────────────────────

def _rle_to_mask(rle: dict) -> np.ndarray | None:
    """將 RLE 格式（Segment API 回傳）解碼為 0/1 二值 numpy mask。

    格式：{"size": [H, W], "counts": [run0, run1, ...]}
    counts[0] 從值 0 開始，交替代表 0 和 1 的連續長度。
    """
    try:
        h, w = rle["size"]
        flat = np.zeros(h * w, dtype=np.uint8)
        pos, val = 0, 0
        for run_len in rle["counts"]:
            if val == 1:
                flat[pos:pos + run_len] = 1
            pos += run_len
            val ^= 1
        return flat.reshape(h, w)
    except Exception as e:
        print(f"[analyser] RLE decode failed: {e}", flush=True)
        return None


def _mask_to_b64(mask: np.ndarray | None) -> str:
    """將 0/1 二值 mask 轉為 PNG base64 字串（供 ui.py 解碼疊加顯示）。"""
    if mask is None:
        return ""
    _, buf = cv2.imencode(".png", (mask * 255).astype(np.uint8))
    return base64.b64encode(buf.tobytes()).decode("ascii")


def analyse(
    frame: np.ndarray,
    segment_url: str,
    encoder_url: str,
    timeout: int = 30,
) -> dict:
    """Segment → Match 推論管線。

    Args:
        frame:        BGR 影像（H,W,3 uint8）
        segment_url:  Segment API 根位址，例如 http://192.168.50.1:8001
        encoder_url:  Matcher API 根位址，例如 http://192.168.50.1:8002
        timeout:      每次 HTTP 請求的逾時秒數

    Returns:
        {"status": "ok", "pills": [...]}, 格式與原 api.py /analyse 端點相同。

    Raises:
        requests.RequestException: 任一 API 無法連線或回傳非 2xx 時。
    """
    t0 = time.time()

    # ── Step 1: Segment ──────────────────────────────────────────
    print("[analyser] calling Segment API...", flush=True)
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    seg_resp = requests.post(
        f"{segment_url.rstrip('/')}/v1/segment/predict",
        files={"file": ("frame.jpg", io.BytesIO(buf.tobytes()), "image/jpeg")},
        data={"confidence": "0.25", "include_mask_rle": "true"},
        timeout=timeout,
    )
    seg_resp.raise_for_status()
    seg_data = seg_resp.json()

    raw_dets = seg_data.get("detections", [])
    print(
        f"[analyser] Segment done  pills={len(raw_dets)}  ({time.time()-t0:.2f}s)",
        flush=True,
    )

    # ── Step 2: Encode + Match ────────────────────────────────────
    pills: list[dict] = []
    for i, det in enumerate(raw_dets):
        x1, y1, x2, y2 = det["bbox"]
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue

        print(
            f"[analyser]   [{i+1}/{len(raw_dets)}] encoding  bbox={det['bbox']}",
            flush=True,
        )

        try:
            _, cbuf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
            enc_resp = requests.post(
                f"{encoder_url.rstrip('/')}/v1/matcher/search",
                files={"file": ("crop.jpg", io.BytesIO(cbuf.tobytes()), "image/jpeg")},
                timeout=timeout,
            )
            enc_resp.raise_for_status()
            enc_data = enc_resp.json()
        except requests.RequestException as e:
            print(f"[analyser]   [{i+1}] Matcher API error: {e}", flush=True)
            continue

        results = enc_data.get("results", [])
        if not results:
            continue

        top1  = results[0]
        lic   = top1.get("license_no", "")
        name  = top1.get("name_en", "") or top1.get("name_zh", "未識別")
        score = float(top1.get("score", 0.0))
        print(
            f"[analyser]   [{i+1}/{len(raw_dets)}] → {lic}  {name}  score={score:.4f}",
            flush=True,
        )

        pills.append({
            "bbox":           det["bbox"],
            "mask_b64":       _mask_to_b64(_rle_to_mask(det["mask_rle"])) if det.get("mask_rle") else "",
            "confidence":     round(float(det["confidence"]), 4),
            "class_id":       int(det["class_id"]),
            "license_number": lic,
            "name":           name,
            "side":           0,
            "score":          round(score, 4),
            "drug_info": {
                "name_zh":   top1.get("name_zh", ""),
                "name_en":   top1.get("name_en", ""),
                "shape":     top1.get("shape", ""),
                "color":     top1.get("color", ""),
                "size":      top1.get("size_mm", ""),
                "mark1":     top1.get("mark1", ""),
                "mark2":     top1.get("mark2", ""),
                "image_url": top1.get("image_url", ""),
            },
        })

    print(
        f"[analyser] done  total={time.time()-t0:.2f}s  matched={len(pills)}",
        flush=True,
    )
    return {"status": "ok", "pills": pills}


def check_reachable(
    segment_url: str,
    encoder_url: str,
    timeout: int = 5,
) -> None:
    """確認 Segment API 與 Encoder API 皆可連線。

    Raises:
        requests.RequestException: 任一 API 無法連線時。
    """
    requests.get(f"{segment_url.rstrip('/')}/readyz", timeout=timeout).raise_for_status()
    requests.get(f"{encoder_url.rstrip('/')}/readyz", timeout=timeout).raise_for_status()
