"""utils/ui.py — FY114 Tkinter GUI 應用程式

此模組包含完整的 Tkinter UI 邏輯：
  - App 類別（主視窗、相機、分析流水線、填報邏輯）
  - 所有 UI 常數（顏色、字體）
  - 資料類別（PillEntry、VerificationState）
  - 輔助函式（get_next_serial_number）

run.py 只需：
    from utils.ui import App
    App(root, gallery, encoder, matcher, detector, fullscreen=..., debug=...)
    root.mainloop()
"""

import base64
import logging
import re
import time
import threading
import tkinter as tk
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image, ImageTk
import yaml

# LED Ring（選配，僅 Raspberry Pi）
try:
    import board
    import neopixel
    HAS_LED = True
except ImportError:
    HAS_LED = False

from .types import Detection, MatchResult

# ============================================================
# 常數
# ============================================================

RECORDS_DIR = Path("records")

# 每種藥品的配色（邊框色、背景色、YOLO覆蓋BGR）
DRUG_COLORS = [
    {"border": "#ffdd55", "bg": "#fff9e0", "bgr": (85, 221, 255)},   # 黃
    {"border": "#7fd37f", "bg": "#f0faf0", "bgr": (127, 211, 127)},  # 綠
    {"border": "#ff9f4a", "bg": "#fff4ec", "bgr": (74, 159, 255)},   # 橙
    {"border": "#6aa6ff", "bg": "#eef4ff", "bgr": (255, 166, 106)},  # 藍
    {"border": "#b07cff", "bg": "#f5f0ff", "bgr": (255, 124, 176)},  # 紫
]

COLOR_TOPBAR   = "#1f2f46"
COLOR_PRIMARY  = "#2196F3"
COLOR_SUCCESS  = "#4CAF50"
COLOR_ERROR    = "#f44336"
COLOR_DONE     = "#ffdf6b"
COLOR_BG       = "#d9d9d9"
COLOR_NUM_BG   = "#eaf2ff"
COLOR_BTN_OK   = "#d8f1d8"
COLOR_BTN_OK_T = "#1f6b1f"
COLOR_BTN_BAD  = "#f6caca"
COLOR_BTN_BAD_T= "#8b0000"

FONT_TITLE  = ("Microsoft JhengHei", 13, "bold")
FONT_NORMAL = ("Microsoft JhengHei", 11)
FONT_BOLD   = ("Microsoft JhengHei", 11, "bold")
FONT_NUM    = ("Microsoft JhengHei", 14, "bold")
FONT_BTN    = ("Microsoft JhengHei", 12, "bold")

# ============================================================
# 資料類別
# ============================================================

@dataclass
class PillEntry:
    """單顆偵測藥錠（每個 Detection 一筆）"""
    license: str
    name: str
    same_count: int    # 同款藥錠（同 license）在畫面中的總數
    color_idx: int     # 顏色索引（0-4）


@dataclass
class VerificationState:
    tray_id: str = ""
    timestamp: str = ""
    variety_count: int = 0       # 不重複藥品種數
    variety_correct: bool | None = None
    total_count: int = 0         # 藥錠總顆數
    total_correct: bool | None = None
    pills: list[PillEntry] = field(default_factory=list)   # 每顆一筆
    current_page: int = 0
    name_answers: list[bool | None] = field(default_factory=list)  # per detection
    dose_answers: dict[str, bool | None] = field(default_factory=dict)  # per license


# ============================================================
# 輔助函式
# ============================================================

def get_next_serial_number() -> str:
    """掃描 records/ 取最大序號 +1，回傳 6 位數字串"""
    max_num = 0
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        for f in RECORDS_DIR.glob("*.yaml"):
            nums = re.findall(r"\d+", f.stem)
            if nums:
                max_num = max(max_num, int(nums[0]))
    except Exception:
        pass
    return f"{max_num + 1:06d}"


# ============================================================
# 主程式
# ============================================================

