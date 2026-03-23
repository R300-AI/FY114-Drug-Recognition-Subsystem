#!/usr/bin/env python3
"""
app.py — FY114 藥物辨識子系統 v3.0

v3 改版重點：
  - 抽屜感測器（MN96100C）自動觸發分析（邊緣觸發：開→閉）
  - AppState 狀態機（IDLE / ANALYSING / REVIEWING）
  - 以「藥種」為分頁單位（DrugPage），每顆獨立確認（DrugItem）
  - 虛擬捲動：▲▼ 箭頭逐列捲動，overflow 才顯示
  - 左圖 Hotspot highlight：hover/點擊 dose 列 → 框選對應藥錠
  - In-place backdrop Modal + Toast（取代 Tkinter Toplevel）
  - MN96100C 不存在時自動顯示手動「分析」按鈕作為 fallback

使用方式：
  python app.py                # 視窗模式（開發測試）
  python app.py --fullscreen   # 全螢幕（觸控螢幕部署）
  python app.py --debug        # 除錯模式（無硬體，用樣本圖）
"""

import argparse
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

import cv2
import numpy as np
import tkinter as tk
import yaml
from PIL import Image, ImageTk

from utils.detector import BaseDetector
from utils.encoder import BaseEncoder
from utils.matcher import BaseMatcher
from utils.gallery import Gallery
from utils.types import Detection, MatchResult
from utils.depth_analysis import DepthAnalyzer, DrawerStateDetector

try:
    import board
    import neopixel
    HAS_LED = True
except ImportError:
    HAS_LED = False


# ============================================================
# 常數
# ============================================================

RECORDS_DIR = Path("records")

DRUG_COLORS = [
    {"border": "#ffdd55", "bg": "#fff9e0", "bgr": (85, 221, 255)},
    {"border": "#7fd37f", "bg": "#f0faf0", "bgr": (127, 211, 127)},
    {"border": "#ff9f4a", "bg": "#fff4ec", "bgr": (74, 159, 255)},
    {"border": "#6aa6ff", "bg": "#eef4ff", "bgr": (255, 166, 106)},
    {"border": "#b07cff", "bg": "#f5f0ff", "bgr": (255, 124, 176)},
]

COLOR_TOPBAR    = "#1f2f46"
COLOR_PRIMARY   = "#2196F3"
COLOR_DONE      = "#ffd95b"
COLOR_BG        = "#d9d9d9"
COLOR_DRUG_NAME = "#81C7D4"
COLOR_NUM_BG    = "#58B2DC"
COLOR_BTN_OK    = "#d8f1d8"
COLOR_BTN_OK_T  = "#1f6b1f"
COLOR_BTN_BAD   = "#f6caca"
COLOR_BTN_BAD_T = "#8b0000"
COLOR_BACKDROP  = "#1a1a1a"

FONT_TITLE  = ("Microsoft JhengHei", 13, "bold")
FONT_NORMAL = ("Microsoft JhengHei", 11)
FONT_BOLD   = ("Microsoft JhengHei", 11, "bold")
FONT_NUM    = ("Microsoft JhengHei", 14, "bold")
FONT_BTN    = ("Microsoft JhengHei", 12, "bold")
FONT_DRUG   = ("Microsoft JhengHei", 12)
FONT_TOAST  = ("Microsoft JhengHei", 20, "bold")

DOSE_ROW_H = 72   # 每個 dose 列的固定高度（px）


# ============================================================
# 狀態機
# ============================================================

class AppState(Enum):
    IDLE      = auto()   # 黑畫面，等待抽屜觸發
    ANALYSING = auto()   # 拍照 + 偵測 + 比對進行中
    REVIEWING = auto()   # 顯示結果，護理師填報中


# ============================================================
# v3 資料模型
# ============================================================

@dataclass
class DrugItem:
    key:       str    # "A1", "A2", "B1"…
    count:     int    # 顆數（此版本固定為 1）
    color_bgr: tuple  # OpenCV BGR（overlay 用）
    color_hex: str    # hex（UI badge 用）
    crop_img:  object # np.ndarray | None（56×56 BGR，來自原圖裁切）
    bbox_pct:  tuple  # (left%, top%, w%, h%)（hotspot 相對位置）
    det_index: int    # 在 detections list 中的索引


@dataclass
class DrugPage:
    code:           str   # "A", "B"…
    title:          str   # 藥品全名
    license_number: str
    items:          list  # list[DrugItem]


@dataclass
class VerificationState:
    tray_id:          str  = ""
    timestamp:        str  = ""
    total_kinds:      int  = 0
    total_pills:      int  = 0
    variety_correct:  object = None   # bool | None
    total_correct:    object = None   # bool | None
    drugs:            list  = field(default_factory=list)   # list[DrugPage]
    current_drug_index: int = 0
    name_answers:     list  = field(default_factory=list)   # list[bool | None]
    dose_answers:     dict  = field(default_factory=dict)   # {item.key: bool | None}


# ============================================================
# 輔助函式
# ============================================================

def get_next_serial_number() -> str:
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
# 預設偵測器（同 run.py）
# ============================================================

class YOLODetector(BaseDetector):
    min_area = 100

    def __init__(self, model_path="src/best.pt", conf=0.25):
        self.model_path = Path(model_path)
        self._conf = conf
        self._model = None

    def _ensure_loaded(self):
        if self._model is not None:
            return True
        if not self.model_path.exists():
            print(f"[detector] Model not found: {self.model_path}")
            return False
        try:
            from ultralytics import YOLO
            self._model = YOLO(str(self.model_path), verbose=False)
            return True
        except Exception as e:
            print(f"[detector] Load error: {e}")
            return False

    def forward(self, image: np.ndarray) -> list:
        if not self._ensure_loaded():
            return []
        try:
            results = self._model.predict(source=image, conf=self._conf, verbose=False)
            if not results or results[0].masks is None:
                return []
            result = results[0]
            h, w = image.shape[:2]
            detections = []
            for idx in range(int(result.masks.data.shape[0])):
                mask = result.masks.data[idx].detach().cpu().numpy()
                mask = (mask > 0.5).astype(np.uint8)
                if mask.shape != (h, w):
                    mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
                contours, _ = cv2.findContours(
                    mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if not contours:
                    continue
                cnt = max(contours, key=cv2.contourArea)
                x, y, bw, bh = cv2.boundingRect(cnt)
                detections.append(Detection(
                    bbox=(x, y, x + bw, y + bh),
                    mask=mask,
                    confidence=float(result.boxes.conf[idx]),
                    class_id=int(result.boxes.cls[idx]),
                ))
            detections.sort(key=lambda d: d.area, reverse=True)
            return detections
        except Exception as e:
            print(f"[detector] Predict error: {e}")
            return []


# ============================================================
# 預設編碼器（同 run.py）
# ============================================================

class ResNet34Encoder(BaseEncoder):
    FEATURE_DIM = 512
    INPUT_SIZE  = 224

    def __init__(self):
        self._model     = None
        self._device    = None
        self._transform = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        import torch
        import torchvision.models as models
        from torchvision import transforms
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        base = models.resnet34(weights=models.ResNet34_Weights.IMAGENET1K_V1)
        self._model = torch.nn.Sequential(*list(base.children())[:-1])
        self._model = self._model.to(self._device).eval()
        self._transform = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((self.INPUT_SIZE, self.INPUT_SIZE)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                  std=[0.229, 0.224, 0.225]),
        ])

    def forward(self, image: np.ndarray) -> np.ndarray:
        self._ensure_loaded()
        import torch
        img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        tensor = self._transform(img_rgb).unsqueeze(0).to(self._device)
        with torch.no_grad():
            feat = self._model(tensor).flatten(1)
        return feat.cpu().numpy().astype(np.float32).flatten()


