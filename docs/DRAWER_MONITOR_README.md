# Drawer Monitor 使用說明

## 概述

本工具使用 MN96100C 2.5D 影像感測器監測抽屜閉合狀態，提供：

- 即時 160×160 深度影像顯示（JET 偽彩色）
- 雙通道時間序列圖（強度 + 相對距離）
- 動態閾值調整（即時滑桿）
- 相機參數控制與 ROI 設定
- 配置自動儲存（`config/drawer_config.yaml`）

---

## 感測器原理

### MN96100C 2.5D Sensor 物理模型

MN96100C 主動式紅外光感測器，每個 pixel 的 8-bit 數值代表**接收到的反射光強度**（晶片內部已扣除環境光）。

```
每個 pixel 值（0-255）= 接收到的反射光強度
```

#### 強度與距離的關係

反射光強度與距離的物理關係為：

```
相對距離 ∝ 1 / √(反射光強度)
```

因此：

| 情況 | Intensity 值 | Relative Distance (1/√I) |
|------|-------------|--------------------------|
| 抽屜完全閉合（近距離，強反射） | 高（例如 150-220） | 低（例如 0.067-0.082） |
| 抽屜插入中（中距離） | 中（例如 80-150） | 中（例如 0.082-0.112） |
| 抽屜完全開啟（遠距離，弱反射，看到地板） | 低（例如 20-80） | 高（例如 0.112-0.224） |

> **注意**：2.5D Sensor 輸出的是**相對距離**，非絕對距離（ToF 才是絕對距離）。
> 實際數值範圍與反射面材質、LED 波長/強度有關，需針對實際環境進行校準。

### 本應用的監測邏輯

相機固定於箱體內，鏡頭直對抽屜平面：

```
抽屜未閉合 → 相機看到更遠的地板 → 弱反射 → Intensity 低
抽屜推入中 → 抽屜前板進入視野 → 反射增強 → Intensity 上升
抽屜完全閉合 → 地板完全被遮擋 → 強反射 → Intensity 高
```

---

## 應用程式介面

### 視窗佈局

```
┌─────────────────────────────────────────────────────────┐
│ MN96100C 2.5D 抽屜閉合監測系統                1024×600  │
├──────────────────────┬──────────────────────────────────┤
│  [數據串流 Tab]       │  [參數配置 Tab]                  │
├──────────────────────┴──────────────────────────────────┤
│                                                          │
│  抽屜狀態：[完全閉合]  [啟動相機]  [停止相機]            │
│                                                          │
│  ┌────────────────┐  ┌──────────────────────────────┐   │
│  │                │  │  Drawer Intensity (0-255)     │   │
│  │   320×320      │  │  ─── Smoothed  --- Threshold  │   │
│  │  JET 偽彩色    │  ├──────────────────────────────┤   │
│  │   + ROI 框     │  │  Relative Distance (1/√I)     │   │
│  │                │  │  ─── 1/√I  --- Threshold      │   │
│  ├────────────────┤  └──────────────────────────────┘   │
│  │ 閉合閾值 [===] │                                      │
│  │ 開啟閾值 [===] │                                      │
│  └────────────────┘                                      │
└──────────────────────────────────────────────────────────┘
```

### Tab 1：數據串流

#### 時間序列雙通道圖

| 圖表 | Y 軸 | 內容 | 物理意義 |
|------|------|------|---------|
| 上圖（ax1） | Intensity 0-255 | ROI 平均強度 + MA 平滑 + 閾值線 | 高=近=閉合，低=遠=開啟 |
| 下圖（ax2） | Relative Distance 0.05-1.05 | 1/√(Intensity) + 對應閾值線 | 高=遠=開啟，低=近=閉合 |

兩圖方向相反，互為驗證：ax1 曲線上升時，ax2 曲線下降，符合物理預期。

#### 閾值滑桿

- **閉合閾值（高）**：Intensity 超過此值 → 判定「完全閉合」（綠色）
- **開啟閾值（低）**：Intensity 低於此值 → 判定「完全開啟」（紅色）
- 介於兩者之間 → 「閉合中」（橙色）
- 拖動滑桿即時儲存至 YAML

```
Intensity > 閉合閾值  → 完全閉合（綠）
開啟閾值 < Intensity ≤ 閉合閾值 → 閉合中（橙）
Intensity ≤ 開啟閾值  → 完全開啟（紅）
```

### Tab 2：參數配置

