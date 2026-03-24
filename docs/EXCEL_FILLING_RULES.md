# Excel 填寫規則與流程說明

## 📋 完整資料流程圖

```
使用者操作 (run.py)
    ↓
辨識完成 → 使用者驗證 → 點擊「完成」
    ↓
顯示填報總覽 Modal
    ↓
點擊「確認送出」
    ↓
_save_results() [utils/ui.py 第 1313 行]
    ├─ 1. 儲存 YAML (records/000001.yaml)
    ├─ 2. 儲存圖片 (records/000001.jpg)
    └─ 3. 呼叫 _export_to_excel() [第 1332 行]
           ↓
        ExcelWriter.write_verification_data() [utils/excel_writer.py 第 80 行]
           ↓
        自動找到下一個空白列
           ↓
        依序填入各欄位
           ↓
        儲存 Excel 檔案
```

---

## 📊 Excel 欄位對應規則

### 目前預設的欄位配置

| 欄位 | 內容 | 資料來源 | 範例值 |
|------|------|----------|--------|
| **A** | 藥盤序號 | `self.state.tray_id` | "000001" |
| **B** | 時間戳記 | `self.state.timestamp` | "2026-03-24 10:30:00" |
| **C** | 品項數量 | `self.state.variety_count` | 3 |
| **D** | 品項正確性 | `self.state.variety_correct` | "正確" / "錯誤" / "未填" |
| **E** | 總顆數 | `self.state.total_count` | 10 |
| **F** | 總數正確性 | `self.state.total_correct` | "正確" / "錯誤" / "未填" |
| **G~** | 各藥品詳細資訊 | `self.state.pills[]` | 見下方說明 |

### 各藥品詳細資訊（每顆藥品佔 5 欄）

假設第一顆藥從 G 欄開始：

| 欄位 | 內容 | 資料來源 | 範例值 |
|------|------|----------|--------|
| **G** | 第1顆藥品名稱 | `pills[0].name` | "普拿疼錠500毫克" |
| **H** | 第1顆許可證字號 | `pills[0].license` | "衛署藥製字第012345號" |
| **I** | 第1顆數量 | `pills[0].same_count` | 3 |
| **J** | 第1顆名稱正確性 | `name_answers[0]` | "正確" |
| **K** | 第1顆劑量正確性 | `dose_answers[0]` | "正確" |
| **L** | 第2顆藥品名稱 | `pills[1].name` | "維他命C錠" |
| **M** | 第2顆許可證字號 | `pills[1].license` | "衛署藥製字第067890號" |
| **N** | 第2顆數量 | `pills[1].same_count` | 5 |
| **O** | 第2顆名稱正確性 | `name_answers[1]` | "錯誤" |
| **P** | 第2顆劑量正確性 | `dose_answers[1]` | "正確" |
| **Q~** | 第3顆... | 依此類推 | ... |

---

## 🔗 與 run.py 的連結流程

### 1. **使用者啟動程式**
```bash
python run.py --fullscreen
```

**run.py 第 30 行**：
```python
App(root, api_url=args.api, fullscreen=args.fullscreen, 
    debug=args.debug, 
    default_verification=True if args.default_correct else None,
    enable_excel_export=args.excel_export)  # ← 預設啟用
```

### 2. **App 初始化（utils/ui.py 第 147 行）**
```python
def __init__(self, ..., enable_excel_export: bool = True):
    self._enable_excel_export = enable_excel_export and HAS_OPENPYXL
    
    # 檢查 Excel 檔案是否存在（第 203 行）
    if self._enable_excel_export:
        if EXCEL_QUESTIONNAIRE.exists():
            print(f"[excel] 問卷檔案已找到: {EXCEL_QUESTIONNAIRE.name}")
        else:
            print(f"[excel] 警告: 問卷檔案不存在: {EXCEL_QUESTIONNAIRE}")
            self._enable_excel_export = False
```

### 3. **辨識與驗證流程**

#### a. 拍照與辨識
```python
# utils/ui.py 第 783 行
def _on_analyse(self):
    frame = self._capture_single_frame()  # 拍攝
    detections, results = self._call_api(frame)  # AI 辨識
    self._update_state_from_results(detections, results)  # 更新狀態
```

#### b. 狀態更新（第 978 行）
```python
def _update_state_from_results(self, detections, results):
    # 建立 PillEntry 列表
    pills: list[PillEntry] = []
    for r in results:
        pills.append(PillEntry(
            license=r.license_number,
            name=r.name,
            same_count=license_count.get(r.license_number, 1),
            color_idx=license_color[r.license_number],
        ))
    
    # 更新 state
    self.state.variety_count = len(unique_licenses)
    self.state.total_count = len(pills)
    self.state.pills = pills
    
    # 套用預設驗證狀態（正確按鈕自動選中）
    self.state.set_defaults(self._default_verification)  # ← True
```

