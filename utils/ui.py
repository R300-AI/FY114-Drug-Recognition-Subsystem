"""utils/ui.py — FY114 Tkinter GUI 應用程式

此模組包含完整的 Tkinter UI 邏輯：
  - App 類別（主視窗、相機、分析流水線、填報邏輯）
  - 所有 UI 常數（顏色、字體）
  - 資料類別（PillEntry、VerificationState）
  - 輔助函式（get_next_serial_number）

run.py 只需：
    from utils.ui import App
    App(root, api_url=..., fullscreen=..., debug=...)
    root.mainloop()
"""

import base64
import logging
import re
import time
import threading
import tkinter as tk

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image, ImageTk

# LED Ring（選配，僅 Raspberry Pi）
try:
    import board
    import neopixel
    HAS_LED = True
except ImportError:
    HAS_LED = False

from .types import Detection, MatchResult
from .excel_writer import ExcelWriter, create_backup, HAS_OPENPYXL

# ============================================================
# 常數
# ============================================================

RECORDS_DIR = Path("records")
EXCEL_QUESTIONNAIRE_SOURCE = Path("成大第一階段辨識問卷_1150304建議修改版.xlsx")
EXCEL_QUESTIONNAIRE = RECORDS_DIR / "成大第一階段辨識問卷_1150304建議修改版.xlsx"

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
    same_count: int        # 同款藥錠（同 license）在畫面中的總數
    color_idx: int         # 顏色索引（0-4）
    category_label: str = ""      # 藥品類別標籤（A, B, C...）
    index_in_category: int = 0    # 在該類別中的序號（1, 2, 3...）
    detection_idx: int = 0        # 全局偵測索引（用於高亮定位）
    
    @property
    def full_label(self) -> str:
        """完整編碼標籤（如 A1, B2, C3）"""
        return f"{self.category_label}{self.index_in_category}" if self.category_label else ""


@dataclass
class DrugCategory:
    """藥品類別（同一種藥的所有藥錠）"""
    license: str
    name: str
    category_label: str    # A, B, C...
    color_idx: int
    pills: list[PillEntry] = field(default_factory=list)  # 該類別下的所有藥錠
    
    @property
    def total_count(self) -> int:
        """該類別的藥錠總數"""
        return len(self.pills)


@dataclass
class VerificationState:
    tray_id: str = ""
    timestamp: str = ""
    variety_count: int = 0       # 不重複藥品種數
    variety_correct: bool | None = None
    total_count: int = 0         # 藥錠總顆數
    total_correct: bool | None = None
    pills: list[PillEntry] = field(default_factory=list)   # 每顆一筆（全局列表）
    categories: list[DrugCategory] = field(default_factory=list)  # 按類別分組
    current_page: int = 0        # 當前頁（藥品類別索引）
    highlighted_pill: int = -1   # 當前高亮的藥錠索引（用於 hover/click）
    name_answers: list[bool | None] = field(default_factory=list)  # per category
    dose_answers: list[list[bool | None]] = field(default_factory=list)  # per pill in category
    
    def set_defaults(self, default_correct: bool | None = True):
        """設定預設的驗證狀態（可選擇預設為正確、錯誤或未選）"""
        self.variety_correct = default_correct
        self.total_correct = default_correct
        # name_answers: 每個類別一個答案
        if self.categories:
            self.name_answers = [default_correct] * len(self.categories)
            # dose_answers: 每個類別下的每顆藥錠各一個答案
            self.dose_answers = [
                [default_correct] * len(cat.pills) for cat in self.categories
            ]


# ============================================================
# 輔助函式
# ============================================================

