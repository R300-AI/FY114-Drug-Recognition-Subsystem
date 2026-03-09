"""utils/encoder.py — 特徵編碼器基底類別

設計理念（參照 PyTorch nn.Module）：
  使用者只需定義 __init__ 與 forward()，其餘由基底類別自動處理。

後端自動處理（__call__）：
  1. 呼叫 forward() 取得原始特徵向量
  2. 轉型為 float32
  3. L2 正規化（norm > 1e-6 才執行，避免零向量 NaN）

使用範例：
    from utils.encoder import BaseEncoder
    import numpy as np

    class MyEncoder(BaseEncoder):
        FEATURE_DIM = 256

        def __init__(self):
            pass  # 載入模型

        def forward(self, image: np.ndarray) -> np.ndarray:
            # image: (H, W, 3) BGR
            # 回傳原始特徵向量 (256,)，不需自行 L2 正規化
            ...

    enc = MyEncoder()
    feat = enc(image)   # (256,) float32, L2-normalized
"""

from abc import ABC, abstractmethod

import numpy as np


class BaseEncoder(ABC):
    """特徵編碼器基底類別

    子類別必須：
      - 宣告 FEATURE_DIM: int
      - 實作 __init__()
      - 實作 forward(image) → np.ndarray，回傳原始特徵（不需 L2 正規化）
    """

    FEATURE_DIM: int  # 子類別宣告，用於 __call__ 維度驗證

    @abstractmethod
    def __init__(self):
        """載入模型權重、初始化預處理管線"""
        ...

    @abstractmethod
    def forward(self, image: np.ndarray) -> np.ndarray:
        """將影像編碼為特徵向量

        Args:
            image: BGR 影像，shape=(H, W, 3)

        Returns:
            特徵向量 shape=(FEATURE_DIM,)。
            不需自行 L2 正規化，__call__ 會自動處理。
        """
        ...

    def __call__(self, image: np.ndarray) -> np.ndarray:
        """後端自動處理：forward → float32 → L2 正規化

        Returns:
            L2 正規化特徵向量 shape=(FEATURE_DIM,) float32
        """
        feat = self.forward(image).astype(np.float32)
        norm = np.linalg.norm(feat)
        if norm > 1e-6:
            feat = feat / norm
        return feat

    def encode_batch(self, images: list[np.ndarray]) -> np.ndarray:
        """批次編碼（每張影像皆經過 __call__ L2 正規化）

        Args:
            images: BGR 影像列表

        Returns:
            特徵矩陣 shape=(N, FEATURE_DIM) float32
        """
        return np.stack([self(img) for img in images])


__all__ = ["BaseEncoder"]
