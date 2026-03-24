# UI 預設驗證狀態功能說明

## 概述
此功能讓辨識結果的「正確/錯誤」按鈕在預設情況下自動選中「正確」，減少使用者手動點選的次數，提升操作效率。

## 設計原則
- **非硬編碼**：預設狀態可由外部參數控制
- **可維護**：統一由 `VerificationState.set_defaults()` 方法管理
- **可擴展**：未來可輕鬆調整為預設「錯誤」或「未選」

## 修改內容

### 1. `utils/ui.py` - VerificationState 類別
新增 `set_defaults()` 方法，統一設定所有驗證狀態的預設值：

```python
def set_defaults(self, default_correct: bool | None = True):
    """設定預設的驗證狀態（可選擇預設為正確、錯誤或未選）"""
    self.variety_correct = default_correct
    self.total_correct = default_correct
    if self.pills:
        self.name_answers = [default_correct] * len(self.pills)
        self.dose_answers = [default_correct] * len(self.pills)
```

### 2. `utils/ui.py` - App 類別
- 新增 `default_verification` 參數（預設為 `True`）
- 在初始化、重置、分析後自動套用預設值

### 3. `run.py` - 命令列參數
新增命令列參數供使用者控制：

```bash
# 預設啟用（預設辨識結果為正確）
python run.py

# 明確啟用
python run.py --default-correct

# 停用（需使用者手動選擇）
python run.py --no-default-correct
```

## 使用方式

### 一般使用（預設啟用）
```bash
python run.py
```
所有「正確/錯誤」按鈕會自動選中「正確」。

### 停用預設值
```bash
python run.py --no-default-correct
```
所有按鈕維持未選狀態，需使用者手動選擇。

### Debug 模式搭配使用
```bash
python run.py --debug --default-correct
```

## 技術細節

### 預設值套用時機
1. **UI 初始化時**：`App.__init__()` 建立 state 後立即套用
2. **重置狀態時**：`_reset_state()` 重建 state 後套用
3. **分析完成時**：`_update_state_from_results()` 更新 state 後套用

### 可選值
- `True`：預設為「正確」（綠色按鈕選中）
- `False`：預設為「錯誤」（紅色按鈕選中）
- `None`：不預設（兩個按鈕都未選中）

## 維護注意事項

若未來需要修改預設行為，只需調整以下任一位置：

1. **程式碼層級**：修改 `App.__init__()` 的 `default_verification` 預設值
2. **命令列層級**：調整 `run.py` 的 `--default-correct` 預設值
3. **使用者層級**：執行時加上 `--no-default-correct` 參數

## 測試建議

1. 啟動程式，確認所有「正確」按鈕已選中
2. 點擊「錯誤」按鈕，確認可正常切換
3. 切換藥品項目，確認每項的預設狀態正確
4. 點擊「完成」後重置，確認新一輪也有預設值
5. 測試 `--no-default-correct` 參數，確認按鈕未選中

## 更新日期
2026-03-24
