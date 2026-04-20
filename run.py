#!/usr/bin/env python3
"""run.py — FY115 藥物辨識子系統 UI 程序

負責：Tkinter GUI、相機拍攝、抽屜感測、驗證填報、紀錄儲存。
AI 推論直接呼叫 AI Search Platform 的 Segment API 與 Encoder API。
連線設定請修改同目錄的 api.yaml。
"""

import argparse
import tkinter as tk
from pathlib import Path

try:
    import yaml
    _cfg_path = Path(__file__).parent / "api.yaml"
    _cfg = yaml.safe_load(_cfg_path.read_text(encoding="utf-8")) if _cfg_path.exists() else {}
except ImportError:
    _cfg = {}

from utils.ui import App


def main():
    _segment_url = _cfg.get("segment_url", "http://192.168.50.1:8001")
    _encoder_url = _cfg.get("encoder_url", "http://192.168.50.1:8002")
    _timeout     = _cfg.get("timeout", 30)

    parser = argparse.ArgumentParser(description="FY115 藥物辨識子系統 UI")
    parser.add_argument("--fullscreen", action="store_true",
                        help="全螢幕模式（觸控螢幕）")
    parser.add_argument("--debug", action="store_true",
                        help="除錯模式：跳過相機、感測器與 API，以樣本圖作為測試輸入，並產生假辨識結果")
    parser.add_argument("--demo", action="store_true",
                        help="展示模式：跳過不可用的硬體，但仍呼叫真實 API 推論（硬體不完整時亦可自動發動）")
    parser.add_argument("--default-correct", dest="default_correct",
                        action="store_true", default=True,
                        help="預設辨識結果為正確（預設：啟用）")
    parser.add_argument("--no-default-correct", dest="default_correct",
                        action="store_false",
                        help="不預設辨識結果為正確（需使用者手動選擇）")
    parser.add_argument("--no-excel-export", dest="excel_export",
                        action="store_false", default=True,
                        help="停用 Excel 問卷自動填寫功能")
    args = parser.parse_args()

    if args.debug:
        print("[init] Debug mode ON: camera, LED and API will be skipped")
    elif args.demo:
        print("[init] Demo mode ON: hardware fallback enabled, API inference active")
    else:
        print(f"[init] Segment URL : {_segment_url}")
        print(f"[init] Encoder URL : {_encoder_url}")
        print(f"[init] Timeout     : {_timeout}s")

    print(f"[init] Default verification: {'Correct' if args.default_correct else 'Not selected'}")
    print(f"[init] Excel export: {'Enabled' if args.excel_export else 'Disabled'}")
    print("[init] Starting GUI...")
    root = tk.Tk()
    App(root,
        segment_url=_segment_url,
        encoder_url=_encoder_url,
        timeout=_timeout,
        fullscreen=args.fullscreen,
        debug=args.debug,
        demo=args.demo,
        default_verification=True if args.default_correct else None,
        enable_excel_export=args.excel_export)
    root.mainloop()


if __name__ == "__main__":
    main()
