# FY114 Developer Guide

## 2.5D 感測器暖機邏輯

### 設計動機

MN96100C 感測器的 LED 光源在冷啟動時需要時間穩定。距上次關閉越久，光學穩定所需時間越長，因此暖機時間動態決定，而非固定秒數。

### 暖機秒數計算規則

```
warmup_secs = min(10, int(距上次關閉秒數 / 30))
```

- 每距上次關閉 **30 秒** → **+1 秒**暖機
- 上限 **10 秒**
- 首次啟動（無 log）或 log 解析失敗 → 保守策略，直接使用 **10 秒**

| 距上次關閉 | 暖機時間 |
|-----------|---------|
| < 30s     | 0s（跳過）|
| 30–59s    | 1s |
| 60–89s    | 2s |
| ...       | ... |
| ≥ 300s    | 10s（上限）|

### 實作流程（`_init_drawer_sensor`）

```
1. 開啟 VideoCapture → 確認 isOpened()
2. 讀取 logs/drawer_state.log 最後一行 → 解析時間戳
3. 計算 diff → warmup_secs
4. 倒數暖機：terminal 印出 + badge_label 顯示「感測器暖機 n/m」
5. 暖機結束 → 重製 log（mode='w' 清空）
6. 啟動 _start_drawer_monitoring()
```

**注意：log 必須在暖機結束後才重製。** 若提前清空，下次啟動就無法讀到上次的最後時間。

### Log 格式

每幀成功讀取後寫入一筆：

```
2024-01-01 12:34:56  state=完全開啟  intensity=45.2  threshold_open=19  threshold_closed=117
```

| 欄位 | 說明 |
|------|------|
| 時間戳 | `%Y-%m-%d %H:%M:%S`（完整日期，跨天重啟仍可正確計算時差）|
| state | 完全開啟 / 閉合中 / 完全閉合 / 未知 |
| intensity | MAX 平滑後的強度值 |
| threshold_open | 當下設定的開啟閾值 |
| threshold_closed | 當下設定的閉合閾值 |

### Log 檔案位置

```
logs/drawer_state.log
```

每次 `_init_drawer_sensor` 成功後重製，避免長時間累積佔用磁碟。

---

## 自訂 Encoder / Matcher / Detector

在 `utils/models.py` 繼承對應基底類別：

```python
from utils.encoder import BaseEncoder
import numpy as np

class MyEncoder(BaseEncoder):
    FEATURE_DIM = 256

    def __init__(self): ...          # 載入模型

    def forward(self, image: np.ndarray) -> np.ndarray:
        ...  # 回傳原始特徵，BaseEncoder.__call__ 自動 L2 正規化
```

> 更換 Encoder 後必須在 FY115 重新建立 Gallery（特徵向量維度必須一致），並重啟 `api.py`。

在 `api.py` 中替換 import：

```python
from utils.models import YOLODetector, Top1Matcher
from my_module import MyEncoder
```

---

## 推論 API

詳細規格見 [API_DESIGN.md](API_DESIGN.md)。
