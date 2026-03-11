"""
Drawer Closure Monitoring Application - Optimized Version
抽屜閉合監測應用程式 - 優化版本

視窗大小：1024x600（與 run.py 一致）
使用 Tab 切換：數據串流頁面 和 參數配置頁面
配置自動同步到 drawer_config.yaml
"""

import tkinter as tk
from tkinter import ttk, messagebox
import cv2
import numpy as np
from PIL import Image, ImageTk
import threading
import time
from collections import deque
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import yaml
from pathlib import Path

from eminent.sensors.vision2p5d import VideoCapture, MN96100CConfig
from utils.depth_analysis import DepthAnalyzer, DrawerStateDetector


class DrawerMonitorApp:
    """抽屜監測應用程式"""
    
    # 視窗尺寸（與 run.py 一致）
    WINDOW_WIDTH = 1024
    WINDOW_HEIGHT = 600
    
    def __init__(self, root):
        self.root = root
        self.root.title("MN96100C 2.5D 抽屜閉合監測系統")
        self.root.geometry(f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}")
        self.root.resizable(False, False)
        
        # 配置文件路徑
        self.config_file = Path("config/drawer_config.yaml")
        
        # 相機相關
        self.cap = None
        self.is_running = False
        self.capture_thread = None
        
        # 數據存儲
        self.max_history = 500
        self.time_data = deque(maxlen=self.max_history)
        self.depth_metric_data = deque(maxlen=self.max_history)
        self.intensity_mean_data = deque(maxlen=self.max_history)
        
        self.start_time = time.time()
        self.frame_count = 0
        
        # 高級分析工具
        self.depth_analyzer = DepthAnalyzer()
        self.state_detector = None
        
        # 默認配置
        self.config = {
            'camera': {
                'vid': 0x04F3,
                'pid': 0x0C7E,
                'frame_rate': 'QUARTER',
                'led_current': 'ULTRA_HIGH',
                'exposure_setting': 'DEFAULT'
            },
            'roi': {
                'enabled': False,
                'x1': 40,
                'y1': 40,
                'x2': 120,
                'y2': 120
            },
            'thresholds': {
                'open': 0.08,
                'closed': 0.06
            },
            'analysis': {
                'use_depth_transform': True,
                'filter_window': 5,
                'min_state_duration': 3
            }
        }
        
        # 加載配置
        self.load_config()
        
        # 創建 UI
        self.create_ui()
        
        # 狀態變量
        self.current_frame = None
        self.current_status = "未知"
        
    def create_ui(self):
        """創建使用者界面"""
        
        # 創建 Notebook（Tab 控件）
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Tab 1: 數據串流
        self.stream_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.stream_frame, text="  數據串流  ")
        
        # Tab 2: 參數配置
        self.config_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.config_frame, text="  參數配置  ")
        
        # 創建各個 Tab 的內容
        self.create_stream_tab()
        self.create_config_tab()
        
    def create_stream_tab(self):
        """創建數據串流頁面"""
        
        # 左側：圖像顯示（固定寬度360，避免撐開）
        left_panel = ttk.Frame(self.stream_frame, width=360)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=5, pady=5)
        left_panel.pack_propagate(False)  # 防止子元件撐開父容器
        
        # 控制區域 - 使用 grid 布局（2:1:1 比例）
        control_frame = ttk.Frame(left_panel)
        control_frame.pack(fill=tk.X, pady=5)
        
        # 配置列權重（2:1:1）
        control_frame.columnconfigure(0, weight=2)
        control_frame.columnconfigure(1, weight=1)
        control_frame.columnconfigure(2, weight=1)
        
        # 左側：抽屜狀態（佔 2 份寬度）
        status_container = ttk.Frame(control_frame, relief='solid', borderwidth=1)
        status_container.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        
        ttk.Label(status_container, text="抽屡狀態：", font=('Arial', 9)
                  ).pack(side=tk.LEFT, padx=5, pady=5)
        self.drawer_status_label = ttk.Label(status_container, text="未知",
                                             font=('Arial', 14, 'bold'),
                                             foreground='gray')
        self.drawer_status_label.pack(side=tk.LEFT, padx=5, pady=5)
        
        # 中間：啟動按鈕（佔 1 份寬度）
        self.start_button = ttk.Button(control_frame, text="啟動相機",
                                       command=self.start_camera)
        self.start_button.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=2)
        
        # 右側：停止按鈕（佔 1 份寬度）
        self.stop_button = ttk.Button(control_frame, text="停止相機",
                                      command=self.stop_camera, state='disabled')
        self.stop_button.grid(row=0, column=2, sticky=(tk.W, tk.E), padx=2)
        
        # 圖像顯示區（固定大小）
        image_frame = ttk.LabelFrame(left_panel, text="2.5D 深度影像", padding=5)
        image_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # 創建固定大小的圖像標籤（320x320）
        self.image_label = ttk.Label(image_frame, relief='solid', borderwidth=1)
        self.image_label.pack()
        
        # 設定占位圖像（灰色背景 + 文字）
        placeholder = Image.new('RGB', (320, 320), color=(80, 80, 80))
        self.placeholder_photo = ImageTk.PhotoImage(placeholder)
        self.image_label.config(image=self.placeholder_photo)
        self.image_label.image = self.placeholder_photo
        
        # 閾值調整 Slider
        threshold_frame = ttk.LabelFrame(left_panel, text="閾值調整", padding=10)
        threshold_frame.pack(fill=tk.X, pady=5)
        
        # Open 閾值 Slider
        ttk.Label(threshold_frame, text="開啟閾值：", font=('Arial', 9)
                  ).grid(row=0, column=0, sticky=tk.W, pady=3)
        
        self.threshold_open_slider = tk.Scale(
            threshold_frame, 
            from_=0.0, to=1.0, resolution=0.001,
            orient=tk.HORIZONTAL,
            command=self.on_threshold_open_change,
            length=300
        )
        self.threshold_open_slider.set(self.config['thresholds']['open'])
        self.threshold_open_slider.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5, pady=3)
        
        self.threshold_open_value_label = ttk.Label(
            threshold_frame, 
            text=f"{self.config['thresholds']['open']:.3f}",
            font=('Arial', 9, 'bold')
        )
        self.threshold_open_value_label.grid(row=0, column=2, sticky=tk.W, padx=5, pady=3)
        
        # Closed 閾值 Slider
        ttk.Label(threshold_frame, text="閉合閾值：", font=('Arial', 9)
                  ).grid(row=1, column=0, sticky=tk.W, pady=3)
        
        self.threshold_closed_slider = tk.Scale(
            threshold_frame,
            from_=0.0, to=1.0, resolution=0.001,
            orient=tk.HORIZONTAL,
            command=self.on_threshold_closed_change,
            length=300
        )
        self.threshold_closed_slider.set(self.config['thresholds']['closed'])
        self.threshold_closed_slider.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5, pady=3)
        
        self.threshold_closed_value_label = ttk.Label(
            threshold_frame,
            text=f"{self.config['thresholds']['closed']:.3f}",
            font=('Arial', 9, 'bold')
        )
        self.threshold_closed_value_label.grid(row=1, column=2, sticky=tk.W, padx=5, pady=3)
        
        # 配置列權重
        threshold_frame.columnconfigure(1, weight=1)
        
        # 右側：圖表顯示
        right_panel = ttk.Frame(self.stream_frame)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        chart_frame = ttk.LabelFrame(right_panel, text="Depth Time Series", padding=5)
        chart_frame.pack(fill=tk.BOTH, expand=True)
        
        # 創建圖表
        self.fig = Figure(figsize=(6, 5), dpi=80)
        
        # 上圖：深度指標
        self.ax1 = self.fig.add_subplot(211)
        self.ax1.set_ylabel('Depth Metric', fontsize=9)
        self.ax1.set_title('Depth Time Series (Physical Model)', fontsize=10)
        self.ax1.grid(True, alpha=0.3)
        self.ax1.tick_params(labelsize=8)
        
        # 下圖：原始強度
        self.ax2 = self.fig.add_subplot(212)
        self.ax2.set_xlabel('Time (seconds)', fontsize=9)
        self.ax2.set_ylabel('Intensity', fontsize=9)
        self.ax2.set_title('Reflection Light Intensity', fontsize=10)
        self.ax2.grid(True, alpha=0.3)
        self.ax2.tick_params(labelsize=8)
        
        self.fig.tight_layout()
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
    def create_config_tab(self):
        """創建參數配置頁面"""
        
        # 使用 Canvas + Scrollbar 支持滾動
        canvas = tk.Canvas(self.config_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.config_frame, orient="vertical",
                                  command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 三列布局，每列最多兩個參數區塊
        container = ttk.Frame(scrollable_frame)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 配置列權重（兩列均等）
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)
        
        # === 第一列：相機參數 + ROI 設定 ===
        
        # 相機參數
        cam_frame = ttk.LabelFrame(container, text="相機參數", padding=15)
        cam_frame.grid(row=0, column=0, sticky=(tk.N, tk.W, tk.E), padx=5, pady=5)
        
        ttk.Label(cam_frame, text="幀率 (Frame Rate):", font=('Arial', 9)
                  ).grid(row=0, column=0, sticky=tk.W, pady=5)
        self.frame_rate_var = tk.StringVar(value=self.config['camera']['frame_rate'])
        frame_rate_combo = ttk.Combobox(cam_frame, textvariable=self.frame_rate_var,
                                        values=['FULL', 'HALF', 'QUARTER', 'EIGHTH', 'SIXTEENTH'],
                                        state='readonly', width=18)
        frame_rate_combo.grid(row=0, column=1, pady=5, padx=5)
        
        ttk.Label(cam_frame, text="LED 電流強度:", font=('Arial', 9)
                  ).grid(row=1, column=0, sticky=tk.W, pady=5)
        self.led_current_var = tk.StringVar(value=self.config['camera']['led_current'])
        led_combo = ttk.Combobox(cam_frame, textvariable=self.led_current_var,
                                 values=['LOW', 'MEDIUM', 'HIGH', 'ULTRA_HIGH'],
                                 state='readonly', width=18)
        led_combo.grid(row=1, column=1, pady=5, padx=5)
        
        ttk.Label(cam_frame, text="曝光設定:", font=('Arial', 9)
                  ).grid(row=2, column=0, sticky=tk.W, pady=5)
        self.exposure_var = tk.StringVar(value=self.config['camera']['exposure_setting'])
        exp_combo = ttk.Combobox(cam_frame, textvariable=self.exposure_var,
                                 values=['DEFAULT', 'UNKNOWN'],
                                 state='readonly', width=18)
        exp_combo.grid(row=2, column=1, pady=5, padx=5)
        
        ttk.Label(cam_frame, text="說明：修改相機參數需重啟相機",
                  font=('Arial', 8), foreground='gray').grid(row=3, column=0,
                                                             columnspan=2, pady=5)
        
        ttk.Button(cam_frame, text="套用相機參數",
                   command=lambda: self.apply_config('camera')).grid(row=4, column=0,
                                                                     columnspan=2, pady=10)
        
        # ROI 設定
        roi_frame = ttk.LabelFrame(container, text="ROI 區域設定", padding=15)
        roi_frame.grid(row=1, column=0, sticky=(tk.N, tk.W, tk.E), padx=5, pady=5)
        
        self.roi_enabled_var = tk.BooleanVar(value=self.config['roi']['enabled'])
        ttk.Checkbutton(roi_frame, text="啟用 ROI（感興趣區域）",
                        variable=self.roi_enabled_var, command=self.toggle_roi
                        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        ttk.Label(roi_frame, text="X1 (左):", font=('Arial', 9)
                  ).grid(row=1, column=0, sticky=tk.W, pady=3)
        self.roi_x1_var = tk.IntVar(value=self.config['roi']['x1'])
        ttk.Spinbox(roi_frame, from_=0, to=159, textvariable=self.roi_x1_var,
                    width=15).grid(row=1, column=1, pady=3, padx=5)
        
        ttk.Label(roi_frame, text="Y1 (上):", font=('Arial', 9)
                  ).grid(row=2, column=0, sticky=tk.W, pady=3)
        self.roi_y1_var = tk.IntVar(value=self.config['roi']['y1'])
        ttk.Spinbox(roi_frame, from_=0, to=159, textvariable=self.roi_y1_var,
                    width=15).grid(row=2, column=1, pady=3, padx=5)
        
        ttk.Label(roi_frame, text="X2 (右):", font=('Arial', 9)
                  ).grid(row=3, column=0, sticky=tk.W, pady=3)
        self.roi_x2_var = tk.IntVar(value=self.config['roi']['x2'])
        ttk.Spinbox(roi_frame, from_=0, to=159, textvariable=self.roi_x2_var,
                    width=15).grid(row=3, column=1, pady=3, padx=5)
        
        ttk.Label(roi_frame, text="Y2 (下):", font=('Arial', 9)
                  ).grid(row=4, column=0, sticky=tk.W, pady=3)
        self.roi_y2_var = tk.IntVar(value=self.config['roi']['y2'])
        ttk.Spinbox(roi_frame, from_=0, to=159, textvariable=self.roi_y2_var,
                    width=15).grid(row=4, column=1, pady=3, padx=5)
        
        ttk.Button(roi_frame, text="套用 ROI 設定",
                   command=lambda: self.apply_config('roi')).grid(row=5, column=0,
                                                                  columnspan=2, pady=10)
        
        # === 第二列：分析參數 + 配置管理 ===
        
        # 分析參數
        analysis_frame = ttk.LabelFrame(container, text="分析參數", padding=15)
        analysis_frame.grid(row=0, column=1, sticky=(tk.N, tk.W, tk.E), padx=5, pady=5)
        
        self.use_transform_var = tk.BooleanVar(
            value=self.config['analysis']['use_depth_transform'])
        ttk.Checkbutton(analysis_frame, text="使用物理模型深度轉換（推薦）",
                        variable=self.use_transform_var
                        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=5)
        
        ttk.Label(analysis_frame, text="濾波窗口大小:", font=('Arial', 9)
                  ).grid(row=1, column=0, sticky=tk.W, pady=5)
        self.filter_window_var = tk.IntVar(value=self.config['analysis']['filter_window'])
        ttk.Spinbox(analysis_frame, from_=1, to=20, textvariable=self.filter_window_var,
                    width=15).grid(row=1, column=1, pady=5, padx=5)
        
        ttk.Label(analysis_frame, text="狀態持續幀數:", font=('Arial', 9)
                  ).grid(row=2, column=0, sticky=tk.W, pady=5)
        self.min_state_duration_var = tk.IntVar(
            value=self.config['analysis']['min_state_duration'])
        ttk.Spinbox(analysis_frame, from_=1, to=10,
                    textvariable=self.min_state_duration_var,
                    width=15).grid(row=2, column=1, pady=5, padx=5)
        
        ttk.Label(analysis_frame,
                  text="說明：濾波窗口越大越穩定但響應慢\n      狀態持續幀數可防止誤判",
                  font=('Arial', 8), foreground='gray', justify=tk.LEFT
                  ).grid(row=3, column=0, columnspan=2, pady=5)
        
        ttk.Button(analysis_frame, text="套用分析參數",
                   command=lambda: self.apply_config('analysis')).grid(row=4, column=0,
                                                                       columnspan=2, pady=10)
        
        # 配置管理
        manage_frame = ttk.LabelFrame(container, text="配置管理", padding=15)
        manage_frame.grid(row=1, column=1, sticky=(tk.N, tk.W, tk.E), padx=5, pady=5)
        
        ttk.Label(manage_frame, text=f"配置文件：{self.config_file.name}",
                  font=('Arial', 9)).pack(pady=5)
        
        ttk.Button(manage_frame, text="全部套用並儲存",
                   command=self.save_all_config).pack(fill=tk.X, pady=5)
        
        ttk.Button(manage_frame, text="重新載入配置",
                   command=self.reload_config).pack(fill=tk.X, pady=5)
        
        # 配置 Canvas 和 Scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
    def on_threshold_open_change(self, value):
        """Open 閾值 Slider 變動時的回調"""
        value = float(value)
        self.config['thresholds']['open'] = value
        self.threshold_open_value_label.config(text=f"{value:.3f}")
        
        # 更新狀態偵測器
        if self.state_detector:
            self.state_detector.threshold_open = value
        
        # 自動儲存到 YAML
        self.save_config()
    
    def on_threshold_closed_change(self, value):
        """Closed 閾值 Slider 變動時的回調"""
        value = float(value)
        self.config['thresholds']['closed'] = value
        self.threshold_closed_value_label.config(text=f"{value:.3f}")
        
        # 更新狀態偵測器
        if self.state_detector:
            self.state_detector.threshold_closed = value
        
        # 自動儲存到 YAML
        self.save_config()
        
    def get_camera_config(self):
        """獲取相機配置"""
        frame_rate_map = {
            'FULL': MN96100CConfig.FrameRate.FULL,
            'HALF': MN96100CConfig.FrameRate.HALF,
            'QUARTER': MN96100CConfig.FrameRate.QUARTER,
            'EIGHTH': MN96100CConfig.FrameRate.EIGHTH,
            'SIXTEENTH': MN96100CConfig.FrameRate.SIXTEENTH
        }
        
        led_current_map = {
            'LOW': MN96100CConfig.LEDCurrent.LOW,
            'MEDIUM': MN96100CConfig.LEDCurrent.MEDIUM,
            'HIGH': MN96100CConfig.LEDCurrent.HIGH,
            'ULTRA_HIGH': MN96100CConfig.LEDCurrent.ULTRA_HIGH
        }
        
        exposure_map = {
            'DEFAULT': MN96100CConfig.ExposureSetting.DEFAULT,
            'UNKNOWN': MN96100CConfig.ExposureSetting.UNKNOWN
        }
        
        return {
            'frame_rate': frame_rate_map[self.config['camera']['frame_rate']],
            'led_current': led_current_map[self.config['camera']['led_current']],
            'exposure_setting': exposure_map[self.config['camera']['exposure_setting']]
        }
    
    def start_camera(self):
        """啟動相機"""
        if self.is_running:
            messagebox.showwarning("警告", "相機已在運行中")
            return
        
        try:
            config = self.get_camera_config()
            
            self.cap = VideoCapture(
                exposure_setting=config['exposure_setting'],
                frame_rate=config['frame_rate'],
                led_current=config['led_current'],
                tx_output=MN96100CConfig.TXOutput.RESOLUTION_160x160,
                vid=self.config['camera']['vid'],
                pid=self.config['camera']['pid']
            )
            
            # 初始化狀態偵測器
            self.state_detector = DrawerStateDetector(
                self.config['thresholds']['open'],
                self.config['thresholds']['closed'],
                self.config['analysis']['filter_window'],
                self.config['analysis']['min_state_duration']
            )
            
            # 重置數據
            self.time_data.clear()
            self.depth_metric_data.clear()
            self.intensity_mean_data.clear()
            self.start_time = time.time()
            self.frame_count = 0
            
            # 啟動捕獲線程
            self.is_running = True
            self.capture_thread = threading.Thread(target=self.capture_loop, daemon=True)
            self.capture_thread.start()
            
            self.start_button.config(state='disabled')
            self.stop_button.config(state='normal')
            
        except Exception as e:
            messagebox.showerror("錯誤", f"無法啟動相機:\n{str(e)}")
            self.is_running = False
            if self.cap:
                self.cap.release()
                self.cap = None
    
    def stop_camera(self):
        """停止相機"""
        self.is_running = False
        
        if self.capture_thread:
            self.capture_thread.join(timeout=2.0)
        
        if self.cap:
            self.cap.release()
            self.cap = None
        
        self.start_button.config(state='normal')
        self.stop_button.config(state='disabled')
    
    def capture_loop(self):
        """相機捕獲循環"""
        while self.is_running:
            ret, frame = self.cap.read()
            
            if ret and frame is not None:
                self.frame_count += 1
                current_time = time.time() - self.start_time
                
                # 轉換為灰度
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                
                # 選擇 ROI
                if self.config['roi']['enabled']:
                    x1, y1 = self.config['roi']['x1'], self.config['roi']['y1']
                    x2, y2 = self.config['roi']['x2'], self.config['roi']['y2']
                    roi = gray[y1:y2, x1:x2]
                    # 繪製 ROI 框
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                else:
                    roi = gray
                
                # 計算深度指標
                metrics = self.depth_analyzer.calculate_depth_metrics(
                    roi, use_transform=self.config['analysis']['use_depth_transform']
                )
                
                depth_metric = metrics['mean']
                intensity_mean = metrics['intensity_mean']
                
                # 狀態判斷
                if self.state_detector:
                    drawer_status = self.state_detector.update(depth_metric)
                else:
                    drawer_status = "未知"
                
                # 更新數據
                self.time_data.append(current_time)
                self.depth_metric_data.append(depth_metric)
                self.intensity_mean_data.append(intensity_mean)
                
                # 更新 UI
                self.root.after(0, self.update_ui, frame, drawer_status,
                                depth_metric, intensity_mean)
            else:
                time.sleep(0.01)
    
    def update_ui(self, frame, drawer_status, depth_metric, intensity_mean):
        """更新 UI"""
        # 更新圖像（320x320，適配窗口尺寸）
        display_frame = cv2.resize(frame, (320, 320),
                                   interpolation=cv2.INTER_NEAREST)
        gray = cv2.cvtColor(display_frame, cv2.COLOR_BGR2GRAY)
        colored = cv2.applyColorMap(gray, cv2.COLORMAP_JET)
        
        image = cv2.cvtColor(colored, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(image)
        photo = ImageTk.PhotoImage(image=image)
        
        self.image_label.config(image=photo)
        self.image_label.image = photo
        
        # 更新狀態
        self.drawer_status_label.config(text=drawer_status)
        color_map = {
            "完全閉合": 'green',
            "閉合中": 'orange',
            "完全開啟": 'red',
            "未知": 'gray'
        }
        self.drawer_status_label.config(foreground=color_map.get(drawer_status, 'gray'))
        
        # 更新圖表
        self.update_chart()
    
    def update_chart(self):
        """更新圖表"""
        if len(self.time_data) < 2:
            return
        
        # 上圖：深度指標
        self.ax1.clear()
        self.ax1.plot(list(self.time_data), list(self.depth_metric_data),
                      'b-', linewidth=2, label='Depth Metric')
        
        if len(self.time_data) > 0:
            time_range = [self.time_data[0], self.time_data[-1]]
            self.ax1.plot(time_range,
                          [self.config['thresholds']['open']] * 2,
                          'r--', label='Open Threshold', alpha=0.7, linewidth=1.5)
            self.ax1.plot(time_range,
                          [self.config['thresholds']['closed']] * 2,
                          'g--', label='Closed Threshold', alpha=0.7, linewidth=1.5)
        
        self.ax1.set_ylabel('Depth Metric', fontsize=9)
        self.ax1.set_ylim(0, 1.0)  # 固定y軸範圍為理論極限
        title = 'Depth Time Series'
        if self.config['analysis']['use_depth_transform']:
            title += ' (Physical Model)'
        else:
            title += ' (Raw Intensity)'
        self.ax1.set_title(title, fontsize=10)
        self.ax1.legend(loc='upper right', fontsize=8)
        self.ax1.grid(True, alpha=0.3)
        self.ax1.tick_params(labelsize=8)
        
        # 下圖：原始強度
        self.ax2.clear()
        self.ax2.plot(list(self.time_data), list(self.intensity_mean_data),
                      'orange', linewidth=1.5, label='Reflection Intensity')
        
        self.ax2.set_xlabel('Time (seconds)', fontsize=9)
        self.ax2.set_ylabel('Intensity Value', fontsize=9)
        self.ax2.set_ylim(0, 255)  # 固定y軸範圍為8-bit極限
        self.ax2.set_title('Reflection Light Intensity', fontsize=10)
        self.ax2.legend(loc='upper right', fontsize=8)
        self.ax2.grid(True, alpha=0.3)
        self.ax2.tick_params(labelsize=8)
        
        self.fig.tight_layout()
        self.canvas.draw()
    
    def toggle_roi(self):
        """切換 ROI"""
        self.config['roi']['enabled'] = self.roi_enabled_var.get()
    
    def apply_config(self, section):
        """套用特定部分的配置"""
        try:
            if section == 'camera':
                self.config['camera']['frame_rate'] = self.frame_rate_var.get()
                self.config['camera']['led_current'] = self.led_current_var.get()
                self.config['camera']['exposure_setting'] = self.exposure_var.get()
                msg = "相機參數已更新"
                if self.is_running:
                    msg += "。\n請重新啟動相機以套用新參數。"
                
            elif section == 'roi':
                x1, y1 = self.roi_x1_var.get(), self.roi_y1_var.get()
                x2, y2 = self.roi_x2_var.get(), self.roi_y2_var.get()
                
                if x1 >= x2 or y1 >= y2:
                    messagebox.showerror("錯誤", "ROI 範圍無效：確保 X1 < X2 且 Y1 < Y2")
                    return
                
                if x1 < 0 or y1 < 0 or x2 > 160 or y2 > 160:
                    messagebox.showerror("錯誤", "ROI 範圍超出邊界（0-160）")
                    return
                
                self.config['roi']['x1'] = x1
                self.config['roi']['y1'] = y1
                self.config['roi']['x2'] = x2
                self.config['roi']['y2'] = y2
                self.config['roi']['enabled'] = self.roi_enabled_var.get()
                msg = f"ROI 設定已更新：({x1},{y1}) 到 ({x2},{y2})"
                
            elif section == 'analysis':
                self.config['analysis']['use_depth_transform'] = self.use_transform_var.get()
                self.config['analysis']['filter_window'] = self.filter_window_var.get()
                self.config['analysis']['min_state_duration'] = self.min_state_duration_var.get()
                
                # 重新初始化狀態偵測器
                if self.state_detector:
                    self.state_detector = DrawerStateDetector(
                        self.config['thresholds']['open'],
                        self.config['thresholds']['closed'],
                        self.config['analysis']['filter_window'],
                        self.config['analysis']['min_state_duration']
                    )
                
                msg = "分析參數已更新"
            
            # 自動儲存到 YAML
            self.save_config()
            messagebox.showinfo("成功", f"{msg}\n\n配置已自動儲存到 {self.config_file.name}")
            
        except Exception as e:
            messagebox.showerror("錯誤", f"套用配置失敗:\n{str(e)}")
    
    def save_all_config(self):
        """儲存所有配置"""
        try:
            # 更新所有配置
            self.config['camera']['frame_rate'] = self.frame_rate_var.get()
            self.config['camera']['led_current'] = self.led_current_var.get()
            self.config['camera']['exposure_setting'] = self.exposure_var.get()
            
            self.config['roi']['x1'] = self.roi_x1_var.get()
            self.config['roi']['y1'] = self.roi_y1_var.get()
            self.config['roi']['x2'] = self.roi_x2_var.get()
            self.config['roi']['y2'] = self.roi_y2_var.get()
            self.config['roi']['enabled'] = self.roi_enabled_var.get()
            
            self.config['analysis']['use_depth_transform'] = self.use_transform_var.get()
            self.config['analysis']['filter_window'] = self.filter_window_var.get()
            self.config['analysis']['min_state_duration'] = self.min_state_duration_var.get()
            
            # 儲存到 YAML
            self.save_config()
            messagebox.showinfo("成功", f"所有配置已儲存到 {self.config_file.name}")
            
        except Exception as e:
            messagebox.showerror("錯誤", f"儲存配置失敗:\n{str(e)}")
    
    def save_config(self):
        """儲存配置到 YAML 檔案"""
        try:
            # 確保配置目錄存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, default_flow_style=False,
                          allow_unicode=True, sort_keys=False)
        except Exception as e:
            print(f"儲存配置失敗: {str(e)}")
    
    def load_config(self):
        """從 YAML 檔案載入配置"""
        if not self.config_file.exists():
            # 如果配置檔案不存在，創建默認配置
            self.save_config()
            return
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                loaded_config = yaml.safe_load(f)
                if loaded_config:
                    # 遞迴更新配置（保留默認值）
                    self._update_dict(self.config, loaded_config)
        except Exception as e:
            print(f"載入配置失敗: {str(e)}")
    
    def _update_dict(self, target, source):
        """遞迴更新字典"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._update_dict(target[key], value)
            else:
                target[key] = value
    
    def reload_config(self):
        """重新載入配置"""
        try:
            self.load_config()
            
            # 更新 UI 組件
            self.frame_rate_var.set(self.config['camera']['frame_rate'])
            self.led_current_var.set(self.config['camera']['led_current'])
            self.exposure_var.set(self.config['camera']['exposure_setting'])
            
            self.roi_enabled_var.set(self.config['roi']['enabled'])
            self.roi_x1_var.set(self.config['roi']['x1'])
            self.roi_y1_var.set(self.config['roi']['y1'])
            self.roi_x2_var.set(self.config['roi']['x2'])
            self.roi_y2_var.set(self.config['roi']['y2'])
            
            # 更新 Slider 值（TAB1）
            self.threshold_open_slider.set(self.config['thresholds']['open'])
            self.threshold_closed_slider.set(self.config['thresholds']['closed'])
            
            self.use_transform_var.set(self.config['analysis']['use_depth_transform'])
            self.filter_window_var.set(self.config['analysis']['filter_window'])
            self.min_state_duration_var.set(self.config['analysis']['min_state_duration'])
            
            messagebox.showinfo("成功", f"配置已從 {self.config_file.name} 重新載入")
            
        except Exception as e:
            messagebox.showerror("錯誤", f"重新載入配置失敗:\n{str(e)}")
    
    def on_closing(self):
        """關閉應用程式"""
        if self.is_running:
            self.stop_camera()
        self.root.destroy()


def main():
    """主程式入口"""
    root = tk.Tk()
    app = DrawerMonitorApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
