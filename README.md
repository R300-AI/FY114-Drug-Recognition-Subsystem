# FY114 藥物辨識子系統

> 基於 Raspberry Pi 5 的嵌入式藥物驗證應用程式

此子專案為 **邊緣端執行環境**，提供觸控螢幕 GUI 介面，讓護理師對藥盤進行 AI 輔助辨識與逐項確認。
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
       └── 「OK」→ 儲存 YAML + JPG → 回到黑畫面
```

---

## 安裝（Raspberry Pi 5，Debian 12 Bookworm）

### 步驟 1：系統套件

更新作業系統，安裝 Pi Camera、虛擬環境及 GPIO 驅動（`python3-lgpio` 為 adafruit-blinka 在 Pi 5 上的底層依賴）。

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv libcamera-dev python3-lgpio
```

---

### 步驟 2：建立虛擬環境

`--system-site-packages` 讓 venv 繼承系統層的 `picamera2`，避免底層相機驅動衝突。

```bash
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
```

---

### 步驟 3：安裝 Python 套件

PyTorch 指定 CPU 版，並將ultralytics 版本鎖定 8.4.3 (numpy 需要 `<2.0.0`版本)。

```bash
pip install picamera2
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install ultralytics==8.4.3
pip install opencv-python pillow pyyaml "numpy>=1.24.0,<2.0.0"
```

---

### 步驟 4：設定 udev 規則與使用者群組

授權 `/dev/pio0`（LED Ring）與 `/dev/gpiomem`（Pi Camera）讓一般使用者存取，並將使用者加入 gpio、video 群組。完成後需**重新登入**。

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

接線DIN → GPIO18（Physical Pin 12），VCC 接外部 5V 電源，並安裝`Adafruit-Blinka-Raspberry-Pi5-Neopixel` 。

```bash
pip install adafruit-blinka
pip install Adafruit-Blinka-Raspberry-Pi5-Neopixel
pip install adafruit-circuitpython-neopixel
```

---

### 步驟 6：硬體測試

`--detector`、`--encoder`、`--matcher` 不需要模型檔，可在部署前提前驗證。

```bash
python test.py --picam --light --detector --encoder --matcher
```

---

## 啟動

```bash
python run.py                # 視窗模式（開發測試）
python run.py --fullscreen   # 全螢幕模式（觸控螢幕部署）

# 指定自訂 Gallery 和模型
python run.py --gallery path/to/gallery --model path/to/best.pt
```

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

從 FY115 工作站工具生成後，複製至此目錄：

```bash
# 透過 SCP 從工作站推送
scp -r path/to/FY115/src/gallery pi@<rpi_ip>:~/FY114-Drug-Recognition-Subsystem/src/
scp path/to/FY115/src/best.pt   pi@<rpi_ip>:~/FY114-Drug-Recognition-Subsystem/src/

# 或透過 Git（需在 Pi 上執行 git pull）
```

---

## 目錄結構

```
FY114-Drug-Recognition-Subsystem/
├── run.py               ← 主程式（Tkinter GUI）
├── test.py              ← 元件測試工具
├── startup.sh           ← 開機自動啟動腳本
├── requirements.txt     ← Python 套件清單
├── utils/
│   ├── detector.py      ← BaseDetector 介面（面積過濾）
│   ├── encoder.py       ← BaseEncoder 介面（L2 正規化）
│   ├── matcher.py       ← BaseMatcher 介面（空庫防護）
│   ├── gallery.py       ← 特徵庫管理（index.json + features.npy）
│   ├── types.py         ← 資料型別（Detection, MatchResult）
│   └── modules/
│       ├── encoder/resnet34.py   ← ResNet34 編碼器（預設）
│       └── matcher/top1.py       ← Top-1 比對器（預設）
└── src/
    ├── best.pt          ← YOLO 分割模型（由 FY115 提供）
    ├── gallery/         ← 特徵庫（index.json + features.npy）
    └── images/          ← 驗證記錄（YAML + JPG）
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

> 更換 Encoder 後，需在 FY115 重新建立 Gallery（特徵向量維度必須一致）。

---

## 儲存格式（src/images/）

每次按「OK」完成驗證後，儲存：

| 檔案 | 說明 |
|------|------|
| `{tray_id}.yaml` | 驗證記錄（品項、總量、逐藥確認結果） |
| `{tray_id}.jpg`  | 拍攝的藥盤原始照片 |

---

## 常見問題

| 錯誤 | 原因 | 解法 |
|------|------|------|
| `No module named 'neopixel_write'` | 缺少 Pi 5 專用後端 | `pip install Adafruit-Blinka-Raspberry-Pi5-Neopixel` |
| `PermissionError: /dev/pio0` | udev 規則未設定或未重新登入 | 重做步驟 4，確認重新登入 |
| `/dev/pio0: No such file` | 韌體過舊，PIO 裝置尚未啟用 | `sudo apt upgrade && sudo rpi-eeprom-update -a` 後重開機 |
| `picamera2` 找不到 | venv 缺少 `--system-site-packages` | 重建 venv（步驟 2） |
| GPIO 操作需要 root | 未加入 gpio 群組或未重新登入 | 重做步驟 4 |
