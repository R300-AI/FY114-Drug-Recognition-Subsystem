# FY114 藥物辨識展示機

> Raspberry Pi 5 臨床前展示裝置 — 用於在正式部署前驗證 AI 辨識流程的可行性

本子系統**並非最終產品**，而是以 Raspberry Pi 5 搭建的**臨床前外部測試機**，供相關人員在院線環境中評估 AI 辨識流程。AI 辨識功能由系統整合商（SI）部署的 **AI Search Platform** 提供，展示機透過網路呼叫其辨識與編碼服務。

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

```bash
# 1. 安裝系統套件
sudo apt update && sudo apt install -y python3-pip python3-venv libcamera-dev python3-lgpio

# 2. 建立虛擬環境（加上 --system-site-packages 以繼承 picamera2）
python3 -m venv .venv --system-site-packages
source .venv/bin/activate

# 3. 安裝 Python 套件
pip install -r requirements.txt
pip install picamera2

# 4. 設定 GPIO 與相機存取權限（完成後需重新登入）
echo 'SUBSYSTEM=="*-pio", GROUP="gpio", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-com.rules
echo 'SUBSYSTEM=="bcm2835-gpiomem", GROUP="gpio", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-com.rules
echo 'SUBSYSTEM=="gpio", GROUP="gpio", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-com.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG gpio,video $USER

# 5. 安裝 LED 環形燈驅動（資料線接 GPIO18，電源接外部 5V）
pip install adafruit-blinka Adafruit-Blinka-Raspberry-Pi5-Neopixel adafruit-circuitpython-neopixel
```

## 設定

向 SI 確認 AI Search Platform 的主機 IP 後，修改 `api.yaml`：

```yaml
segment_url: "http://<主機IP>:8001"   # 影像切割服務
encoder_url: "http://<主機IP>:8002"   # 特徵比對服務
timeout: 30                            # 連線逾時秒數
```

---

## 啟動展示機

```bash
source .venv/bin/activate
python run.py --fullscreen
```

開機自動啟動：執行 `crontab -e` 並加入 `@reboot /path/to/startup.sh`

---

## 硬體與服務驗證

```bash
python test.py --picam --light --drawer --api
```

| 選項 | 說明 |
|-----|------|
| `--picam` | 測試相機是否正常拍攝 |
| `--light` | 測試 LED 環形燈是否亮起 |
| `--drawer` | 測試抽屜感測器是否正確偵測開關 |
| `--api` | 測試與 AI 辨識服務的完整連線流程（位址讀自 api.yaml） |