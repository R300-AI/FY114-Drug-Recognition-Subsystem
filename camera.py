"""
camera.py — White balance calibration capture tool for Logitech C270.

Disables AWB and auto-exposure, provides a live diagnostic dashboard to find
the WB temperature + exposure combination that yields a neutral gray background.

Keys:
    SPACE   Capture and save frame to captures/
    S       Save current settings to camera_settings.json (auto-loaded next run)
    Q       Quit
"""
from __future__ import annotations

import json
import sys
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np


# ── Configuration ─────────────────────────────────────────────────────────────
DEVICE_ID     = 0
BACKEND       = cv2.CAP_DSHOW     # DirectShow (Windows). Try CAP_MSMF if this fails.
FRAME_W       = 1280
FRAME_H       = 720
TARGET_GRAY   = 128.0
STABILITY_N   = 30                # frames in rolling-std window

OUTPUT_DIR    = Path("captures")
SETTINGS_FILE = Path("camera_settings.json")

WB_RANGE      = (2800, 6500)      # Kelvin
EXP_RANGE     = (-13, -1)         # DirectShow log2 scale
GAIN_RANGE    = (0, 255)
BRIGHT_RANGE  = (0, 255)
CONT_RANGE    = (0, 255)

WIN_PREV      = "Preview — WB Calibration"
WIN_CTRL      = "Controls"
TB_WB         = "WB Temp (2800-6500 K)"
TB_EXP        = "Exposure  (-13 to -1)"
TB_GAIN       = "Gain"
TB_BRIG       = "Brightness"
TB_CONT       = "Contrast"

_PANEL_H      = 150


# ── Camera ────────────────────────────────────────────────────────────────────
def open_camera() -> cv2.VideoCapture:
    cap = cv2.VideoCapture(DEVICE_ID, BACKEND)
    if not cap.isOpened():
        sys.exit(f"Camera {DEVICE_ID} not found. Check DEVICE_ID or BACKEND.")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)
    return cap


def apply_settings(cap: cv2.VideoCapture,
                   wb: int, exp: int, gain: int, bright: int, cont: int) -> dict:
    return {
        "awb_off":    cap.set(cv2.CAP_PROP_AUTO_WB,        0),
        "wb_temp":    cap.set(cv2.CAP_PROP_WB_TEMPERATURE,  wb),
        "auto_exp":   cap.set(cv2.CAP_PROP_AUTO_EXPOSURE,   0.25),
        "exposure":   cap.set(cv2.CAP_PROP_EXPOSURE,        exp),
        "gain":       cap.set(cv2.CAP_PROP_GAIN,            gain),
        "brightness": cap.set(cv2.CAP_PROP_BRIGHTNESS,      bright),
        "contrast":   cap.set(cv2.CAP_PROP_CONTRAST,        cont),
    }


# ── Controls window ────────────────────────────────────────────────────────────
def _load_defaults() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        pass
    # trackbar positions (not raw values)
    return {"wb": 50, "exp": 7, "gain": 0, "bright": 128, "cont": 128}


def init_controls() -> None:
    d = _load_defaults()
    cv2.namedWindow(WIN_CTRL, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN_CTRL, 440, 230)
    noop = lambda _: None
    cv2.createTrackbar(TB_WB,   WIN_CTRL, d["wb"],   100, noop)
    cv2.createTrackbar(TB_EXP,  WIN_CTRL, d["exp"],   12, noop)
    cv2.createTrackbar(TB_GAIN, WIN_CTRL, d["gain"], 255, noop)
    cv2.createTrackbar(TB_BRIG, WIN_CTRL, d["bright"], 255, noop)
    cv2.createTrackbar(TB_CONT, WIN_CTRL, d["cont"],  255, noop)


def read_controls() -> tuple[int, int, int, int, int]:
    g   = lambda name: cv2.getTrackbarPos(name, WIN_CTRL)
    wb  = WB_RANGE[0]  + g(TB_WB)  * (WB_RANGE[1]  - WB_RANGE[0])  // 100
    exp = EXP_RANGE[0] + g(TB_EXP)
    return wb, exp, g(TB_GAIN), g(TB_BRIG), g(TB_CONT)


