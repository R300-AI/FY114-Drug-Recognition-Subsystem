# 開發者指南

> 本文件涵蓋模組 API、資料格式、擴充開發方式，供需要修改或擴充系統的工程師參考。

---

## 目錄

1. [完整目錄結構](#1-完整目錄結構)
2. [核心模組 API](#2-核心模組-api)
3. [自訂 Encoder / Matcher](#3-自訂-encoder--matcher)
4. [Gallery 格式](#4-gallery-格式)
5. [驗證記錄格式（src/images/）](#5-驗證記錄格式srcimages)

---

## 1. 完整目錄結構

```
FY114-Drug-Recognition-Subsystem/
├── run.py                        ← 主程式（Tkinter GUI，create_components() 在此）
├── drawer_monitor.py             ← MN96100C 2.5D 傳感器校準工具
├── test.py                       ← 硬體與模組整合測試
├── startup.sh                    ← 開機自動啟動腳本
│
├── config/
│   ├── drawer_config.yaml        ← Drawer Monitor 運行時配置（自動生成與儲存）
│   └── drawer_config_example.yaml ← 配置說明範例（含完整注釋）
│
├── src/
│   ├── best.pt                   ← YOLO 分割模型（由 FY115 提供）
│   ├── gallery/
│   │   ├── index.json            ← 特徵庫索引（品項 metadata）
│   │   └── features.npy          ← 特徵向量矩陣（shape: [N, DIM]，float32）
│   └── images/                   ← 驗證記錄（每次按 OK 後生成）
│       ├── {tray_id}.yaml
│       └── {tray_id}.jpg
│
├── utils/
│   ├── __init__.py
│   ├── types.py                  ← Detection, MatchResult dataclass
│   ├── detector.py               ← BaseDetector 抽象類別
│   ├── encoder.py                ← BaseEncoder 抽象類別
│   ├── matcher.py                ← BaseMatcher 抽象類別
│   ├── gallery.py                ← Gallery 特徵庫管理
│   ├── depth_analysis.py         ← DepthAnalyzer, DrawerStateDetector
│   ├── ui.py                     ← UI 輔助元件
│   └── modules/
│       ├── encoder/
│       │   └── resnet34.py       ← ResNet34Encoder（預設）
│       └── matcher/
│           └── top1.py           ← Top1Matcher（預設）
│
├── eminent/
│   └── sensors/
│       └── vision2p5d/
│           ├── __init__.py       ← VideoCapture, MN96100CConfig
│           └── mn96100c.py       ← USBDeviceComm 底層 USB 驅動
│
└── docs/
    ├── DRAWER_MONITOR_README.md  ← 2.5D 傳感器完整技術文件
    └── DEVELOPER_GUIDE.md        ← 本文件
```

---

## 2. 核心模組 API

### BaseDetector（`utils/detector.py`）

```python
class BaseDetector(ABC):
    min_area: int = 0  # 過濾面積下限（子類別可覆寫）

    @abstractmethod
    def forward(self, image: np.ndarray) -> list[Detection]:
        """輸入 BGR 影像，回傳原始偵測結果（不過濾面積）"""

    def __call__(self, image: np.ndarray) -> list[Detection]:
        """forward() 後自動套用 min_area 面積過濾"""

    def detect_and_crop(self, image: np.ndarray) -> list[tuple[Detection, np.ndarray]]:
        """偵測 + 依 bbox 裁切，回傳 [(Detection, crop_image), ...]"""
```

**Detection dataclass**（`utils/types.py`）：

```python
@dataclass
class Detection:
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    mask: np.ndarray                 # 與原圖同尺寸的二值 mask
    confidence: float
```

---

### BaseEncoder（`utils/encoder.py`）

```python
class BaseEncoder(ABC):
    FEATURE_DIM: int  # 子類別必須定義

    @abstractmethod
    def forward(self, image: np.ndarray) -> np.ndarray:
        """輸入裁切後的藥錠影像，回傳特徵向量（任意 float）"""

    def __call__(self, image: np.ndarray) -> np.ndarray:
        """forward() → float32 → L2 normalize，回傳單位向量"""

    def encode_batch(self, images: list[np.ndarray]) -> np.ndarray:
        """批次編碼，回傳 shape (N, FEATURE_DIM) 的 float32 矩陣"""
```

---

### BaseMatcher（`utils/matcher.py`）

```python
class BaseMatcher(ABC):
    def __init__(self, gallery: Gallery):
        self.gallery = gallery

    @abstractmethod
    def forward(self, feature: np.ndarray) -> MatchResult | None:
        """在 gallery 中搜尋最佳比對，回傳結果或 None"""

    def __call__(self, feature: np.ndarray) -> MatchResult | None:
        """空庫防護：gallery 為空時直接回傳 None，否則呼叫 forward()"""
```

**MatchResult dataclass**（`utils/types.py`）：

```python
@dataclass
class MatchResult:
    license_number: str
    name: str
    side: int    # 0 = 正面, 1 = 背面
    score: float
```

---

### Gallery（`utils/gallery.py`）

```python
gallery = Gallery("src/gallery")

gallery.features       # np.ndarray, shape (N, DIM), float32
gallery.get_metadata(idx)  # dict: {license_number, name, side, ...}
gallery.is_empty()     # bool
```

---

## 3. 自訂 Encoder / Matcher

### 新增 Encoder

在 `utils/modules/encoder/` 新建檔案：

```python
# utils/modules/encoder/my_encoder.py
from utils.encoder import BaseEncoder
import numpy as np

class MyEncoder(BaseEncoder):
    FEATURE_DIM = 512

    def __init__(self, model_path: str):
        # 載入模型
        ...

    def forward(self, image: np.ndarray) -> np.ndarray:
        # 前向推理，回傳原始特徵向量（__call__ 會自動 L2 正規化）
        ...
```

### 新增 Matcher

在 `utils/modules/matcher/` 新建檔案：

```python
# utils/modules/matcher/my_matcher.py
from utils.matcher import BaseMatcher
from utils.gallery import Gallery
from utils.types import MatchResult
import numpy as np

class MyMatcher(BaseMatcher):
    def forward(self, feature: np.ndarray) -> MatchResult | None:
        scores = np.dot(self.gallery.features, feature)
        best = int(np.argmax(scores))
        meta = self.gallery.get_metadata(best)
        return MatchResult(
            license_number=meta['license_number'],
            name=meta['name'],
            side=meta['side'],
            score=float(scores[best])
        )
```

### 在 run.py 替換

```python
def create_components(...):
    from utils.modules.encoder.my_encoder import MyEncoder
    from utils.modules.matcher.my_matcher import MyMatcher

    encoder = MyEncoder("src/my_model.pt")
    matcher = MyMatcher(gallery)
    return encoder, matcher
```

> **重要**：更換 Encoder 後，`FEATURE_DIM` 改變，必須在 FY115 用新 Encoder 重新建立 Gallery。
> 舊 Gallery 的 features.npy 維度與新 Encoder 不符會導致比對錯誤。

---

## 4. Gallery 格式

### 目錄結構

```
src/gallery/
├── index.json        ← 品項 metadata 索引
└── features.npy      ← 特徵向量矩陣
```

### index.json 格式

```json
{
  "entries": [
    {
      "license_number": "衛署藥製字第123456號",
      "name": "藥品名稱",
      "side": 0
    },
    ...
  ]
}
```

- `side`：0 = 正面，1 = 背面
- 索引 i 對應 `features.npy` 的第 i 行

### features.npy 格式

- shape：`(N, FEATURE_DIM)`，dtype：`float32`
- 每行為已 L2 正規化的特徵向量（單位向量）
- N 必須與 `index.json["entries"]` 的長度一致

---

## 5. 驗證記錄格式（src/images/）

每次護理師按「OK」完成驗證後，系統在 `src/images/` 儲存兩個檔案：

| 檔案 | 說明 |
|------|------|
| `{tray_id}.yaml` | 驗證記錄（品項、總量、逐藥確認結果） |
| `{tray_id}.jpg` | 拍攝的藥盤原始照片 |

### YAML 記錄結構

```yaml
tray_id: "2026-03-12T10:30:00"
timestamp: "2026-03-12T10:30:00"

summary:
  item_count_correct: true      # 品項數量確認
  total_quantity_correct: true  # 總量顆數確認

items:
  - license_number: "衛署藥製字第123456號"
    name: "藥品名稱"
    side: 0
    score: 0.95
    quantity_correct: true      # 劑量確認
    identity_correct: true      # 品項核對
```