class App:
    WINDOW_WIDTH  = 1024
    WINDOW_HEIGHT = 600

    def __init__(
        self,
        root: tk.Tk,
        api_url: str = "http://localhost:5000",
        fullscreen: bool = False,
        debug: bool = False,
    ):
        self.root    = root
        self._api_url = api_url.rstrip("/")
        self._debug  = debug

        # --- 狀態 ---
        self.state = VerificationState()
        self.current_tab: str = "cam"         # "cam" | "ai"
        self._captured_image: np.ndarray | None = None   # 拍攝原圖
        self._ai_image: np.ndarray | None = None          # YOLO 疊加圖（動態更新）
        self._detections: list = []                        # 本次偵測結果（供重繪用）
        self._is_analysed: bool = False        # 是否已完成分析

        # --- 相機 ---
        self._camera = None
        self._is_picamera = False
        self._camera_lock = threading.Lock()

        # --- LED ---
        self.led_pixels = None
        self._init_led()

        # --- 抽屜感測器 ---
        self._drawer_cap              = None
        self._drawer_analyzer         = None
        self._drawer_detector         = None
        self._drawer_cfg              = {}
        self._drawer_history          = deque(maxlen=500)
        self._drawer_running          = False
        self._drawer_thread           = None
        self._drawer_consecutive_closed = 0   # 連續「完全閉合」次數
        self._drawer_triggered        = False  # True = 已觸發分析，等待開啟後才可再觸發
        self._drawer_close_threshold  = 5      # 預設值，init 時從 config 覆寫
        self._drawer_logger           = None   # 狀態 log

        # --- 視窗 ---
        self.root.title("AI藥品輔助辨識")
        self.root.configure(bg=COLOR_BG)
        if fullscreen:
            self.root.attributes("-fullscreen", True)
            self.root.bind("<Escape>", lambda e: self.root.attributes("-fullscreen", False))
        else:
            self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")

        # --- 建 UI ---
        self._build_ui()

        # --- 初始化（不啟動串流）---
        self._init_camera()
        self._init_drawer_sensor()
        self._update_tray_id()
        self._reset_state()   # 確保 UI 為 IDLE 狀態

        # --- 關閉事件 ---
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # --------------------------------------------------------
    # LED
    # --------------------------------------------------------

    def _init_led(self):
        if self._debug or not HAS_LED:
            if self._debug:
                print("[light] Debug mode: LED skipped")
            return
        try:
            self.led_pixels = neopixel.NeoPixel(board.D18, 24)
            self.led_pixels.fill((255, 255, 255))
            print("[light] WS2812 LED Ring ON")
        except Exception as e:
            print(f"[light] LED init failed: {e}")
            self.led_pixels = None

    # --------------------------------------------------------
    # 相機初始化（不啟動串流）
    # --------------------------------------------------------

    def _init_camera(self):
        if self._debug:
            self._camera = None
            self._is_picamera = False
            print("[camera] Debug mode: camera skipped (noise image will be used)")
            return
        try:
            from picamera2 import Picamera2
            self._camera = Picamera2()
            self._is_picamera = True
            print("[camera] Picamera2 ready (not started)")
        except ImportError:
            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                self._camera = cap
                self._is_picamera = False
                print("[camera] OpenCV camera ready (not started)")
            else:
                cap.release()
                self._camera = None
                print("[camera] Warning: no camera available")

    # --------------------------------------------------------
    # 抽屜感測器
    # --------------------------------------------------------

    def _init_drawer_sensor(self):
        if self._debug:
            print("[drawer] Debug mode: sensor skipped — press Space to simulate close")
            self.root.bind("<space>", lambda e: self._on_drawer_closed())
            # 啟動模擬串流 loop（讓 terminal 可看到假資料在跑）
            self._drawer_running = True
            self._drawer_thread = threading.Thread(
                target=self._debug_drawer_loop, daemon=True)
            self._drawer_thread.start()
            return

        cfg_path = Path("config/drawer_config.yaml")
        if not cfg_path.exists():
            print("[drawer] drawer_config.yaml not found — auto-trigger disabled")
            return

        try:
            from utils.depth_analysis import DepthAnalyzer, DrawerStateDetector
            from eminent.sensors.vision2p5d import VideoCapture, MN96100CConfig

            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            self._drawer_cfg = cfg
            self._drawer_close_threshold = cfg['analysis'].get('min_state_duration', 5)

            self._drawer_cap = VideoCapture(
                vid=cfg['camera']['vid'],
                pid=cfg['camera']['pid'],
                frame_rate=getattr(MN96100CConfig.FrameRate,
                                   cfg['camera']['frame_rate']),
                led_current=getattr(MN96100CConfig.LEDCurrent,
                                    cfg['camera']['led_current']),
                exposure_setting=getattr(MN96100CConfig.ExposureSetting,
                                         cfg['camera'].get('exposure_setting', 'DEFAULT')),
            )
            if not self._drawer_cap.isOpened():
                raise RuntimeError("MN96100C not opened")

            self._drawer_analyzer = DepthAnalyzer()
            self._drawer_detector = DrawerStateDetector(
                threshold_open=cfg['thresholds']['open'],
                threshold_closed=cfg['thresholds']['closed'],
                min_state_duration=cfg['analysis']['min_state_duration'],
            )

            # 建立狀態 log（每次啟動清空）
            log_path = Path("logs/drawer_state.log")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._drawer_logger = logging.getLogger("drawer.state")
            self._drawer_logger.setLevel(logging.DEBUG)
            self._drawer_logger.propagate = False
            if not self._drawer_logger.handlers:
                handler = logging.FileHandler(log_path, mode='w', encoding='utf-8')
                handler.setFormatter(logging.Formatter('%(asctime)s  %(message)s',
                                                        datefmt='%H:%M:%S'))
                self._drawer_logger.addHandler(handler)

            self._start_drawer_monitoring()
            print("[drawer] MN96100C ready, monitoring started")

        except Exception as e:
            print(f"[drawer] Init failed: {e} — auto-trigger disabled")
            self._drawer_cap = None

    def _debug_drawer_loop(self):
        """Debug 模式：模擬持續串流輸出（正弦波強度，不觸發分析）"""
        import math
        t = 0
        while self._drawer_running:
            intensity = 60.0 + 40.0 * math.sin(t * 0.05)  # 20~100，永遠開啟區間
            state = "完全開啟"
            print(f"[drawer] state={state:<6}  intensity={intensity:6.1f}  [debug sim]",
                  flush=True)
            t += 1
            time.sleep(0.1)

    def _start_drawer_monitoring(self):
        self._drawer_running = True
        self._drawer_thread = threading.Thread(
            target=self._drawer_capture_loop, daemon=True)
        self._drawer_thread.start()

    def _stop_drawer_monitoring(self):
        self._drawer_running = False
        if self._drawer_thread:
            self._drawer_thread.join(timeout=2.0)
        if self._drawer_cap:
            try:
                self._drawer_cap.release()
            except Exception:
                pass

    def _drawer_capture_loop(self):
        MAX_FAILURES = 30
        consecutive_failures = 0

        while self._drawer_running:
            try:
                ret, frame = self._drawer_cap.read()
            except Exception:
                ret, frame = False, None

            if not ret or frame is None:
                consecutive_failures += 1
                if consecutive_failures >= MAX_FAILURES:
                    print("[drawer] Sensor disconnected")
                    break
                time.sleep(0.1)
                continue

            consecutive_failures = 0

            try:
                gray = (cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        if frame.ndim == 3 else frame)

                roi = self._drawer_cfg.get('roi', {})
                if roi.get('enabled', False):
                    gray = gray[roi['y1']:roi['y2'], roi['x1']:roi['x2']]

                metrics = self._drawer_analyzer.calculate_depth_metrics(gray)
                self._drawer_history.append(metrics['mean'])

                # MAX 平滑（與 drawer_monitor 一致）
                n = self._drawer_cfg['display']['smoothing_window']
                enable = self._drawer_cfg['display'].get('enable_smoothing', True)
                if enable:
                    recent = list(self._drawer_history)[-n:]
                    smoothed = max(recent)
                else:
                    smoothed = metrics['mean']

                state = self._drawer_detector.update(smoothed)

                # 每幀都串流輸出（terminal + file）
                log_line = f"[drawer] state={state:<6}  intensity={smoothed:6.1f}"
                print(log_line, flush=True)
                if self._drawer_logger:
                    self._drawer_logger.info(f"state={state}  intensity={smoothed:.1f}")

                if not self._drawer_triggered:
                    # 等待連續閉合 → 觸發分析
                    if state == "完全閉合":
                        self._drawer_consecutive_closed += 1
                        if self._drawer_consecutive_closed >= self._drawer_close_threshold:
                            self._drawer_triggered = True
                            self._drawer_consecutive_closed = 0
                            self.root.after(0, self._on_drawer_closed)
                    else:
                        self._drawer_consecutive_closed = 0
                else:
                    # 已觸發，等待抽屜完全開啟後才解鎖
                    if state == "完全開啟":
                        self._drawer_triggered = False
                        self._drawer_consecutive_closed = 0

            except Exception as e:
                print(f"[drawer] Loop error: {e}")

    def _on_drawer_closed(self):
        """抽屜閉合事件（UI 執行緒）— 分析丟到背景執行緒避免凍結 UI"""
        t = threading.Thread(target=self._on_analyse, daemon=True)
        t.start()

    def _capture_single_frame(self) -> np.ndarray | None:
        """短暫啟動相機，拍攝一幀後立即停止。回傳 BGR (H,W,3) 或 None"""
        if self._debug:
            sample_path = Path("src/sample/sample.jpg")
            if sample_path.exists():
                img = cv2.imread(str(sample_path))
                if img is not None:
                    print(f"[camera] Debug mode: loaded sample image {sample_path}")
                    return img
            print("[camera] Debug mode: sample not found, returning noise image")
            return np.random.randint(0, 256, (720, 960, 3), dtype=np.uint8)
        if self._camera is None:
            return None
        try:
            if self._is_picamera:
                config = self._camera.create_still_configuration(
                    main={"size": (1296, 972), "format": "BGR888"}
                )
                self._camera.configure(config)
                self._camera.start()
                time.sleep(0.5)           # 暖機
                frame = self._camera.capture_array()
                self._camera.stop()
                if frame is None:
                    return None
                # BGR888 → BGR
                if frame.ndim == 3 and frame.shape[2] == 4:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                return frame
            else:
                ret, frame = self._camera.read()
                return frame if ret else None
        except Exception as e:
            print(f"[camera] capture failed: {e}")
            return None

    # --------------------------------------------------------
    # UI 建置
    # --------------------------------------------------------

    def _build_ui(self):
        self._build_topbar()
        self._build_content()
        self._update_tab_buttons()  # badge_label 在 _build_content 後才存在

    def _build_topbar(self):
        topbar = tk.Frame(self.root, bg=COLOR_TOPBAR, height=52)
        topbar.pack(fill=tk.X)
        topbar.pack_propagate(False)

        # 標題
        tk.Label(
            topbar, text="AI藥品輔助辨識",
            bg=COLOR_TOPBAR, fg="white", font=FONT_TITLE,
        ).pack(side=tk.LEFT, padx=(14, 18))

        # Tab：鏡頭
        self.tab_cam = tk.Button(
            topbar, text="鏡頭", font=FONT_BTN, width=7,
            command=lambda: self._switch_tab("cam"),
        )
        self.tab_cam.pack(side=tk.LEFT, padx=3, pady=8)

        # Tab：AI
        self.tab_ai = tk.Button(
            topbar, text="AI", font=FONT_BTN, width=7,
            command=lambda: self._switch_tab("ai"),
        )
        self.tab_ai.pack(side=tk.LEFT, padx=3, pady=8)

        # 藥盤序號
        tk.Label(topbar, text="藥盤序號：", bg=COLOR_TOPBAR, fg="white", font=FONT_NORMAL).pack(side=tk.LEFT, padx=(18, 2))
        self.tray_label = tk.Label(
            topbar, text="------", bg=COLOR_NUM_BG, fg="#111",
            font=FONT_BOLD, width=10, relief=tk.FLAT, padx=6,
        )
        self.tray_label.pack(side=tk.LEFT)

        # 時間
        self.time_label = tk.Label(topbar, text="", bg=COLOR_TOPBAR, fg="white", font=FONT_NORMAL)
        self.time_label.pack(side=tk.LEFT, padx=18)
        self._update_time()

        # 完成按鈕（右側）
        self.done_btn = tk.Button(
            topbar, text="完成", font=FONT_BTN, width=7,
            bg=COLOR_DONE, fg="#333",
            relief=tk.FLAT, command=self._on_done,
        )
        self.done_btn.pack(side=tk.RIGHT, padx=(4, 14), pady=8)

    def _build_content(self):
        content = tk.Frame(self.root, bg=COLOR_BG)
        content.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # 左側：影像顯示區
        self.left_panel = tk.Frame(content, bg="#000")
        self.left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.image_label = tk.Label(self.left_panel, bg="#000", text="", image="")
        self.image_label.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Badge 浮動標籤
        self.badge_label = tk.Label(
            self.left_panel, text="待分析",
            bg="white", fg="#111", font=FONT_BOLD,
            padx=8, pady=4, relief=tk.SOLID, bd=1,
        )
        self.badge_label.place(x=10, y=10)

        # 右側：資訊面板
        self.right_panel = tk.Frame(content, bg=COLOR_BG, width=390)
        self.right_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))
        self.right_panel.pack_propagate(False)

        self._build_right_panel()

    def _build_right_panel(self):
        # --- 全局驗證區 ---
        global_frame = tk.Frame(self.right_panel, bg=COLOR_BG, bd=1, relief=tk.SOLID)
        global_frame.pack(fill=tk.X, pady=(0, 10))

        inner_g = tk.Frame(global_frame, bg=COLOR_BG)
        inner_g.pack(fill=tk.X, padx=10, pady=8)

        # 品項列
        self.variety_row = tk.Frame(inner_g, bg=COLOR_BG)
        self.variety_row.pack(fill=tk.X, pady=3)
        tk.Label(self.variety_row, text="品項", bg=COLOR_BG, font=FONT_BOLD, width=4).pack(side=tk.LEFT)
        self.variety_num = tk.Label(self.variety_row, text="0", bg=COLOR_NUM_BG, font=FONT_NUM, width=5, relief=tk.FLAT, padx=4)
        self.variety_num.pack(side=tk.LEFT, padx=4)
        tk.Label(self.variety_row, text="種", bg=COLOR_BG, font=FONT_NORMAL).pack(side=tk.LEFT)
        self.variety_err_btn = self._make_check_btn(self.variety_row, "錯誤", "bad", lambda: self._set_variety(False))
        self.variety_err_btn.pack(side=tk.RIGHT, padx=2)
        self.variety_ok_btn = self._make_check_btn(self.variety_row, "正確", "ok", lambda: self._set_variety(True))
        self.variety_ok_btn.pack(side=tk.RIGHT, padx=2)

        # 總量列
        self.total_row = tk.Frame(inner_g, bg=COLOR_BG)
        self.total_row.pack(fill=tk.X, pady=3)
        tk.Label(self.total_row, text="總量", bg=COLOR_BG, font=FONT_BOLD, width=4).pack(side=tk.LEFT)
        self.total_num = tk.Label(self.total_row, text="0", bg=COLOR_NUM_BG, font=FONT_NUM, width=5, relief=tk.FLAT, padx=4)
        self.total_num.pack(side=tk.LEFT, padx=4)
        tk.Label(self.total_row, text="顆", bg=COLOR_BG, font=FONT_NORMAL).pack(side=tk.LEFT)
        self.total_err_btn = self._make_check_btn(self.total_row, "錯誤", "bad", lambda: self._set_total(False))
        self.total_err_btn.pack(side=tk.RIGHT, padx=2)
        self.total_ok_btn = self._make_check_btn(self.total_row, "正確", "ok", lambda: self._set_total(True))
        self.total_ok_btn.pack(side=tk.RIGHT, padx=2)

        # --- 單碇驗證區 ---
        self.drug_frame = tk.Frame(
            self.right_panel, bg=COLOR_BG,
            bd=3, relief=tk.SOLID,
            highlightbackground="#ffdd55",
            highlightthickness=3,
        )
        self.drug_frame.pack(fill=tk.BOTH, expand=True)

        # 分頁導航 — 固定在 drug_frame 底部（先 pack 才能佔底）
        nav = tk.Frame(self.drug_frame, bg=COLOR_BG)
        nav.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(4, 8))
        self.prev_btn = tk.Button(nav, text="上一項", font=FONT_BTN, width=7, command=self._prev_drug)
        self.prev_btn.pack(side=tk.LEFT)
        self.page_label = tk.Label(nav, text="第 0 項 / 共 0 項", bg=COLOR_BG, font=FONT_NORMAL)
        self.page_label.pack(side=tk.LEFT, expand=True)
        self.next_btn = tk.Button(nav, text="下一項", font=FONT_BTN, width=7, command=self._next_drug)
        self.next_btn.pack(side=tk.RIGHT)

        inner_d = tk.Frame(self.drug_frame, bg=COLOR_BG)
        inner_d.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))

        # 藥品名稱
        self.drug_name_label = tk.Label(
            inner_d, text="--",
            bg="white", fg="#111",
            font=("Microsoft JhengHei", 13),
            wraplength=350, justify=tk.LEFT,
            anchor=tk.NW, padx=8, pady=6,
            relief=tk.SOLID, bd=1,
        )
        self.drug_name_label.pack(fill=tk.X, pady=(0, 8))

        # 品項核對列
        self.name_row = tk.Frame(inner_d, bg=COLOR_BG)
        self.name_row.pack(fill=tk.X, pady=3)
        tk.Label(self.name_row, text="品項核對", bg=COLOR_BG, font=FONT_BOLD).pack(side=tk.LEFT)
        self.name_err_btn = self._make_check_btn(self.name_row, "錯誤", "bad", lambda: self._set_name(False))
        self.name_err_btn.pack(side=tk.RIGHT, padx=2)
        self.name_ok_btn = self._make_check_btn(self.name_row, "正確", "ok", lambda: self._set_name(True))
        self.name_ok_btn.pack(side=tk.RIGHT, padx=2)

        # 劑量列
        self.dose_row = tk.Frame(inner_d, bg=COLOR_BG)
        self.dose_row.pack(fill=tk.X, pady=3)
        self.dose_num = tk.Label(self.dose_row, text="0", bg=COLOR_NUM_BG, font=FONT_NUM, width=5, relief=tk.FLAT, padx=4)
        self.dose_num.pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(self.dose_row, text="顆", bg=COLOR_BG, font=FONT_NORMAL).pack(side=tk.LEFT)
        self.dose_err_btn = self._make_check_btn(self.dose_row, "錯誤", "bad", lambda: self._set_dose(False))
        self.dose_err_btn.pack(side=tk.RIGHT, padx=2)
        self.dose_ok_btn = self._make_check_btn(self.dose_row, "正確", "ok", lambda: self._set_dose(True))
        self.dose_ok_btn.pack(side=tk.RIGHT, padx=2)

    @staticmethod
    def _make_check_btn(parent, text: str, kind: str, cmd) -> tk.Button:
        """製作正確/錯誤按鈕（ok=綠, bad=紅）"""
        if kind == "ok":
            bg, fg = COLOR_BTN_OK, COLOR_BTN_OK_T
        else:
            bg, fg = COLOR_BTN_BAD, COLOR_BTN_BAD_T
        return tk.Button(
            parent, text=text, font=FONT_BTN, width=7,
            bg=bg, fg=fg, relief=tk.SOLID, bd=1,
            command=cmd,
        )

    # --------------------------------------------------------
    # 時間 & 流水號
    # --------------------------------------------------------

    def _update_time(self):
        dt = datetime.now()
        txt = f"{dt.year}/{dt.month}/{dt.day} {dt.strftime('%H:%M:%S')}"
        self.time_label.config(text=txt)
        self.root.after(1000, self._update_time)

    def _update_tray_id(self):
        self.state.tray_id = get_next_serial_number()
        self.tray_label.config(text=self.state.tray_id)

    # --------------------------------------------------------
    # Tab 切換與影像顯示
    # --------------------------------------------------------

    def _update_tab_buttons(self):
        if self.current_tab == "cam":
            self.tab_cam.config(bg="#e6e6e6", relief=tk.SUNKEN)
            self.tab_ai.config(bg="#bfbfbf", relief=tk.FLAT)
            self.badge_label.config(text="鏡頭" if self._is_analysed else "待分析")
        else:
            self.tab_cam.config(bg="#bfbfbf", relief=tk.FLAT)
            self.tab_ai.config(bg="#e6e6e6", relief=tk.SUNKEN)
            self.badge_label.config(text="AI")

    def _switch_tab(self, tab: str):
        if tab == self.current_tab:
            return
        self.current_tab = tab
        self._update_tab_buttons()
        self._refresh_image()

    def _refresh_image(self):
        """根據當前 tab 顯示對應靜態圖"""
        img = self._captured_image if self.current_tab == "cam" else self._ai_image
        if img is None:
            self.image_label.config(image="", bg="#000")
            self.image_label.image = None
            return
        self._display_bgr(img)

    def _display_bgr(self, bgr: np.ndarray):
        """將 BGR ndarray 縮放後顯示在 image_label"""
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)

        self.left_panel.update_idletasks()
        w = self.left_panel.winfo_width()
        h = self.left_panel.winfo_height()
        if w < 2 or h < 2:
            w, h = 600, 500

        iw, ih = pil.size
        scale = min(w / iw, h / ih)
        pil = pil.resize((int(iw * scale), int(ih * scale)), Image.Resampling.LANCZOS)

        photo = ImageTk.PhotoImage(pil)
        self.image_label.config(image=photo, bg="#000")
        self.image_label.image = photo  # 防止 GC

    # --------------------------------------------------------
    # 分析流水線
    # --------------------------------------------------------

    def _debug_fake_results(self, n: int) -> list:
        """Debug 模式：為每顆偵測到的藥錠分配不同的假 MatchResult（不需 API）。"""
        return [
            MatchResult(
                license_number=f"DEMO-{i+1:03d}",
                name=f"Demo Drug {i+1}",
                side=0,
                score=0.95,
            )
            for i in range(n)
        ]

    def _load_sample_detections(self, frame: np.ndarray) -> list:
        """Debug 模式：解析 src/sample/sample.txt（YOLO-seg 格式）合成 Detection 列表。

        格式：每行 `class_id x1 y1 x2 y2 ...`（正規化多邊形頂點）
        回傳的 Detection 物件與 YOLODetector 輸出完全相同，
        可直接送入 Encoder / Matcher。
        """
        from .types import Detection
        txt_path = Path("src/sample/sample.txt")
        if not txt_path.exists():
            print("[debug] sample.txt not found")
            return []

        h, w = frame.shape[:2]
        detections = []

        with open(txt_path) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 5:
                    continue
                class_id = int(parts[0])
                coords = list(map(float, parts[1:]))
                xs = [round(coords[i] * w) for i in range(0, len(coords), 2)]
                ys = [round(coords[i] * h) for i in range(1, len(coords), 2)]

                x1, x2 = max(0, min(xs)), min(w, max(xs))
                y1, y2 = max(0, min(ys)), min(h, max(ys))

                mask = np.zeros((h, w), dtype=np.uint8)
                pts = np.array(list(zip(xs, ys)), dtype=np.int32)
                cv2.fillPoly(mask, [pts], 1)

                detections.append(Detection(
                    bbox=(x1, y1, x2, y2),
                    mask=mask,
                    confidence=0.95,
                    class_id=class_id,
                ))

        print(f"[debug] Loaded {len(detections)} detections from sample.txt")
        return detections

    def _call_api(self, frame: np.ndarray) -> tuple[list[Detection], list[MatchResult | None]]:
        """將影像 POST 至推論 API，回傳重建後的 Detection 與 MatchResult 列表。"""
        _, img_buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        files = {"image": ("image.jpg", img_buf.tobytes(), "image/jpeg")}
        resp = requests.post(f"{self._api_url}/analyse", files=files, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        detections: list[Detection] = []
        results:    list[MatchResult | None] = []

        for p in data.get("pills", []):
            # 解碼 mask（base64 PNG → numpy uint8 0/1）
            mask = None
            if p.get("mask_b64"):
                mask_bytes = base64.b64decode(p["mask_b64"])
                mask_arr   = np.frombuffer(mask_bytes, dtype=np.uint8)
                mask_gray  = cv2.imdecode(mask_arr, cv2.IMREAD_GRAYSCALE)
                if mask_gray is not None:
                    mask = (mask_gray > 128).astype(np.uint8)

            detections.append(Detection(
                bbox=tuple(p["bbox"]),
                mask=mask,
                confidence=float(p["confidence"]),
                class_id=int(p["class_id"]),
            ))

            lic = p.get("license_number", "")
            if lic:
                results.append(MatchResult(
                    license_number=lic,
                    name=p.get("name", ""),
                    side=int(p.get("side", 0)),
                    score=float(p.get("score", 0.0)),
                ))
            else:
                results.append(None)

        return detections, results

    def _on_analyse(self):
        """抽屜閉合觸發：拍照 → 呼叫推論 API（背景執行緒），UI 更新回拋主執行緒"""
        if self._is_analysed:
            return   # 正在 REVIEWING 中，忽略重複觸發

        # ── 拍攝（背景執行緒）──
        print("[analyse] Capturing frame...")
        frame = self._capture_single_frame()
        if frame is None:
            print("[analyse] Capture failed")
            self.root.after(0, lambda: self._show_info_modal(
                "提示", "相機拍攝失敗，請確認相機連接狀態。"))
            return

        self._captured_image = frame.copy()

        # ── 偵測 & 比對（背景執行緒）──
        print("[analyse] Running detection...")
        try:
            if self._debug:
                detections = self._load_sample_detections(frame)
                results    = self._debug_fake_results(len(detections))
            else:
                detections, results = self._call_api(frame)
        except requests.exceptions.ConnectionError:
            print("[analyse] API connection failed")
            self.root.after(0, lambda: self._show_info_modal(
                "連線錯誤", f"無法連線至推論伺服器 {self._api_url}\n請確認 api.py 已啟動。"))
            return
        except Exception as e:
            print(f"[analyse] Error: {e}")
            self.root.after(0, lambda: self._show_info_modal(
                "辨識錯誤", f"推論過程發生錯誤：{e}"))
            return

        if not detections:
            print("[analyse] No pills detected")
            _ai_img = frame.copy()
            def _no_detect():
                self._ai_image = _ai_img
                self._is_analysed = True
                self._update_state_from_results([], [])
                self._switch_tab("cam")
                self._refresh_image()
                self._show_info_modal("提示", "未偵測到任何藥錠，請確認藥盤擺放位置與光線條件。")
            self.root.after(0, _no_detect)
            return

        # ── 純資料計算，可在背景做 ──
        self._update_state_from_results(detections, results)
        self._detections = detections
        _ai_img = self._generate_ai_overlay(frame, detections, self.state.pills, current_page=0)

        # ── 所有 UI 操作回拋主執行緒 ──
        def _update_ui():
            self._is_analysed = True
            self._ai_image = _ai_img
            self.current_tab = "ai"
            self._update_tab_buttons()
            self._refresh_image()
            self._update_info_panel()
            self.done_btn.config(state=tk.NORMAL, bg=COLOR_DONE)
            print("[analyse] Done")

        self.root.after(0, _update_ui)

    def _generate_ai_overlay(
        self,
        image: np.ndarray,
        detections: list[Detection],
        pills: list,
        current_page: int = -1,
    ) -> np.ndarray:
        """在原圖上疊加 YOLO 分割遮罩、邊界框與編號徽章。

        配色直接取自 PillEntry.color_idx（與右側面板完全一致）。
        current_page 對應的藥錠以高透明度遮罩 + 粗框高亮顯示，
        其餘藥錠以低透明度淡化，讓使用者清楚知道黃色框框對應哪顆。
        """
        h_img, w_img = image.shape[:2]
        overlay = image.copy()

        # ── Pass 1：分割遮罩（current 高亮，其餘淡化）──
        for i, (det, pill) in enumerate(zip(detections, pills)):
            color_bgr = (
                DRUG_COLORS[pill.color_idx]["bgr"] if pill.license
                else (128, 128, 128)
            )
            color_arr = np.array(color_bgr, dtype=np.float32)
            is_cur = (i == current_page)
            alpha = 0.65 if is_cur else 0.25

            if det.mask is not None:
                mask = det.mask
                if mask.shape != (h_img, w_img):
                    mask = cv2.resize(mask, (w_img, h_img), interpolation=cv2.INTER_NEAREST)
                mb = mask > 0
                overlay[mb] = (
                    overlay[mb].astype(np.float32) * (1 - alpha) + color_arr * alpha
                ).clip(0, 255).astype(np.uint8)

        # ── Pass 2：邊界框 + 編號徽章 ──
        for i, (det, pill) in enumerate(zip(detections, pills)):
            color_bgr = (
                DRUG_COLORS[pill.color_idx]["bgr"] if pill.license
                else (128, 128, 128)
            )
            is_cur = (i == current_page)
            x1, y1, x2, y2 = det.bbox

            # 邊界框：current 粗框，其餘細框
            thickness = 3 if is_cur else 1
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color_bgr, thickness)

            # 編號徽章（圓形背景 + 白色數字）
            num = str(i + 1)
            r_badge = 12 if is_cur else 9
            cx = x1 + r_badge + 2
            cy = y1 + r_badge + 2
            cv2.circle(overlay, (cx, cy), r_badge, color_bgr, -1)
            cv2.circle(overlay, (cx, cy), r_badge, (255, 255, 255), 1)
            font_scale = 0.45 if is_cur else 0.35
            tw, th = cv2.getTextSize(num, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)[0]
            cv2.putText(
                overlay, num,
                (cx - tw // 2, cy + th // 2),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                (255, 255, 255), 1, cv2.LINE_AA,
            )

        return overlay

    def _update_state_from_results(
        self,
        detections: list[Detection],
        results: list[MatchResult | None],
    ):
        """由偵測結果更新 VerificationState。

        每顆偵測藥錠建立一筆 PillEntry（含未識別），
        藥品種類以 license_number 去重計算 variety_count。
        """
        # 分配每個 license 的配色（首次出現順序）
        license_color: dict[str, int] = {}
        color_counter = 0
        for r in results:
            if r and r.license_number not in license_color:
                license_color[r.license_number] = color_counter % len(DRUG_COLORS)
                color_counter += 1

        # 統計每個 license 出現幾顆（供 same_count 顯示）
        license_count: dict[str, int] = {}
        for r in results:
            if r:
                license_count[r.license_number] = license_count.get(r.license_number, 0) + 1

        # 每顆 detection 建立一筆 PillEntry
        pills: list[PillEntry] = []
        for r in results:
            if r is None:
                pills.append(PillEntry(
                    license="",
                    name="未識別",
                    same_count=1,
                    color_idx=len(DRUG_COLORS) - 1,
                ))
            else:
                pills.append(PillEntry(
                    license=r.license_number,
                    name=r.name,
                    same_count=license_count.get(r.license_number, 1),
                    color_idx=license_color[r.license_number],
                ))

        unique_licenses = {p.license for p in pills if p.license}
        self.state.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state.variety_count = len(unique_licenses)
        self.state.total_count = len(pills)
        self.state.variety_correct = None
        self.state.total_correct = None
        self.state.pills = pills
        self.state.current_page = 0
        self.state.name_answers = [None] * len(pills)
        self.state.dose_answers = {lic: None for lic in unique_licenses}

    # --------------------------------------------------------
    # 資訊面板更新
    # --------------------------------------------------------

    def _update_info_panel(self):
        self.variety_num.config(text=str(self.state.variety_count))
        self.total_num.config(text=str(self.state.total_count))

        if self.state.pills and 0 <= self.state.current_page < len(self.state.pills):
            pill = self.state.pills[self.state.current_page]
            self.drug_name_label.config(text=pill.name or "--")
            self.dose_num.config(text=str(pill.same_count))  # 同款共幾顆
            self.page_label.config(
                text=f"第 {self.state.current_page + 1} 顆 / 共 {len(self.state.pills)} 顆"
            )
            c = DRUG_COLORS[pill.color_idx]
            self.drug_frame.config(highlightbackground=c["border"], bg=c["bg"])
            for w in self.drug_frame.winfo_children():
                try:
                    w.config(bg=c["bg"])
                    for ww in w.winfo_children():
                        try:
                            ww.config(bg=c["bg"])
                        except Exception:
                            pass
                except Exception:
                    pass
        else:
            self.drug_name_label.config(text="--")
            self.dose_num.config(text="0")
            self.page_label.config(text="第 0 顆 / 共 0 顆")
            self.drug_frame.config(highlightbackground="#ffdd55", bg=COLOR_BG)

        self._update_button_states()
        self._update_nav_buttons()
        self._clear_highlights()

        # 重繪 overlay（highlight 當前頁對應的藥錠）
        if (self._is_analysed and self._detections
                and self._captured_image is not None
                and self.state.pills):
            self._ai_image = self._generate_ai_overlay(
                self._captured_image,
                self._detections,
                self.state.pills,
                current_page=self.state.current_page,
            )
            if self.current_tab == "ai":
                self._refresh_image()

    def _update_button_states(self):
        """更新所有正確/錯誤按鈕的視覺狀態"""
        self._apply_btn_state(self.variety_ok_btn, self.variety_err_btn, self.state.variety_correct)
        self._apply_btn_state(self.total_ok_btn, self.total_err_btn, self.state.total_correct)
        if self.state.pills and 0 <= self.state.current_page < len(self.state.pills):
            pill = self.state.pills[self.state.current_page]
            self._apply_btn_state(self.name_ok_btn, self.name_err_btn,
                                  self.state.name_answers[self.state.current_page])
            # dose_answers 以 license 為 key；未識別藥錠無 dose 按鈕狀態
            self._apply_btn_state(self.dose_ok_btn, self.dose_err_btn,
                                  self.state.dose_answers.get(pill.license))
        else:
            self._apply_btn_state(self.name_ok_btn, self.name_err_btn, None)
            self._apply_btn_state(self.dose_ok_btn, self.dose_err_btn, None)

    @staticmethod
    def _apply_btn_state(ok_btn: tk.Button, err_btn: tk.Button, value: bool | None):
        ACTIVE_BD = 3
        NORMAL_BD = 1
        if value is True:
            ok_btn.config(relief=tk.SUNKEN, bd=ACTIVE_BD, fg=COLOR_BTN_OK_T)
            err_btn.config(relief=tk.SOLID,  bd=NORMAL_BD, fg="#999")
        elif value is False:
            ok_btn.config(relief=tk.SOLID,  bd=NORMAL_BD, fg="#999")
            err_btn.config(relief=tk.SUNKEN, bd=ACTIVE_BD, fg=COLOR_BTN_BAD_T)
        else:
            ok_btn.config(relief=tk.SOLID, bd=NORMAL_BD, fg=COLOR_BTN_OK_T)
            err_btn.config(relief=tk.SOLID, bd=NORMAL_BD, fg=COLOR_BTN_BAD_T)

    def _update_nav_buttons(self):
        total = len(self.state.pills)
        page  = self.state.current_page
        self.prev_btn.config(state=tk.NORMAL if page > 0 else tk.DISABLED)
        self.next_btn.config(state=tk.NORMAL if page < total - 1 else tk.DISABLED)

    # --------------------------------------------------------
    # 回饋設定（互斥單選，不可取消）
    # --------------------------------------------------------

    def _set_variety(self, value: bool):
        self.state.variety_correct = value
        self._update_button_states()
        self._clear_highlight(self.variety_row)
        self._auto_switch_ai()

    def _set_total(self, value: bool):
        self.state.total_correct = value
        self._update_button_states()
        self._clear_highlight(self.total_row)
        self._auto_switch_ai()

    def _set_name(self, value: bool):
        if self.state.pills and 0 <= self.state.current_page < len(self.state.pills):
            self.state.name_answers[self.state.current_page] = value
            self._update_button_states()
            self._clear_highlight(self.name_row)
            self._auto_switch_ai()

    def _set_dose(self, value: bool):
        if self.state.pills and 0 <= self.state.current_page < len(self.state.pills):
            pill = self.state.pills[self.state.current_page]
            if pill.license:  # 未識別藥錠不記錄 dose
                self.state.dose_answers[pill.license] = value
            self._update_button_states()
            self._clear_highlight(self.dose_row)
            self._auto_switch_ai()

    def _auto_switch_ai(self):
        if self.current_tab != "ai" and self._is_analysed:
            self._switch_tab("ai")

    # --------------------------------------------------------
    # 導航
    # --------------------------------------------------------

    def _prev_drug(self):
        if self.state.current_page > 0:
            self.state.current_page -= 1
            self._update_info_panel()
            self._auto_switch_ai()

    def _next_drug(self):
        if self.state.current_page < len(self.state.pills) - 1:
            self.state.current_page += 1
            self._update_info_panel()
            self._auto_switch_ai()

    # --------------------------------------------------------
    # 紅框提示
    # --------------------------------------------------------

    def _highlight_missing(self, row: tk.Frame):
        row.config(highlightbackground="red", highlightthickness=2, highlightcolor="red")

    def _clear_highlight(self, row: tk.Frame):
        row.config(highlightthickness=0)

    def _clear_highlights(self):
        for row in [self.variety_row, self.total_row, self.name_row, self.dose_row]:
            self._clear_highlight(row)

    # --------------------------------------------------------
    # 「完成」邏輯
    # --------------------------------------------------------

    def _find_first_missing(self) -> tuple[str, int] | None:
        """找第一筆未填項目，回傳 (欄位類型, 要跳到的頁碼) 或 None（全填完）"""
        if self.state.variety_correct is None:
            return ("variety", self.state.current_page)
        if self.state.total_correct is None:
            return ("total", self.state.current_page)
        # name_answers：每顆獨立
        for i, ans in enumerate(self.state.name_answers):
            if ans is None:
                return ("name", i)
        # dose_answers：per license，找第一顆該 license 的頁碼
        for lic, ans in self.state.dose_answers.items():
            if ans is None:
                for i, pill in enumerate(self.state.pills):
                    if pill.license == lic:
                        return ("dose", i)
        return None

    def _on_done(self):
        self._show_review_modal()

    def _show_review_modal(self):
        """填報總覽 Modal：顯示所有答案，確認送出才寫入磁碟"""
        MODAL_W, MODAL_H = 500, 520
        modal = tk.Toplevel(self.root)
        modal.title("填報總覽")
        modal.resizable(False, False)
        modal.grab_set()
        modal.transient(self.root)
        self._center_window(modal, MODAL_W, MODAL_H)
        modal.geometry(f"{MODAL_W}x{MODAL_H}")

        tk.Label(modal, text="填報總覽", font=FONT_TITLE).pack(
            anchor=tk.W, padx=16, pady=(12, 2))
        tk.Frame(modal, bg="#ccc", height=1).pack(fill=tk.X, padx=16, pady=(0, 2))

        scroll_outer = tk.Frame(modal)
        scroll_outer.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)

        canvas = tk.Canvas(scroll_outer, highlightthickness=0)
        scrollbar = tk.Scrollbar(scroll_outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg="white")
        canvas_win = canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        def _on_inner_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_inner_configure)

        def _on_canvas_configure(e):
            canvas.itemconfig(canvas_win, width=e.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def modal_destroy():
            canvas.unbind_all("<MouseWheel>")
            modal.destroy()

        def answer_style(value: bool | None) -> tuple[str, str]:
            if value is True:
                return "正確", "#1f6b1f"
            elif value is False:
                return "錯誤", "#8b0000"
            else:
                return "⚠ 未填", "#cc0000"

        def add_row(parent, label_txt: str, value: bool | None, bg: str):
            row = tk.Frame(parent, bg=bg)
            row.pack(fill=tk.X, padx=0, pady=1)
            tk.Label(row, text=label_txt, font=FONT_NORMAL, bg=bg,
                     anchor=tk.W, width=20).pack(side=tk.LEFT, padx=8, pady=4)
            ans_txt, ans_col = answer_style(value)
            tk.Label(row, text=ans_txt, font=FONT_BOLD, bg=bg,
                     fg=ans_col).pack(side=tk.RIGHT, padx=8)

        global_bg = "#f8f8f8"
        add_row(inner, f"品項　{self.state.variety_count} 種", self.state.variety_correct, global_bg)
        add_row(inner, f"總量　{self.state.total_count} 顆", self.state.total_correct, global_bg)
        tk.Frame(inner, bg="#ccc", height=1).pack(fill=tk.X, padx=8, pady=4)

        # 先收集 dose_answers 顯示（以第一次出現的 license 為代表）
        shown_dose: set[str] = set()
        for i, pill in enumerate(self.state.pills):
            c = DRUG_COLORS[pill.color_idx]
            drug_bg = c["bg"]
            hdr = tk.Frame(inner, bg=drug_bg,
                           highlightbackground=c["border"], highlightthickness=2)
            hdr.pack(fill=tk.X, padx=8, pady=(6, 0))
            tk.Label(hdr, text=f"第 {i+1} 顆｜{pill.name or pill.license}",
                     font=FONT_BOLD, bg=drug_bg, fg="#333",
                     wraplength=440, justify=tk.LEFT, anchor=tk.W,
                     padx=8, pady=4).pack(fill=tk.X)
            add_row(inner, "品項核對", self.state.name_answers[i], drug_bg)
            # 同款藥只在第一次出現時顯示劑量核對
            if pill.license and pill.license not in shown_dose:
                shown_dose.add(pill.license)
                dose_ans = self.state.dose_answers.get(pill.license)
                add_row(inner, f"同款 {pill.same_count} 顆", dose_ans, drug_bg)

        all_filled = self._find_first_missing() is None
        btn_frame = tk.Frame(modal, bg=COLOR_BG)
        btn_frame.pack(fill=tk.X, padx=16, pady=(4, 12))

        def do_reset():
            modal_destroy()
            self._reset_feedback()

        def do_go_back():
            missing = self._find_first_missing()
            modal_destroy()
            if missing:
                missing_type, drug_idx = missing
                self.state.current_page = drug_idx
                self._update_info_panel()
                row_map = {
                    "variety": self.variety_row,
                    "total":   self.total_row,
                    "name":    self.name_row,
                    "dose":    self.dose_row,
                }
                if missing_type in row_map:
                    self._highlight_missing(row_map[missing_type])

        def do_submit():
            modal_destroy()
            self._save_results()
            self._reset_state()

        tk.Button(btn_frame, text="重新回饋", font=FONT_BTN,
                  bg="#555", fg="white", width=9,
                  command=do_reset).pack(side=tk.LEFT)

        if not all_filled:
            tk.Button(btn_frame, text="回去補填", font=FONT_BTN,
                      bg="#111", fg="white", width=9,
                      command=do_go_back).pack(side=tk.LEFT, padx=(8, 0))

        tk.Button(btn_frame,
                  text="確認送出", font=FONT_BTN, width=9,
                  bg=COLOR_SUCCESS if all_filled else "#aaa",
                  fg="white",
                  state=tk.NORMAL if all_filled else tk.DISABLED,
                  command=do_submit).pack(side=tk.RIGHT)

    def _show_info_modal(self, title: str, message: str):
        """一般提示 Modal（只有關閉按鈕）"""
        modal = tk.Toplevel(self.root)
        modal.title(title)
        modal.geometry("400x160")
        modal.resizable(False, False)
        modal.grab_set()
        modal.transient(self.root)
        self._center_window(modal, 400, 160)

        tk.Label(modal, text=title, font=FONT_TITLE).pack(anchor=tk.W, padx=16, pady=(14, 0))
        tk.Label(modal, text=message, font=FONT_NORMAL, wraplength=360, justify=tk.LEFT).pack(padx=16, pady=10)
        tk.Button(modal, text="關閉", font=FONT_BTN, bg="#111", fg="white",
                  width=8, command=modal.destroy).pack(pady=8)

    def _center_window(self, win: tk.Toplevel, w: int, h: int):
        self.root.update_idletasks()
        rx = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        win.geometry(f"{w}x{h}+{rx}+{ry}")

    # --------------------------------------------------------
    # 儲存 & 重置
    # --------------------------------------------------------

    def _save_results(self):
        RECORDS_DIR.mkdir(parents=True, exist_ok=True)
        tray_id = self.state.tray_id or datetime.now().strftime("%Y%m%d_%H%M%S")

        yaml_data = {
            "tray_id": self.state.tray_id,
            "timestamp": self.state.timestamp,
            "variety_count": self.state.variety_count,
            "variety_correct": self.state.variety_correct,
            "total_count": self.state.total_count,
            "total_correct": self.state.total_correct,
            "pills": {},
        }
        for i, pill in enumerate(self.state.pills):
            yaml_data["pills"][f"pill_{i+1}"] = {
                "license": pill.license,
                "name": pill.name,
                "same_count": pill.same_count,
                "name_correct": self.state.name_answers[i],
                # dose 答案以 license 共用，未識別藥錠為 None
                "dose_correct": self.state.dose_answers.get(pill.license),
            }

        yaml_path = RECORDS_DIR / f"{tray_id}.yaml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False)
        print(f"[save] {yaml_path}")

        if self._captured_image is not None:
            img_path = RECORDS_DIR / f"{tray_id}.jpg"
            cv2.imwrite(str(img_path), self._captured_image)
            print(f"[save] {img_path}")

    def _reset_feedback(self):
        """只重置回饋回答，保留辨識結果"""
        self.state.variety_correct = None
        self.state.total_correct = None
        self.state.name_answers = [None] * len(self.state.pills)
        self.state.dose_answers = {lic: None for lic in self.state.dose_answers}
        self.state.current_page = 0
        self._update_info_panel()

    def _reset_state(self):
        """完整重置至 IDLE 狀態（黑畫面）"""
        self._captured_image = None
        self._ai_image = None
        self._detections = []
        self._is_analysed = False

        self.state = VerificationState()
        self._update_tray_id()

        self.current_tab = "cam"
        self._update_tab_buttons()
        self.image_label.config(image="", bg="#000")
        self.image_label.image = None
        self.badge_label.config(text="待分析")

        self.variety_num.config(text="0")
        self.total_num.config(text="0")
        self.drug_name_label.config(text="--")
        self.dose_num.config(text="0")
        self.page_label.config(text="第 0 項 / 共 0 項")
        self._update_button_states()
        self._update_nav_buttons()
        self._clear_highlights()
        self.drug_frame.config(highlightbackground="#ffdd55", bg=COLOR_BG)

        self.done_btn.config(state=tk.DISABLED, bg="#bbb")

    # --------------------------------------------------------
    # 關閉
    # --------------------------------------------------------

    def _on_close(self):
        self._stop_drawer_monitoring()
        if self.led_pixels:
            try:
                self.led_pixels.fill((0, 0, 0))
            except Exception:
                pass
        if self._camera:
            try:
                if self._is_picamera:
                    self._camera.close()
                else:
                    self._camera.release()
            except Exception:
                pass
        self.root.destroy()


__all__ = ["App", "DRUG_COLORS", "RECORDS_DIR", "PillEntry", "VerificationState"]