def save_settings(wb: int, exp: int, gain: int, bright: int, cont: int) -> None:
    g = lambda name: cv2.getTrackbarPos(name, WIN_CTRL)
    payload = {
        "wb": g(TB_WB), "exp": g(TB_EXP),
        "gain": gain, "bright": bright, "cont": cont,
        "_wb_kelvin": wb, "_exposure_log2": exp,
    }
    SETTINGS_FILE.write_text(json.dumps(payload, indent=2))
    print(f"Settings saved → {SETTINGS_FILE}  (WB={wb}K, Exp={exp})")


# ── Statistics ────────────────────────────────────────────────────────────────
def frame_stats(rgb: np.ndarray) -> dict:
    """Full-frame mean RGB (correct when no pills present — just the gray card)."""
    mean  = rgb.reshape(-1, 3).mean(axis=0).astype(float)  # [R, G, B]
    scale = TARGET_GRAY / np.clip(mean, 1.0, None)
    return {
        "rgb":         mean,
        "scale":       scale,
        "neutral_dev": float(np.max(np.abs(mean - mean.mean()))),
        "brightness":  float(mean.mean()),
    }


# ── Overlay ───────────────────────────────────────────────────────────────────
# BGR colours for R / G / B channel indicators
_CH_BGR   = [(0, 60, 220), (0, 190, 0), (210, 60, 0)]
_CH_LABEL = ["R", "G", "B"]


