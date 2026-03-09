"""utils/matcher.py — 特徵比對器基底類別

設計理念（參照 PyTorch nn.Module）：
  使用者只需定義 forward()，其餘由基底類別自動處理。

後端自動處理（__call__）：
  1. 檢查 Gallery 是否已載入且非空（保護）
  2. 呼叫 forward() 執行比對邏輯

使用範例：
    from utils.matcher import BaseMatcher
    from utils.types import MatchResult
    import numpy as np

    class MyMatcher(BaseMatcher):
        def __init__(self, gallery, threshold=0.5):
            super().__init__(gallery)
            self.threshold = threshold

        def forward(self, feature: np.ndarray) -> MatchResult | None:
            # feature 已由 BaseEncoder.__call__ 保證為 L2-normalized float32
            # 透過 self.gallery 存取特徵庫
            scores = np.dot(self.gallery.features, feature)
            ...

    matcher = MyMatcher(gallery)
    result = matcher(feature)   # MatchResult 或 None
"""

from abc import ABC, abstractmethod

import numpy as np

from .gallery import Gallery
from .types import MatchResult


class BaseMatcher(ABC):
    """特徵比對器基底類別

    子類別必須：
      - 實作 forward(feature) → MatchResult | None

    可選覆寫：
      - __init__(gallery, ...) — 需呼叫 super().__init__(gallery)
    """

    def __init__(self, gallery: Gallery):
        """初始化比對器，注入 Gallery

        Args:
            gallery: 已載入（或待載入）的 Gallery 實例
        """
        self.gallery = gallery

    @abstractmethod
    def forward(self, feature: np.ndarray) -> MatchResult | None:
        """比對特徵向量

        Args:
            feature: L2-normalized 特徵向量 shape=(D,) float32，
                     由 BaseEncoder.__call__ 保證。
                     透過 self.gallery 存取特徵庫。

        Returns:
            最佳比對的 MatchResult，或 None（未達閾值 / 無結果）
        """
        ...

    def __call__(self, feature: np.ndarray) -> MatchResult | None:
        """後端自動處理：空庫防護 → forward

        Returns:
            MatchResult 或 None
        """
        if not self.gallery.is_loaded() or self.gallery.size == 0:
            return None
        return self.forward(feature)


__all__ = ["BaseMatcher"]
