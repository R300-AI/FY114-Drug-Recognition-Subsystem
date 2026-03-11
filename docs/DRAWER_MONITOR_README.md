# Drawer Monitor 使用說明

## 概述

這是一個使用 MN96100C 2.5D 影像感測器來監測抽屜閉合狀態的專業校準工具。應用程式提供實時深度圖像顯示、雙通道時間序列分析和動態閾值調整功能。

## 感測器原理

### 物理模型
- **MN96100C 2.5D Sensor**: 輸出 160x160 的 8-bit 灰度圖像（反射光強度）
- **測量方式**: 主動式紅外光投射，晶片內部已扣除環境光
- **深度計算公式**: `depth_metric = 1 / √(intensity)`
  - 強度範圍: 1-255 (8-bit)
  - 深度指標範圍: 0.0626-1.0 (理論值)
- **物理意義**: 
  - **高 depth_metric 值** (>0.08) → 弱反射 → 遠距離 → 抽屜開啟（看到遠處地板）
  - **低 depth_metric 值** (<0.06) → 強反射 → 近距離 → 抽屜閉合（遮擋地板）

## 應用場景

### 抽屜閉合監測
1. **安裝位置**: 2.5D camera 直對抽屜平面，固定於櫃體
2. **未閉合狀態**: 
   - 相機直接看到更遠的地板（弱反射）
   - depth_metric 值較高（例如 0.09-0.12）
   - 顯示為「完全開啟」（紅色）
3. **閉合過程**: 
   - 抽屜逐漸插入，遮擋地板（反射增強）
   - depth_metric 值下降（例如 0.06-0.08）
   - 顯示為「閉合中」（橙色）
4. **完全閉合**: 
   - 地板完全被抽屜前板遮住（強反射）
   - depth_metric 值最低（例如 <0.06）
   -3. 動態閾值調整（Tab 1 數據串流）
- **即時滑桿控制**:
  - 開啟閾值（Threshold Open）: 0.00-1.00，步進 0.01
  - 閉合閾值（Threshold Closed）: 0.00-1.00，步進 0.01
  - 預設值: Open=0.08, Closed=0.06
- **自動儲存**: 拖動滑桿即時更新 YAML 配置檔
- **視覺回饋**: 滑桿旁顯示當前數值

### 4. 雙通道時間序列圖（Tab 1）
- **上圖 - Depth Metric**:
  - Y 軸: 0.0-1.0（固定範圍）
  - 藍色曲線: 實時深度指標
  - 紅色虛線: 開啟閾值參考線
  - 綠色虛線: 閉合閾值參考線
  - 英文標籤（Time / Depth Metric）
  
- **下圖 - Average Intensity**:
  - Y 軸: 0-255（固定範圍）
  - 橙色曲線: 平均反射光強度
  - 英文標籤（Time / Avg Intensity）
  
- 最多保存 500 幀歷史數據
- 自動滾動顯示

### 5. 狀態顯示
- **即時狀態**: 完全開啟（紅）/ 閉合中（橙）/ 完全閉合（綠）
- **數值指標**:
  - Depth Metric: 當前深度指標（小數點後 4 位）
  - Avg Intensity: ROI 區域平均強度
  - FPS: 實時幀率

### 6. 相機參數控制（Tab 2 參數配置）
- **幀率 (Frame Rate)**: 
  - FULL / HALF / QUARTER (預設) / EIGHTH / SIXTEENTH
  
- **LED 電流 (LED Current)**:
  - ULTRA_HIGH (400mA×2, 預設) / HIGH / MEDIUM / LOW

- **曝光設定 (Exposure)**:
  - DEFAULT (預設) / UNKNOWN

### 7. ROI 區域設定（Tab 2）
- 可選擇性啟用感興趣區域
- 設定範圍: 0-160 像素
- 預設 ROI: (40, 40) 到 (120, 120)
- 即時生效（勾選啟用 ROI）