def _bar(canvas, x0, y, width, value, max_val, color, *, centered=False):
    """Draw a filled progress bar or centred deviation bar."""
    cv2.rectangle(canvas, (x0, y - 9), (x0 + width, y + 7), (45, 45, 45), -1)
    if centered:
        cx   = x0 + width // 2
        fill = int(min(abs(value) / max_val, 1.0) * (width // 2))
        cv2.line(canvas, (cx, y - 9), (cx, y + 7), (100, 100, 100), 1)
        if value >= 0:
            cv2.rectangle(canvas, (cx, y - 9), (cx + fill, y + 7), color, -1)
        else:
            cv2.rectangle(canvas, (cx - fill, y - 9), (cx, y + 7), color, -1)
    else:
        fill = int(min(abs(value) / max_val, 1.0) * width)
        cv2.rectangle(canvas, (x0, y - 9), (x0 + fill, y + 7), color, -1)


def draw_overlay(frame_bgr: np.ndarray, stats: dict, std_rgb: np.ndarray,
                 wb: int, exp: int, awb_disabled: bool) -> np.ndarray:
    out = frame_bgr.copy()
    h, w = out.shape[:2]
    F    = cv2.FONT_HERSHEY_SIMPLEX
    DIM  = (155, 155, 155)

    # Dark panel
    overlay = out.copy()
    cv2.rectangle(overlay, (0, h - _PANEL_H), (w, h), (12, 12, 12), -1)
    cv2.addWeighted(overlay, 0.72, out, 0.28, 0, out)

    y0 = h - _PANEL_H + 22

    # ── Colour swatch (what the camera currently "sees") ──────────────────
    r, g, b = stats["rgb"]
    cv2.rectangle(out, (10, y0 - 18), (72, y0 + 100), (int(b), int(g), int(r)), -1)
    cv2.rectangle(out, (10, y0 - 18), (72, y0 + 100), (160, 160, 160), 1)
    tg = int(TARGET_GRAY)
    cv2.rectangle(out, (76, y0 + 70), (92, y0 + 100), (tg, tg, tg), -1)
    cv2.putText(out, "target", (76, y0 + 67), F, 0.30, DIM, 1)

    # ── Per-channel centred deviation bars ───────────────────────────────
    bx, bw = 100, 130
    for i, (ch_val, col, lbl) in enumerate(zip(stats["rgb"], _CH_BGR, _CH_LABEL)):
        by  = y0 + i * 28
        dev = ch_val - TARGET_GRAY
        _bar(out, bx, by, bw, dev, TARGET_GRAY, col, centered=True)
        cv2.putText(out, f"{lbl} {ch_val:5.1f}  ×{stats['scale'][i]:.3f}",
                    (bx + bw + 8, by + 5), F, 0.42, col, 1)

    # ── Neutral deviation (colour cast indicator) ─────────────────────────
    nd    = stats["neutral_dev"]
    nd_col = (0, 210, 0) if nd < 6 else (0, 170, 255) if nd < 15 else (0, 40, 240)
    by_nd = y0 + 94
    _bar(out, bx, by_nd, 200, nd, 40.0, nd_col)
    cv2.putText(out, f"Neutral dev  {nd:4.1f}  (goal < 6)",
                (bx, by_nd - 12), F, 0.40, DIM, 1)

    # ── Stability (rolling std) ───────────────────────────────────────────
    std_m  = float(std_rgb.mean())
    st_col = (0, 210, 0) if std_m < 2 else (0, 170, 255) if std_m < 5 else (0, 40, 240)
    by_st  = by_nd + 28
    _bar(out, bx, by_st, 200, std_m, 10.0, st_col)
    cv2.putText(out, f"Stability σ  {std_m:4.2f}  (goal < 2)",
                (bx, by_st - 12), F, 0.40, DIM, 1)

    # ── Right panel: settings + hint ─────────────────────────────────────
    rx = 400
    cv2.putText(out, f"WB {wb} K     Exp {exp}",
                (rx, y0 + 6), F, 0.50, (210, 210, 210), 1)
    cv2.putText(out, f"Brightness {stats['brightness']:5.1f}",
                (rx, y0 + 28), F, 0.43, DIM, 1)

    if not awb_disabled:
        cv2.putText(out, "WARNING: AWB still active (driver may not support manual WB)",
                    (rx, y0 + 52), F, 0.40, (0, 50, 240), 1)
    elif nd > 6:
        if r > b:
            hint = "Image is warm (R>B) — try increasing WB temperature K"
        else:
            hint = "Image is cool (B>R) — try decreasing WB temperature K"
        cv2.putText(out, hint, (rx, y0 + 52), F, 0.41, (0, 195, 255), 1)
    else:
        cv2.putText(out, "Balance OK — colour cast within target",
                    (rx, y0 + 52), F, 0.41, (0, 210, 0), 1)

    cv2.putText(out, "SPACE capture   S save settings   Q quit",
                (rx, y0 + 106), F, 0.39, (110, 110, 110), 1)

    return out


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    cap = open_camera()
    init_controls()

    cv2.namedWindow(WIN_PREV, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN_PREV, FRAME_W, FRAME_H)

    buf:         deque[list]    = deque(maxlen=STABILITY_N)
    prev_ctrl:   tuple | None   = None
    awb_disabled: bool          = False

    print("Camera opened. Adjust sliders in the Controls window.")
    print("Place the gray card in view, then tune WB until Neutral dev < 6.")

    while True:
        ctrl = read_controls()
        if ctrl != prev_ctrl:
            result       = apply_settings(cap, *ctrl)
            awb_disabled = result["awb_off"] and result["wb_temp"]
            prev_ctrl    = ctrl

        ret, frame = cap.read()
        if not ret:
            continue

        rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        stats = frame_stats(rgb)
        buf.append(stats["rgb"].tolist())
        std_rgb = np.std(np.array(buf), axis=0) if len(buf) > 3 else np.zeros(3)

        display = draw_overlay(frame, stats, std_rgb, ctrl[0], ctrl[1], awb_disabled)
        cv2.imshow(WIN_PREV, display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord(" "):
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = OUTPUT_DIR / f"{ts}.jpg"
            cv2.imwrite(str(path), frame)
            print(f"Saved {path}  "
                  f"R={stats['rgb'][0]:.1f} G={stats['rgb'][1]:.1f} B={stats['rgb'][2]:.1f}  "
                  f"dev={stats['neutral_dev']:.1f}  σ={float(std_rgb.mean()):.2f}")
        elif key == ord("s"):
            save_settings(*ctrl)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