def get_category_label(index: int) -> str:
    """將數字索引轉換為類別標籤（0→A, 1→B, ..., 25→Z, 26→AA, ...）"""
    result = ""
    index += 1  # 從 1 開始計算
    while index > 0:
        index -= 1
        result = chr(ord('A') + (index % 26)) + result
        index //= 26
    return result


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
        default_verification: bool | None = True,
        enable_excel_export: bool = True,
    ):
        self.root    = root
        self._api_url = api_url.rstrip("/")
        self._debug  = debug
        self._default_verification = default_verification  # 預設驗證狀態（True=正確, False=錯誤, None=未選）
        self._enable_excel_export = enable_excel_export and HAS_OPENPYXL  # Excel 匯出功能

        # --- 狀態 ---
        self.state = VerificationState()
        self.state.set_defaults(self._default_verification)  # 套用預設值
        self.current_tab: str = "cam"         # "cam" | "ai"
        self._captured_image: np.ndarray | None = None   # 拍攝原圖
        self._ai_image: np.ndarray | None = None          # YOLO 疊加圖（動態更新）
        self._detections: list = []                        # 本次偵測結果（供重繪用）
        self._is_analysed: bool = False        # 是否已完成分析

        # --- 相機 ---
        self._camera = None
        self._is_picamera = False

        # --- LED ---
        self.led_pixels = None
        self._init_led()

        # --- 抽屜感測器 ---
        self._drawer_cap              = None
        self._drawer_running          = False
        self._drawer_thread           = None
        # 狀態機：WAIT_OPEN → WAIT_CLOSE → ANALYSING → WAIT_CLOSE → ...
        # WAIT_OPEN : 開機後等待首次確認開啟（避免開機抽屜已閉誤觸）
        # WAIT_CLOSE: 已確認開啟，等待閉合以觸發分析
        # ANALYSING : 分析已觸發，鎖住直到抽屜再次確認開啟
        self._drawer_sm_state         = "WAIT_OPEN"
        self._drawer_consecutive_closed  = 0
        self._drawer_consecutive_opened  = 0
        self._drawer_close_threshold  = 5      # 連續 N 幀「完全閉合」才觸發
        self._drawer_open_threshold   = 5      # 連續 N 幀「完全開啟」才確認開啟

        # --- 視窗 ---
        self.root.title("AI藥品輔助辨識")
        self.root.configure(bg=COLOR_BG)
        if fullscreen:
            self.root.attributes("-fullscreen", True)
            self.root.bind("<Escape>", lambda e: self.root.attributes("-fullscreen", False))
        else:
            self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")

        # 暖機完成前隱藏視窗，避免使用者看到未就緒的 UI
        self.root.withdraw()

        # --- 建 UI ---
        self._build_ui()

        # --- 初始化（含感測器暖機，blocking）---
        self._init_camera()
        self._init_drawer_sensor()
        self._update_tray_id()
        self._reset_state()   # 確保 UI 為 IDLE 狀態
        
        # --- Excel 匯出檢查 ---
        if self._enable_excel_export:
            # 如果 records 資料夾中沒有問卷檔案，從專案根目錄複製
            if not EXCEL_QUESTIONNAIRE.exists():
                if EXCEL_QUESTIONNAIRE_SOURCE.exists():
                    import shutil
                    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(EXCEL_QUESTIONNAIRE_SOURCE, EXCEL_QUESTIONNAIRE)
                    print(f"[excel] 已複製問卷至 records 資料夾")
                else:
                    print(f"[excel] 警告: 找不到問卷檔案: {EXCEL_QUESTIONNAIRE_SOURCE}")
                    self._enable_excel_export = False
            else:
                print(f"[excel] 問卷檔案已就緒: {EXCEL_QUESTIONNAIRE}")
        elif not HAS_OPENPYXL:
            print("[excel] openpyxl 未安裝，Excel 匯出功能已停用")

        # --- 關閉事件 ---
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 所有初始化完成 → 顯示視窗
        self.root.deiconify()

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
    # 相機初始化
    # --------------------------------------------------------

    def _init_camera(self):
        if self._debug:
            self._camera = None
            self._is_picamera = False
            print("[camera] Debug mode: camera skipped (noise image will be used)")
            return
        try:
            from picamera2 import Picamera2
            cam = Picamera2()
            config = cam.create_still_configuration(
                main={"size": (1296, 972), "format": "BGR888"}
            )
            cam.configure(config)
            cam.start()
            # Discard initial frames so AEC/AWB can converge before first real capture
            print("[camera] AEC warmup...", flush=True)
            for _ in range(20):
                cam.capture_array()
            print("[camera] Picamera2 ready", flush=True)
            self._camera = cam
            self._is_picamera = True
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
            import yaml
            from eminent.sensors.vision2p5d import VideoCapture, MN96100CConfig

            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
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
                threshold_open=cfg['thresholds']['open'],
                threshold_closed=cfg['thresholds']['closed'],
                min_state_duration=cfg['analysis']['min_state_duration'],
                roi=cfg.get('roi', {}),
                smoothing_window=cfg['display']['smoothing_window'],
                enable_smoothing=cfg['display'].get('enable_smoothing', True),
                history_size=cfg['analysis'].get('history_size', 500),
            )
            if not self._drawer_cap.isOpened():
                raise RuntimeError("MN96100C not opened")

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
                if consecutive_failures == 1 or consecutive_failures % 10 == 0:
                    print(f"[drawer] Read failed (consecutive={consecutive_failures})", flush=True)
                if consecutive_failures >= MAX_FAILURES:
                    print("[drawer] Sensor disconnected")
                    break
                time.sleep(0.1)
                continue

            consecutive_failures = 0
            state = self._drawer_cap.state

            if self._drawer_sm_state == "WAIT_OPEN":
                # 等待連續 N 幀「完全開啟」確認抽屜已實際拉出
                if state == "完全開啟":
                    self._drawer_consecutive_opened += 1
                    if self._drawer_consecutive_opened >= self._drawer_open_threshold:
                        self._drawer_sm_state = "WAIT_CLOSE"
                        self._drawer_consecutive_opened = 0
                        self._drawer_consecutive_closed = 0
                        print("[drawer] 抽屜開啟確認，開始監控閉合", flush=True)
                        self.root.after(0, self._update_badge)
                else:
                    self._drawer_consecutive_opened = 0

            elif self._drawer_sm_state == "WAIT_CLOSE":
                # 等待連續 N 幀「完全閉合」才觸發分析
                if state == "完全閉合":
                    self._drawer_consecutive_closed += 1
                    if self._drawer_consecutive_closed >= self._drawer_close_threshold:
                        self._drawer_sm_state = "ANALYSING"
                        self._drawer_consecutive_closed = 0
                        self._drawer_consecutive_opened = 0
                        self.root.after(0, self._on_drawer_closed)
                else:
                    self._drawer_consecutive_closed = 0

            elif self._drawer_sm_state == "ANALYSING":
                # 分析鎖住期間，需連續 N 幀「完全開啟」才解鎖
                if state == "完全開啟":
                    self._drawer_consecutive_opened += 1
                    if self._drawer_consecutive_opened >= self._drawer_open_threshold:
                        self._drawer_sm_state = "WAIT_CLOSE"
                        self._drawer_consecutive_opened = 0
                        self._drawer_consecutive_closed = 0
                        print("[drawer] 抽屜重新開啟，準備下次觸發", flush=True)
                        self.root.after(0, self._reset_state)
                        # _reset_state 內部會呼叫 _update_badge，顯示「請關閉抽屜」
                else:
                    self._drawer_consecutive_opened = 0

    def _on_drawer_closed(self):
        """抽屜閉合事件（主執行緒）— 直接呼叫分析，UI 在分析期間暫停回應"""
        self._on_analyse()

    def _capture_single_frame(self) -> np.ndarray | None:
        """拍攝一幀。Picamera2 在 init 時已啟動並持續運行，直接 capture_array()。回傳 BGR (H,W,3) 或 None"""
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
                frame = self._camera.capture_array()
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

        # 品項列（藥盤總品項）
        self.variety_row = tk.Frame(inner_g, bg=COLOR_BG)
        self.variety_row.pack(fill=tk.X, pady=3)
        tk.Label(self.variety_row, text="【藥盤】總品項", bg=COLOR_BG, font=FONT_BOLD).pack(side=tk.LEFT)
        self.variety_num = tk.Label(self.variety_row, text="0", bg=COLOR_NUM_BG, font=FONT_NUM, width=4, relief=tk.FLAT, padx=4)
        self.variety_num.pack(side=tk.LEFT, padx=4)
        tk.Label(self.variety_row, text="種", bg=COLOR_BG, font=FONT_NORMAL).pack(side=tk.LEFT)
        self.variety_err_btn = self._make_check_btn(self.variety_row, "錯誤", "bad", lambda: self._set_variety(False))
        self.variety_err_btn.pack(side=tk.RIGHT, padx=2)
        self.variety_ok_btn = self._make_check_btn(self.variety_row, "正確", "ok", lambda: self._set_variety(True))
        self.variety_ok_btn.pack(side=tk.RIGHT, padx=2)

        # 總量列（藥盤總數量）
        self.total_row = tk.Frame(inner_g, bg=COLOR_BG)
        self.total_row.pack(fill=tk.X, pady=3)
        tk.Label(self.total_row, text="【藥盤】總數量", bg=COLOR_BG, font=FONT_BOLD).pack(side=tk.LEFT)
        self.total_num = tk.Label(self.total_row, text="0", bg=COLOR_NUM_BG, font=FONT_NUM, width=4, relief=tk.FLAT, padx=4)
        self.total_num.pack(side=tk.LEFT, padx=4)
        tk.Label(self.total_row, text="顆", bg=COLOR_BG, font=FONT_NORMAL).pack(side=tk.LEFT)
        self.total_err_btn = self._make_check_btn(self.total_row, "錯誤", "bad", lambda: self._set_total(False))
        self.total_err_btn.pack(side=tk.RIGHT, padx=2)
        self.total_ok_btn = self._make_check_btn(self.total_row, "正確", "ok", lambda: self._set_total(True))
        self.total_ok_btn.pack(side=tk.RIGHT, padx=2)

        # --- 單種藥品驗證區 ---
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

        # 藥品內容區（包含名稱、名稱核對、藥錠列表、總數）
        self.drug_content = tk.Frame(self.drug_frame, bg=COLOR_BG)
        self.drug_content.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))

        # 藥品名稱
        self.drug_name_label = tk.Label(
            self.drug_content, text="--",
            bg="white", fg="#111",
            font=("Microsoft JhengHei", 13),
            wraplength=350, justify=tk.LEFT,
            anchor=tk.NW, padx=8, pady=6,
            relief=tk.SOLID, bd=1,
        )
        self.drug_name_label.pack(fill=tk.X, pady=(0, 8))

        # 名稱核對列
        self.name_row = tk.Frame(self.drug_content, bg=COLOR_BG)
        self.name_row.pack(fill=tk.X, pady=3)
        tk.Label(self.name_row, text="【藥品】名稱核對", bg=COLOR_BG, font=FONT_BOLD).pack(side=tk.LEFT)
        self.name_err_btn = self._make_check_btn(self.name_row, "錯誤", "bad", lambda: self._set_name(False))
        self.name_err_btn.pack(side=tk.RIGHT, padx=2)
        self.name_ok_btn = self._make_check_btn(self.name_row, "正確", "ok", lambda: self._set_name(True))
        self.name_ok_btn.pack(side=tk.RIGHT, padx=2)

        # 藥錠列表容器（可滾動）
        self.pills_container = tk.Frame(self.drug_content, bg=COLOR_BG)
        self.pills_container.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        
        # 滾動區域
        self.pills_canvas = tk.Canvas(self.pills_container, bg=COLOR_BG, highlightthickness=0)
        self.pills_scrollbar = tk.Scrollbar(self.pills_container, orient=tk.VERTICAL, command=self.pills_canvas.yview)
        self.pills_inner = tk.Frame(self.pills_canvas, bg=COLOR_BG)
        
        self.pills_canvas.configure(yscrollcommand=self.pills_scrollbar.set)
        self.pills_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.pills_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.pills_canvas_window = self.pills_canvas.create_window((0, 0), window=self.pills_inner, anchor=tk.NW)
        
        # 綁定滾動事件
        self.pills_inner.bind("<Configure>", self._on_pills_inner_configure)
        self.pills_canvas.bind("<Configure>", self._on_pills_canvas_configure)
        self.pills_canvas.bind_all("<MouseWheel>", self._on_pills_mousewheel)
        
        # 藥錠列表（動態生成）
        self.pill_rows: list[dict] = []  # 儲存每列的 widget 參照
        
        # 總數顯示列
        self.total_pills_row = tk.Frame(self.drug_content, bg=COLOR_BG, bd=1, relief=tk.SOLID)
        self.total_pills_row.pack(fill=tk.X, pady=(8, 0))
        self.total_pills_label = tk.Label(
            self.total_pills_row, text="共計 0 顆",
            bg=COLOR_BG, font=FONT_BOLD, pady=4
        )
        self.total_pills_label.pack()

    def _on_pills_inner_configure(self, event):
        """更新滾動區域"""
        self.pills_canvas.configure(scrollregion=self.pills_canvas.bbox("all"))
    
    def _on_pills_canvas_configure(self, event):
        """調整內部 frame 寬度以填滿 canvas"""
        self.pills_canvas.itemconfig(self.pills_canvas_window, width=event.width)
    
    def _on_pills_mousewheel(self, event):
        """滾輪滾動"""
        if self.pills_canvas.winfo_height() < self.pills_inner.winfo_height():
            self.pills_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _build_pill_rows(self, category: DrugCategory):
        """動態建立當前類別的藥錠列表"""
        # 清除舊的藥錠列
        for row_data in self.pill_rows:
            row_data["frame"].destroy()
        self.pill_rows.clear()
        
        bg_color = DRUG_COLORS[category.color_idx]["bg"]
        border_color = DRUG_COLORS[category.color_idx]["border"]
        
        for i, pill in enumerate(category.pills):
            row = tk.Frame(self.pills_inner, bg=bg_color, bd=1, relief=tk.SOLID)
            row.pack(fill=tk.X, pady=2)
            
            # 編碼標籤（如 C1, C2）
            label_frame = tk.Frame(row, bg=border_color, padx=4, pady=2)
            label_frame.pack(side=tk.LEFT, padx=(4, 8), pady=4)
            label = tk.Label(
                label_frame, text=pill.full_label,
                bg=border_color, fg="white", font=FONT_BOLD
            )
            label.pack()
            
            # 數量文字
            tk.Label(row, text="數量", bg=bg_color, font=FONT_NORMAL).pack(side=tk.LEFT)
            dose_num = tk.Label(row, text="1", bg=COLOR_NUM_BG, font=FONT_NUM, width=3, padx=2)
            dose_num.pack(side=tk.LEFT, padx=4)
            tk.Label(row, text="顆", bg=bg_color, font=FONT_NORMAL).pack(side=tk.LEFT)
            
            # 正確/錯誤按鈕
            page = self.state.current_page
            pill_idx = i
            err_btn = self._make_check_btn(row, "錯誤", "bad", lambda p=page, pi=pill_idx: self._set_pill_dose(p, pi, False))
            err_btn.pack(side=tk.RIGHT, padx=2)
            ok_btn = self._make_check_btn(row, "正確", "ok", lambda p=page, pi=pill_idx: self._set_pill_dose(p, pi, True))
            ok_btn.pack(side=tk.RIGHT, padx=2)
            
            # 綁定 hover/click 事件
            detection_idx = pill.detection_idx
            row.bind("<Enter>", lambda e, idx=detection_idx: self._on_pill_hover(idx))
            row.bind("<Leave>", lambda e: self._on_pill_leave())
            row.bind("<Button-1>", lambda e, idx=detection_idx: self._on_pill_click(idx))
            # 綁定所有子元件
            for child in row.winfo_children():
                child.bind("<Enter>", lambda e, idx=detection_idx: self._on_pill_hover(idx))
                child.bind("<Leave>", lambda e: self._on_pill_leave())
                if not isinstance(child, tk.Button):  # 按鈕保留自己的點擊事件
                    child.bind("<Button-1>", lambda e, idx=detection_idx: self._on_pill_click(idx))
            
            self.pill_rows.append({
                "frame": row,
                "label": label,
                "dose_num": dose_num,
                "ok_btn": ok_btn,
                "err_btn": err_btn,
                "detection_idx": detection_idx,
            })
    
    def _on_pill_hover(self, detection_idx: int):
        """滑鼠移入藥錠列時高亮左側對應藥錠"""
        self.state.highlighted_pill = detection_idx
        self._refresh_ai_overlay()
    
    def _on_pill_leave(self):
        """滑鼠移出藥錠列時取消高亮"""
        self.state.highlighted_pill = -1
        self._refresh_ai_overlay()
    
    def _on_pill_click(self, detection_idx: int):
        """點擊藥錠列時高亮（平板用）"""
        self.state.highlighted_pill = detection_idx
        self._refresh_ai_overlay()
    
    def _refresh_ai_overlay(self):
        """重繪 AI 疊加層（用於高亮更新）"""
        if self._is_analysed and self._captured_image is not None and self._detections:
            self._ai_image = self._generate_ai_overlay(
                self._captured_image,
                self._detections,
                self.state.pills,
                highlighted_idx=self.state.highlighted_pill,
            )
            if self.current_tab == "ai":
                self._refresh_image()

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
            if self._is_analysed:
                self.badge_label.config(text="鏡頭")
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

    def _update_badge(self):
        """依抽屜狀態機與分析狀態決定左上角引導文字（主執行緒呼叫）"""
        if self._is_analysed:
            # 分析完成後由 _update_tab_buttons 決定顯示 鏡頭/AI
            self._update_tab_buttons()
            return
        sm = self._drawer_sm_state
        if self._drawer_cap is None and not self._debug:
            text = "感測器未連線"
        elif sm == "WAIT_OPEN":
            text = "請拉開抽屜"
        elif sm == "WAIT_CLOSE":
            text = "請放入藥盤並關閉抽屜"
        elif sm == "ANALYSING":
            # 分析失敗後仍在此狀態，引導使用者重拉抽屜
            text = "請重新拉開抽屜"
        else:
            text = "待分析"
        self.badge_label.config(text=text)

    def _set_status(self, text: str):
        """暫時覆寫 badge（拍攝/辨識進行中），強制重繪"""
        self.badge_label.config(text=text)
        self.root.update_idletasks()

    def _on_analyse(self):
        """抽屜閉合觸發：拍照 → 呼叫推論 API → 更新 UI（全程主執行緒）"""
        if self._is_analysed:
            return   # 正在 REVIEWING 中，忽略重複觸發

        self._set_status("拍攝中...")
        print("[analyse] Capturing frame...")
        frame = self._capture_single_frame()
        if frame is None:
            print("[analyse] Capture failed")
            self._update_badge()
            self._show_info_modal("提示", "相機拍攝失敗，請確認相機連接狀態。")
            return

        self._captured_image = frame.copy()

        self._set_status("辨識中...")
        print("[analyse] Running detection...")
        try:
            if self._debug:
                detections = self._load_sample_detections(frame)
                results    = self._debug_fake_results(len(detections))
            else:
                detections, results = self._call_api(frame)
        except requests.exceptions.ConnectionError:
            print("[analyse] API connection failed")
            self._update_badge()
            self._show_info_modal(
                "連線錯誤", f"無法連線至推論伺服器 {self._api_url}\n請確認 api.py 已啟動。")
            return
        except Exception as e:
            print(f"[analyse] Error: {e}")
            self._update_badge()
            self._show_info_modal("辨識錯誤", f"推論過程發生錯誤：{e}")
            return

        if not detections:
            print("[analyse] No pills detected")
            self._ai_image = frame.copy()
            self._is_analysed = True
            self._update_state_from_results([], [])
            self._switch_tab("cam")
            self._refresh_image()
            self.done_btn.config(state=tk.NORMAL, bg=COLOR_DONE)
            self._show_info_modal("提示", "未偵測到任何藥錠，請確認藥盤擺放位置與光線條件。")
            return

        self._update_state_from_results(detections, results)
        self._detections = detections
        self._is_analysed = True
        self._ai_image = self._generate_ai_overlay(frame, detections, self.state.pills, highlighted_idx=-1)
        self.current_tab = "ai"
        self._update_tab_buttons()
        self._refresh_image()
        self._update_info_panel()
        self.done_btn.config(state=tk.NORMAL, bg=COLOR_DONE)
        print("[analyse] Done")

    def _generate_ai_overlay(
        self,
        image: np.ndarray,
        detections: list[Detection],
        pills: list[PillEntry],
        highlighted_idx: int = -1,
    ) -> np.ndarray:
        """在原圖上疊加 YOLO 分割遮罩、邊界框與類別編碼標籤。

        配色直接取自 PillEntry.color_idx（與右側面板完全一致）。
        highlighted_idx 對應的藥錠以高透明度遮罩 + 粗框高亮顯示，
        其餘藥錠以低透明度淡化。
        標籤顯示格式為 A1, B2, C3 等類別編碼。
        """
        h_img, w_img = image.shape[:2]
        overlay = image.copy()

        # ── Pass 1：分割遮罩（highlighted 高亮，其餘淡化）──
        for i, (det, pill) in enumerate(zip(detections, pills)):
            color_bgr = (
                DRUG_COLORS[pill.color_idx]["bgr"] if pill.license
                else (128, 128, 128)
            )
            color_arr = np.array(color_bgr, dtype=np.float32)
            is_highlighted = (i == highlighted_idx)
            alpha = 0.65 if is_highlighted else 0.35

            if det.mask is not None:
                mask = det.mask
                if mask.shape != (h_img, w_img):
                    mask = cv2.resize(mask, (w_img, h_img), interpolation=cv2.INTER_NEAREST)
                mb = mask > 0
                overlay[mb] = (
                    overlay[mb].astype(np.float32) * (1 - alpha) + color_arr * alpha
                ).clip(0, 255).astype(np.uint8)

        # ── Pass 2：邊界框 + 類別編碼標籤 ──
        for i, (det, pill) in enumerate(zip(detections, pills)):
            color_bgr = (
                DRUG_COLORS[pill.color_idx]["bgr"] if pill.license
                else (128, 128, 128)
            )
            is_highlighted = (i == highlighted_idx)
            x1, y1, x2, y2 = det.bbox

            # 邊界框：highlighted 粗框，其餘細框
            thickness = 4 if is_highlighted else 2
            cv2.rectangle(overlay, (x1, y1), (x2, y2), color_bgr, thickness)

            # 類別編碼標籤（圓角矩形背景 + 白色文字）
            label = pill.full_label or "?"
            font_scale = 0.6 if is_highlighted else 0.5
            font_thickness = 2 if is_highlighted else 1
            (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thickness)
            
            # 標籤位置（左上角）
            pad = 4
            lx1 = x1
            ly1 = y1
            lx2 = x1 + tw + pad * 2
            ly2 = y1 + th + pad * 2 + baseline
            
            # 繪製標籤背景
            cv2.rectangle(overlay, (lx1, ly1), (lx2, ly2), color_bgr, -1)
            cv2.rectangle(overlay, (lx1, ly1), (lx2, ly2), (255, 255, 255), 1)
            
            # 繪製標籤文字
            cv2.putText(
                overlay, label,
                (lx1 + pad, ly1 + th + pad),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                (255, 255, 255), font_thickness, cv2.LINE_AA,
            )

        return overlay

    def _update_state_from_results(
        self,
        detections: list[Detection],
        results: list[MatchResult | None],
    ):
        """由偵測結果更新 VerificationState。

        每顆偵測藥錠建立一筆 PillEntry（含未識別），
        藥品種類以 license_number 去重建立 DrugCategory。
        """
        # 分配每個 license 的配色與類別標籤（首次出現順序）
        license_info: dict[str, dict] = {}  # license -> {color_idx, category_label, name}
        category_counter = 0
        for r in results:
            if r and r.license_number not in license_info:
                license_info[r.license_number] = {
                    "color_idx": category_counter % len(DRUG_COLORS),
                    "category_label": get_category_label(category_counter),
                    "name": r.name,
                }
                category_counter += 1
        
        # 為未識別藥品分配一個特殊類別
        unidentified_label = get_category_label(category_counter) if any(r is None for r in results) else ""
        
        # 統計每個 license 出現幾顆
        license_count: dict[str, int] = {}
        for r in results:
            if r:
                license_count[r.license_number] = license_count.get(r.license_number, 0) + 1

        # 追蹤每個類別中的藥錠序號
        category_pill_counter: dict[str, int] = {}  # license/category -> 當前計數
        
        # 每顆 detection 建立一筆 PillEntry
        pills: list[PillEntry] = []
        for i, r in enumerate(results):
            if r is None:
                # 未識別藥品
                cat_key = "__unidentified__"
                category_pill_counter[cat_key] = category_pill_counter.get(cat_key, 0) + 1
                pills.append(PillEntry(
                    license="",
                    name="未識別",
                    same_count=1,
                    color_idx=len(DRUG_COLORS) - 1,
                    category_label=unidentified_label,
                    index_in_category=category_pill_counter[cat_key],
                    detection_idx=i,
                ))
            else:
                info = license_info[r.license_number]
                category_pill_counter[r.license_number] = category_pill_counter.get(r.license_number, 0) + 1
                pills.append(PillEntry(
                    license=r.license_number,
                    name=r.name,
                    same_count=license_count.get(r.license_number, 1),
                    color_idx=info["color_idx"],
                    category_label=info["category_label"],
                    index_in_category=category_pill_counter[r.license_number],
                    detection_idx=i,
                ))

        # 建立 DrugCategory 列表（按首次出現順序）
        categories: list[DrugCategory] = []
        seen_licenses: set[str] = set()
        
        for pill in pills:
            cat_key = pill.license if pill.license else "__unidentified__"
            if cat_key not in seen_licenses:
                seen_licenses.add(cat_key)
                # 收集該類別的所有藥錠
                cat_pills = [p for p in pills if (p.license if p.license else "__unidentified__") == cat_key]
                categories.append(DrugCategory(
                    license=pill.license,
                    name=pill.name,
                    category_label=pill.category_label,
                    color_idx=pill.color_idx,
                    pills=cat_pills,
                ))

        self.state.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state.variety_count = len(categories)
        self.state.total_count = len(pills)
        self.state.pills = pills
        self.state.categories = categories
        self.state.current_page = 0
        self.state.highlighted_pill = -1
        
        # 套用預設驗證狀態
        self.state.set_defaults(self._default_verification)

    # --------------------------------------------------------
    # 資訊面板更新
    # --------------------------------------------------------

    def _update_info_panel(self):
        """更新右側資訊面板（按藥品類別分頁）"""
        self.variety_num.config(text=str(self.state.variety_count))
        self.total_num.config(text=str(self.state.total_count))

        if self.state.categories and 0 <= self.state.current_page < len(self.state.categories):
            category = self.state.categories[self.state.current_page]
            
            # 更新藥品名稱
            self.drug_name_label.config(text=category.name or "--")
            
            # 更新分頁標籤
            self.page_label.config(
                text=f"第 {self.state.current_page + 1} 項 / 共 {len(self.state.categories)} 項"
            )
            
            # 更新框架顏色
            c = DRUG_COLORS[category.color_idx]
            self.drug_frame.config(highlightbackground=c["border"], bg=c["bg"])
            self.drug_content.config(bg=c["bg"])
            self.name_row.config(bg=c["bg"])
            self.total_pills_row.config(bg=c["bg"])
            self.total_pills_label.config(bg=c["bg"])
            for w in self.name_row.winfo_children():
                try:
                    if not isinstance(w, tk.Button):
                        w.config(bg=c["bg"])
                except Exception:
                    pass
            
            # 動態建立藥錠列表
            self._build_pill_rows(category)
            
            # 更新總數顯示
            self.total_pills_label.config(text=f"共計 {category.total_count} 顆")
            
        else:
            self.drug_name_label.config(text="--")
            self.page_label.config(text="第 0 項 / 共 0 項")
            self.drug_frame.config(highlightbackground="#ffdd55", bg=COLOR_BG)
            self.total_pills_label.config(text="共計 0 顆")
            # 清空藥錠列表
            for row_data in self.pill_rows:
                row_data["frame"].destroy()
            self.pill_rows.clear()

        self._update_button_states()
        self._update_nav_buttons()
        self._clear_highlights()

        # 重繪 overlay
        if (self._is_analysed and self._detections
                and self._captured_image is not None
                and self.state.pills):
            self._ai_image = self._generate_ai_overlay(
                self._captured_image,
                self._detections,
                self.state.pills,
                highlighted_idx=self.state.highlighted_pill,
            )
            if self.current_tab == "ai":
                self._refresh_image()

    def _update_button_states(self):
        """更新所有正確/錯誤按鈕的視覺狀態"""
        self._apply_btn_state(self.variety_ok_btn, self.variety_err_btn, self.state.variety_correct)
        self._apply_btn_state(self.total_ok_btn, self.total_err_btn, self.state.total_correct)
        
        # 名稱核對按鈕（per category）
        if self.state.categories and 0 <= self.state.current_page < len(self.state.categories):
            self._apply_btn_state(self.name_ok_btn, self.name_err_btn,
                                  self.state.name_answers[self.state.current_page])
            # 更新每顆藥錠的按鈕狀態
            self._update_pill_row_button_states()
        else:
            self._apply_btn_state(self.name_ok_btn, self.name_err_btn, None)
    
    def _update_pill_row_button_states(self):
        """更新藥錠列表中每列的按鈕狀態"""
        page = self.state.current_page
        if page < 0 or page >= len(self.state.dose_answers):
            return
        
        dose_answers_for_page = self.state.dose_answers[page]
        for i, row_data in enumerate(self.pill_rows):
            if i < len(dose_answers_for_page):
                self._apply_btn_state(
                    row_data["ok_btn"],
                    row_data["err_btn"],
                    dose_answers_for_page[i]
                )

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
        """更新分頁導航按鈕狀態（按類別分頁）"""
        total = len(self.state.categories)
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
        """設定當前類別的名稱核對結果"""
        if self.state.categories and 0 <= self.state.current_page < len(self.state.categories):
            self.state.name_answers[self.state.current_page] = value
            self._update_button_states()
            self._clear_highlight(self.name_row)
            self._auto_switch_ai()

    def _set_pill_dose(self, page: int, pill_idx: int, value: bool):
        """設定指定藥錠的數量核對結果"""
        if 0 <= page < len(self.state.dose_answers):
            if 0 <= pill_idx < len(self.state.dose_answers[page]):
                self.state.dose_answers[page][pill_idx] = value
                self._update_pill_row_button_states()
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
            self.state.highlighted_pill = -1  # 清除高亮
            self._update_info_panel()
            self._auto_switch_ai()

    def _next_drug(self):
        if self.state.current_page < len(self.state.categories) - 1:
            self.state.current_page += 1
            self.state.highlighted_pill = -1  # 清除高亮
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
        for row in [self.variety_row, self.total_row, self.name_row]:
            self._clear_highlight(row)

    # --------------------------------------------------------
    # 「完成」邏輯
    # --------------------------------------------------------

    def _find_first_missing(self) -> tuple[str, int, int] | None:
        """找第一筆未填項目，回傳 (欄位類型, 類別索引, 藥錠索引) 或 None（全填完）"""
        if self.state.variety_correct is None:
            return ("variety", self.state.current_page, -1)
        if self.state.total_correct is None:
            return ("total", self.state.current_page, -1)
        # name_answers：每個類別一個
        for i, ans in enumerate(self.state.name_answers):
            if ans is None:
                return ("name", i, -1)
        # dose_answers：每個類別下的每顆藥錠
        for cat_idx, cat_answers in enumerate(self.state.dose_answers):
            for pill_idx, ans in enumerate(cat_answers):
                if ans is None:
                    return ("dose", cat_idx, pill_idx)
        return None

    def _on_done(self):
        self._show_review_modal()

    def _show_review_modal(self):
        """填報總覽 Modal：顯示所有答案，確認送出才寫入磁碟"""
        MODAL_W, MODAL_H = 500, 560
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
                     anchor=tk.W, width=24).pack(side=tk.LEFT, padx=8, pady=4)
            ans_txt, ans_col = answer_style(value)
            tk.Label(row, text=ans_txt, font=FONT_BOLD, bg=bg,
                     fg=ans_col).pack(side=tk.RIGHT, padx=8)

        global_bg = "#f8f8f8"
        add_row(inner, f"【藥盤】總品項　{self.state.variety_count} 種", self.state.variety_correct, global_bg)
        add_row(inner, f"【藥盤】總數量　{self.state.total_count} 顆", self.state.total_correct, global_bg)
        tk.Frame(inner, bg="#ccc", height=1).pack(fill=tk.X, padx=8, pady=4)

        # 按類別顯示
        for cat_idx, category in enumerate(self.state.categories):
            c = DRUG_COLORS[category.color_idx]
            drug_bg = c["bg"]
            
            # 類別標題
            hdr = tk.Frame(inner, bg=drug_bg,
                           highlightbackground=c["border"], highlightthickness=2)
            hdr.pack(fill=tk.X, padx=8, pady=(6, 0))
            tk.Label(hdr, text=f"【{category.category_label}】{category.name or '未識別'}",
                     font=FONT_BOLD, bg=drug_bg, fg="#333",
                     wraplength=440, justify=tk.LEFT, anchor=tk.W,
                     padx=8, pady=4).pack(fill=tk.X)
            
            # 名稱核對
            add_row(inner, "　　名稱核對", self.state.name_answers[cat_idx] if cat_idx < len(self.state.name_answers) else None, drug_bg)
            
            # 每顆藥錠的數量核對
            dose_answers_for_cat = self.state.dose_answers[cat_idx] if cat_idx < len(self.state.dose_answers) else []
            for pill_idx, pill in enumerate(category.pills):
                ans = dose_answers_for_cat[pill_idx] if pill_idx < len(dose_answers_for_cat) else None
                add_row(inner, f"　　{pill.full_label} 數量核對", ans, drug_bg)
            
            # 小計
            tk.Label(inner, text=f"　　共計 {category.total_count} 顆", 
                     font=FONT_NORMAL, bg=drug_bg, fg="#666", anchor=tk.W,
                     padx=8, pady=2).pack(fill=tk.X)

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
                missing_type, cat_idx, pill_idx = missing
                self.state.current_page = cat_idx
                self._update_info_panel()
                row_map = {
                    "variety": self.variety_row,
                    "total":   self.total_row,
                    "name":    self.name_row,
                }
                if missing_type in row_map:
                    self._highlight_missing(row_map[missing_type])
                # 如果是 dose 類型，高亮對應的藥錠列
                elif missing_type == "dose" and pill_idx >= 0 and pill_idx < len(self.pill_rows):
                    self._highlight_missing(self.pill_rows[pill_idx]["frame"])

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
        import yaml
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
                "dose_correct": self.state.dose_answers[i],
            }

        yaml_path = RECORDS_DIR / f"{tray_id}.yaml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False)
        print(f"[save] {yaml_path}")

        # 儲存三種圖片：原始圖、AI 標記圖
        if self._captured_image is not None:
            raw_img_path = RECORDS_DIR / f"{tray_id}_raw.jpg"
            cv2.imwrite(str(raw_img_path), self._captured_image)
            print(f"[save] {raw_img_path}")
        
        if self._ai_image is not None:
            ai_img_path = RECORDS_DIR / f"{tray_id}_marked.jpg"
            cv2.imwrite(str(ai_img_path), self._ai_image)
            print(f"[save] {ai_img_path}")
        
        # --- Excel 問卷自動填寫 ---
        if self._enable_excel_export:
            try:
                self._export_to_excel(tray_id)
            except Exception as e:
                print(f"[excel] 匯出失敗: {e}")
                import traceback
                traceback.print_exc()
                # 不中斷流程，只記錄錯誤
    
    def _export_to_excel(self, tray_id: str):
        """將驗證結果匯出至 Excel 問卷"""
        if not EXCEL_QUESTIONNAIRE.exists():
            print(f"[excel] 問卷檔案不存在: {EXCEL_QUESTIONNAIRE}")
            return
        
        # 建立備份（首次寫入時）
        backup_dir = RECORDS_DIR / "excel_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            writer = ExcelWriter(EXCEL_QUESTIONNAIRE)
            
            # 寫入驗證資料
            writer.write_verification_data(
                tray_id=self.state.tray_id,
                timestamp=self.state.timestamp,
                variety_count=self.state.variety_count,
                variety_correct=self.state.variety_correct,
                total_count=self.state.total_count,
                total_correct=self.state.total_correct,
                pills=self.state.pills,
                name_answers=self.state.name_answers,
                dose_answers=self.state.dose_answers,
                image_path=f"{tray_id}_raw.jpg"  # 相對於 Excel 檔案的路徑
            )
            
            # 儲存
            writer.save()
            writer.close()
            
            print(f"[excel] 已成功匯出至問卷")
            
        except Exception as e:
            print(f"[excel] 寫入錯誤: {e}")
            raise

    def _reset_feedback(self):
        """只重置回饋回答，保留辨識結果"""
        self.state.variety_correct = None
        self.state.total_correct = None
        self.state.name_answers = [None] * len(self.state.categories)
        self.state.dose_answers = [
            [None] * len(cat.pills) for cat in self.state.categories
        ]
        self.state.current_page = 0
        self.state.highlighted_pill = -1
        self._update_info_panel()

    def _reset_state(self):
        """完整重置至 IDLE 狀態（黑畫面）"""
        self._captured_image = None
        self._ai_image = None
        self._detections = []
        self._is_analysed = False

        self.state = VerificationState()
        self.state.set_defaults(self._default_verification)  # 重置時也套用預設值
        self._update_tray_id()

        self.current_tab = "cam"
        self._update_tab_buttons()
        self.image_label.config(image="", bg="#000")
        self.image_label.image = None
        self._update_badge()

        self.variety_num.config(text="0")
        self.total_num.config(text="0")
        self.drug_name_label.config(text="--")
        self.total_pills_label.config(text="共計 0 顆")
        self.page_label.config(text="第 0 項 / 共 0 項")
        
        # 清空藥錠列表
        for row_data in self.pill_rows:
            row_data["frame"].destroy()
        self.pill_rows.clear()
        
        self._update_button_states()
        self._update_nav_buttons()
        self._clear_highlights()
        self.drug_frame.config(highlightbackground="#ffdd55", bg=COLOR_BG)
        self.drug_content.config(bg=COLOR_BG)

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
                    self._camera.stop()
                    self._camera.close()
                else:
                    self._camera.release()
            except Exception:
                pass
        self.root.destroy()


__all__ = ["App", "DRUG_COLORS", "RECORDS_DIR", "PillEntry", "DrugCategory", "VerificationState", "get_category_label"]
