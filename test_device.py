#!/usr/bin/env python3
"""test_device.py — 測試 DirectML 設備檢測

快速驗證 torch-directml 是否正確安裝並可偵測到 GPU
"""

print("測試 DirectML 設備檢測...")
print("=" * 60)

# 檢測 DirectML
import torch

device = "cpu"
try:
    import torch_directml
    device = torch_directml.device()
    print(f"✓ DirectML GPU detected: {device}")
    print(f"  Device count: {torch_directml.device_count()}")
    if torch_directml.device_count() > 0:
        print(f"  Device name: {torch_directml.device_name(0)}")
except ImportError:
    print("✗ torch-directml not installed")
    print("  Install: pip install torch-directml")
except Exception as e:
    print(f"✗ DirectML unavailable: {e}")

print("=" * 60)
print(f"\nFinal device: {device}")

# 測試簡單的 tensor 操作
print("\n測試 tensor 操作...")
try:
    import torch
    x = torch.randn(3, 3).to(device)
    y = x + 1
    print(f"✓ Tensor operation successful")
    print(f"  Shape: {y.shape}, Device: {y.device}")
except Exception as e:
    print(f"✗ Tensor operation failed: {e}")
