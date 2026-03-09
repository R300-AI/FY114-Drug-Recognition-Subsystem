"""utils/gallery.py - 特徵庫管理

Gallery 資料結構：
    src/gallery/
    ├── index.json     # 索引檔（metadata）
    ├── features.npy   # 特徵向量 (N, D)
    └── images/        # 藥錠影像（可選）

使用範例：
    from utils.gallery import Gallery
    
    gallery = Gallery("src/gallery")
    gallery.load()
    features = gallery.features
    meta = gallery.get_metadata(idx)
"""

import json
from pathlib import Path

import numpy as np


class Gallery:
    """特徵庫管理
    
    Attributes:
        path: Gallery 目錄路徑
        features: 特徵矩陣，shape=(N, D)
    """
    
    def __init__(self, gallery_path: str | Path = "src/gallery"):
        self.path = Path(gallery_path)
        self._features: np.ndarray | None = None
        self._index: dict | None = None
    
    @property
    def features(self) -> np.ndarray:
        if self._features is None:
            raise RuntimeError("Gallery not loaded. Call load() first.")
        return self._features
    
    @property
    def feature_dim(self) -> int:
        return self.features.shape[1]
    
    @property
    def size(self) -> int:
        if self._index is None:
            return 0
        return len(self._index.get("entries", []))
    
    def is_loaded(self) -> bool:
        return self._features is not None
    
    def load(self) -> bool:
        """載入特徵庫"""
        if self._features is not None:
            return True
        
        index_path = self.path / "index.json"
        features_path = self.path / "features.npy"
        
        if not index_path.exists():
            print(f"[gallery] index.json not found: {index_path}")
            return False
        
        if not features_path.exists():
            print(f"[gallery] features.npy not found: {features_path}")
            return False
        
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                self._index = json.load(f)
            self._features = np.load(features_path).astype(np.float32)
            return True
        except Exception as e:
            print(f"[gallery] Error: {e}")
            return False
    
    def get_metadata(self, idx: int) -> dict:
        """取得指定索引的 metadata"""
        if self._index is None:
            raise RuntimeError("Gallery not loaded. Call load() first.")
        entries = self._index.get("entries", [])
        if idx < 0 or idx >= len(entries):
            raise IndexError(f"Index {idx} out of range")
        return entries[idx]
    
    def search(self, query_feature: np.ndarray, top_k: int = 1) -> list[tuple[int, float]]:
        """搜尋最相似的條目"""
        if self._features is None:
            raise RuntimeError("Gallery not loaded. Call load() first.")
        
        scores = np.dot(self._features, query_feature)
        
        if top_k >= len(scores):
            top_indices = np.argsort(scores)[::-1]
        else:
            top_indices = np.argpartition(scores, -top_k)[-top_k:]
            top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
        
        return [(int(idx), float(scores[idx])) for idx in top_indices[:top_k]]
