#!/usr/bin/env python3
"""run.py — FY114 藥物辨識子系統 UI 程序

負責：Tkinter GUI、相機拍攝、抽屜感測、驗證填報、紀錄儲存。
AI 推論由 api.py 負責，透過 HTTP 溝通。

啟動順序：先啟動 api.py，再啟動 run.py。

替換模型請修改 utils/models.py 中的對應類別。
"""

import argparse
import tkinter as tk

from utils.ui import App


def main():
    parser = argparse.ArgumentParser(description="FY114 藥物辨識子系統 UI")
    parser.add_argument("--fullscreen", action="store_true",
                        help="全螢幕模式（觸控螢幕）")
    parser.add_argument("--api", default="http://localhost:5000",
                        help="推論 API 伺服器位址（預設：http://localhost:5000）")
    parser.add_argument("--debug", action="store_true",
                        help="除錯模式：跳過相機、感測器與 API，以樣本圖作為測試輸入")
    args = parser.parse_args()

    if args.debug:
        print("[init] Debug mode ON: camera, LED and API will be skipped")
    else:
        print(f"[init] API endpoint: {args.api}")

    print("[init] Starting GUI...")
    root = tk.Tk()
    App(root, api_url=args.api, fullscreen=args.fullscreen, debug=args.debug)
    root.mainloop()


if __name__ == "__main__":
    main()
