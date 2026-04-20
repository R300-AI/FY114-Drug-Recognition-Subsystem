# FY114 藥物辨識展示機

> Raspberry Pi 5 臨床前展示裝置 — 用於在正式部署前驗證 AI 辨識流程的可行性

本子系統**並非最終產品**，而是以 Raspberry Pi 5 搭建的**臨床前外部測試機**，供相關人員在院線環境中評估 AI 辨識流程。AI 辨識功能由系統整合商（SI）部署的 **AI Search Platform** 提供，展示機透過網路呼叫其辨識與編碼服務。

> **給首次接觸本專案的人：**
> 您只需要一台已完成硬體組裝的 Raspberry Pi 5。AI 辨識運算**不在本機執行**，展示機的職責是「拍照 → 傳送給遠端 AI 伺服器 → 顯示結果」。安裝前請先向系統整合商（SI）取得 AI Search Platform 的主機 IP，並確認兩台設備已透過有線網路連接。

---

## 系統定位

```
┌───────────────────────────────────────────────┐
│          AI Search Platform（SI 部署）         │
│  影像切割服務 :8001  │  特徵比對服務 :8002     │
└──────────────────────┬────────────────────────┘
                       │ HTTP
          ┌────────────┼───────────┐
     ┌────┴─────┐  ┌───┴────┐  ┌──┴──────┐
     │  本展示機 │  │ 網頁介面│  │手機應用 │
     │ Pi5+觸控 │  │（客製）│  │（客製） │
     └──────────┘  └────────┘  └─────────┘
```

展示機預設透過有線網路與主機直連（展示機：192.168.50.2 / 主機：192.168.50.1）。
實際部署的 IP 位址由系統整合商規劃，**請向 SI 確認後再填入 `api.yaml`**。

---

## 硬體配置

| 元件 | 規格 |
|-----|------|
| 主板 | Raspberry Pi 5（8 GB 記憶體） |
| 相機 | Raspberry Pi Camera Module 3 |
| 螢幕 | Raspberry Pi 官方 7 吋觸控螢幕（直立放置） |
| 抽屜感測器 | MN96100C 2.5D 紅外線深度感測器 |
| 光箱光源 | WS2812 NeoPixel LED 環形燈（24 顆，接 GPIO18） |

---

## 操作流程

```
                    啟動 → 確認辨識服務可連線
                     ├── 無法連線 → 顯示錯誤訊息並結束（除錯模式不檢查）
                     └── 連線成功 → 黑畫面待機
                               │
          ┌───────────────────┼───────────────────┐
       一般模式            展示模式            除錯模式（--debug）
       感測器偵測抽屜關閉   按空白鍵模擬觸發    按空白鍵模擬觸發
       相機拍攝藥盤         載入內建範例圖片    載入內建範例圖片
       呼叫 AI 辨識服務     呼叫 AI 辨識服務    使用假辨識結果（不連網）
          └───────────────────┬───────────────────┘
                         顯示辨識結果
                    護理師確認後按「完成」
                      儲存紀錄 → 黑畫面待機
```

> **展示模式**自動觸發條件：相機、抽屜感測器、光箱燈光任一項無法正常啟動時，系統會自動切換至展示模式；
> 亦可在啟動時加上 `--demo` 旗標強制進入展示模式。

---

## 安裝（Raspberry Pi 5，Debian 12 Bookworm）

> 以下步驟請在 Raspberry Pi 5 上開啟終端機執行。全部步驟只需在**第一次部署時**執行一次。

### 步驟 1：安裝系統套件

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv libcamera-dev python3-lgpio
```

> `python3-lgpio` 是 LED 環形燈驅動（adafruit-blinka）在 Pi 5 上的底層依賴；`libcamera-dev` 是相機底層函式庫。

---

### 步驟 2：建立 Python 虛擬環境

```bash
# 切換到本專案目錄
cd /path/to/FY114-Drug-Recognition-Subsystem