### 8. 配置管理（Tab 2）
- **自動儲存**: 閾值滑桿拖動即儲存
- **手動載入/儲存**: 相機參數、ROI、分析設定
- **配置檔**: `config/drawer_config.yaml`（自動建立目錄）
- **配置結構**:
  ```yaml
  camera:
    frame_rate: QUARTER
    led_current: ULTRA_HIGH
    exposure_setting: DEFAULT
  roi:
    enabled: true
    x1: 40
    y1: 40
    x2: 120
    y2:硬體測試
```bash
# 測試 MN96100C 傳感器
python test.py --drawer
```
應該看到：
- ✓ MN96100C sensor initialized
- ✓ Captured frame shape: (160, 160, 3)
- ✓ DepthAnalyzer metrics calculated
- ✓ DrawerStateDetector state detected

### 2. 啟動應用程式
```bash
python drawer_monitor.py
```

應用視窗規格：
- 解析度: 1024x600
- 左側面板: 360px 寬（圖像 320x320 + 閾值滑桿）
- 右側面板: 664px 寬（雙通道時間序列圖）

### 3. 初次設定流程

#### 步驟 A: 相機啟動（Tab 2 參數配置）
1. 檢查預設參數（通常無需調整）:
   - 幀率: QUARTER
   - LED 電流: ULTRA_HIGH
   - 曝光: DEFAULT
2. 點擊「啟動相機」按鈕
3. 回到 **Tab 1 數據串流** 觀察即時畫面

#### 步驟 B: ROI 設定（Tab 2，選用）
1. 切換至 Tab 2 參數配置
2. 勾選「啟用 ROI」
3. 根據實際安裝位置調整矩形範圍
   - X1, Y1: 左上角座標（預設 40, 40）
   - X2, Y2: 右下角座標（預設 120, 120）
4. 建議只監測抽屜會遮擋的關鍵區域
5. Tab 1 圖像會顯示 ROI 紅色框線

#### 步驟 C: 閾值校準（Tab 1 數據串流）
1. **測試完全開啟狀態**:
   - 將抽屜完全拉開
   - 觀察「Depth Metric」數值（應該較高，例如 0.09-0.12）
   - 觀察時間序列上圖的藍色曲線位置
   - 記錄穩定後的數值範圍

2. **測試完全閉合狀態**:
   - 將抽屜完全推入閉合
   - 觀察「Depth Metric」數值（應該較低，例如 0.04-0.06）
   - 觀察藍色曲線下降情況
   - 記錄穩定後的數值範圍

3. **調整閾值滑桿**:
   - **開啟閾值** (Threshold Open): 設定在閉合狀態最大值之上
     - 例如: 閉合時 max=0.065 → 設定 0.08
   - **閉合閾值** (Threshold Closed): 設定在閉合狀態平均值附近
     - 例如: 閉合時 avg=0.055 → 設定 0.06
   - 拖動滑桿時自動儲存至 YAML

4. **驗證與微調**:
   - 多次開關抽屜測試
   - 觀察狀態顯示是否準確切換：
     * 「完全開啟」（紅色）: depth_metric > 0.08
     * 「閉合中」（橙色）: 0.06 < depth_metric < 0.08
     * 「完全閉合」（綠色）: depth_metric < 0.06
   - 微調閾值直到狀態判斷穩定
閾值設定策略**:
   - 開啟閾值應 > 閉合狀態最大值 + 0.01 安全裕度
   - 閉合閾值應略高於完全閉合時的平均值
   - 兩個閾值之間保持 0.02-0.03 的間隔（遲滯區間）
   - 避免閾值過於接近，導致頻繁切換狀態

2. **LED 電流與幀率**:
   - 預設 ULTRA_HIGH + QUARTER 已是最佳平衡
   - 若發熱過大可降至 HIGH，但注意信噪比下降
   - 較低的幀率（QUARTER/EIGHTH）可減少雜訊

3. **ROI 使用**:
   - 優先監測抽屜中央區域（40-120 範圍）
   - 避免包含抽屜邊緣（可能有反光或陰影）
   - 排除固定背景（牆壁、櫃體側板）

### 抗干擾措施
1. **硬體安裝**:
   - 固定相機與抽屜的相對位置（使用支架）
   - 感測器鏡頭與被測面垂直（±5° 以內）
   - 避免外部光源直射感測器或抽屜表面
   
2. **環境控制**:
   - 確保抽屜表面平整，材質均勻
   - 定期清潔感測器鏡頭（避免灰塵堆積）
   - 室溫使用（0-50°C），避免結露

3. **軟體濾波**:
   - 使用 ROI 排除干擾區域
   - 觀察時間序列找出穩定區間（至少 10 幀）
   - 考慮記錄不同溫度/濕度下的數值變化

### 閾值調整技巧
1. **觀察時間序列圖**:
   - 藍色曲線應在開啟/閉合時有明顯分離（>0.03 差距）
   - 閉合過程應呈現平滑下降趨勢
   - 完全閉合後數值應穩定（標準差 <0.005）

2. **使用雙通道資訊**:
   - Depth Metric 圖用於狀態判斷（主要依據）
   - Avg Intensity 圖用於檢查信號質量
   - 若兩圖變化不同步，檢查環境光干擾

3. **建立基準值**:
   - 記錄典型開啟狀態: depth_metric ≈ 0.10
   - 記錄典型閉合狀態: depth_metric ≈ 0.05
   - 設定閾值: Open=0.08, Closed=0.06（介於兩者中間）否正確
   - 微調閾值直到滿意

#### 步驟 D: 儲存設定
1. 點擊「儲存設定」
**症狀**: 點擊「啟動相機」後無回應或錯誤訊息

**解決方法**:
1. 執行硬體測試: `python test.py --drawer`
2. 檢查 USB 連接（建議使用 USB 3.0 埠）
3. 確認 VID/PID: 預設 0x04F3:0x0C7E
4. Windows: 安裝 libusb-win32 驅動
5. Linux/Pi: 檢查 USB 權限 `sudo chmod 666 /dev/bus/usb/*/*`

### 問題: 圖像全黑或全白
**症狀**: 320x320 顯示區域無正常圖像

**解決方法**:
1. Tab 2 調整 LED 電流（全黑→ULTRA_HIGH，全白→MEDIUM）
2. 檢查鏡頭是否被遮擋或沾染灰塵
3. 嘗試切換曝光設定（DEFAULT ↔ UNKNOWN）

### 問題: 狀態判斷不準確
**症狀**: 抽屜明明閉合卻顯示「開啟」，或相反

**解決方法**:
1. 觀察 Depth Metric 數值範圍（應為 0.04-0.12）
2. 重新執行「步驟 C: 閾值校準」流程
3. 檢查物理安裝:
   - depth_metric **高** (>0.08) = 遠距離 = 開啟
   - depth_metric **低** (<0.06) = 近距離 = 閉合
4. 若數值範圍相反，檢查安裝方向是否顛倒
5. 使用 ROI 排除干擾區域

### 問題: 狀態頻繁切換
**症狀**: 狀態在「閉合中」和其他狀態間快速跳動

**解決方法**:
1. 增加閾值間隔（Open - Closed ≥ 0.02）
2. 檢查抽屜運動過程是否平穩
3. 降低幀率（EIGHTH）以減少雜訊
4. 確認環境光干擾（關閉附近照明測試）

### 問題: FPS 過低
**症狀**: GUI 卡頓，刷新率 <5 FPS

**解決方法**:
1. 提高相機幀率（QUARTER → HALF）
2. 關閉其他佔用 CPU 的程式
3. 檢查 matplotlib 渲染效能（可能需更新驅動）
# 將核心邏輯整合到主程式 run.py
from eminent.sensors.vision2p5d import VideoCapture, FrameRate, LEDCurrent
from utils.depth_analysis import DepthAnalyzer, DrawerStateDetector

# 初始化感測器
camera = VideoCapture(
    frame_rate=FrameRate.QUARTER,
    led_current=LEDCurrent.ULTRA_HIGH
)
camera.start()

# 初始化分析器
analyzer = DepthAnalyzer()
detector = DrawerStateDetector(threshold_open=0.08, threshold_closed=0.06)

# 主迴圈
while True:
    frame = camera.read()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # 計算 ROI 深度指標
    roi = gray[40:120, 40:120]
    metrics = analyzer.calculate_depth_metrics(roi)
    state = detector.detect_state(metrics['depth_metric'])
    
    # 根據狀態執行動作
    if state == "完全閉合":
        print("✓ 抽屜已安全關閉，啟動藥物識別")
        break
    elif state == "完全開啟":
        print("⚠ 請關閉抽屜")
```

### 數據記錄與分析
可以添加功能：
```python
import pandas as pd
from datetime import datetime

# 記錄歷史數據
history = []
while True:
    metrics = analyzer.calculate_depth_metrics(roi)
    history.append({
        'timestamp': datetime.now(),
        'depth_metric': metrics['depth_metric'],
        'avg_intensity': metrics['avg_intensity'],
        'state': detector.detect_state(metrics['depth_metric'])
    })

# 儲存為 CSV
df = pd.DataFrame(history)
df.to_csv('drawer_log.csv', index=False)

# 統計分析
print(f"開啟次數: {(df['state'].shift() != df['state']).sum() // 2}")
print(f"平均閒置時間: {df[df['state']=='完全閉合'].shape[0] / fps} 秒")
```

### 多抽屜監測
```python
# 使用多個 USB 裝置（不同 VID/PID 或 serial number）
cameras = [
    VideoCapture(vid=0x04F3, pid=0x0C7E),  # 抽屜 A
    VideoCapture(vid=0x04F3, pid=0x0C7F),  # 抽屜 B
]

for i, camera in enumerate(cameras):
    camera.start()
    frame = camera.read()
    state = process_frame(frame)
    print(f"抽屜 {i+1}: {state}")
```

## 相關檔案

```
FY114-Drug-Recognition-Subsystem/
├── drawer_monitor.py              # 主應用程式（GUI）
├── config/
│   └── drawer_config.yaml         # 配置檔（自動生成）
├── utils/
│   └── depth_analysis.py          # 核心分析模組
├── eminent/
│   └── sensors/
│       └── vision2p5d/
│           ├── __init__.py        # VideoCapture, FrameRate, LEDCurrent
│           └── mn96100c.py        # MN96100C 硬體驅動
├── test.py                        # 測試框架（含 --drawer 選項）
└── docs/
    └── DRAWER_MONITOR_README.md   # 本文件
```

## 版本歷史

- **v2.0** (Current): Tab 介面、YAML 配置、depth_metric 物理模型、即時滑桿
- **v1.5**: 增強版，JSON 配置、雙通道時間序列
- **v1.0**: 基礎版，單視窗佈局

## 聯絡與支援

- 專案 GitHub: [FY114-Drug-Recognition-Subsystem](https://github.com/...)
- 硬體測試: `python test.py --drawer`
- 主要文檔: [README.md](../README.md)
- 問題回報: 請提供 `config/drawer_config.yaml` 和錯誤訊息截圖h_metric 高 (0.14) → 遠距離 → 抽屜開啟

### 狀態判斷邏輯
```python
# utils/depth_analysis.py - DrawerStateDetector
if depth_metric > threshold_open:  # 例如 >0.08
    return "完全開啟"
elif depth_metric > threshold_closed:  # 0.06 < x < 0.08
    return "閉合中"
else:  # <0.06
    return "完全閉合"
```

### 數據流程
```
1. VideoCapture 捕獲 160x160 RGB 圖像
2. 轉換為灰度（8-bit intensity）
3. 若啟用 ROI，裁切至指定區域
4. DepthAnalyzer 計算:
   - depth_map = 1/√(intensity)  # 逐像素轉換
   - depth_metric = mean(depth_map)  # 平均深度指標
   - avg_intensity = mean(intensity)  # 平均強度
5. DrawerStateDetector 判斷狀態
6. GUI 更新:
   - 320x320 偽彩色圖（JET colormap）
   - 雙通道時間序列（Matplotlib）
   - 狀態標籤與數值
```

### 窗口佈局
```
┌─────────────────────────────────────────────────────────┐
│ Drawer Monitor - MN96100C 2.5D Sensor      1024x600    │
├──────────────┬──────────────────────────────────────────┤
│              │ [Tab 1: 數據串流] [Tab 2: 參數配置]      │
│              ├──────────────────────────────────────────┤
│   320x320    │                                          │
│  偽彩色圖     │         Depth Metric (0.0-1.0)           │
│  JET色圖     │         ┌─────────────────────┐          │
│   + ROI框    │         │  時間序列上圖        │ 664px   │
│              │         │  (藍線 + 閾值虛線)   │  寬     │
│              │         └─────────────────────┘          │
│ ─────────    │                                          │
│ Open:  0.08  │         Avg Intensity (0-255)            │
│ [═══●════]   │         ┌─────────────────────┐          │
│              │  360px  │  時間序列下圖        │         │
│ Closed:0.06  │   寬    │  (橙線)              │         │
│ [═══●════]   │         └─────────────────────┘          │
│              │                                          │
│ 狀態: 完全閉合│  Depth: 0.0543  Intensity: 187  FPS: 8  │
└──────────────┴──────────────────────────────────────────┘
### 問題: 相機無法啟動
- 檢查 USB 連接
- 確認 VID/PID 是否正確（預設 0x04F3:0x0C7E）
- 檢查 libusb 驅動是否安裝

### 問題: 圖像噪點多
- 提高 LED 電流
- 降低幀率
- 調整曝光設定

### 問題: 狀態判斷不準確
- 重新校準閾值
- 調整 ROI 範圍
- 檢查安裝位置是否穩定

### 問題: FPS 過低
- 提高幀率設定
- 檢查 CPU 使用率
- 確保 USB 2.0/3.0 連接正常

## 技術細節

### 深度計算原理
```
像素值 (8-bit) = 反射光強度
相對距離 ∝ 1 / √(反射光強度)
```

因此：
- **高像素值** → 強反射 → 近距離（抽屜插入）
- **低像素值** → 弱反射 → 遠距離（看到地板）

### 數據流程
```
1. 相機捕獲 160x160 原始數據
2. 選擇 ROI 或全圖
3. 計算統計指標（平均、最小、最大、標準差）
4. 深度指標 = 平均像素值
5. 與閾值比較判斷狀態
6. 更新 UI 和時間序列
```

## 擴展應用

### 整合到自動化系統
```python
from set_drawer import DrawerMonitorApp
import tkinter as tk

# 可以修改程式碼提取核心邏輯
# 作為模組整合到其他系統中
```

### 數據記錄
可以添加功能記錄：
- 每次開關抽屜的時間戳
- 深度指標變化曲線
- 異常事件（未完全閉合）

### 多抽屜監測
可以修改為同時監測多個抽屜：
- 使用多個 USB 相機
- 為每個相機設定不同的 ROI
- 統一管理和顯示

## 相關檔案

- `set_drawer.py`: 主應用程式
- `drawer_monitor_settings.json`: 設定檔（自動生成）
- `run_25d.py`: 簡單測試程式
- `eminent/sensors/vision2p5d/`: 感測器驅動模組

## 聯絡與支援

如有問題或建議，請參考專案 README 或聯絡開發團隊。