# ============================================================
# 預設比對器（同 run.py）
# ============================================================

class Top1Matcher(BaseMatcher):
    def __init__(self, gallery: Gallery, threshold: float = 0.0):
        super().__init__(gallery)
        self.threshold = threshold

    def forward(self, feature: np.ndarray):
        scores = np.dot(self.gallery.features, feature)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        if best_score < self.threshold:
            return None
        meta = self.gallery.get_metadata(best_idx)
        return MatchResult(
            license_number=meta.get("license_number", ""),
            name=meta.get("name", ""),
            side=meta.get("side", 0),
            score=best_score,
        )


# ============================================================
# AppV3
# ============================================================

class AppV3:
    WINDOW_WIDTH  = 1024
    WINDOW_HEIGHT = 600

    # 藥品面板內固定元素高度合計（名稱 + 名稱核對 + 共計 + footer + padding）
    _PANEL_FIXED_H = 88 + 44 + 30 + 52 + 60

    def __init__(
        self,
        root: tk.Tk,
        gallery: Gallery,
        encoder: BaseEncoder,
        matcher: BaseMatcher,
        detector: BaseDetector,
        fullscreen: bool = False,
        debug: bool = False,
    ):
        self.root     = root
        self.gallery  = gallery
        self.encoder  = encoder
        self.matcher  = matcher
        self.detector = detector
        self._debug   = debug

        # --- 狀態機 ---
        self._app_state = AppState.IDLE

        # --- 驗證資料 ---
        self.state = VerificationState()

        # --- 影像 ---
        self._captured_image: np.ndarray | None = None
        self._ai_image:       np.ndarray | None = None
        self._detections:     list = []
        self._is_analysed:    bool = False

        # --- Tab ---
        self.current_tab: str = "cam"

        # --- 相機 ---
        self._camera      = None
        self._is_picamera = False

        # --- 藥品圖示 PhotoImage 參考（防止 GC）---
        self._dose_icon_refs: list = []

        # --- LED ---
        self.led_pixels = None

        # --- 抽屜感測器 ---
        self._drawer_cap        = None
        self._drawer_analyzer   = None
        self._drawer_detector   = None
        self._drawer_cfg        = {}
        self._drawer_history    = deque(maxlen=500)
        self._drawer_prev_state = None
        self._drawer_running    = False
        self._drawer_thread     = None
        self._drawer_sma_win    = 10

        # --- 虛擬捲動 ---
        self._dose_scroll_offset: int = 0
        self._dose_visible_count: int = 2
        self._dose_frame_h_prev:  int = 0   # 防止重複計算

        # --- 缺漏標記 ---
        self._missing_key: str | None = None

        # --- 視窗 ---
        self.root.title("AI藥品輔助辨識 v3")
        self.root.configure(bg=COLOR_BG)
        if fullscreen:
            self.root.attributes("-fullscreen", True)
            self.root.bind("<Escape>",
                           lambda e: self.root.attributes("-fullscreen", False))
        else:
            self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")

        # --- 建 UI ---
        self._build_ui()

        # --- 初始化硬體 ---
        self._init_led()
        self._init_camera()
        self._init_drawer_sensor()   # 內部決定是否顯示手動分析按鈕

        # --- 初始化顯示 ---
        self._update_tray_id()
        self._reset_state()

        # --- 關閉事件 ---
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # --------------------------------------------------------
    # LED
    # --------------------------------------------------------

    def _init_led(self):
        if self._debug or not HAS_LED:
            return
        try:
            self.led_pixels = neopixel.NeoPixel(board.D18, 24)
            self.led_pixels.fill((255, 255, 255))
            print("[light] LED Ring ON")
        except Exception as e:
            print(f"[light] LED init failed: {e}")

    # --------------------------------------------------------
    # 相機
    # --------------------------------------------------------

    def _init_camera(self):
        if self._debug:
            print("[camera] Debug mode: camera skipped")
            return
        try:
            from picamera2 import Picamera2
            self._camera = Picamera2()
            self._is_picamera = True
            print("[camera] Picamera2 ready")
        except ImportError:
            cap = cv2.VideoCapture(0)
            if cap.isOpened():
                self._camera = cap
                self._is_picamera = False
                print("[camera] OpenCV camera ready")
            else:
                cap.release()
                print("[camera] Warning: no camera available")

    def _capture_single_frame(self) -> np.ndarray | None:
        if self._debug:
            sample = Path("src/sample/sample.jpg")
            if sample.exists():
                img = cv2.imread(str(sample))
                if img is not None:
                    return img
            return np.random.randint(0, 256, (720, 960, 3), dtype=np.uint8)
        if self._camera is None:
            return None
        try:
            if self._is_picamera:
                cfg = self._camera.create_still_configuration(
                    main={"size": (1296, 972), "format": "BGR888"})
                self._camera.configure(cfg)
                self._camera.start()
                time.sleep(0.5)
                frame = self._camera.capture_array()
                self._camera.stop()
                if frame is None:
                    return None
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
    # 抽屜感測器
    # --------------------------------------------------------

    def _init_drawer_sensor(self):
        if self._debug:
            print("[drawer] Debug mode: sensor skipped, Space = simulate drawer close")
            self.root.bind("<space>", lambda e: self._on_drawer_closed())
            self._set_sensor_status("除錯模式：按 Space 模擬抽屜關閉")
            return

        cfg_path = Path("config/drawer_config.yaml")
        if not cfg_path.exists():
            print("[drawer] drawer_config.yaml not found")
            self._set_sensor_status("⚠ 未偵測到感測器設定")
            return

        try:
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            from eminent.sensors.vision2p5d import VideoCapture, MN96100CConfig

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

            self._drawer_cfg      = cfg
            self._drawer_analyzer = DepthAnalyzer()
            self._drawer_detector = DrawerStateDetector(
                threshold_open=cfg['thresholds']['open'],
                threshold_closed=cfg['thresholds']['closed'],
                min_state_duration=cfg['analysis']['min_state_duration'],
            )
            self._drawer_sma_win = cfg['display'].get('smoothing_window', 10)

            self._start_drawer_monitoring()
            self._set_sensor_status("")   # 正常：清空狀態文字
            print("[drawer] MN96100C ready, monitoring started")

        except Exception as e:
            print(f"[drawer] Init failed: {e}")
            self._drawer_cap = None
            self._set_sensor_status("⚠ 感測器無法連線")

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
                    self.root.after(0, self._on_drawer_disconnect)
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

                n = self._drawer_sma_win
                recent = list(self._drawer_history)[-n:]
                sma = sum(recent) / len(recent)

                new_state = self._drawer_detector.update(sma)

                # 邊緣觸發：「非完全閉合」→「完全閉合」
                if (self._drawer_prev_state is not None
                        and self._drawer_prev_state != "完全閉合"
                        and new_state == "完全閉合"):
                    self.root.after(0, self._on_drawer_closed)

                self._drawer_prev_state = new_state

            except Exception as e:
                print(f"[drawer] Loop error: {e}")

    def _on_drawer_closed(self):
        """抽屜閉合事件（UI 執行緒）"""
        if self._app_state != AppState.IDLE:
            return
        self._on_analyse()

    def _on_drawer_disconnect(self):
        self._set_sensor_status("⚠ 感測器已斷線")
        from tkinter import messagebox
        messagebox.showerror(
            "感測器斷線",
            "MN96100C 2.5D 感測器已斷線，請檢查 USB 連接。")

    def _set_sensor_status(self, text: str):
        if hasattr(self, 'sensor_status_label'):
            self.sensor_status_label.config(text=text)

    # --------------------------------------------------------
    # UI 建置
    # --------------------------------------------------------

    def _build_ui(self):
        self._build_topbar()
        self._build_content()

    def _build_topbar(self):
        topbar = tk.Frame(self.root, bg=COLOR_TOPBAR, height=52)
        topbar.pack(fill=tk.X)
        topbar.pack_propagate(False)

        tk.Label(topbar, text="AI藥品輔助辨識",
                 bg=COLOR_TOPBAR, fg="white", font=FONT_TITLE
                 ).pack(side=tk.LEFT, padx=(14, 18))

        self.tab_cam = tk.Button(topbar, text="鏡頭", font=FONT_BTN, width=7,
                                  command=lambda: self._switch_tab("cam"))
        self.tab_cam.pack(side=tk.LEFT, padx=3, pady=8)

        self.tab_ai = tk.Button(topbar, text="AI", font=FONT_BTN, width=7,
                                 command=lambda: self._switch_tab("ai"))
        self.tab_ai.pack(side=tk.LEFT, padx=3, pady=8)

        # 右側：完成
        self.done_btn = tk.Button(topbar, text="完成", font=FONT_BTN, width=7,
                                   bg=COLOR_DONE, fg="#333", relief=tk.FLAT,
                                   command=self._on_done)
        self.done_btn.pack(side=tk.RIGHT, padx=(4, 14), pady=8)

        # 右側：感測器狀態指示（正常時不顯示；斷線或不可用時顯示警告）
        self.sensor_status_label = tk.Label(
            topbar, text="", bg=COLOR_TOPBAR, fg="#ffcc44", font=FONT_NORMAL)
        self.sensor_status_label.pack(side=tk.RIGHT, padx=(0, 8))

        # 時間
        self.time_label = tk.Label(topbar, text="",
                                    bg=COLOR_TOPBAR, fg="white", font=FONT_NORMAL)
        self.time_label.pack(side=tk.RIGHT, padx=(0, 14))
        self._update_time()

        # 藥盤序號
        self.tray_label = tk.Label(topbar, text="------",
                                    bg="#eaf2ff", fg="#111",
                                    font=FONT_BOLD, width=12, padx=6)
        self.tray_label.pack(side=tk.RIGHT)
        tk.Label(topbar, text="藥盤序號：",
                 bg=COLOR_TOPBAR, fg="white", font=FONT_NORMAL
                 ).pack(side=tk.RIGHT, padx=(8, 2))

    def _build_content(self):
        content = tk.Frame(self.root, bg=COLOR_BG)
        content.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # ── 左側影像 ──
        self.left_panel = tk.Frame(content, bg="#000")
        self.left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.image_label = tk.Label(self.left_panel, bg="#000", image="")
        self.image_label.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.badge_label = tk.Label(self.left_panel, text="待分析",
                                     bg="white", fg="#111", font=FONT_BOLD,
                                     padx=8, pady=4, relief=tk.SOLID, bd=1)
        self.badge_label.place(x=10, y=10)

        # Hotspot 框（初始隱藏）
        self._hl_rect = tk.Frame(
            self.left_panel, bg="",
            highlightbackground="#ff3333",
            highlightthickness=3,
        )

        # ── 右側面板 ──
        self.right_panel = tk.Frame(content, bg=COLOR_BG, width=400)
        self.right_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(12, 0))
        self.right_panel.pack_propagate(False)
        self._build_right_panel()

    def _build_right_panel(self):
        # 全域摘要
        gf = tk.Frame(self.right_panel, bg=COLOR_BG, bd=1, relief=tk.SOLID)
        gf.pack(fill=tk.X, pady=(0, 8))
        inner_g = tk.Frame(gf, bg=COLOR_BG)
        inner_g.pack(fill=tk.X, padx=10, pady=6)

        self.variety_row = tk.Frame(inner_g, bg=COLOR_BG)
        self.variety_row.pack(fill=tk.X, pady=2)
        tk.Label(self.variety_row, text="【藥盤】總品項",
                 bg=COLOR_BG, font=FONT_BOLD).pack(side=tk.LEFT)
        self.variety_num = tk.Label(self.variety_row, text="0",
                                     bg=COLOR_NUM_BG, fg="#111",
                                     font=FONT_NUM, width=4, padx=4)
        self.variety_num.pack(side=tk.LEFT, padx=4)
        tk.Label(self.variety_row, text="種",
                 bg=COLOR_BG, font=FONT_NORMAL).pack(side=tk.LEFT)
        self.variety_err_btn = self._make_check_btn(
            self.variety_row, "錯誤", "bad", lambda: self._set_variety(False))
        self.variety_err_btn.pack(side=tk.RIGHT, padx=2)
        self.variety_ok_btn = self._make_check_btn(
            self.variety_row, "正確", "ok", lambda: self._set_variety(True))
        self.variety_ok_btn.pack(side=tk.RIGHT, padx=2)

        self.total_row = tk.Frame(inner_g, bg=COLOR_BG)
        self.total_row.pack(fill=tk.X, pady=2)
        tk.Label(self.total_row, text="【藥盤】總數量",
                 bg=COLOR_BG, font=FONT_BOLD).pack(side=tk.LEFT)
        self.total_num = tk.Label(self.total_row, text="0",
                                   bg=COLOR_NUM_BG, fg="#111",
                                   font=FONT_NUM, width=4, padx=4)
        self.total_num.pack(side=tk.LEFT, padx=4)
        tk.Label(self.total_row, text="顆",
                 bg=COLOR_BG, font=FONT_NORMAL).pack(side=tk.LEFT)
        self.total_err_btn = self._make_check_btn(
            self.total_row, "錯誤", "bad", lambda: self._set_total(False))
        self.total_err_btn.pack(side=tk.RIGHT, padx=2)
        self.total_ok_btn = self._make_check_btn(
            self.total_row, "正確", "ok", lambda: self._set_total(True))
        self.total_ok_btn.pack(side=tk.RIGHT, padx=2)

        # 藥品面板
        self.drug_frame = tk.Frame(self.right_panel, bg=COLOR_BG,
                                    bd=2, relief=tk.SOLID)
        self.drug_frame.pack(fill=tk.BOTH, expand=True)

        # Footer（先 pack 佔底部）
        nav = tk.Frame(self.drug_frame, bg=COLOR_BG)
        nav.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(4, 8))
        self.prev_btn = tk.Button(nav, text="上一種", font=FONT_BTN, width=7,
                                   command=self._prev_drug)
        self.prev_btn.pack(side=tk.LEFT)
        self.page_label = tk.Label(nav, text="第 0 種 / 共 0 種",
                                    bg=COLOR_BG, font=FONT_NORMAL)
        self.page_label.pack(side=tk.LEFT, expand=True)
        self.next_btn = tk.Button(nav, text="下一種", font=FONT_BTN, width=7,
                                   command=self._next_drug)
        self.next_btn.pack(side=tk.RIGHT)

        # 共計（nav 上方）
        self.drug_total_label = tk.Label(self.drug_frame, text="共計 0 顆",
                                          bg=COLOR_BG, font=FONT_BOLD)
        self.drug_total_label.pack(side=tk.BOTTOM, pady=(0, 4))

        inner_d = tk.Frame(self.drug_frame, bg=COLOR_BG)
        inner_d.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

        # 藥品名稱（藍底）
        self.drug_name_label = tk.Label(
            inner_d, text="--",
            bg=COLOR_DRUG_NAME, fg="#111",
            font=FONT_DRUG,
            wraplength=360, justify=tk.LEFT,
            anchor=tk.W, padx=8, pady=8,
            relief=tk.FLAT,
        )
        self.drug_name_label.pack(fill=tk.X, pady=(0, 6))

        # 名稱核對列
        self.name_row = tk.Frame(inner_d, bg=COLOR_BG)
        self.name_row.pack(fill=tk.X, pady=2)
        tk.Label(self.name_row, text="【藥品】名稱核對",
                 bg=COLOR_BG, font=FONT_BOLD).pack(side=tk.LEFT)
        self.name_err_btn = self._make_check_btn(
            self.name_row, "錯誤", "bad", lambda: self._set_name(False))
        self.name_err_btn.pack(side=tk.RIGHT, padx=2)
        self.name_ok_btn = self._make_check_btn(
            self.name_row, "正確", "ok", lambda: self._set_name(True))
        self.name_ok_btn.pack(side=tk.RIGHT, padx=2)

        # Dose 列容器（動態重建）
        self._dose_container = tk.Frame(inner_d, bg=COLOR_BG)
        self._dose_container.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        # 監聽 drug_frame 尺寸變化 → 重算可見列數
        self.drug_frame.bind("<Configure>", self._on_drug_frame_resize)

    @staticmethod
    def _make_check_btn(parent, text: str, kind: str, cmd) -> tk.Button:
        bg, fg = ((COLOR_BTN_OK, COLOR_BTN_OK_T) if kind == "ok"
                  else (COLOR_BTN_BAD, COLOR_BTN_BAD_T))
        return tk.Button(parent, text=text, font=FONT_BTN, width=7,
                          bg=bg, fg=fg, relief=tk.SOLID, bd=1, command=cmd)

    # --------------------------------------------------------
    # 時間 & 流水號
    # --------------------------------------------------------

    def _update_time(self):
        dt = datetime.now()
        self.time_label.config(
            text=f"{dt.year}/{dt.month}/{dt.day} {dt.strftime('%H:%M:%S')}")
        self.root.after(1000, self._update_time)

    def _update_tray_id(self):
        self.state.tray_id = get_next_serial_number()
        self.tray_label.config(text=self.state.tray_id)

    # --------------------------------------------------------
    # Tab 切換 & 影像顯示
    # --------------------------------------------------------

    def _update_tab_buttons(self):
        if self.current_tab == "cam":
            self.tab_cam.config(bg="#e6e6e6", relief=tk.SUNKEN)
            self.tab_ai.config(bg="#bfbfbf", relief=tk.FLAT)
            self.badge_label.config(text="鏡頭" if self._is_analysed else "待分析")
            self._hide_hl()
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

    def _auto_switch_ai(self):
        if self.current_tab != "ai" and self._is_analysed:
            self._switch_tab("ai")

    def _refresh_image(self):
        img = (self._captured_image if self.current_tab == "cam"
               else self._ai_image)
        if img is None:
            self.image_label.config(image="", bg="#000")
            self.image_label.image = None
            return
        self._display_bgr(img)

    def _display_bgr(self, bgr: np.ndarray):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        self.left_panel.update_idletasks()
        w = self.left_panel.winfo_width()
        h = self.left_panel.winfo_height()
        if w < 2 or h < 2:
            w, h = 600, 500
        iw, ih = pil.size
        scale = min(w / iw, h / ih)
        pil = pil.resize((int(iw * scale), int(ih * scale)),
                          Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(pil)
        self.image_label.config(image=photo, bg="#000")
        self.image_label.image = photo

    # --------------------------------------------------------
    # 分析流水線
    # --------------------------------------------------------

    def _on_analyse(self):
        if self._app_state != AppState.IDLE:
            return
        self._app_state = AppState.ANALYSING
        self.done_btn.config(state=tk.DISABLED)
        self.root.update_idletasks()

        print("[analyse] Capturing frame...")
        frame = self._capture_single_frame()
        if frame is None:
            self._show_info_modal("提示", "相機拍攝失敗，請確認相機連接狀態。")
            self._app_state = AppState.IDLE
            return

        self._captured_image = frame.copy()

        print("[analyse] Running detection + matching...")
        if self._debug:
            detections = self._load_sample_detections(frame)
            results = self._debug_fake_results(len(detections))
        else:
            detections = self.detector(frame)
            results = []
            for det in detections:
                x1, y1, x2, y2 = det.bbox
                crop = frame[y1:y2, x1:x2]
                if crop.size == 0:
                    results.append(None)
                    continue
                try:
                    feat = self.encoder(crop)
                    results.append(self.matcher(feat))
                except Exception as e:
                    print(f"[analyse] encode/match error: {e}")
                    results.append(None)

        if not detections:
            self._ai_image = frame.copy()
            self._is_analysed = True
            self._update_state_from_results([], [], frame)
            self._switch_tab("cam")
            self._refresh_image()
            self._show_info_modal("提示", "未偵測到任何藥錠，請確認藥盤擺放位置與光線條件。")
            self._app_state = AppState.IDLE
            self.done_btn.config(state=tk.NORMAL)
            return

        self._update_state_from_results(detections, results, frame)
        self._detections = detections
        self._is_analysed = True
        self._ai_image = self._generate_ai_overlay(frame, detections, 0)

        self.current_tab = "ai"
        self._update_tab_buttons()
        self._refresh_image()
        self._update_info_panel()

        self._app_state = AppState.REVIEWING
        self.done_btn.config(state=tk.NORMAL, bg=COLOR_DONE)
        print("[analyse] Done")

    def _debug_fake_results(self, n: int) -> list:
        results = []
        size = self.gallery.size
        for i in range(n):
            idx = (i * 2) % size if size > 0 else 0
            meta = self.gallery.get_metadata(idx) if size > 0 else {}
            results.append(MatchResult(
                license_number=meta.get("license_number", f"DEMO-{i+1:03d}"),
                name=meta.get("name", f"Demo Drug {i+1}"),
                side=meta.get("side", 0),
                score=0.95,
            ))
        return results

    def _load_sample_detections(self, frame: np.ndarray) -> list:
        txt = Path("src/sample/sample.txt")
        if not txt.exists():
            return []
        h, w = frame.shape[:2]
        detections = []
        with open(txt) as f:
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
        return detections

    # --------------------------------------------------------
    # 狀態更新
    # --------------------------------------------------------

    def _update_state_from_results(
            self,
            detections: list,
            results: list,
            frame: np.ndarray):
        """Detection + MatchResult list → DrugPage list（以 license 分組）"""
        CODES = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        h_img, w_img = frame.shape[:2]

        # 以 license 分組，保持出現順序
        license_order: list[str] = []
        license_groups: dict[str, list] = {}

        for det_idx, (det, res) in enumerate(zip(detections, results)):
            lic = res.license_number if res else f"__unknown_{det_idx}"
            if lic not in license_groups:
                license_order.append(lic)
                license_groups[lic] = []
            license_groups[lic].append((det_idx, det, res))

        drugs: list[DrugPage] = []
        for drug_i, lic in enumerate(license_order):
            pairs = license_groups[lic]
            code = CODES[drug_i % len(CODES)]
            c = DRUG_COLORS[drug_i % len(DRUG_COLORS)]

            first_res = pairs[0][2]
            title = first_res.name if first_res else "未識別"
            license_number = first_res.license_number if first_res else ""

            items: list[DrugItem] = []
            for item_i, (det_idx, det, res) in enumerate(pairs):
                key = f"{code}{item_i + 1}"
                x1, y1, x2, y2 = det.bbox

                crop = frame[y1:y2, x1:x2]
                crop_56 = cv2.resize(crop, (56, 56)) if crop.size > 0 else None

                bbox_pct = (
                    x1 / w_img, y1 / h_img,
                    (x2 - x1) / w_img, (y2 - y1) / h_img,
                )
                items.append(DrugItem(
                    key=key,
                    count=1,
                    color_bgr=c["bgr"],
                    color_hex=c["border"],
                    crop_img=crop_56,
                    bbox_pct=bbox_pct,
                    det_index=det_idx,
                ))

            drugs.append(DrugPage(
                code=code,
                title=title,
                license_number=license_number,
                items=items,
            ))

        self.state.timestamp     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state.total_kinds   = len(drugs)
        self.state.total_pills   = sum(len(d.items) for d in drugs)
        self.state.variety_correct = None
        self.state.total_correct   = None
        self.state.drugs             = drugs
        self.state.current_drug_index = 0
        self.state.name_answers  = [None] * len(drugs)
        self.state.dose_answers  = {
            item.key: None
            for drug in drugs for item in drug.items
        }

    def _generate_ai_overlay(
            self,
            image: np.ndarray,
            detections: list,
            current_drug_index: int) -> np.ndarray:
        """YOLO overlay：當前藥種高亮（高 alpha），其餘淡化（低 alpha）"""
        overlay = image.copy()
        h_img, w_img = image.shape[:2]

        for drug_idx, drug in enumerate(self.state.drugs):
            is_cur = (drug_idx == current_drug_index)
            alpha = 0.65 if is_cur else 0.20
            thickness = 3 if is_cur else 1
            c = DRUG_COLORS[drug_idx % len(DRUG_COLORS)]
            color_bgr = c["bgr"]
            color_arr = np.array(color_bgr, dtype=np.float32)

            for item in drug.items:
                if item.det_index >= len(detections):
                    continue
                det = detections[item.det_index]

                # 分割遮罩
                if det.mask is not None:
                    mask = det.mask
                    if mask.shape != (h_img, w_img):
                        mask = cv2.resize(mask, (w_img, h_img),
                                          interpolation=cv2.INTER_NEAREST)
                    mb = mask > 0
                    overlay[mb] = (
                        overlay[mb].astype(np.float32) * (1 - alpha)
                        + color_arr * alpha
                    ).clip(0, 255).astype(np.uint8)

                # 邊框
                x1, y1, x2, y2 = det.bbox
                cv2.rectangle(overlay, (x1, y1), (x2, y2), color_bgr, thickness)

                # 編號徽章
                r = 12 if is_cur else 9
                cx, cy = x1 + r + 2, y1 + r + 2
                cv2.circle(overlay, (cx, cy), r, color_bgr, -1)
                cv2.circle(overlay, (cx, cy), r, (255, 255, 255), 1)
                fs = 0.42 if is_cur else 0.32
                tw, th = cv2.getTextSize(item.key, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)[0]
                cv2.putText(overlay, item.key,
                            (cx - tw // 2, cy + th // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, fs,
                            (255, 255, 255), 1, cv2.LINE_AA)

        return overlay

    # --------------------------------------------------------
    # 虛擬捲動：可見列數計算
    # --------------------------------------------------------

    def _on_drug_frame_resize(self, event):
        new_h = event.height
        if abs(new_h - self._dose_frame_h_prev) < 4:
            return
        self._dose_frame_h_prev = new_h
        new_count = max(1, (new_h - self._PANEL_FIXED_H) // DOSE_ROW_H)
        if new_count != self._dose_visible_count:
            self._dose_visible_count = new_count
            if self._is_analysed and self.state.drugs:
                self._render_dose_rows()

    # --------------------------------------------------------
    # 虛擬捲動：渲染
    # --------------------------------------------------------

    def _render_dose_rows(self):
        """清空 _dose_container 並依 offset / visible_count 重建 dose 列"""
        # 清空
        for w in self._dose_container.winfo_children():
            w.destroy()
        self._dose_icon_refs.clear()
        self._missing_key = None   # 重繪後清除缺漏標記

        if not self.state.drugs:
            return

        drug = self.state.drugs[self.state.current_drug_index]
        items = drug.items
        total = len(items)
        offset = self._dose_scroll_offset
        visible = self._dose_visible_count
        overflow = total > visible

        bg = COLOR_BG

        # ▲ 按鈕（只在 overflow 且 offset > 0 時顯示）
        if overflow and offset > 0:
            tk.Button(self._dose_container, text="▲",
                      font=FONT_BTN, height=2, bg="#e0e0e0",
                      relief=tk.FLAT, command=self._dose_scroll_up
                      ).pack(fill=tk.X, pady=(0, 2))

        # 顯示可見範圍
        for item in items[offset: offset + visible]:
            self._render_single_dose_row(item, bg)

        # ▼ 按鈕（只在 overflow 且後面還有時顯示）
        if overflow and offset + visible < total:
            tk.Button(self._dose_container, text="▼",
                      font=FONT_BTN, height=2, bg="#e0e0e0",
                      relief=tk.FLAT, command=self._dose_scroll_down
                      ).pack(fill=tk.X, pady=(2, 0))

    def _render_single_dose_row(self, item: DrugItem, bg: str):
        """渲染一個 dose item 列"""
        row = tk.Frame(self._dose_container, bg=bg, pady=2)
        row.pack(fill=tk.X)

        # 圖示（56×56）
        icon_label = tk.Label(row, bg=bg, width=56, height=56)
        icon_label.pack(side=tk.LEFT, padx=(0, 6))
        if item.crop_img is not None:
            try:
                rgb = cv2.cvtColor(item.crop_img, cv2.COLOR_BGR2RGB)
                pil = Image.fromarray(rgb).resize((56, 56), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(pil)
                icon_label.config(image=photo)
                icon_label.image = photo
                self._dose_icon_refs.append(photo)
            except Exception:
                pass

        # 中間資訊
        mid = tk.Frame(row, bg=bg)
        mid.pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Label(mid, text=f"{item.key}  數量 {item.count} 顆",
                 bg=bg, font=FONT_BOLD, anchor=tk.W).pack(anchor=tk.W)

        # 正確 / 錯誤 按鈕
        btn_frame = tk.Frame(row, bg=bg)
        btn_frame.pack(side=tk.RIGHT)

        ok_btn = self._make_check_btn(
            btn_frame, "正確", "ok",
            lambda k=item.key: self._on_dose_click(k, True))
        ok_btn.pack(side=tk.LEFT, padx=2)

        bad_btn = self._make_check_btn(
            btn_frame, "錯誤", "bad",
            lambda k=item.key: self._on_dose_click(k, False))
        bad_btn.pack(side=tk.LEFT, padx=2)

        # 更新按鈕視覺狀態
        self._apply_btn_state(ok_btn, bad_btn, self.state.dose_answers.get(item.key))

        # Hover → hotspot
        for widget in (row, mid, icon_label):
            widget.bind("<Enter>", lambda e, k=item.key: self._show_hl(k))
            widget.bind("<Leave>", lambda e: self._hide_hl())

    def _dose_scroll_up(self):
        if self._dose_scroll_offset > 0:
            self._dose_scroll_offset -= 1
            self._render_dose_rows()

    def _dose_scroll_down(self):
        if not self.state.drugs:
            return
        drug = self.state.drugs[self.state.current_drug_index]
        max_offset = max(0, len(drug.items) - self._dose_visible_count)
        if self._dose_scroll_offset < max_offset:
            self._dose_scroll_offset += 1
            self._render_dose_rows()

    def _on_dose_click(self, item_key: str, value: bool):
        self._set_dose(item_key, value)
        self._show_hl(item_key)
        self._auto_switch_ai()
        # 重繪該列按鈕狀態（不整個 re-render，避免閃爍）
        self._update_dose_btn_in_container(item_key)

    def _update_dose_btn_in_container(self, item_key: str):
        """更新 _dose_container 內指定 item 的按鈕視覺狀態"""
        # 重新渲染比逐一找 widget 更簡單，且 row 數量少不會有效能問題
        self._render_dose_rows()

    # --------------------------------------------------------
    # Hotspot Highlight
    # --------------------------------------------------------

    def _show_hl(self, item_key: str):
        if self.current_tab != "ai" or not self.state.drugs:
            return
        drug = self.state.drugs[self.state.current_drug_index]
        item = next((it for it in drug.items if it.key == item_key), None)
        if item is None:
            return
        lp, tp, wp, hp = item.bbox_pct
        self.left_panel.update_idletasks()
        pw = self.left_panel.winfo_width()
        ph = self.left_panel.winfo_height()
        if pw < 2 or ph < 2:
            return
        self._hl_rect.place(
            x=int(lp * pw), y=int(tp * ph),
            width=max(4, int(wp * pw)),
            height=max(4, int(hp * ph)),
        )
        self._hl_rect.lift()

    def _hide_hl(self):
        self._hl_rect.place_forget()

    # --------------------------------------------------------
    # 資訊面板更新
    # --------------------------------------------------------

    def _update_info_panel(self):
        self.variety_num.config(text=str(self.state.total_kinds))
        self.total_num.config(text=str(self.state.total_pills))

        if not self.state.drugs:
            self.drug_name_label.config(text="--")
            self.drug_total_label.config(text="共計 0 顆")
            self.page_label.config(text="第 0 種 / 共 0 種")
            self.drug_frame.config(bg=COLOR_BG)
            return

        idx = self.state.current_drug_index
        drug = self.state.drugs[idx]
        total_items = sum(it.count for it in drug.items)

        self.drug_name_label.config(text=drug.title or "--")
        self.drug_total_label.config(text=f"共計 {total_items} 顆")
        self.page_label.config(
            text=f"第 {idx + 1} 種 / 共 {len(self.state.drugs)} 種")

        self._update_nav_buttons()
        self._update_button_states()
        self._render_dose_rows()
        self._hide_hl()

        # 重繪 overlay（高亮當前藥種）
        if self._is_analysed and self._captured_image is not None:
            self._ai_image = self._generate_ai_overlay(
                self._captured_image, self._detections, idx)
            if self.current_tab == "ai":
                self._refresh_image()

    def _update_button_states(self):
        self._apply_btn_state(self.variety_ok_btn, self.variety_err_btn,
                               self.state.variety_correct)
        self._apply_btn_state(self.total_ok_btn, self.total_err_btn,
                               self.state.total_correct)
        if self.state.drugs:
            idx = self.state.current_drug_index
            self._apply_btn_state(self.name_ok_btn, self.name_err_btn,
                                   self.state.name_answers[idx])

    @staticmethod
    def _apply_btn_state(ok_btn: tk.Button, err_btn: tk.Button,
                          value: bool | None):
        if value is True:
            ok_btn.config(relief=tk.SUNKEN, bd=3, fg=COLOR_BTN_OK_T)
            err_btn.config(relief=tk.SOLID,  bd=1, fg="#999")
        elif value is False:
            ok_btn.config(relief=tk.SOLID,  bd=1, fg="#999")
            err_btn.config(relief=tk.SUNKEN, bd=3, fg=COLOR_BTN_BAD_T)
        else:
            ok_btn.config(relief=tk.SOLID, bd=1, fg=COLOR_BTN_OK_T)
            err_btn.config(relief=tk.SOLID, bd=1, fg=COLOR_BTN_BAD_T)

    def _update_nav_buttons(self):
        total = len(self.state.drugs)
        idx = self.state.current_drug_index
        self.prev_btn.config(state=tk.NORMAL if idx > 0 else tk.DISABLED)
        self.next_btn.config(state=tk.NORMAL if idx < total - 1 else tk.DISABLED)

    # --------------------------------------------------------
    # 確認邏輯
    # --------------------------------------------------------

    def _set_variety(self, value: bool):
        self.state.variety_correct = value
        self._apply_btn_state(self.variety_ok_btn, self.variety_err_btn, value)
        self._auto_switch_ai()

    def _set_total(self, value: bool):
        self.state.total_correct = value
        self._apply_btn_state(self.total_ok_btn, self.total_err_btn, value)
        self._auto_switch_ai()

    def _set_name(self, value: bool):
        if not self.state.drugs:
            return
        idx = self.state.current_drug_index
        self.state.name_answers[idx] = value
        self._apply_btn_state(self.name_ok_btn, self.name_err_btn, value)
        self._auto_switch_ai()

    def _set_dose(self, item_key: str, value: bool):
        self.state.dose_answers[item_key] = value

    # --------------------------------------------------------
    # 導航（藥種）
    # --------------------------------------------------------

    def _prev_drug(self):
        if self.state.current_drug_index > 0:
            self.state.current_drug_index -= 1
            self._dose_scroll_offset = 0
            self._update_info_panel()
            self._auto_switch_ai()

    def _next_drug(self):
        if self.state.current_drug_index < len(self.state.drugs) - 1:
            self.state.current_drug_index += 1
            self._dose_scroll_offset = 0
            self._update_info_panel()
            self._auto_switch_ai()

    # --------------------------------------------------------
    # 缺漏檢查
    # --------------------------------------------------------

    def _find_first_missing(self) -> tuple | None:
        """回傳 (drug_index, item_key_or_field) 或 None"""
        if self.state.variety_correct is None:
            return (self.state.current_drug_index, "variety")
        if self.state.total_correct is None:
            return (self.state.current_drug_index, "total")
        for i, ans in enumerate(self.state.name_answers):
            if ans is None:
                return (i, "name")
        for drug in self.state.drugs:
            drug_idx = self.state.drugs.index(drug)
            for item in drug.items:
                if self.state.dose_answers.get(item.key) is None:
                    return (drug_idx, item.key)
        return None

    # --------------------------------------------------------
    # 「完成」邏輯
    # --------------------------------------------------------

    def _on_done(self):
        if self._app_state != AppState.REVIEWING:
            return
        self._switch_tab("ai")
        missing = self._find_first_missing()
        if missing is not None:
            self._show_missing_modal(missing)
        else:
            self._show_review_modal()

    # --------------------------------------------------------
    # Modal：缺漏提示
    # --------------------------------------------------------

    def _show_missing_modal(self, missing_info: tuple):
        drug_idx, key = missing_info
        backdrop = self._make_backdrop()

        card_w = min(420, self.root.winfo_width() - 40)
        card = tk.Frame(backdrop, bg="white", relief=tk.SOLID, bd=1)
        card.place(relx=0.5, rely=0.2, anchor=tk.N, width=card_w)

        header = tk.Frame(card, bg="#fff0f0", height=48)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="提示",
                 bg="#fff0f0", fg="#cc0000", font=FONT_BOLD
                 ).pack(side=tk.LEFT, padx=16, pady=10)

        tk.Label(card, text="請完成所有藥品查核並確實反饋",
                 font=FONT_NORMAL, bg="white", wraplength=370, pady=20
                 ).pack(padx=16)

        def go_back():
            backdrop.destroy()
            self.state.current_drug_index = drug_idx
            self._dose_scroll_offset = 0
            self._update_info_panel()
            # 紅框標記缺漏列
            self._highlight_missing_row(key)

        tk.Button(card, text="回去檢查", font=FONT_BTN,
                  bg=COLOR_PRIMARY, fg="white", bd=0, padx=16, pady=8,
                  command=go_back).pack(pady=(0, 16))

    def _highlight_missing_row(self, key: str):
        """在 variety_row / total_row / name_row / dose 列加紅框"""
        def add_hl(frame: tk.Frame):
            frame.config(highlightbackground="red",
                          highlightthickness=2,
                          highlightcolor="red")

        if key == "variety":
            add_hl(self.variety_row)
        elif key == "total":
            add_hl(self.total_row)
        elif key == "name":
            add_hl(self.name_row)
        # dose item key 的紅框透過 _render_dose_rows 內的 missing 標記處理
        # （後續版本可擴充）

    # --------------------------------------------------------
    # Modal：填報總覽
    # --------------------------------------------------------

    def _show_review_modal(self):
        backdrop = self._make_backdrop()

        card_w = min(600, self.root.winfo_width() - 40)
        card_h = min(520, self.root.winfo_height() - 60)
        card = tk.Frame(backdrop, bg="white", relief=tk.SOLID, bd=1)
        card.place(relx=0.5, rely=0.06, anchor=tk.N,
                   width=card_w, height=card_h)

        # Header
        header = tk.Frame(card, bg="#eef3ff", height=50)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text="填報總覽",
                 bg="#eef3ff", font=FONT_BOLD
                 ).pack(side=tk.LEFT, padx=16, pady=12)

        btn_fr = tk.Frame(header, bg="#eef3ff")
        btn_fr.pack(side=tk.RIGHT, padx=8)

        def on_reset():
            self.state.variety_correct = None
            self.state.total_correct   = None
            self.state.name_answers    = [None] * len(self.state.drugs)
            self.state.dose_answers    = {k: None for k in self.state.dose_answers}
            backdrop.destroy()
            self._update_info_panel()

        def on_save():
            backdrop.destroy()
            self._save_record()
            self._show_toast("儲存完成")
            self.root.after(1700, self._reset_to_idle)

        tk.Button(btn_fr, text="重新回饋", font=FONT_BTN,
                  bg="#555", fg="white", bd=0, padx=10, pady=4,
                  command=on_reset).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_fr, text="儲存", font=FONT_BTN,
                  bg=COLOR_PRIMARY, fg="white", bd=0, padx=10, pady=4,
                  command=on_save).pack(side=tk.LEFT)

        # 可捲動 feedback list
        content = tk.Frame(card, bg="white")
        content.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        canvas = tk.Canvas(content, bg="white", highlightthickness=0)
        sb = tk.Scrollbar(content, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg="white")
        win_id = canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))

        # 全域摘要
        self._fb_row(inner, f"總品項 {self.state.total_kinds} 種",
                     self.state.variety_correct)
        self._fb_row(inner, f"總數量 {self.state.total_pills} 顆",
                     self.state.total_correct)

        # 逐種藥
        for i, drug in enumerate(self.state.drugs):
            hdr = tk.Frame(inner, bg="#f0f4ff")
            hdr.pack(fill=tk.X, pady=(8, 2))
            title_short = (drug.title[:38] + "…") if len(drug.title) > 40 else drug.title
            tk.Label(hdr, text=f"── {title_short} ──",
                     bg="#f0f4ff", font=FONT_BOLD, anchor=tk.W,
                     padx=8).pack(fill=tk.X)

            self._fb_row(inner, "品項核對",
                         self.state.name_answers[i], indent=24)

            for item in drug.items:
                self._fb_row(inner,
                             f"{item.key}  數量 {item.count} 顆",
                             self.state.dose_answers.get(item.key),
                             indent=36)

    @staticmethod
    def _fb_row(parent: tk.Frame, label: str, value, indent: int = 8):
        row = tk.Frame(parent, bg="white")
        row.pack(fill=tk.X, padx=0, pady=1)
        tk.Label(row, text=label, font=FONT_NORMAL, bg="white",
                 anchor=tk.W, padx=indent).pack(side=tk.LEFT)
        if value is True:
            txt, col = "正確", COLOR_BTN_OK_T
        elif value is False:
            txt, col = "錯誤", COLOR_BTN_BAD_T
        else:
            txt, col = "⚠ 未填", "#cc0000"
        tk.Label(row, text=txt, font=FONT_BOLD, bg="white",
                 fg=col, padx=8).pack(side=tk.RIGHT)

    # --------------------------------------------------------
    # Backdrop 輔助
    # --------------------------------------------------------

    def _make_backdrop(self) -> tk.Frame:
        bd = tk.Frame(self.root, bg=COLOR_BACKDROP)
        bd.place(relx=0, rely=0, relwidth=1, relheight=1)
        bd.lift()
        return bd

    # --------------------------------------------------------
    # 簡易 Info Modal
    # --------------------------------------------------------

    def _show_info_modal(self, title: str, message: str):
        backdrop = self._make_backdrop()
        card_w = min(420, self.root.winfo_width() - 40)
        card = tk.Frame(backdrop, bg="white", relief=tk.SOLID, bd=1)
        card.place(relx=0.5, rely=0.25, anchor=tk.N, width=card_w)

        header = tk.Frame(card, bg="#eef3ff", height=46)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text=title, bg="#eef3ff",
                 font=FONT_BOLD).pack(side=tk.LEFT, padx=16, pady=10)

        tk.Label(card, text=message, font=FONT_NORMAL, bg="white",
                 wraplength=370, pady=20).pack(padx=16)

        tk.Button(card, text="確定", font=FONT_BTN,
                  bg=COLOR_PRIMARY, fg="white", bd=0, padx=20, pady=6,
                  command=backdrop.destroy).pack(pady=(0, 14))

    # --------------------------------------------------------
    # Toast
    # --------------------------------------------------------

    def _show_toast(self, message: str, duration_ms: int = 1500):
        toast = tk.Label(
            self.root, text=message,
            bg="#2c5f8a", fg="white",
            font=FONT_TOAST, padx=28, pady=18,
            relief=tk.FLAT,
        )
        toast.place(relx=0.5, rely=0.28, anchor=tk.CENTER)
        toast.lift()
        self.root.after(duration_ms, toast.destroy)

    # --------------------------------------------------------
    # 儲存記錄
    # --------------------------------------------------------

    def _save_record(self):
        RECORDS_DIR.mkdir(parents=True, exist_ok=True)
        tray_id = self.state.tray_id

        # YAML
        data = {
            "tray_id":   tray_id,
            "timestamp": self.state.timestamp,
            "summary": {
                "total_kinds":      self.state.total_kinds,
                "total_pills":      self.state.total_pills,
                "variety_correct":  self.state.variety_correct,
                "total_correct":    self.state.total_correct,
            },
            "drugs": [
                {
                    "code":           drug.code,
                    "name":           drug.title,
                    "license_number": drug.license_number,
                    "name_correct":   self.state.name_answers[i],
                    "items": [
                        {
                            "key":          item.key,
                            "count":        item.count,
                            "dose_correct": self.state.dose_answers.get(item.key),
                        }
                        for item in drug.items
                    ],
                }
                for i, drug in enumerate(self.state.drugs)
            ],
        }
        yaml_path = RECORDS_DIR / f"{tray_id}.yaml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        # JPG
        if self._captured_image is not None:
            jpg_path = RECORDS_DIR / f"{tray_id}.jpg"
            cv2.imwrite(str(jpg_path), self._captured_image)

        print(f"[save] {yaml_path}")

    # --------------------------------------------------------
    # 重置
    # --------------------------------------------------------

    def _reset_state(self):
        self._captured_image = None
        self._ai_image       = None
        self._detections     = []
        self._is_analysed    = False
        self.current_tab     = "cam"
        self._dose_scroll_offset = 0
        self.state = VerificationState(tray_id=self.state.tray_id)

        self.image_label.config(image="", bg="#000")
        self.image_label.image = None
        self.badge_label.config(text="待分析")
        self._update_tab_buttons()

        self.variety_num.config(text="0")
        self.total_num.config(text="0")
        self.drug_name_label.config(text="--", bg=COLOR_DRUG_NAME)
        self.drug_total_label.config(text="共計 0 顆")
        self.page_label.config(text="第 0 種 / 共 0 種")
        self.done_btn.config(state=tk.DISABLED, bg=COLOR_DONE)

        for w in self._dose_container.winfo_children():
            w.destroy()
        self._dose_icon_refs.clear()
        self._hide_hl()

        self._apply_btn_state(self.variety_ok_btn, self.variety_err_btn, None)
        self._apply_btn_state(self.total_ok_btn,   self.total_err_btn,   None)
        self._apply_btn_state(self.name_ok_btn,    self.name_err_btn,    None)

        self.prev_btn.config(state=tk.DISABLED)
        self.next_btn.config(state=tk.DISABLED)

    def _reset_to_idle(self):
        self._reset_state()
        self._update_tray_id()
        self._app_state = AppState.IDLE

    # --------------------------------------------------------
    # 關閉
    # --------------------------------------------------------

    def _on_close(self):
        self._stop_drawer_monitoring()
        if self._camera and not self._is_picamera:
            self._camera.release()
        if self.led_pixels:
            try:
                self.led_pixels.fill((0, 0, 0))
            except Exception:
                pass
        self.root.destroy()


