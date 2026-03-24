# Excel 問卷自動填寫功能說明

## 概述
系統現已整合自動填寫 Excel 問卷的功能，每次完成藥品辨識驗證後，會自動將結果寫入「成大第一階段辨識問卷_1150304建議修改版.xlsx」。

## 功能特點

✅ **自動填寫**：點擊「完成」送出後自動寫入 Excel  
✅ **保留格式**：保留原始 Excel 格式與巨集  
✅ **追加模式**：每次寫入新的一列，不覆蓋舊資料  
✅ **容錯處理**：即使 Excel 寫入失敗，YAML 與圖片仍會正常儲存  
✅ **可選功能**：可透過命令列參數停用  

## 安裝依賴套件

```bash
# 安裝 openpyxl
pip install openpyxl

# 或更新整個環境
pip install -r requirements.txt
```

## 使用方式

### 預設行為（啟用 Excel 匯出）
```bash
python run.py
```

### 停用 Excel 匯出
```bash
python run.py --no-excel-export
```

### 搭配其他參數
```bash
# Debug 模式 + 停用 Excel
python run.py --debug --no-excel-export

# 全螢幕模式 + 啟用 Excel
python run.py --fullscreen
```

## Excel 檔案要求

### 檔案位置
問卷檔案必須放在專案根目錄：
```
FY114-Drug-Recognition-Subsystem/
├── 成大第一階段辨識問卷_1150304建議修改版.xlsx  ← 必須存在
├── run.py
├── api.py
└── ...
```

### 工作表格式（範例）
系統會自動找到下一個空白列，並依序填入以下欄位：

| A 欄 | B 欄 | C 欄 | D 欄 | E 欄 | F 欄 | G 欄起... |
|------|------|------|------|------|------|-----------|
| 藥盤序號 | 時間戳記 | 品項數 | 品項正確 | 總顆數 | 總數正確 | 各藥品詳細資訊 |
| 000001 | 2026-03-24 10:30:00 | 3 | 正確 | 10 | 正確 | ... |

### 各藥品詳細資訊（每顆藥佔 5 欄）
- 藥品名稱
- 許可證字號
- 顆數
- 名稱正確性
- 劑量正確性

## 自訂欄位對應

如果您的問卷格式不同，可以修改 `utils/excel_writer.py` 中的 `write_verification_data()` 方法：

```python
def write_verification_data(self, ...):
    row = self.find_next_empty_row()
    
    # 自訂您的欄位對應
    self.sheet.cell(row, 1, tray_id)      # A 欄：藥盤序號
    self.sheet.cell(row, 2, timestamp)    # B 欄：時間
    self.sheet.cell(row, 3, variety_count) # C 欄：品項數
    # ... 繼續調整
```

## 資料流程

```
使用者點擊「完成」
    ↓
顯示填報總覽 Modal
    ↓
使用者點擊「確認送出」
    ↓
1. 儲存 YAML (records/000001.yaml)
2. 儲存圖片 (records/000001.jpg)
3. 寫入 Excel 問卷 ← 新功能
    ↓
UI 重置，準備下一輪辨識
```

## 錯誤處理

### Excel 檔案不存在
```
[excel] 警告: 問卷檔案不存在: 成大第一階段辨識問卷_1150304建議修改版.xlsx
[excel] 匯出失敗: ...
```
**解決方式**：確認檔案存在於專案根目錄

### openpyxl 未安裝
```
[excel] openpyxl 未安裝，Excel 匯出功能已停用
```
**解決方式**：執行 `pip install openpyxl`

### Excel 檔案被開啟中
```
[excel] 寫入錯誤: [Errno 13] Permission denied: '成大第一階段辨識問卷_1150304建議修改版.xlsx'
```
**解決方式**：關閉 Excel 檔案後再重試

## 備份建議

雖然系統以追加模式寫入（不覆蓋舊資料），仍建議定期備份 Excel 問卷：

```bash
# 手動備份
cp 成大第一階段辨識問卷_1150304建議修改版.xlsx backups/問卷_$(date +%Y%m%d).xlsx
```

或使用程式內建的備份功能（在 `utils/excel_writer.py` 中）：

```python
from utils.excel_writer import create_backup

backup_path = create_backup("成大第一階段辨識問卷_1150304建議修改版.xlsx")
```

## 進階設定

### 修改工作表名稱
如果問卷有多個工作表，可以在初始化時指定：

```python
# 在 utils/ui.py 的 _export_to_excel() 中修改
writer = ExcelWriter(EXCEL_QUESTIONNAIRE, sheet_name="辨識結果")
```

### 修改起始列
預設從第 2 列開始（第 1 列為標題），可以調整：

```python
writer.write_verification_data(
    ...,
    start_row=3  # 從第 3 列開始寫入
)
```

## 疑難排解

### Q: Excel 檔案格式損壞怎麼辦？
A: 使用備份還原，並檢查 `openpyxl` 版本是否為 3.1.0+

### Q: 可以同時寫入多個 Excel 檔案嗎？
A: 可以，修改 `_export_to_excel()` 方法，建立多個 `ExcelWriter` 實例

### Q: 如何只匯出特定欄位？
A: 在 `write_verification_data()` 中調整需要寫入的欄位

### Q: 支援 .xls 舊格式嗎？
A: 不支援，請先將 .xls 轉換為 .xlsx 格式

## 相關檔案

- `utils/excel_writer.py` - Excel 寫入核心模組
- `utils/ui.py` - UI 整合（`_export_to_excel()` 方法）
- `run.py` - 命令列參數控制
- `requirements.txt` - 依賴套件（含 openpyxl）

## 更新日期
2026-03-24