#### c. 使用者驗證（UI 按鈕互動）
```python
# 使用者點擊「錯誤」按鈕時（第 1144 行）
def _set_variety(self, value: bool):
    self.state.variety_correct = value  # ← 更新為 False
    self._update_button_states()

def _set_name(self, value: bool):
    self.state.name_answers[self.state.current_page] = value
    self._update_button_states()
```

### 4. **點擊「完成」按鈕（第 1219 行）**
```python
def _on_done(self):
    self._show_review_modal()  # 顯示填報總覽
```

### 5. **填報總覽 Modal（第 1224 行）**
使用者確認所有資料後，點擊「確認送出」：
```python
def do_submit():
    modal_destroy()
    self._save_results()  # ← 觸發儲存
    self._reset_state()
```

### 6. **儲存結果（第 1313 行）**
```python
def _save_results(self):
    # 1. 儲存 YAML
    yaml_path = RECORDS_DIR / f"{tray_id}.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f, allow_unicode=True, default_flow_style=False)
    
    # 2. 儲存圖片
    img_path = RECORDS_DIR / f"{tray_id}.jpg"
    cv2.imwrite(str(img_path), self._captured_image)
    
    # 3. 匯出至 Excel
    if self._enable_excel_export:
        try:
            self._export_to_excel()  # ← 呼叫 Excel 匯出
        except Exception as e:
            print(f"[excel] 匯出失敗: {e}")
```

### 7. **Excel 匯出（第 1332 行）**
```python
def _export_to_excel(self):
    writer = ExcelWriter(EXCEL_QUESTIONNAIRE)
    
    # 傳遞所有驗證資料
    writer.write_verification_data(
        tray_id=self.state.tray_id,           # "000001"
        timestamp=self.state.timestamp,       # "2026-03-24 10:30:00"
        variety_count=self.state.variety_count,     # 3
        variety_correct=self.state.variety_correct, # True → "正確"
        total_count=self.state.total_count,         # 10
        total_correct=self.state.total_correct,     # True → "正確"
        pills=self.state.pills,               # [PillEntry(...), ...]
        name_answers=self.state.name_answers, # [True, False, True, ...]
        dose_answers=self.state.dose_answers, # [True, True, False, ...]
    )
    
    writer.save()
    writer.close()
```

### 8. **ExcelWriter 寫入（utils/excel_writer.py 第 80 行）**
```python
def write_verification_data(self, tray_id, timestamp, ...):
    row = self.find_next_empty_row()  # 找到下一個空白列（如第 2 列）
    
    # 依序寫入欄位
    self.sheet.cell(row, 1, tray_id)        # A2 = "000001"
    self.sheet.cell(row, 2, timestamp)      # B2 = "2026-03-24 10:30:00"
    self.sheet.cell(row, 3, variety_count)  # C2 = 3
    self.sheet.cell(row, 4, self._bool_to_text(variety_correct))  # D2 = "正確"
    self.sheet.cell(row, 5, total_count)    # E2 = 10
    self.sheet.cell(row, 6, self._bool_to_text(total_correct))    # F2 = "正確"
    
    # 寫入各藥品資訊（G2 開始）
    col = 7  # G 欄
    for i, pill in enumerate(pills):
        self.sheet.cell(row, col, pill.name)           # G2 = "普拿疼錠"
        self.sheet.cell(row, col+1, pill.license)      # H2 = "衛署..."
        self.sheet.cell(row, col+2, pill.same_count)   # I2 = 3
        self.sheet.cell(row, col+3, self._bool_to_text(name_answers[i]))  # J2 = "正確"
        self.sheet.cell(row, col+4, self._bool_to_text(dose_answers[i]))  # K2 = "正確"
        col += 5  # 下一顆藥從 L 欄開始
```

---

## 🎯 資料來源對照表

| Excel 欄位 | 程式變數 | 取得位置 | 說明 |
|-----------|---------|---------|------|
| A: 藥盤序號 | `self.state.tray_id` | `get_next_serial_number()` | 自動流水號 000001, 000002... |
| B: 時間戳記 | `self.state.timestamp` | `datetime.now()` | 辨識完成時間 |
| C: 品項數量 | `self.state.variety_count` | `len(unique_licenses)` | 不重複藥品種類數 |
| D: 品項正確 | `self.state.variety_correct` | 使用者點擊按鈕 | 預設 True（正確） |
| E: 總顆數 | `self.state.total_count` | `len(pills)` | 所有偵測到的藥錠數 |
| F: 總數正確 | `self.state.total_correct` | 使用者點擊按鈕 | 預設 True（正確） |
| G: 藥品名稱 | `pills[i].name` | API 辨識結果 | 如"普拿疼錠500毫克" |
| H: 許可證 | `pills[i].license` | API 辨識結果 | 如"衛署藥製字第..." |
| I: 藥品數量 | `pills[i].same_count` | 同 license 計數 | 畫面中相同藥品的顆數 |
| J: 名稱正確 | `name_answers[i]` | 使用者點擊按鈕 | 預設 True（正確） |
| K: 劑量正確 | `dose_answers[i]` | 使用者點擊按鈕 | 預設 True（正確） |