| 參數區塊 | 說明 |
|---------|------|
| 相機參數 | Frame Rate / LED 電流 / 曝光設定（修改需重啟相機） |
| ROI 設定 | 感興趣區域，僅分析指定矩形範圍（0-159 像素） |
| 分析參數 | 狀態持續幀數（防抖動，3-15 幀） |
| 顯示參數 | Moving Average 視窗大小、是否同時顯示原始數據 |
| 配置管理 | 全部套用並儲存 / 重新載入配置 |

---

## 快速啟動

### 1. 啟動應用程式

```bash
python drawer_monitor.py
```

### 2. 初次設定流程

#### 步驟 A：啟動相機

1. 點擊「啟動相機」（預設參數通常可直接使用）
2. 確認 320×320 圖像區域有畫面出現
3. 若畫面全黑：Tab 2 → LED 電流調高至 `ULTRA_HIGH`
4. 若畫面全白：LED 電流調低至 `HIGH` 或 `MEDIUM`

#### 步驟 B：觀察基準值

1. **抽屜完全拉開**（相機看到地板）
   - 觀察 ax1 曲線穩定後的 Intensity 值，記錄（例如：30-60）
   - 此為「開啟基準」

2. **抽屜完全推入閉合**
   - 觀察 ax1 曲線穩定後的 Intensity 值，記錄（例如：150-200）
   - 此為「閉合基準」

#### 步驟 C：設定閾值

根據觀察到的基準值，設定兩個閾值（兩者之間保留 20-30 的間隔作為遲滯區間）：

```
閉合閾值 = 閉合基準值的低端 - 安全裕度（例如：150 - 10 = 140）
開啟閾值 = 開啟基準值的高端 + 安全裕度（例如：60 + 10 = 70）
```

> **建議**：兩閾值間距 ≥ 20，避免在邊界值附近頻繁切換狀態。

#### 步驟 D：驗證與微調

多次開關抽屜，確認狀態標籤切換正確，再點擊「全部套用並儲存」。

---

## 相機參數說明

### Frame Rate（幀率）

| 設定 | 說明 | 建議使用場景 |
|------|------|-------------|
| `FULL` | 最高幀率 | 需要快速響應時 |
| `HALF` | 1/2 幀率 | — |
| `QUARTER` | 1/4 幀率（**預設**） | 一般使用，雜訊低 |
| `EIGHTH` | 1/8 幀率 | 環境干擾大時 |
| `SIXTEENTH` | 1/16 幀率 | 極低雜訊需求 |

### LED Current（LED 電流）

| 設定 | 電流 | 說明 |
|------|------|------|
| `LOW` | 50mA × 2 | 近距離、高反射面 |
| `MEDIUM` | 100mA × 2 | — |
| `HIGH` | 200mA × 2 | — |
| `ULTRA_HIGH` | 400mA × 2（**預設**） | 遠距離或低反射面 |

### Exposure Setting（曝光設定）

| 設定 | 說明 |
|------|------|
| `DEFAULT`（**預設**） | 標準自動曝光 |
| `UNKNOWN` | 替代曝光模式（可嘗試用於改善特定材質） |

---

## 配置檔說明

配置自動儲存於 `config/drawer_config.yaml`：

```yaml
camera:
  vid: 0x04F3          # USB Vendor ID
  pid: 0x0C7E          # USB Product ID
  frame_rate: QUARTER
  led_current: ULTRA_HIGH
  exposure_setting: DEFAULT

roi:
  enabled: false
  x1: 40               # ROI 左上角 X
  y1: 40               # ROI 左上角 Y
  x2: 120              # ROI 右下角 X
  y2: 120              # ROI 右下角 Y

thresholds:
  open: 80             # 開啟閾值（Intensity 低於此值 → 完全開啟）
  closed: 150          # 閉合閾值（Intensity 高於此值 → 完全閉合）

analysis:
  min_state_duration: 5   # 狀態確認所需連續幀數（防抖動）
  history_size: 500

display:
  smoothing_window: 10    # Moving Average 視窗大小
  show_raw_data: false    # 是否同時顯示原始未平滑數據
  enable_smoothing: true
```

---

## API 整合範例

校準完成後，將核心邏輯整合至主系統：

