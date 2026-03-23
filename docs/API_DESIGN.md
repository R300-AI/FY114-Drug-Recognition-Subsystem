# FY114 藥物辨識子系統 — API 工程設計文件

版本：1.0　　日期：2026-03-23

---

## 1. 背景與目標

原架構中，YOLO 偵測、特徵編碼、Gallery 比對全部在 `run.py` 的 UI 程序內執行。
這造成：

- AI 推論與 UI 事件循環共用同一 Python 程序，難以獨立替換或水平擴展
- 未來若要在雲端或獨立推論機器執行 AI，需重寫大量程式碼
- 不易對 AI pipeline 做單獨壓測或整合測試

**目標**：將 AI 辨識功能抽離為獨立 Flask REST API（`api.py`），UI 程序透過 HTTP 呼叫取得辨識結果。

---

## 2. 系統架構

```
┌──────────────────────────────────────────┐     ┌────────────────────────────────────────────┐
│  UI 程序  (run.py + utils/ui.py)          │     │  推論伺服器  (api.py)                       │
│                                          │     │                                            │
│  ┌──────────────────────────────────┐   │     │  GET  /health                              │
│  │  App (Tkinter)                   │   │HTTP │  POST /analyse                             │
│  │  ├─ 抽屜感測 (_drawer_capture)   │──→│────→│    ├─ YOLODetector  (best.pt)              │
│  │  ├─ 相機拍攝 (_capture_frame)   │   │     │    ├─ ResNet34Encoder                       │
│  │  ├─ 驗證填報 (UI 回饋按鈕)      │←──│─────│    ├─ Top1Matcher + Gallery                 │
│  │  └─ 紀錄儲存 (_save_results)    │   │JSON │    └─ DrugTW2025.csv 藥品資料庫             │
│  └──────────────────────────────────┘   │     │                                            │
└──────────────────────────────────────────┘     └────────────────────────────────────────────┘
         run.py --api http://HOST:5000                    python api.py --model src/best.pt
```

### 程序職責分工

| 程序 | 職責 |
|------|------|
| `api.py` | YOLO 分割、特徵編碼、Gallery 比對、DrugTW2025.csv 查詢、HTTP 服務 |
| `run.py` | 啟動 Tkinter App、解析 CLI 參數、無 AI 元件 |
| `utils/ui.py` | 相機拍攝、抽屜感測、呼叫 API、UI 顯示、驗證填報、紀錄儲存 |

---

## 3. API 規格

### 3.1 `GET /health`

健康檢查，確認伺服器就緒。

**Response 200**
```json
{
  "status": "ok",
  "gallery_size": 1024,
  "mock": false
}
```

---

### 3.2 `POST /analyse`

送入影像，回傳所有偵測到藥錠的辨識結果。

**Request**
- Content-Type: `multipart/form-data`
- Field: `image` — JPEG 或 PNG 二進位影像

**Response 200**
```json
{
  "status": "ok",
  "pills": [
    {
      "bbox": [x1, y1, x2, y2],
      "mask_b64": "<base64 PNG 灰階遮罩，白=前景>",
      "confidence": 0.95,
      "class_id": 0,
      "license_number": "內衛成製字第000075號",
      "name": "福元蘇打錠500毫克",
      "side": 0,
      "score": 0.92,
      "drug_info": {
        "name_zh": "福元蘇打錠500毫克",
        "name_en": "SODIUM BICARBONATE TABLETS",
        "shape": "圓形",
        "color": "白",
        "size": "8",
        "mark1": "FY T061",
        "mark2": "",
        "image_url": "https://mcp.fda.gov.tw/..."
      }
    }
  ]
}
```

若無偵測到任何藥錠：`"pills": []`

**Response 400**（影像格式錯誤）
```json
{ "error": "Cannot decode image" }
```

---

## 4. 元件設計

### 4.1 `api.py`

```
api.py
├─ _load_drug_db(csv_path)     載入 DrugTW2025.csv → dict[license → drug_info]
├─ GET  /health                回傳伺服器狀態
├─ POST /analyse               主要辨識端點
│    ├─ 解析 multipart image
│    ├─ detector(frame)        → list[Detection]
│    ├─ for each Detection:
│    │    ├─ crop + encoder()  → feature vector
│    │    ├─ matcher(feature)  → MatchResult | None
│    │    └─ drug_db.get(license_number) → drug_info
│    └─ 回傳 JSON（含 mask_b64）
└─ main()                      argparse + app.run()
```

