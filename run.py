#!/usr/bin/env python3
"""run.py — FY115 藥物辨識子系統 UI 程序

負責：Tkinter GUI、相機拍攝、抽屜感測、驗證填報、紀錄儲存。
AI 推論直接呼叫 AI Search Platform 的 Segment API 與 Encoder API。
所有可調整參數請修改同目錄的 config.yaml；命令列引數可覆蓋個別設定。
"""

import argparse
import tkinter as tk
from pathlib import Path

try:
    import yaml
    _cfg_path = Path(__file__).parent / "config.yaml"
    _cfg = yaml.safe_load(_cfg_path.read_text(encoding="utf-8")) if _cfg_path.exists() else {}
except ImportError:
    _cfg = {}

from utils.ui import App


def main():
    _api_cfg    = _cfg.get("api", {})
    _camera_cfg = _cfg.get("camera", {})
    _light_cfg  = _cfg.get("light", {})

    parser = argparse.ArgumentParser(description="FY115 藥物辨識子系統 UI")

    # ── 執行模式 ──────────────────────────────────────────────
    parser.add_argument("--fullscreen", action="store_true",
                        help="全螢幕模式（觸控螢幕）")
    parser.add_argument("--debug", action="store_true",
                        help="除錯模式：跳過相機、感測器與 API，以樣本圖作為測試輸入，並產生假辨識結果")
    parser.add_argument("--demo", action="store_true",
                        help="展示模式：跳過不可用的硬體，但仍呼叫真實 API 推論")
    parser.add_argument("--default-correct", dest="default_correct",
                        action="store_true", default=True,
                        help="預設辨識結果為正確（預設：啟用）")
    parser.add_argument("--no-default-correct", dest="default_correct",
                        action="store_false",
                        help="不預設辨識結果為正確（需使用者手動選擇）")
    parser.add_argument("--no-excel-export", dest="excel_export",
                        action="store_false", default=True,
                        help="停用 Excel 問卷自動填寫功能")

    # ── API 連線（預設讀自 config.yaml） ──────────────────────
    parser.add_argument("--segment-url",
                        default=_api_cfg.get("segment_url", "http://192.168.50.1:8001"),
                        help="影像切割服務位址")
    parser.add_argument("--encoder-url",
                        default=_api_cfg.get("encoder_url", "http://192.168.50.1:8002"),
                        help="特徵比對服務位址")
    parser.add_argument("--timeout", type=int,
                        default=_api_cfg.get("timeout", 30),
                        help="HTTP 逾時秒數")

    # ── 相機（預設讀自 config.yaml） ──────────────────────────
    parser.add_argument("--camera-index", type=int,
                        default=_camera_cfg.get("device_index", 0),
                        help="USB 相機裝置索引（/dev/video0 → 0）")
    parser.add_argument("--rotation", type=int, choices=[0, 90, 180, 270],
                        default=_camera_cfg.get("rotation", 0),
                        help="影像順時針旋轉角度：0 / 90 / 180 / 270")

    args = parser.parse_args()

    # 不透過 argparse 的相機與燈光參數直接從 config 讀取
    camera_width   = _camera_cfg.get("width", 1280)
    camera_height  = _camera_cfg.get("height", 720)
    camera_warmup  = _camera_cfg.get("warmup_frames", 20)
    camera_capture_warmup = _camera_cfg.get("capture_warmup_frames", 5)
    camera_backend = _camera_cfg.get("backend", "auto")

    _cc_cfg = _cfg.get("color_correction", {})
    cc_enabled      = _cc_cfg.get("enabled", False)
    cc_wb           = tuple(_cc_cfg.get("white_balance", [1.0, 1.0, 1.0])) if cc_enabled else None
    cc_wb_temp      = _cc_cfg.get("wb_temperature", None) if cc_enabled else None

    light_gpio       = _light_cfg.get("gpio_pin", 18)
    light_count      = _light_cfg.get("led_count", 24)
    light_order      = _light_cfg.get("pixel_order", "GRB")
    light_brightness = _light_cfg.get("brightness", 1.0)
    light_color_on   = tuple(_light_cfg.get("color_on",  [255, 255, 255]))
    light_color_off  = tuple(_light_cfg.get("color_off", [0, 0, 0]))

    if args.debug:
        print("[init] Debug mode ON: camera, LED and API will be skipped")
    elif args.demo:
        print("[init] Demo mode ON: hardware fallback enabled, API inference active")
    else:
        print(f"[init] Segment URL : {args.segment_url}")
        print(f"[init] Encoder URL : {args.encoder_url}")
        print(f"[init] Timeout     : {args.timeout}s")
        print(f"[init] Camera      : index={args.camera_index}  {camera_width}x{camera_height}"
              f"  backend={camera_backend}  rotation={args.rotation}°")
        print(f"[init] Light       : GPIO{light_gpio}  {light_count}LED  order={light_order}")

    print(f"[init] Default verification: {'Correct' if args.default_correct else 'Not selected'}")
    print(f"[init] Excel export: {'Enabled' if args.excel_export else 'Disabled'}")
    print("[init] Starting GUI...")

    root = tk.Tk()
    App(root,
        segment_url=args.segment_url,
        encoder_url=args.encoder_url,
        timeout=args.timeout,
        fullscreen=args.fullscreen,
        debug=args.debug,
        demo=args.demo,
        default_verification=True if args.default_correct else None,
        enable_excel_export=args.excel_export,
        camera_index=args.camera_index,
        camera_width=camera_width,
        camera_height=camera_height,
        camera_warmup_frames=camera_warmup,
        camera_capture_warmup_frames=camera_capture_warmup,
        camera_backend=camera_backend,
        camera_rotation=args.rotation,
        color_correction_wb=cc_wb,
        color_correction_wb_temp=cc_wb_temp,
        light_gpio_pin=light_gpio,
        light_led_count=light_count,
        light_pixel_order=light_order,
        light_brightness=light_brightness,
        light_color_on=light_color_on,
        light_color_off=light_color_off)
    root.mainloop()


if __name__ == "__main__":
    main()
