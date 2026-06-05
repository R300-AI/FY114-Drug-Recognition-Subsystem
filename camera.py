"""
camera.py — White balance calibration capture tool for Logitech C270 (V4L2/Linux).

Disables AWB and sets manual WB temperature. Provides a live diagnostic dashboard
to find the SW RGB gain combination that yields a neutral gray background.

Keys:
    SPACE / 拍照按鈕   Capture and save frame to imgs/
    Q                  Quit
"""
from __future__ import annotations

import json
import sys
import threading
import tkinter as tk
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml
# ── Configuration ─────────────────────────────────────────────────────────────
DEVICE_ID     = 0
BACKEND       = cv2.CAP_V4L2
FRAME_W       = 640
FRAME_H       = 480
TARGET_GRAY   = 128.0
STABILITY_N   = 30                # frames in rolling-std window

OUTPUT_DIR    = Path("captures")
IMGS_DIR      = Path("imgs")
SETTINGS_FILE = Path("camera_settings.json")
CONFIG_FILE   = Path("config.yaml")


# V4L2 白平衡溫度範圍（v4l2-ctl 查詢 C270：min=0 max=10000 step=10）
WB_RANGE      = (0, 10000)

WIN_PREV      = "Preview — WB Calibration"
WIN_CTRL      = "Controls"
TB_WB         = "WB Temp (0-10000)"
TB_GAIN       = "Gain"
TB_BRIG       = "Brightness"
TB_CONT       = "Contrast"
TB_R          = "SW R (0~2x, 50=1x)"
TB_G          = "SW G (0~2x, 50=1x)"
TB_B          = "SW B (0~2x, 50=1x)"
SW_GAIN_RANGE = (0.0, 2.0)   # 0 → 0.0x, 50 → 1.0x, 100 → 2.0x

_PANEL_H      = 150


# ── Capture Button Panel ───────────────────────────────────────────────────────
class CapturePanel:
    """獨立 tkinter 視窗，提供拍照按鈕與狀態顯示。"""
    def __init__(self):
        self._frame_fn = None
        self._root = None
        self._status = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def register(self, fn):
        """fn() 回傳目前已校正的 BGR frame。"""
        self._frame_fn = fn

    def _run(self):
        self._root = tk.Tk()
        self._root.title("拍照")
        self._root.geometry("220x100")
        self._root.resizable(False, False)
        self._root.attributes("-topmost", True)
        self._status = tk.StringVar(value="按下按鈕或 SPACE 拍照")
        tk.Button(
            self._root, text="📷  拍照存入 imgs/",
            font=("Sans", 12, "bold"), bg="#d8f1d8",
            command=self._capture, pady=8,
        ).pack(fill=tk.X, padx=12, pady=(14, 4))
        tk.Label(
            self._root, textvariable=self._status,
            font=("Sans", 9), fg="#555",
        ).pack()
        self._root.mainloop()

    def _capture(self):
        if self._frame_fn is None:
            return
        frame = self._frame_fn()
        if frame is None:
            self._status.set("相機尚未就緒")
            return
        IMGS_DIR.mkdir(exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = IMGS_DIR / f"{ts}.jpg"
        cv2.imwrite(str(path), frame)
        self._status.set(f"已存入 {path.name}")
        print(f"[capture] {path}")

    def set_status(self, msg: str):
        if self._status:
            self._status.set(msg)

    def destroy(self):
        if self._root:
            try:
                self._root.quit()
            except Exception:
                pass


# ── LED ────────────────────────────────────────────────────────────────────────
def init_led():
    """讀取 config.yaml 的 light 設定，開啟 LED。如果無 LED 硬體或設定缺失則跳過。"""
    try:
        cfg = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
        light = cfg.get("light", {})
        import board, neopixel
        _ORDER_MAP = {"RGB": neopixel.RGB, "GRB": neopixel.GRB,
                      "RGBW": neopixel.RGBW, "GRBW": neopixel.GRBW}
        pin        = getattr(board, f"D{light.get('gpio_pin', 18)}")
        count      = light.get("led_count", 24)
        brightness = light.get("brightness", 1.0)
        order      = _ORDER_MAP.get(light.get("pixel_order", "GRB").upper(), neopixel.GRB)
        color_on   = tuple(light.get("color_on", [255, 255, 255]))
        pixels = neopixel.NeoPixel(pin, count, brightness=brightness, pixel_order=order)
        pixels.fill(color_on)
        print(f"[light] LED ON  gpio=D{light.get('gpio_pin', 18)}  count={count}")
        return pixels
    except Exception as e:
        print(f"[light] LED 無法啟動（{e}），校正在無燈模式下進行。")
        return None


# ── Camera ────────────────────────────────────────────────────────────────────
def open_camera() -> cv2.VideoCapture:
    cap = cv2.VideoCapture(DEVICE_ID, BACKEND)
    if not cap.isOpened():
        sys.exit(f"Camera {DEVICE_ID} not found. Check DEVICE_ID or BACKEND.")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)
    return cap


