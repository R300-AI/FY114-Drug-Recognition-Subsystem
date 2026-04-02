"""utils/models_gpu.py — GPU 加速版本的 YOLO 偵測器

自動檢測並使用可用的 GPU 加速（DirectML/CUDA/ROCm）

安裝需求：
  - DirectML (AMD/Intel iGPU): pip install torch-directml
  - CUDA (NVIDIA GPU): 預設支援
  - ROCm (AMD GPU Linux): 需安裝 ROCm PyTorch
"""

from pathlib import Path

import cv2
import numpy as np

from .detector import BaseDetector
from .types import Detection


class YOLODetectorGPU(BaseDetector):
    """GPU 加速的 YOLO 偵測器
    
    自動選擇最佳可用設備：DirectML > CUDA > ROCm > CPU
    """

    min_area = 100

    def __init__(self, model_path: str | Path = "src/best.pt", conf: float = 0.25):
        self.model_path = Path(model_path)
        self._conf = conf
        self._model = None
        self._device = None
        self._device_name = "CPU"
        
        # 自動檢測並設定設備
        self._setup_device()

    def _setup_device(self):
        """自動檢測並設定最佳 GPU 設備"""
        import torch
        
        # 優先順序：DirectML > CUDA > ROCm > CPU
        
        # 1. DirectML (AMD/Intel iGPU on Windows)
        try:
            import torch_directml
            if torch_directml.is_available():
                self._device = torch_directml.device()
                self._device_name = f"DirectML ({torch_directml.device_name(0)})"
                print(f"[detector] 使用 DirectML: {torch_directml.device_name(0)}")
                return
        except ImportError:
            pass
        except Exception as e:
            print(f"[detector] DirectML 初始化失敗: {e}")
        
        # 2. CUDA (NVIDIA GPU)
        if torch.cuda.is_available():
            self._device = torch.device('cuda:0')
            self._device_name = f"CUDA ({torch.cuda.get_device_name(0)})"
            print(f"[detector] 使用 CUDA: {torch.cuda.get_device_name(0)}")
            return
        
        # 3. ROCm (AMD GPU on Linux)
        if hasattr(torch, 'hip') and torch.hip.is_available():
            self._device = torch.device('hip:0')
            self._device_name = f"ROCm ({torch.hip.get_device_name(0)})"
            print(f"[detector] 使用 ROCm: {torch.hip.get_device_name(0)}")
            return
        
        # 4. Fallback: CPU
        self._device = torch.device('cpu')
        self._device_name = "CPU"
        print(f"[detector] ⚠️  無可用 GPU，回退至 CPU")

    def _ensure_loaded(self) -> bool:
        """載入 YOLO 模型並移至 GPU"""
        if self._model is not None:
            return True
        
        if not self.model_path.exists():
            print(f"[detector] 模型不存在: {self.model_path}")
            return False
        
        try:
            from ultralytics import YOLO
            import torch
            
            # 載入模型
            self._model = YOLO(str(self.model_path), verbose=False)
            
            # 移至指定設備
            if self._device is not None:
                # ultralytics 會自動處理 device，但我們可以預先指定
                print(f"[detector] 模型載入完成，設備: {self._device_name}")
            
            return True
            
        except Exception as e:
            print(f"[detector] 模型載入失敗: {e}")
            return False

    def forward(self, image: np.ndarray) -> list[Detection]:
        """使用 GPU 執行 YOLO 推論"""
        if not self._ensure_loaded():
            return []
        
        try:
            # ultralytics 的 predict 方法支援 device 參數
            device_str = self._get_device_string()
            
            results = self._model.predict(
                source=image,
                conf=self._conf,
                verbose=False,
                device=device_str  # 'cuda', 'cpu', 或 DirectML device
            )
            
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
            print(f"[detector] 推論失敗: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _get_device_string(self) -> str:
        """將 device 物件轉換為 ultralytics 可用的字串"""
        if self._device is None:
            return 'cpu'
        
        device_str = str(self._device)
        
        # DirectML 裝置需要特殊處理
        if 'privateuseone' in device_str or hasattr(self._device, 'type'):
            # 對於 DirectML，ultralytics 可能不直接支援
            # 我們需要檢查 ultralytics 版本
            try:
                import torch_directml
                # 嘗試直接傳遞 device 物件
                return self._device
            except:
                # Fallback to CPU if DirectML not properly integrated
                return 'cpu'
        
        return device_str

    def get_device_info(self) -> dict:
        """取得設備資訊（用於 API /health endpoint）"""
        return {
            "device": self._device_name,
            "backend": "GPU" if self._device != "cpu" else "CPU"
        }
