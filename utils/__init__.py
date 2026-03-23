"""utils/ — FY114 藥物配發驗證系統核心模組

模組總覽：
  encoder   BaseEncoder   特徵編碼器基底類別（__call__ 自動 L2 正規化）
  detector  BaseDetector  藥錠偵測器基底類別（__call__ 自動面積過濾）
  matcher   BaseMatcher   特徵比對器基底類別（__call__ 自動空庫防護）
  gallery   Gallery       特徵庫管理（index.json + features.npy）
  types     Detection     偵測結果資料類別
            MatchResult   比對結果資料類別
  ui        App           Tkinter GUI 應用程式

自訂模型（在 utils/models.py 繼承以下基底類別）：
  class MyDetector(BaseDetector):
      def __init__(self): ...
      def forward(self, image) -> list[Detection]: ...

  class MyEncoder(BaseEncoder):
      FEATURE_DIM = 256
      def __init__(self): ...
      def forward(self, image) -> np.ndarray: ...

  class MyMatcher(BaseMatcher):
      def __init__(self, gallery): super().__init__(gallery)
      def forward(self, feature) -> MatchResult | None: ...
"""

from .types import Detection, MatchResult
from .encoder import BaseEncoder
from .detector import BaseDetector
from .matcher import BaseMatcher
from .gallery import Gallery

__all__ = [
    "Detection",
    "MatchResult",
    "BaseEncoder",
    "BaseDetector",
    "BaseMatcher",
    "Gallery",
]

__version__ = "2.0.0"