def apply_settings(cap: cv2.VideoCapture,
                   wb: int, gain: int, bright: int, cont: int) -> bool:
    """Apply V4L2 camera settings. Returns True if AWB was successfully disabled."""
    awb_off = cap.set(cv2.CAP_PROP_AUTO_WB, 0)
    cap.set(cv2.CAP_PROP_WB_TEMPERATURE, wb)
    cap.set(cv2.CAP_PROP_GAIN,           gain)
    cap.set(cv2.CAP_PROP_BRIGHTNESS,     bright)
    cap.set(cv2.CAP_PROP_CONTRAST,       cont)
    return bool(awb_off)


# ── Controls window ────────────────────────────────────────────────────────────
def _load_defaults() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        pass
    # trackbar positions (not raw values); wb=400 → 4000K (C270 default)
    return {"wb": 400, "gain": 0, "bright": 128, "cont": 128,
            "sw_r": 50, "sw_g": 50, "sw_b": 50}


def _tb_to_sw(pos: int) -> float:
    """Convert trackbar position 0-100 to SW gain 0.0-2.0 (50 → 1.0x)."""
    lo, hi = SW_GAIN_RANGE
    return lo + pos * (hi - lo) / 100


def init_controls() -> None:
    d = _load_defaults()
    cv2.namedWindow(WIN_CTRL, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN_CTRL, 560, 300)
    noop = lambda _: None
    cv2.createTrackbar(TB_WB,   WIN_CTRL, d["wb"],    1000, noop)  # 0-1000 → WB 0-10000
    cv2.createTrackbar(TB_GAIN, WIN_CTRL, d["gain"],   255, noop)
    cv2.createTrackbar(TB_BRIG, WIN_CTRL, d["bright"], 255, noop)
    cv2.createTrackbar(TB_CONT, WIN_CTRL, d["cont"],   255, noop)
    cv2.createTrackbar(TB_R,    WIN_CTRL, d.get("sw_r", 50), 100, noop)
    cv2.createTrackbar(TB_G,    WIN_CTRL, d.get("sw_g", 50), 100, noop)
    cv2.createTrackbar(TB_B,    WIN_CTRL, d.get("sw_b", 50), 100, noop)


def read_controls() -> tuple:
    """Returns (wb, gain, bright, cont, sw_gain)."""
    g  = lambda name: cv2.getTrackbarPos(name, WIN_CTRL)
    wb = g(TB_WB) * 10   # slider 0-1000 → V4L2 0-10000 step 10
    sw_gain = (_tb_to_sw(g(TB_R)), _tb_to_sw(g(TB_G)), _tb_to_sw(g(TB_B)))
    return wb, g(TB_GAIN), g(TB_BRIG), g(TB_CONT), sw_gain


def apply_sw_gain(frame_bgr: np.ndarray, sw_gain: tuple) -> np.ndarray:
    """Apply per-channel software gain (R, G, B) to a BGR frame."""
    r, g, b = sw_gain
    lut_r = np.clip(np.arange(256) * r, 0, 255).astype(np.uint8)
    lut_g = np.clip(np.arange(256) * g, 0, 255).astype(np.uint8)
    lut_b = np.clip(np.arange(256) * b, 0, 255).astype(np.uint8)
    out = frame_bgr.copy()
    out[:, :, 2] = lut_r[frame_bgr[:, :, 2]]  # R
    out[:, :, 1] = lut_g[frame_bgr[:, :, 1]]  # G
    out[:, :, 0] = lut_b[frame_bgr[:, :, 0]]  # B
    return out


