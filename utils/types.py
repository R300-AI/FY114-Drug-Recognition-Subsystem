"""utils/types.py - 資料型別定義

此模組定義系統中使用的資料類別：
- Detection: YOLO 偵測結果
- MatchResult: 特徵比對結果
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class Detection:
    """YOLO 偵測結果
    
    Attributes:
        bbox: 邊界框 (x1, y1, x2, y2)
        mask: 二值遮罩，shape=(H, W)
        confidence: 偵測信心度 [0, 1]
        class_id: 類別 ID
    """
    bbox: tuple[int, int, int, int]
    mask: np.ndarray
    confidence: float
    class_id: int = 0
    
    @property
    def area(self) -> int:
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1) * (y2 - y1)
    
    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)


@dataclass
class MatchResult:
    """特徵比對結果
    
    Attributes:
        license_number: 藥證字號
        name: 藥品名稱
        side: 正反面 (0=正面, 1=反面)
        score: 相似度分數 [0, 1]
    """
    license_number: str
    name: str
    side: int
    score: float
    
    def __repr__(self) -> str:
        side_str = "正面" if self.side == 0 else "反面"
        return f"MatchResult({self.license_number}, {self.name}, {side_str}, {self.score:.4f})"
