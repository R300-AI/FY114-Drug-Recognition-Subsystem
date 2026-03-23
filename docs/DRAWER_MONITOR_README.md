# Drawer Monitor — 完整技術文件

> **版本**：v2.0｜**日期**：2026-03-12
>
> 本文件為 `drawer_monitor.py` 的唯一權威參考，涵蓋感測器原理、訊號架構、UI 操作、參數調校、API 整合與故障排除。

---

## 目錄

1. [感測器物理原理](#1-感測器物理原理)
2. [訊號處理架構](#2-訊號處理架構)
3. [快速啟動](#3-快速啟動)
4. [應用程式介面（UI）](#4-應用程式介面ui)
5. [配置檔說明](#5-配置檔說明)
6. [校準流程](#6-校準流程)
7. [SMA 濾波調校指南](#7-sma-濾波調校指南)
8. [相機參數說明](#8-相機參數說明)
9. [API 整合範例](#9-api-整合範例)
10. [相關檔案結構](#10-相關檔案結構)
11. [故障排除](#11-故障排除)

---

## 1. 感測器物理原理

### MN96100C 2.5D Sensor

主動式紅外光感測器，160×160 px，每個 pixel 的 8-bit 值代表**接收到的反射光強度**（晶片內部已扣除環境光）。

```
每個 pixel 值（0–255）= 接收到的反射光強度
```

### 強度與距離的關係

```
相對距離 ∝ 1 / √(反射光強度)
```

| 情況 | Intensity（0–255） | Relative Distance（1/√I） |
|------|-------------------|--------------------------|
| 抽屜完全閉合（近距離，強反射） | 高（例如 150–220） | 低（例如 0.067–0.082） |
| 抽屜推入中（中距離） | 中（例如 80–150） | 中（例如 0.082–0.112） |
| 抽屜完全開啟（遠距離，弱反射） | 低（例如 20–80） | 高（例如 0.112–0.224） |

> **注意**：輸出的是**相對距離**，非 ToF 絕對距離。實際數值範圍與反射面材質、LED 電流有關，需針對實際環境校準。

### 本應用的監測邏輯

相機固定於箱體內，鏡頭直對抽屜平面：

```
抽屜未閉合 → 相機看到更遠的地板 → 弱反射 → Intensity 低
抽屜推入中 → 抽屜前板進入視野 → 反射增強 → Intensity 上升
抽屜完全閉合 → 地板完全被遮擋 → 強反射 → Intensity 高
```

---

## 2. 訊號處理架構

### 完整訊號流程

```
MN96100C Sensor
    ↓
intensity_mean (0–255)  ← ROI 區域的算術平均
    ↓
deque（最近 history_size 幀）
    ↓
[SMA(N)]  取最近 N 幀算術平均
    ↓
平滑後 intensity 值（同時用於圖表顯示與狀態判斷）
    ↓
[DrawerStateDetector 閾值比較]
  intensity > threshold_closed  → 完全閉合
  threshold_open < intensity ≤ threshold_closed → 閉合中
  intensity ≤ threshold_open   → 完全開啟
    ↓
[防抖] 需連續 min_state_duration 幀才確認狀態變更
    ↓
最終狀態：完全閉合 / 閉合中 / 完全開啟 / 未知
```

### SMA 公式（與股票 N 日均線相同）

```
SMA(t) = (I(t) + I(t-1) + ... + I(t-N+1)) / N
```

- 每個樣本均等加權
- 樣本不足 N 幀時使用自適應分母（以實際幀數為分母）
- N 幀後維持固定視窗滑動
- **同一個 N 值同時作用於圖表顯示與狀態判斷**

### 雙通道圖表

| 圖表 | Y 軸 | 公式 | 物理意義 |
|------|------|------|---------|
| ax1（上） | Intensity 0–255 | SMA(N) of intensity_mean | 高=近=閉合，低=遠=開啟 |
| ax2（下） | Relative Distance 0.05–1.05 | 1/√(intensity_mean) | 高=遠=開啟，低=近=閉合 |

兩圖方向相反，互為驗證。

---

## 3. 快速啟動

```bash
python drawer_monitor.py
```

初次執行時若無 `config/drawer_config.yaml`，自動以預設值建立。

---

## 4. 應用程式介面（UI）

### 視窗佈局（1024×600）

```
┌────────────────────────────────────────────────┐
│  [數據串流 Tab]          [參數配置 Tab]          │
├────────────────────┬───────────────────────────┤
│  抽屜狀態  啟動 停止  │  雙通道時間序列圖          │
│                    │  ax1: Intensity SMA(N)     │
│  320×320 JET 影像  │  ax2: Relative Distance   │
│                    │                           │
│  閉合閾值 [═══════] │                           │
│  開啟閾值 [═══════] │                           │
└────────────────────┴───────────────────────────┘
```

### Tab 1：數據串流

| 元件 | 說明 |
|------|------|
| 抽屜狀態標籤 | 完全閉合（綠）/ 閉合中（橙）/ 完全開啟（紅）/ 未知（灰） |
| 啟動相機 | 建立 USB 連線，啟動 capture thread |
| 停止相機 | 停止 capture thread，釋放 USB |
| JET 偽彩色影像 | 320×320 顯示（原始 160×160 放大 2x），ROI 框以綠線標示 |
| 閉合閾值 Slider | intensity > 此值 → 完全閉合；即時儲存至 YAML |
| 開啟閾值 Slider | intensity ≤ 此值 → 完全開啟；即時儲存至 YAML |

**閾值順序驗證**：Slider 拖動時自動確保 `threshold_closed > threshold_open`，防止設定矛盾。

### Tab 2：參數配置

| 區塊 | 參數 | 說明 |
|------|------|------|
| 相機參數 | Frame Rate | 修改需重啟相機 |
| | LED 電流 | 修改需重啟相機 |
| | 曝光設定 | 修改需重啟相機 |
| ROI 設定 | 啟用/停用 | 感興趣區域（0–159 像素） |
| | X1/Y1/X2/Y2 | ROI 矩形座標 |
| 分析參數 | 狀態持續幀數 | 防抖，3–15 幀 |
| 顯示參數 | 啟用 SMA | 停用時使用原始 intensity |
| | SMA 視窗大小 N | 1–30；同時影響圖表與狀態判斷 |
| | 同時顯示原始數據 | ax1 加繪灰色原始線 |
| 配置管理 | 全部套用並儲存 | 一次性儲存所有設定 |
| | 重新載入配置 | 從 YAML 重新載入並更新 UI |

---

## 5. 配置檔說明

路徑：`config/drawer_config.yaml`（自動建立與儲存）

```yaml
camera:
  vid: 0x04F3            # USB Vendor ID（十六進位，YAML 儲存後轉十進位 1267）
  pid: 0x0C7E            # USB Product ID（十六進位，YAML 儲存後轉十進位 3198）
  frame_rate: QUARTER    # FULL / HALF / QUARTER / EIGHTH / SIXTEENTH
  led_current: ULTRA_HIGH  # LOW / MEDIUM / HIGH / ULTRA_HIGH
  exposure_setting: DEFAULT  # DEFAULT / UNKNOWN

roi:
  enabled: false         # true = 只分析指定矩形區域
  x1: 40                 # 左上角 X（0–159）
  y1: 40                 # 左上角 Y（0–159）
  x2: 120                # 右下角 X（0–159，必須 > x1）
  y2: 120                # 右下角 Y（0–159，必須 > y1）

thresholds:
  open: 80               # intensity ≤ 此值 → 完全開啟（整數，必須 < closed）
  closed: 150            # intensity > 此值 → 完全閉合（整數，必須 > open）
                         # 中間帶（open < intensity ≤ closed）→ 閉合中
                         # 建議間距 ≥ 20 以避免邊界抖動

analysis:
  min_state_duration: 5  # 狀態確認所需連續幀數（3–15）
  history_size: 500      # 時間序列 deque 容量

display:
  smoothing_window: 10   # SMA 視窗大小 N（1–30）
  show_raw_data: false   # 在 ax1 同時顯示原始曲線（灰色）
  enable_smoothing: true # false = 停用 SMA，直接用原始 intensity
```

### 參數約束

| 約束 | 說明 |
|------|------|
| `threshold_closed > threshold_open` | 必須；違反時載入程式自動交換並警告 |
| `x1 < x2`、`y1 < y2` | 套用 ROI 時驗證 |
| `smoothing_window ≥ 1` | < 1 時程式內部修正為 1 |

---

## 6. 校準流程

### 步驟 A：啟動相機

1. `python drawer_monitor.py` → 點擊「啟動相機」
2. 確認 JET 影像有畫面
   - 全黑 → Tab 2 → LED 電流調至 `ULTRA_HIGH`
   - 全白 → LED 電流調低至 `HIGH` 或 `MEDIUM`

### 步驟 B：觀察基準 intensity

1. **抽屜完全拉開**：觀察 ax1 穩定後的 intensity 值，記錄範圍（例如：30–60）
2. **抽屜完全推入閉合**：觀察 ax1 穩定後的 intensity 值，記錄範圍（例如：150–200）

> 若兩者差距 < 30，參考[故障排除](#11-故障排除) — 訊號差異不足。

### 步驟 C：設定閾值

```
閉合閾值 = 閉合基準的低端 − 安全裕度（建議 10–20）
開啟閾值 = 開啟基準的高端 + 安全裕度（建議 10–20）

例：
  閉合基準 150–200 → 閉合閾值 = 150 − 10 = 140
  開啟基準  30– 60 → 開啟閾值 =  60 + 10 =  70
  間距 = 140 − 70 = 70（>20，良好）
```

拖動 Slider 即時套用，閾值自動儲存至 YAML。

### 步驟 D：選擇 SMA 視窗大小 N

先在 Tab 2 勾選「同時顯示原始數據」，觀察原始曲線的噪聲幅度：

```
開啟或閉合狀態下的 intensity 波動範圍（max − min）：

wave_range < 5   → N = 5（低噪聲）
wave_range 5–15  → N = 10（中等，預設）
wave_range 15–30 → N = 15（高噪聲）
wave_range > 30  → N = 20，並檢查安裝穩固性
```

### 步驟 E：驗證

多次開關抽屜，確認：
- ax1 曲線在兩種狀態有清楚分離帶
- 狀態標籤正確切換，無頻繁抖動
- ax2 方向與 ax1 相反（符合物理預期）

點擊「全部套用並儲存」完成校準。

---

## 7. SMA 濾波調校指南

### N 值對響應的影響（FPS ≈ 8）

| N 值 | 平滑強度 | 響應延遲 | 可抑制頻率上限 | 適用場景 |
|------|---------|---------|--------------|---------|
| 1 | 無（Raw） | 0 s | — | 觀察原始信號 |
| 5 | 低 | 0.6 s | 0.8 Hz | 噪聲極小 |
| 10（預設） | 中 | 1.25 s | 0.4 Hz | 一般室內環境 |
| 15 | 高 | 1.9 s | 0.27 Hz | 高頻噪聲或不穩定反射 |
| 20 | 極高 | 2.5 s | 0.2 Hz | 嚴苛環境（不建議 > 20） |

**響應延遲** ≈ N / FPS
**可抑制頻率** ≤ FPS / (2 × N)

### min_state_duration 防抖

| 幀數 | 防抖時間（8 FPS） | 適用場景 |
|------|----------------|---------|
| 3–4 | 0.4–0.5 s | 信號乾淨、響應要求高 |
| 5–7（預設 5） | 0.6–0.9 s | 一般使用 |
| 8–12 | 1.0–1.5 s | 噪聲大或閾值設定較緊 |

### 推薦配置方案

**方案 A：快速響應**
```yaml
display:
  smoothing_window: 5
analysis:
  min_state_duration: 4
```
響應時間 ≈ 0.6 s｜適用：安裝穩固、材質均勻

**方案 B：平衡（預設）**
```yaml
display:
  smoothing_window: 10
analysis:
  min_state_duration: 5
```
響應時間 ≈ 1.2 s｜適用：一般辦公室、病房

**方案 C：高穩定**
```yaml
display:
  smoothing_window: 15
analysis:
  min_state_duration: 8
```
響應時間 ≈ 1.9 s｜適用：反射面不均、輕微振動

---

## 8. 相機參數說明

### Frame Rate（幀率）

| 設定 | 說明 | 建議使用場景 |
|------|------|-------------|
| `FULL` | 最高幀率 | 需要快速響應時 |
| `HALF` | 1/2 幀率 | — |
| `QUARTER`（預設） | 1/4 幀率，≈ 8 FPS | 一般使用，噪聲低 |
| `EIGHTH` | 1/8 幀率 | 環境干擾大時 |
| `SIXTEENTH` | 1/16 幀率 | 極低噪聲需求 |

### LED Current（LED 電流）

| 設定 | 電流 | 說明 |
|------|------|------|
| `LOW` | 50 mA × 2 | 近距離、高反射面 |
| `MEDIUM` | 100 mA × 2 | — |
| `HIGH` | 200 mA × 2 | — |
| `ULTRA_HIGH`（預設） | 400 mA × 2 | 遠距離或低反射面 |

### Exposure Setting（曝光設定）

| 設定 | 說明 |
|------|------|
| `DEFAULT`（預設） | 標準自動曝光 |
| `UNKNOWN` | 替代曝光模式（可改善特定材質的反射） |

> 修改相機參數後需點擊「停止相機」再「啟動相機」才會生效。

---

## 9. API 整合範例

校準完成後，將核心邏輯整合至主系統：

```python
from eminent.sensors.vision2p5d import VideoCapture, MN96100CConfig
from utils.depth_analysis import DepthAnalyzer, DrawerStateDetector
from collections import deque
import cv2

# 初始化感測器（參數來自 drawer_config.yaml 校準結果）
cap = VideoCapture(
    frame_rate=MN96100CConfig.FrameRate.QUARTER,
    led_current=MN96100CConfig.LEDCurrent.ULTRA_HIGH,
    exposure_setting=MN96100CConfig.ExposureSetting.DEFAULT,
    tx_output=MN96100CConfig.TXOutput.RESOLUTION_160x160,
    vid=0x04F3,
    pid=0x0C7E
)

# 初始化分析器與狀態偵測器
analyzer = DepthAnalyzer()
detector = DrawerStateDetector(
    threshold_open=80,      # 從 drawer_config.yaml 讀取
    threshold_closed=150,   # 從 drawer_config.yaml 讀取
    min_state_duration=5
)

# SMA 緩衝區
SMA_N = 10
intensity_buffer = deque(maxlen=SMA_N)

# 主迴圈
while True:
    ret, frame = cap.read()
    if not ret:
        continue

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    roi = gray[40:120, 40:120]  # 依校準時的 ROI 設定

    metrics = analyzer.calculate_depth_metrics(roi)
    intensity_buffer.append(metrics['mean'])

    # SMA 平滑（與 drawer_monitor.py 使用相同算法）
    smoothed = sum(intensity_buffer) / len(intensity_buffer)
    state = detector.update(smoothed)

    if state == "完全閉合":
        print("✓ 抽屜已安全關閉")
        break
    elif state == "完全開啟":
        print("⚠ 請關閉抽屜")

cap.release()
```

### `calculate_depth_metrics()` 返回值

| 欄位 | 類型 | 說明 |
|------|------|------|
| `mean` | float | ROI 平均強度值（0–255），**狀態判斷的主要依據** |
| `relative_distance` | float | 1/√mean，相對距離指標（0.063–1.0） |
| `median` | float | ROI 中位數強度 |
| `std` | float | ROI 強度標準差 |
| `min` / `max` | float | ROI 最小/最大強度值 |
| `percentile_10/90` | float | 第 10 / 90 百分位數 |
| `range` | float | max − min |

### `DrawerStateDetector` API

```python
detector = DrawerStateDetector(
    threshold_open=80,       # intensity ≤ 此值 → 完全開啟
    threshold_closed=150,    # intensity > 此值 → 完全閉合
    min_state_duration=5     # 連續幾幀才確認狀態變更
)

state = detector.update(smoothed_intensity)
# 回傳：「完全閉合」/「閉合中」/「完全開啟」/「未知」

detector.update_thresholds(new_open, new_closed)  # 動態更新閾值
detector.reset()                                   # 重置狀態
```

**注意**：`threshold_closed` 必須 > `threshold_open`，否則建構時拋出 `ValueError`。

---

## 10. 相關檔案結構

```
FY114-Drug-Recognition-Subsystem/
├── drawer_monitor.py              # 主應用程式（校準工具 GUI）
├── config/
│   ├── drawer_config.yaml         # 運行時配置（自動生成與儲存）
│   └── drawer_config_example.yaml # 配置範例與說明注釋
├── utils/
│   └── depth_analysis.py          # DepthAnalyzer、DrawerStateDetector
├── eminent/
│   └── sensors/
│       └── vision2p5d/
│           ├── __init__.py        # VideoCapture、MN96100CConfig
│           └── mn96100c.py        # USBDeviceComm 底層 USB 驅動
├── tests/
│   └── run_25d.py                 # 最簡相機連線測試
├── test.py                        # 硬體整合測試（--drawer 選項）
└── docs/
    └── DRAWER_MONITOR_README.md   # 本文件（唯一技術參考）
```

---

## 11. 故障排除

### 相機無法啟動

| 症狀 | 原因 | 解決方法 |
|------|------|---------|
| `Device not found` | USB 未連接或 VID/PID 不符 | 確認 VID=0x04F3、PID=0x0C7E；嘗試重新插拔 USB 3.0 |
| Windows 驅動問題 | 缺少 libusb | 使用 Zadig 工具安裝 libusb-win32 驅動 |
| `Resource busy` | 其他程式占用 USB | 關閉其他程式；重插 USB；重啟電腦 |

### 影像異常

| 症狀 | 原因 | 解決方法 |
|------|------|---------|
| 全黑 | LED 電流不足或距離太遠 | LED 電流 → `ULTRA_HIGH` |
| 全白 | LED 電流過強或距離太近 | LED 電流 → `HIGH` 或 `MEDIUM` |
| 噪聲多、畫面抖動 | 幀率過高 | Frame Rate → `QUARTER` 或 `EIGHTH` |

### 狀態判斷問題

| 症狀 | 原因 | 解決方法 |
|------|------|---------|
| 狀態一直是「閉合中」 | 兩個閾值間距太小 | 確保 `closed − open ≥ 20` |
| 開啟/閉合 intensity 差異 < 30 | 信號不足 | ① 提高 LED → `ULTRA_HIGH`；② 調整相機角度使鏡頭垂直抽屜面；③ 縮小 ROI 至前板中央；④ 嘗試切換曝光設定 |
| 狀態頻繁切換 | 噪聲穿越閾值 | ① 增大 SMA N（+5）；② 增大 `min_state_duration`（+2）；③ 縮小 ROI 排除邊緣反光 |
| 狀態切換太慢 | N 值過大 | 降低 SMA N；以 `min_state_duration` 補充防抖 |

### GUI 卡頓

1. Frame Rate → `QUARTER`（避免過高幀率）
2. 關閉「同時顯示原始數據」
3. 減小 `history_size`（在 YAML 手動調整，預設 500）

### 相機掉線（自動偵測）

連續 30 幀讀取失敗時，`capture_loop` 自動呼叫 `_on_camera_disconnect()`：
- 停止 capture thread
- 釋放 USB 資源
- 狀態標籤顯示「掉線」（紅色）
- 彈出錯誤對話框

處理後重新插拔 USB，點擊「啟動相機」即可恢復。