def save_settings(wb: int, gain: int, bright: int, cont: int,
                  sw_gain: tuple) -> None:
    g = lambda name: cv2.getTrackbarPos(name, WIN_CTRL)
    r, gg, b = sw_gain
    payload = {
        "wb": g(TB_WB),
        "gain": gain, "bright": bright, "cont": cont,
        "sw_r": g(TB_R), "sw_g": g(TB_G), "sw_b": g(TB_B),
        "_wb_v4l2": wb,
        "_sw_gain_rgb": [round(r, 4), round(gg, 4), round(b, 4)],
    }
    SETTINGS_FILE.write_text(json.dumps(payload, indent=2))
    print(f"Settings saved → {SETTINGS_FILE}  "
          f"(WB={wb}, SW R={r:.3f} G={gg:.3f} B={b:.3f})")


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
                 wb: int, awb_disabled: bool) -> np.ndarray:
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
    cv2.putText(out, f"WB {wb}  (V4L2 0-10000)",
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

    cv2.putText(out, "SPACE capture   S save to JSON   Q quit",
                (rx, y0 + 106), F, 0.39, (110, 110, 110), 1)

    return out


def save_to_config(wb: int, sw_gain: tuple) -> None:
    """將白平衡設定寫入 config.yaml 的 color_correction 區塊。"""
    r, g, b = sw_gain
    try:
        lines = CONFIG_FILE.read_text(encoding="utf-8").splitlines() if CONFIG_FILE.exists() else []
        new_lines, in_block, replaced = [], False, False
        for line in lines:
            if line.startswith("color_correction:"):
                in_block = True
                new_lines.append("color_correction:")
                new_lines.append(f"  enabled: true")
                new_lines.append(f"  wb_temperature: {wb}")
                new_lines.append(f"  white_balance: [{r:.4f}, {g:.4f}, {b:.4f}]")
                replaced = True
                continue
            if in_block:
                if line and not line.startswith(" ") and not line.startswith("#"):
                    in_block = False
                    new_lines.append(line)
            else:
                new_lines.append(line)
        if not replaced:
            new_lines.append("color_correction:")
            new_lines.append(f"  enabled: true")
            new_lines.append(f"  wb_temperature: {wb}")
            new_lines.append(f"  white_balance: [{r:.4f}, {g:.4f}, {b:.4f}]")
        CONFIG_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"已存入 config.yaml  WB={wb} R={r:.4f} G={g:.4f} B={b:.4f}")
    except Exception as e:
        print(f"[config] save failed: {e}")





# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    IMGS_DIR.mkdir(exist_ok=True)
    led = init_led()          # 開啟 LED，確保和 run.py 相同光源
    cap = open_camera()
    init_controls()

    panel = CapturePanel()
    latest: list = [None]     # 最新已校正幀，供按鈕使用
    panel.register(lambda: latest[0])

    cv2.namedWindow(WIN_PREV, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN_PREV, FRAME_W, FRAME_H)

    buf:         deque[list]    = deque(maxlen=STABILITY_N)
    prev_ctrl:   tuple | None   = None
    awb_disabled: bool          = False

    print("Camera opened. Adjust sliders in the Controls window.")
    print("Place the gray card in view, then tune WB until Neutral dev < 6.")

    while True:
        # ctrl = (wb, gain, bright, cont, sw_gain)
        ctrl = read_controls()
        if ctrl != prev_ctrl:
            awb_disabled = apply_settings(cap, ctrl[0], ctrl[1], ctrl[2], ctrl[3])
            save_to_config(ctrl[0], ctrl[4])
            save_settings(ctrl[0], ctrl[1], ctrl[2], ctrl[3], ctrl[4])
            prev_ctrl = ctrl

        ret, frame = cap.read()
        if not ret:
            continue

        sw_gain = ctrl[4]
        frame_corrected = apply_sw_gain(frame, sw_gain)
        latest[0] = frame_corrected   # 更新按鈕可取用的最新幀

        rgb   = cv2.cvtColor(frame_corrected, cv2.COLOR_BGR2RGB)
        stats = frame_stats(rgb)
        buf.append(stats["rgb"].tolist())
        std_rgb = np.std(np.array(buf), axis=0) if len(buf) > 3 else np.zeros(3)

        r_g, g_g, b_g = sw_gain
        display = draw_overlay(frame_corrected, stats, std_rgb, ctrl[0], awb_disabled)
        cv2.putText(display, f"SW R={r_g:.2f} G={g_g:.2f} B={b_g:.2f}",
                    (400, display.shape[0] - _PANEL_H + 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 255), 1)
        cv2.imshow(WIN_PREV, display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord(" "):
            IMGS_DIR.mkdir(exist_ok=True)
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = IMGS_DIR / f"{ts}.jpg"
            cv2.imwrite(str(path), frame_corrected)
            msg = (f"Saved {path.name}  "
                   f"R={stats['rgb'][0]:.1f} G={stats['rgb'][1]:.1f} B={stats['rgb'][2]:.1f}  "
                   f"dev={stats['neutral_dev']:.1f}  \u03c3={float(std_rgb.mean()):.2f}")
            print(msg)
            panel.set_status(path.name)

    cap.release()
    cv2.destroyAllWindows()
    panel.destroy()
    if led:
        try:
            led.fill((0, 0, 0))
        except Exception:
            pass


if __name__ == "__main__":
    main()