# ============================================================
# 元件工廠
# ============================================================

def create_components(
    gallery_path: str = "src/gallery",
    model_path:   str = "src/best.pt",
) -> tuple:
    gallery  = Gallery(gallery_path)
    gallery.load()
    encoder  = ResNet34Encoder()
    matcher  = Top1Matcher(gallery)
    detector = YOLODetector(model_path)
    return gallery, encoder, matcher, detector


# ============================================================
# 主程式入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="FY114 藥物辨識子系統 v3")
    parser.add_argument("--fullscreen", action="store_true",
                        help="全螢幕模式（觸控螢幕）")
    parser.add_argument("--gallery", default="src/gallery",
                        help="Gallery 目錄路徑")
    parser.add_argument("--model", default="src/best.pt",
                        help="YOLO 模型路徑")
    parser.add_argument("--debug", action="store_true",
                        help="除錯模式：跳過相機與 LED，以樣本圖作為輸入")
    args = parser.parse_args()

    if args.debug:
        print("[init] Debug mode ON")

    print("[init] Loading components...")
    gallery, encoder, matcher, detector = create_components(
        gallery_path=args.gallery,
        model_path=args.model,
    )

    print("[init] Starting GUI...")
    root = tk.Tk()
    AppV3(root, gallery, encoder, matcher, detector,
          fullscreen=args.fullscreen, debug=args.debug)
    root.mainloop()


if __name__ == "__main__":
    main()
