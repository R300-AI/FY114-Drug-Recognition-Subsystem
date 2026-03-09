"""utils/detector.py — 藥錠偵測器基底類別

設計理念（參照 PyTorch nn.Module）：
  使用者只需定義 __init__ 與 forward()，其餘由基底類別自動處理。

後端自動處理（__call__）：
  1. 呼叫 forward() 取得所有偵測結果
  2. 過濾 area < min_area 的偵測（雜訊）

使用範例：
    from utils.detector import BaseDetector
    from utils.types import Detection
    import numpy as np

    class MyDetector(BaseDetector):
        min_area = 200   # 可覆寫最小面積閾值

        def __init__(self, model_path):
            pass  # 載入模型

        def forward(self, image: np.ndarray) -> list[Detection]:
            # 回傳所有偵測結果（不需自行過濾面積）
            ...

    det = MyDetector("model.pt")
    detections = det(image)   # 已自動過濾小偵測
"""

from abc import ABC, abstractmethod

import cv2
import numpy as np

from .types import Detection


class BaseDetector(ABC):
    """藥錠偵測器基底類別

    子類別必須：
      - 實作 __init__()
      - 實作 forward(image) → list[Detection]（回傳未過濾結果）

    可選覆寫：
      - min_area: int — 最小有效面積（預設 100 px²）
    """

    min_area: int = 100  # 子類別可覆寫

    @abstractmethod
    def __init__(self):
        """載入模型"""
        ...

    @abstractmethod
    def forward(self, image: np.ndarray) -> list[Detection]:
        """偵測影像中的藥錠

        Args:
            image: BGR 影像，shape=(H, W, 3)

        Returns:
            Detection 列表（包含所有偵測，不需自行過濾面積）。
            __call__ 會自動過濾 area < min_area 的項目。
        """
        ...

    def __call__(self, image: np.ndarray) -> list[Detection]:
        """後端自動處理：forward → 過濾 area < min_area

        Returns:
            已過濾的 Detection 列表
        """
        return [d for d in self.forward(image) if d.area >= self.min_area]

    def detect_and_crop(
        self,
        image: np.ndarray,
        padding: int = 0,
    ) -> list[tuple[Detection, np.ndarray]]:
        """便利方法：偵測後直接裁切每個藥錠影像

        Args:
            image: BGR 影像
            padding: bbox 向外擴充的像素數

        Returns:
            list of (Detection, cropped_BGR)，已套用 min_area 過濾
        """
        h, w = image.shape[:2]
        out = []
        for det in self(image):
            x1, y1, x2, y2 = det.bbox
            x1 = max(0, x1 - padding)
            y1 = max(0, y1 - padding)
            x2 = min(w, x2 + padding)
            y2 = min(h, y2 + padding)
            out.append((det, image[y1:y2, x1:x2].copy()))
        return out


__all__ = ["BaseDetector"]