**CLI 參數**

| 參數 | 預設 | 說明 |
|------|------|------|
| `--model` | `src/best.pt` | YOLO 模型路徑 |
| `--gallery` | `src/gallery` | Gallery 目錄 |
| `--drug-db` | `DrugTW2025.csv` | 藥品清單 CSV |
| `--host` | `0.0.0.0` | 綁定位址 |
| `--port` | `5000` | 監聽埠號 |
| `--mock` | off | Mock 模式：跳過 encoder/matcher，固定回傳許可證字號 00008 |

### 4.2 `utils/ui.py` — `App` 類別修改

`__init__` 簽名由：
```python
App(root, gallery, encoder, matcher, detector, fullscreen, debug)
```
改為：
```python
App(root, api_url, fullscreen, debug)
```

新增 `_call_api(frame)` 方法：
1. `cv2.imencode(".jpg", frame)` → bytes
2. `requests.post(api_url + "/analyse", files={"image": ...})` → JSON
3. 從 JSON 重建 `Detection` 和 `MatchResult` 物件（mask 從 base64 PNG 解碼）
4. 回傳 `(detections, results)`

`_on_analyse` 邏輯：
```
if debug → _load_sample_detections + _debug_fake_results (本機，無需 API)
else     → _call_api(frame) → (detections, results)
```

### 4.3 `run.py` 修改

- 保留 `YOLODetector`、`ResNet34Encoder`、`Top1Matcher` 類別定義（供 `api.py` 匯入使用及替換參考）
- 移除 `create_components()`（AI 元件改由 api.py 管理）
- `main()` 新增 `--api` 參數（預設 `http://localhost:5000`）
- `App(root, api_url, ...)` 取代原本的 `App(root, gallery, encoder, matcher, detector, ...)`

---

## 5. 資料流

```
使用者關閉抽屜
      │
[抽屜監測] 連續 5 幀「完全閉合」
      │
root.after(0, _on_drawer_closed)
      │  (背景執行緒)
_on_analyse()
      ├─ _capture_single_frame()        ← 相機拍照
      ├─ POST /analyse  (multipart)     ← HTTP 至 api.py
      │        │
      │   [api.py]
      │   detector(frame)               → N 個 Detection
      │   for det in detections:
      │       encoder(crop) → feature
      │       matcher(feature) → MatchResult
      │       drug_db.get(license) → drug_info
      │   return JSON
      │        │
      ├─ 解析 JSON → Detection[] + MatchResult[]
      ├─ _update_state_from_results()
      ├─ _generate_ai_overlay()
      └─ root.after(0, _update_ui)      ← 回主執行緒更新 UI
```

---

## 6. 啟動方式

### 推論伺服器（需先啟動）
```bash
python api.py --model src/best.pt --gallery src/gallery --port 5000
```

Mock 模式（無 Gallery 也可測試 UI）：
```bash
python api.py --model src/best.pt --mock
```

### UI 程序
```bash
python run.py --api http://localhost:5000
python run.py --api http://localhost:5000 --fullscreen
python run.py --debug          # 本機 Debug，不需 API 伺服器
```

---

## 7. 依賴套件新增

| 套件 | 用途 | 安裝 |
|------|------|------|
| `flask` | API 伺服器 | `pip install flask` |
| `requests` | UI 程序呼叫 API | `pip install requests` |

---

## 8. mock 模式行為

`api.py --mock` 時，`/analyse` 端點：
- 仍呼叫 `detector(frame)` 取得真實偵測框與遮罩
- 跳過 encoder/matcher
- 每顆藥錠固定回傳 `license_number="00008"`，delay 200~300ms 模擬推論時間
- 方便在 Gallery 尚未建立前測試 UI 流程

---

## 9. 未來擴充方向

- 將 `YOLODetector`、`ResNet34Encoder`、`Top1Matcher` 遷移至 `utils/models.py`，使 api.py 不需匯入 run.py
- `api.py` 加入 `--workers` 多程序並行處理（gunicorn/waitress）
- `/analyse` 支援 batch（一次送多張影像）
- 在 API response 加入 overlay image（base64）選項，由 UI 決定是否取用
