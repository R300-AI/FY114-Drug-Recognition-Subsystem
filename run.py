#!/usr/bin/env python3
"""
run.py — FY114 藥物辨識子系統

此檔案包含三個預設模型實作（可直接替換）：

  YOLODetector   繼承 BaseDetector，使用 ultralytics YOLO 分割模型
  ResNet34Encoder 繼承 BaseEncoder，使用 torchvision ResNet34（512 維）
  Top1Matcher    繼承 BaseMatcher，使用 Top-1 餘弦相似度

替換範例：
  class MyEncoder(BaseEncoder):
      FEATURE_DIM = 256
      def __init__(self): ...
      def forward(self, image): ...  # 回傳 (256,) 原始特徵，不需 L2 正規化

  # 在 create_components() 中替換：
  encoder = MyEncoder()

  # 更換 Encoder 後需在 FY115 重新建立 Gallery。
"""

import argparse
import tkinter as tk
from pathlib import Path

import cv2
import numpy as np

from utils.ui import App
from utils.detector import BaseDetector
from utils.encoder import BaseEncoder
from utils.matcher import BaseMatcher
from utils.gallery import Gallery
from utils.types import Detection, MatchResult


# ============================================================
# 預設偵測器（YOLO 分割模型）
# ============================================================

class YOLODetector(BaseDetector):
    """YOLO 藥錠偵測器（ultralytics YOLO-seg）

    forward() 回傳所有偵測，BaseDetector.__call__ 自動過濾 area < min_area。
    """

    min_area = 100  # 最小有效面積（px²），可繼承後覆寫

    def __init__(self, model_path: str | Path = "src/best.pt", conf: float = 0.25):
        self.model_path = Path(model_path)
        self._conf = conf
        self._model = None  # 延遲載入

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        if not self.model_path.exists():
            print(f"[detector] Model not found: {self.model_path}")
            return False
        try:
            from ultralytics import YOLO
            self._model = YOLO(str(self.model_path), verbose=False)
            return True
        except Exception as e:
            print(f"[detector] Load error: {e}")
            return False

    def forward(self, image: np.ndarray) -> list[Detection]:
        """YOLO 偵測，回傳所有結果（未過濾面積）"""
        if not self._ensure_loaded():
            return []
        try:
            results = self._model.predict(source=image, conf=self._conf, verbose=False)
            if not results or results[0].masks is None:
                return []

            result = results[0]
            h, w = image.shape[:2]
            detections = []

            for idx in range(int(result.masks.data.shape[0])):
                mask = result.masks.data[idx].detach().cpu().numpy()
                mask = (mask > 0.5).astype(np.uint8)
                if mask.shape != (h, w):
                    mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)

                contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if not contours:
                    continue
                cnt = max(contours, key=cv2.contourArea)

                x, y, bw, bh = cv2.boundingRect(cnt)
                detections.append(Detection(
                    bbox=(x, y, x + bw, y + bh),
                    mask=mask,
                    confidence=float(result.boxes.conf[idx]),
                    class_id=int(result.boxes.cls[idx]),
                ))

            detections.sort(key=lambda d: d.area, reverse=True)
            return detections

        except Exception as e:
            print(f"[detector] Predict error: {e}")
            return []


# ============================================================
# 預設編碼器（ResNet34，512 維）
# ============================================================

class ResNet34Encoder(BaseEncoder):
    """ResNet34 特徵編碼器（ImageNet1K 預訓練，512 維）

    forward() 回傳原始特徵向量，BaseEncoder.__call__ 自動 L2 正規化。
    """

    FEATURE_DIM = 512
    INPUT_SIZE  = 224

    def __init__(self):
        self._model     = None
        self._device    = None
        self._transform = None  # 延遲載入

    def _ensure_loaded(self):
        if self._model is not None:
            return
        import torch
        import torchvision.models as models
        from torchvision import transforms

        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        base = models.resnet34(weights=models.ResNet34_Weights.IMAGENET1K_V1)
        self._model = torch.nn.Sequential(*list(base.children())[:-1])
        self._model = self._model.to(self._device).eval()

        self._transform = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((self.INPUT_SIZE, self.INPUT_SIZE)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    def forward(self, image: np.ndarray) -> np.ndarray:
        """BGR 影像 → 512 維原始特徵（不含 L2 正規化，由 BaseEncoder.__call__ 處理）"""
        self._ensure_loaded()
        import torch

        img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        tensor = self._transform(img_rgb).unsqueeze(0).to(self._device)
        with torch.no_grad():
            feat = self._model(tensor).flatten(1)
        return feat.cpu().numpy().astype(np.float32).flatten()


# ============================================================
# 預設比對器（Top-1 餘弦相似度）
# ============================================================

class Top1Matcher(BaseMatcher):
    """Top-1 餘弦相似度比對器

    forward() 接收已 L2-normalized 特徵（由 BaseEncoder.__call__ 保證），
    以 dot-product 計算分數，回傳最高分的 MatchResult 或 None。
    BaseMatcher.__call__ 自動檢查 Gallery 是否已載入。
    """

    def __init__(self, gallery: Gallery, threshold: float = 0.0):
        super().__init__(gallery)
        self.threshold = threshold

    def forward(self, feature: np.ndarray) -> MatchResult | None:
        scores = np.dot(self.gallery.features, feature)
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])

        if best_score < self.threshold:
            return None

        meta = self.gallery.get_metadata(best_idx)
        return MatchResult(
            license_number=meta.get("license_number", ""),
            name=meta.get("name", ""),
            side=meta.get("side", 0),
            score=best_score,
        )


# ============================================================
# 元件工廠
# ============================================================

def create_components(
    gallery_path: str = "src/gallery",
    model_path:   str = "src/best.pt",
) -> tuple[Gallery, BaseEncoder, BaseMatcher, BaseDetector]:
    """建立並回傳預設元件

    替換模型時，修改此函式即可，無需更動 utils/ui.py。
    """
    if not Path(model_path).exists():
        raise FileNotFoundError(f"找不到模型檔案：{model_path}")

    gallery = Gallery(gallery_path)
    gallery.load()
    if gallery.size == 0:
        print(f"[init] Warning: Gallery 為空或載入失敗：{gallery_path}")

    encoder  = ResNet34Encoder()
    matcher  = Top1Matcher(gallery)
    detector = YOLODetector(model_path)
    return gallery, encoder, matcher, detector


# ============================================================
# 主程式入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="FY114 藥物辨識子系統")
    parser.add_argument("--fullscreen", action="store_true",
                        help="全螢幕模式（觸控螢幕）")
    parser.add_argument("--gallery", default="src/gallery",
                        help="Gallery 目錄路徑")
    parser.add_argument("--model", default="src/best.pt",
                        help="YOLO 模型路徑")
    parser.add_argument("--debug", action="store_true",
                        help="除錯模式（Windows/無相機）：跳過相機與 LED，以雜訊圖作為測試輸入")
    args = parser.parse_args()

    if args.debug:
        print("[init] Debug mode ON: camera and LED will be skipped")

    print("[init] Loading components...")
    gallery, encoder, matcher, detector = create_components(
        gallery_path=args.gallery,
        model_path=args.model,
    )

    print("[init] Starting GUI...")
    root = tk.Tk()
    App(root, gallery, encoder, matcher, detector,
        fullscreen=args.fullscreen, debug=args.debug)
    root.mainloop()


if __name__ == "__main__":
    main()