```python
from eminent.sensors.vision2p5d import VideoCapture, MN96100CConfig
from utils.depth_analysis import DepthAnalyzer, DrawerStateDetector
import cv2

# 初始化感測器
cap = VideoCapture(
    frame_rate=MN96100CConfig.FrameRate.QUARTER,
    led_current=MN96100CConfig.LEDCurrent.ULTRA_HIGH,
    exposure_setting=MN96100CConfig.ExposureSetting.DEFAULT,
    tx_output=MN96100CConfig.TXOutput.RESOLUTION_160x160,
    vid=0x04F3,
    pid=0x0C7E
)

# 初始化分析器（閾值來自校準結果）
analyzer = DepthAnalyzer()
detector = DrawerStateDetector(
    threshold_open=80,     # 從 drawer_config.yaml 讀取
    threshold_closed=150,  # 從 drawer_config.yaml 讀取
    min_state_duration=5
)

# 主迴圈
while True:
    ret, frame = cap.read()
    if not ret:
        continue

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    roi = gray[40:120, 40:120]  # 依校準時的 ROI 設定

    metrics = analyzer.calculate_depth_metrics(roi)
    state = detector.update(metrics['mean'])  # 傳入 intensity_mean (0-255)

    if state == "完全閉合":
        print("✓ 抽屜已安全關閉")
        break
    elif state == "完全開啟":
        print("⚠ 請關閉抽屜")

cap.release()
```

### metrics 字典欄位說明

| 欄位 | 類型 | 說明 |
|------|------|------|
| `mean` | float | ROI 平均強度值（0-255），**狀態判斷的主要依據** |
| `relative_distance` | float | 1/√mean，相對距離指標（0.063-1.0） |
| `median` | float | ROI 中位數強度 |
| `std` | float | ROI 強度標準差 |
| `min` / `max` | float | ROI 最小/最大強度值 |
| `percentile_10/90` | float | 10th / 90th 百分位數 |
| `range` | float | max - min |

---

## 故障排除

### 相機無法啟動

1. 確認 USB 連接（建議使用 USB 3.0 埠）
2. 確認 VID/PID：預設 `0x04F3:0x0C7E`
3. Windows：安裝 libusb-win32 驅動（使用 Zadig 工具）
4. 確認 `pyusb` 已安裝：`pip install pyusb`

### 圖像全黑或全白

| 症狀 | 原因 | 解決方法 |
|------|------|---------|
| 全黑 | LED 電流不足或距離太遠 | Tab 2 → LED 電流調至 `ULTRA_HIGH` |
| 全白 | LED 電流過強或距離太近 | LED 電流調至 `HIGH` 或 `MEDIUM` |
| 雜訊多 | 幀率過高 | Frame Rate 調至 `QUARTER` 或 `EIGHTH` |

### 狀態判斷不準確

確認閾值方向：

```
Intensity 高（150-255）= 近距離 = 抽屜閉合  → 閉合閾值應設在此範圍下緣
Intensity 低（0-80）   = 遠距離 = 抽屜開啟  → 開啟閾值應設在此範圍上緣
```

若數值範圍與預期相反，檢查相機安裝方向是否正確（鏡頭需正對抽屜平面）。

### 狀態頻繁切換

1. 增大兩閾值間距（`closed - open ≥ 20`）
2. 增加「狀態持續幀數」（Tab 2 → 分析參數 → 調至 8-10）
3. 縮小 ROI 至抽屜前板的中央穩定區域，排除邊緣反光

### FPS 過低 / GUI 卡頓

1. Frame Rate 調高（`QUARTER` → `HALF`）
2. 關閉「同時顯示原始數據」選項（Tab 2 → 顯示參數）
3. 減小 Moving Average 視窗大小

---

## 相關檔案

```
FY114-Drug-Recognition-Subsystem/
├── drawer_monitor.py              # 主應用程式（校準工具 GUI）
├── config/
│   └── drawer_config.yaml         # 配置檔（自動生成與儲存）
├── utils/
│   └── depth_analysis.py          # DepthAnalyzer、DrawerStateDetector
├── eminent/
│   └── sensors/
│       └── vision2p5d/
│           ├── __init__.py        # VideoCapture、MN96100CConfig
│           └── mn96100c.py        # USBDeviceComm 底層驅動
├── tests/
│   └── run_25d.py                 # 最簡測試程式（確認相機可讀幀）
└── docs/
    └── DRAWER_MONITOR_README.md   # 本文件
```

## 版本歷史

- **v2.0**（目前）：Tab 介面、YAML 配置、直接使用 intensity (0-255) 作為判斷依據、雙通道圖（intensity + relative distance）
- **v1.5**：JSON 配置、雙通道時間序列
- **v1.0**：基礎版，單視窗佈局