# 建立虛擬環境（--system-site-packages 讓 venv 繼承系統層的 picamera2，避免底層相機驅動衝突）
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
```

---

### 步驟 3：安裝 Python 套件

```bash
pip install -r requirements.txt
pip install picamera2
```

> `requirements.txt` 包含 numpy、opencv、requests、pyyaml、openpyxl 等主要依賴。`picamera2` 因底層驅動需額外獨立安裝。

---

### 步驟 4：設定 GPIO 與相機存取權限

授予目前使用者存取 GPIO（抽屜感測器）與相機的權限。**完成後必須重新登入才會生效。**

```bash
echo 'SUBSYSTEM=="*-pio", GROUP="gpio", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-com.rules
echo 'SUBSYSTEM=="bcm2835-gpiomem", GROUP="gpio", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-com.rules
echo 'SUBSYSTEM=="gpio", GROUP="gpio", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-com.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG gpio,video $USER
# 執行完後登出再登入
```

---

### 步驟 5：安裝 LED 環形燈驅動

接線方式：WS2812 DIN → GPIO18（實體腳位 12），VCC 接外部 5V 電源（**勿接 Pi 的 5V 腳位**，電流不足）。

```bash
pip install adafruit-blinka Adafruit-Blinka-Raspberry-Pi5-Neopixel adafruit-circuitpython-neopixel
```

## 設定網路

向 SI 確認 AI Search Platform 的主機 IP 後，修改專案根目錄的 `api.yaml`：

```yaml
segment_url: "http://<主機IP>:8001"   # 影像切割服務
encoder_url: "http://<主機IP>:8002"   # 特徵比對服務
timeout: 30                            # 連線逾時秒數（視網路狀況調整）
```

預設值為 `192.168.50.1`（展示機透過有線直連主機的預設 IP）。`run.py` 與 `test.py` 啟動時會自動讀取此檔。

用 dhcpcd.conf 永久設定 eth0 靜態 IP：
```yaml
sudo nano /etc/dhcpcd.conf
```
```yaml
interface eth0
static ip_address=192.168.50.x/24
nolink
```
```yaml
sudo systemctl restart dhcpcd
```

---

## 啟動展示機

### 手動啟動（開發測試用）

```bash
source .venv/bin/activate
python run.py --fullscreen
```

| 啟動參數 | 說明 |
|---|---|
| `--fullscreen` | 全螢幕模式，觸控螢幕部署時使用 |
| `--demo` | 展示模式：強制跳過不可用硬體，仍呼叫真實 API |
| `--debug` | 除錯模式：完全跳過相機、感測器與 API，使用內建樣本圖與假辨識結果 |
| `--no-default-correct` | 辨識結果不預設為「正確」，需護理師手動逐項選擇 |
| `--no-excel-export` | 停用完成後自動填寫 Excel 問卷的功能 |

---

### 開機自動啟動（正式部署）

`startup.sh` 會在開機時自動旋轉螢幕、啟動虛擬環境並執行 `run.py`，啟動過程的 log 記錄於 `/tmp/drug_recognition_startup.log`。

**設定步驟：**

```bash
# 1. 確認 startup.sh 有執行權限
chmod +x /path/to/FY114-Drug-Recognition-Subsystem/startup.sh

# 2. 開啟 crontab 編輯器
crontab -e

# 3. 在檔案最後加入以下這行（將路徑改為實際完整路徑）
@reboot /完整路徑/FY114-Drug-Recognition-Subsystem/startup.sh
```

> **注意**：`startup.sh` 預設螢幕輸出名稱為 `XWAYLAND0`。若旋轉未生效，請先執行 `DISPLAY=:0 xrandr` 查詢實際輸出名稱，再修改 `startup.sh` 中對應的行。

---

## 硬體與服務驗證

安裝完成後，建議先執行硬體驗證，確認所有元件正常運作再正式啟動。

```bash
source .venv/bin/activate
python test.py --picam --light --drawer --api
```

| 選項 | 說明 | 需要硬體 |
|---|---|---|
| `--picam` | 測試相機是否正常拍攝 | ✅ |
| `--light` | 測試 LED 環形燈是否亮起 | ✅ |
| `--drawer` | 測試抽屜感測器是否正確偵測開關 | ✅ |
| `--api` | 測試與 AI 辨識服務的完整連線流程（位址讀自 `api.yaml`） | 需網路連至 AI Search Platform |

> 可單獨指定選項，例如只測試網路連線：`python test.py --api`