---

## 🔧 自訂填寫規則

### 如何修改欄位順序或增減欄位

編輯 `utils/excel_writer.py` 的 `write_verification_data()` 方法（第 116-161 行）：

```python
# 假設您的問卷格式是：
# A: 時間, B: 序號, C: 品項數, D: 品項正確, ...

def write_verification_data(self, ...):
    row = self.find_next_empty_row()
    
    col = 1  # A 欄
    self.sheet.cell(row, col, timestamp)  # ← 改為先寫時間
    
    col += 1  # B 欄
    self.sheet.cell(row, col, tray_id)    # ← 再寫序號
    
    col += 1  # C 欄
    self.sheet.cell(row, col, variety_count)
    
    # ... 依此類推
```

### 如何指定工作表

```python
# 在 _export_to_excel() 中修改（utils/ui.py 第 1343 行）
writer = ExcelWriter(EXCEL_QUESTIONNAIRE, sheet_name="辨識結果")
#                                          ^^^^^^^^^^^^^^^^ 指定工作表名稱
```

### 如何指定起始列

```python
# 如果問卷第 1-3 列是標題，從第 4 列開始寫入
writer.write_verification_data(
    ...,
    start_row=4  # ← 明確指定起始列
)
```

---

## 🧪 測試填寫功能

### 1. 使用測試腳本
```bash
python test_excel_writer.py
```

### 2. Debug 模式測試
```bash
python run.py --debug
# 按空白鍵模擬辨識 → 驗證 → 完成 → 自動寫入 Excel
```

### 3. 檢查 Excel 結果
開啟問卷檔案，檢查最後一列是否正確填入：
- 序號、時間、品項數、總數
- 各藥品的名稱、許可證、數量、正確性

---

## 📝 實際範例

假設辨識結果：
- 3 種藥品
- 共 10 顆（藥品 A: 3 顆, 藥品 B: 5 顆, 藥品 C: 2 顆）
- 使用者標記：品項正確、總數正確、所有藥品名稱和劑量都正確

**Excel 寫入結果（第 2 列）：**

| A | B | C | D | E | F | G | H | I | J | K | L | M | N | O | P | ... |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|-----|
| 000001 | 2026-03-24 10:30:00 | 3 | 正確 | 10 | 正確 | 普拿疼錠 | 衛署... | 3 | 正確 | 正確 | 維他命C錠 | 衛署... | 5 | 正確 | 正確 | ... |

---

## 🎯 關鍵程式碼位置總覽

| 功能 | 檔案 | 行號 | 說明 |
|------|------|------|------|
| 啟動參數 | run.py | 23-29 | `--no-excel-export` 參數 |
| Excel 初始化 | utils/ui.py | 147-150 | `enable_excel_export` 參數 |
| Excel 檔案檢查 | utils/ui.py | 203-210 | 檢查問卷是否存在 |
| 辨識完成 | utils/ui.py | 978-1007 | 更新 state 資料 |
| 使用者驗證 | utils/ui.py | 1144-1173 | 按鈕點擊更新狀態 |
| 儲存觸發 | utils/ui.py | 1313-1330 | `_save_results()` |
| Excel 匯出 | utils/ui.py | 1332-1359 | `_export_to_excel()` |
| 欄位寫入 | utils/excel_writer.py | 80-161 | `write_verification_data()` |

---

## 💡 常見問題

### Q: 如果使用者沒填完就點「完成」？
A: 未填的欄位會顯示「未填」（None → "未填"）

### Q: Excel 檔案被開啟時會怎樣？
A: 寫入失敗，顯示錯誤訊息，但 YAML 和圖片仍會正常儲存

### Q: 可以同時寫入多個 Excel 檔案嗎？
A: 可以，在 `_export_to_excel()` 中建立多個 `ExcelWriter` 實例

### Q: 如何追蹤寫入的是哪一列？
A: `write_verification_data()` 回傳寫入的列號，可以記錄下來

---

這份文件涵蓋了完整的填寫規則與流程，需要我針對特定部分做更詳細的說明嗎？

