# FY114 藥物辨識子系統

> 基於 Raspberry Pi 5 的嵌入式藥物驗證應用程式

此子專案為**邊緣端執行環境**，提供觸控螢幕 GUI 介面，讓護理師對藥盤進行 AI 輔助辨識與逐項確認。
Gallery（特徵庫）與 YOLO 模型由 [FY115-Drug-Visual-AI-Search-Platform](../FY115-Drug-Visual-AI-Search-Platform/) 生成後部署至此。

---

## 操作流程

```
1. 系統啟動 → 黑畫面（待分析狀態）

2. 將藥盤放置於相機下方 → 按「分析」

3. 系統自動：
   ├── 拍攝一張靜態照片
   ├── YOLO 偵測藥錠
   ├── 特徵編碼 + Gallery 比對
   └── 自動切換到 AI 頁（顯示 YOLO 遮罩疊加圖）

4. 護理師逐項確認：
   ├── 全局：品項數量 → 正確/錯誤
   ├── 全局：總量顆數 → 正確/錯誤
   └── 逐藥品：品項核對 + 劑量 → 正確/錯誤
      （可切換鏡頭/AI 頁對照確認）

5. 按「完成」
   ├── 有未填 → 「提示」Modal（只能「回去檢查」）
   └── 全填完 → 「完成」Modal
       ├── 「重新回饋」→ 清空答案，重新確認
       └── 「OK」→ 儲存驗證記錄 → 回到黑畫面
```

---

## 安裝（Raspberry Pi 5，Debian 12 Bookworm）

### 步驟 1：系統套件

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv libcamera-dev python3-lgpio
```

> `python3-lgpio` 是 adafruit-blinka 在 Pi 5 上的底層依賴。

---

### 步驟 2：建立虛擬環境

```bash
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
```

> `--system-site-packages` 讓 venv 繼承系統層的 `picamera2`，避免底層相機驅動衝突。

---

### 步驟 3：安裝 Python 套件

```bash
pip install picamera2
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install ultralytics==8.4.3
pip install opencv-python pillow pyyaml "numpy>=1.24.0,<2.0.0"
pip install pyusb matplotlib
```

> PyTorch 指定 CPU 版；ultralytics 鎖定 8.4.3（numpy < 2.0.0 相容性限制）。

---

### 步驟 4：設定 udev 規則與使用者群組

授權 LED Ring（`/dev/pio0`）與 Pi Camera（`/dev/gpiomem`），完成後需**重新登入**。

```bash
echo 'SUBSYSTEM=="*-pio", GROUP="gpio", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-com.rules
echo 'SUBSYSTEM=="bcm2835-gpiomem", GROUP="gpio", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-com.rules
echo 'SUBSYSTEM=="gpio", GROUP="gpio", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-com.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo usermod -aG gpio $USER
sudo usermod -aG video $USER
```

---

### 步驟 5：安裝 LED Ring 驅動

接線：DIN → GPIO18（Physical Pin 12），VCC 接外部 5V 電源。

```bash
pip install adafruit-blinka
pip install Adafruit-Blinka-Raspberry-Pi5-Neopixel
pip install adafruit-circuitpython-neopixel
```

---

### 步驟 6：硬體測試

```bash
# 測試所有元件
python test.py --picam --light --drawer --detector --encoder --matcher

# 僅測試硬體（需接硬體）
python test.py --picam --light --drawer

# 僅測試模組（不需要硬體，部署前可先跑）
python test.py --detector --encoder --matcher
```

---

## 啟動

```bash
# 主程式
python run.py                # 視窗模式（開發測試）
python run.py --fullscreen   # 全螢幕模式（觸控螢幕部署）

# 指定自訂 Gallery 和模型
python run.py --gallery path/to/gallery --model path/to/best.pt

# Drawer Monitor（MN96100C 2.5D 傳感器校準工具）
python drawer_monitor.py
```

> Drawer Monitor 提供即時深度影像、雙通道時間序列圖、動態閾值調整與 SMA 濾波調校。
> 詳細操作說明：[docs/DRAWER_MONITOR_README.md](docs/DRAWER_MONITOR_README.md)

---

## 開機自動啟動

```bash
chmod +x startup.sh
crontab -e
# 在最後加入：
# @reboot /完整路徑/FY114-Drug-Recognition-Subsystem/startup.sh
```

---

## 部署 Gallery 與模型

從 FY115 工作站生成後，複製至此目錄：

```bash
# 透過 SCP 從工作站推送
scp -r path/to/FY115/src/gallery pi@<rpi_ip>:~/FY114-Drug-Recognition-Subsystem/src/
scp path/to/FY115/src/best.pt   pi@<rpi_ip>:~/FY114-Drug-Recognition-Subsystem/src/

# 或在 Pi 上執行 git pull
```

---

## 自訂 Encoder / Matcher

在 `utils/modules/encoder/` 或 `utils/modules/matcher/` 新增模組，繼承對應基底類別，
再於 `run.py` 的 `create_components()` 中替換：

```python
def create_components(...):
    # encoder = ResNet34Encoder()
    encoder = MyEncoder()
    # matcher = Top1Matcher(gallery)
    matcher = MyMatcher(gallery)
```

> **注意**：更換 Encoder 後，必須在 FY115 重新建立 Gallery（特徵向量維度必須與新 Encoder 一致）。
>
> 基底類別 API 與模組結構說明：[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)

---

## 目錄結構

```
FY114-Drug-Recognition-Subsystem/
├── run.py                     ← 主程式（Tkinter GUI）
├── drawer_monitor.py          ← 2.5D 傳感器校準工具
├── test.py                    ← 硬體與模組整合測試
├── startup.sh                 ← 開機自動啟動腳本
├── config/
│   ├── drawer_config.yaml     ← Drawer Monitor 運行時配置（自動生成）
│   └── drawer_config_example.yaml  ← 配置說明範例
├── src/
│   ├── best.pt                ← YOLO 分割模型（由 FY115 提供）
│   ├── gallery/               ← 特徵庫（index.json + features.npy）
│   └── images/                ← 驗證記錄（YAML + JPG）
├── utils/                     ← 核心模組（BaseDetector/Encoder/Matcher 等）
├── eminent/sensors/vision2p5d/ ← MN96100C 2.5D 傳感器驅動
└── docs/
    ├── DRAWER_MONITOR_README.md  ← 2.5D 傳感器完整技術文件
    └── DEVELOPER_GUIDE.md        ← 模組 API、儲存格式、擴充開發指南
```

---

## 常見問題

| 錯誤 | 原因 | 解法 |
|------|------|------|
| `No module named 'neopixel_write'` | 缺少 Pi 5 專用後端 | `pip install Adafruit-Blinka-Raspberry-Pi5-Neopixel` |
| `PermissionError: /dev/pio0` | udev 規則未設定或未重新登入 | 重做步驟 4，確認重新登入 |
| `/dev/pio0: No such file` | 韌體過舊，PIO 裝置尚未啟用 | `sudo apt upgrade && sudo rpi-eeprom-update -a` 後重開機 |
| `picamera2` 找不到 | venv 缺少 `--system-site-packages` | 重建 venv（步驟 2） |
| GPIO 操作需要 root | 未加入 gpio 群組或未重新登入 | 重做步驟 4 |
| `usb.core.USBError` | MN96100C USB 裝置權限不足 | `sudo chmod 666 /dev/bus/usb/*/*` 或設定 udev 規則 |
| MN96100C 無法初始化 | VID/PID 錯誤或裝置未連接 | 確認 `lsusb` 顯示 `04f3:0c7e`，檢查 USB 連接 |
