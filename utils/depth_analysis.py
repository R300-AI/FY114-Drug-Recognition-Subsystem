"""
Depth Calculation Utilities for MN96100C 2.5D Sensor
"""

import numpy as np


class DepthAnalyzer:
    """
    深度分析器

    根據 MN96100C 2.5D sensor 特性進行深度計算：
    - 像素值 = 反射光強度
    - intensity 越高 → 距離越近 → 抽屜關閉
    - intensity 越低 → 距離越遠 → 抽屜打開
    """

    def calculate_depth_metrics(self, intensity_roi) -> dict:
        """
        計算深度指標

        核心指標：
        - mean: ROI 平均強度值 (0-255)，高=近=閉合，低=遠=開啟

        Args:
            intensity_roi: numpy array，ROI 區域的像素值 (0-255)

        Returns:
            dict，包含各種深度統計指標
        """
        intensity_mean = np.mean(intensity_roi)
        clipped = np.clip(intensity_mean, 1, 255)

        return {
            'mean':            intensity_mean,
            'relative_distance': 1.0 / np.sqrt(clipped),
            'median':          np.median(intensity_roi),
            'std':             np.std(intensity_roi),
            'min':             np.min(intensity_roi),
            'max':             np.max(intensity_roi),
            'percentile_10':   np.percentile(intensity_roi, 10),
            'percentile_90':   np.percentile(intensity_roi, 90),
            'range':           np.max(intensity_roi) - np.min(intensity_roi),
        }


class DrawerStateDetector:
    """
    抽屜狀態偵測器

    直接基於 intensity 判斷，加防抖（需持續 min_state_duration 幀才確認狀態變更）。

    閾值邏輯：threshold_closed > threshold_open
    
    開啟判斷：連續 min_open_duration 幀 intensity < threshold_open 即判斷開啟
    關閉判斷：連續 min_close_duration 幀 intensity > threshold_closed 即判斷關閉
    """

    def __init__(
        self,
        threshold_open: float,
        threshold_closed: float,
        min_state_duration: int = 5,
        min_open_duration: int = 3,
        min_close_duration: int = 5,
    ):
        """
        Args:
            threshold_closed: intensity > 此值 → 完全閉合（應為較高值，如 150）
            threshold_open:   intensity < 此值 → 完全開啟（應為較低值，如 80）
            min_state_duration: 狀態變更前需持續的最小幀數（向下相容，已棄用）
            min_open_duration: 開啟狀態變更前需持續的最小幀數（預設 3）
            min_close_duration: 關閉狀態變更前需持續的最小幀數（預設 5）
        """
        if threshold_closed <= threshold_open:
            raise ValueError(
                f"閾值順序錯誤: threshold_closed({threshold_closed}) 必須大於 "
                f"threshold_open({threshold_open})"
            )

        self.threshold_open   = threshold_open
        self.threshold_closed = threshold_closed
        self.min_state_duration = min_state_duration  # 向下相容
        self.min_open_duration = min_open_duration
        self.min_close_duration = min_close_duration

        self.current_state = "未知"
        self.state_counter = 0
        self.pending_state = None

    def update(self, intensity_value: float) -> str:
        """
        更新狀態（基於 intensity 值）

        Args:
            intensity_value: 當前 intensity 平均值 (0-255)

        Returns:
            str: 當前抽屜狀態（完全閉合 / 閉合中 / 完全開啟 / 未知）
        """
        if intensity_value > self.threshold_closed:
            new_state = "完全閉合"
        elif intensity_value > self.threshold_open:
            new_state = "閉合中"
        else:
            new_state = "完全開啟"

        if new_state != self.current_state:
            if self.pending_state == new_state:
                self.state_counter += 1
                # 根據目標狀態選擇不同的持續幀數要求
                if new_state == "完全開啟":
                    required_duration = self.min_open_duration
                elif new_state == "完全閉合":
                    required_duration = self.min_close_duration
                else:
                    required_duration = self.min_state_duration
                
                if self.state_counter >= required_duration:
                    old_state = self.current_state
                    self.current_state = new_state
                    self.state_counter = 0
                    self.pending_state = None
                    print(f"[狀態變更] {old_state} -> {new_state} (intensity: {intensity_value:.1f})")
            else:
                self.pending_state = new_state
                self.state_counter = 1
        else:
            self.pending_state = None
            self.state_counter = 0

        return self.current_state

    def update_thresholds(self, threshold_open: float, threshold_closed: float):
        """動態更新閾值"""
        self.threshold_open   = threshold_open
        self.threshold_closed = threshold_closed

    def reset(self):
        """重置狀態偵測器"""
        self.current_state = "未知"
        self.state_counter = 0
        self.pending_state = None
