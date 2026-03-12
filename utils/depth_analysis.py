"""
Advanced Depth Calculation Utilities for MN96100C 2.5D Sensor
提供更準確的深度計算方法和數據分析工具
"""

import numpy as np
import csv
from datetime import datetime
from collections import deque


class DepthAnalyzer:
    """
    深度分析器
    
    根據 MN96100C 2.5D sensor 特性進行深度計算：
    - 像素值 = 反射光強度
    - 相對距離 ∝ 1 / √(反射光強度)
    """
    
    def __init__(self):
        """初始化深度分析器"""
        self.calibration_baseline = None  # 校準基準值
        self.calibration_distance = None  # 校準距離（如果有絕對測量）
        
    def intensity_to_relative_depth(self, intensity_values):
        """
        將反射光強度轉換為相對深度指標
        
        基於物理模型: 相對距離 ∝ 1 / √(反射光強度)
        歸一化到 [0, 1] 範圍:
        - 0.0 = 最近距離（intensity = 255，高反射，紅色）
        - 1.0 = 最遠距離（intensity = 1，低反射，藍色）
        
        Args:
            intensity_values: numpy array，8-bit 像素值（反射光強度）
            
        Returns:
            歸一化深度指標，範圍[0, 1]（值越大表示距離越遠）
        """
        # 避免除以零，限制在有效範圍
        intensity_values = np.clip(intensity_values, 1, 255).astype(np.float32)
        
        # 物理模型計算：depth ∝ 1/√intensity
        raw_depth = 1.0 / np.sqrt(intensity_values)
        
        # 計算理論極限值（用於歸一化）
        depth_at_max_intensity = 1.0 / np.sqrt(255.0)  # ≈ 0.0626（最近距離）
        depth_at_min_intensity = 1.0 / np.sqrt(1.0)     # = 1.0（最遠距離）
        
        # 歸一化到 [0, 1]：將原始範圍 [0.0626, 1.0] 映射到 [0, 1]
        normalized_depth = (raw_depth - depth_at_max_intensity) / \
                           (depth_at_min_intensity - depth_at_max_intensity)
        
        # 確保在有效範圍內（防止浮點誤差）
        normalized_depth = np.clip(normalized_depth, 0.0, 1.0)
        
        return normalized_depth
    
    def calculate_depth_metrics(self, intensity_roi):
        """
        計算深度指標

        核心指標：
        - intensity_mean: ROI 平均強度值 (0-255)，高=近=閉合，低=遠=開啟
        - relative_distance: 1/√intensity_mean，正比於相對距離，高=遠=開啟，低=近=閉合

        Args:
            intensity_roi: numpy array，ROI 區域的像素值 (0-255)

        Returns:
            dict，包含各種深度統計指標
        """
        intensity_mean = np.mean(intensity_roi)

        # 相對距離指標：1/√intensity，正比於實際距離
        # intensity 高(255) → relative_distance ≈ 0.063（近）
        # intensity 低(1)   → relative_distance = 1.0（遠）
        clipped = np.clip(intensity_mean, 1, 255)
        relative_distance = 1.0 / np.sqrt(clipped)

        metrics = {
            'mean': intensity_mean,            # 平均強度值 (0-255)
            'relative_distance': relative_distance,  # 相對距離指標 (0.063-1.0)
            'median': np.median(intensity_roi),
            'std': np.std(intensity_roi),
            'min': np.min(intensity_roi),
            'max': np.max(intensity_roi),
            'percentile_10': np.percentile(intensity_roi, 10),
            'percentile_90': np.percentile(intensity_roi, 90),
            'range': np.max(intensity_roi) - np.min(intensity_roi),
        }

        return metrics
    
    def set_calibration_baseline(self, intensity_roi, distance=None):
        """
        設定校準基準
        
        Args:
            intensity_roi: 校準時的 ROI 像素值
            distance: 如果有絕對距離測量（例如用 ToF），可以提供
        """
        self.calibration_baseline = np.mean(intensity_roi)
        self.calibration_distance = distance
        
        print(f"校準基準已設定：強度 = {self.calibration_baseline:.2f}", end='')
        if distance is not None:
            print(f"，距離 = {distance:.2f} mm")
        else:
            print()
    
    def estimate_relative_distance_change(self, intensity_roi):
        """
        估算相對於校準基準的距離變化
        
        Args:
            intensity_roi: 當前的 ROI 像素值
            
        Returns:
            相對距離變化比例（1.0 = 校準位置）
        """
        if self.calibration_baseline is None:
            print("警告：未設定校準基準")
            return None
        
        current_intensity = np.mean(intensity_roi)
        
        # 根據公式：d ∝ 1/√I
        # d2/d1 = √(I1/I2)
        relative_distance = np.sqrt(self.calibration_baseline / current_intensity)
        
        return relative_distance


class DataLogger:
    """數據記錄器，用於導出時間序列數據"""
    
    def __init__(self, filename=None):
        """
        初始化數據記錄器
        
        Args:
            filename: CSV 檔案名稱，如果為 None 則自動生成時間戳檔名
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"drawer_monitor_log_{timestamp}.csv"
        
        self.filename = filename
        self.data_buffer = []
        self.is_logging = False
        
    def start_logging(self):
        """開始記錄"""
        self.is_logging = True
        self.data_buffer = []
        print(f"開始記錄數據到: {self.filename}")
    
    def stop_logging(self):
        """停止記錄並寫入檔案"""
        self.is_logging = False
        self.write_to_csv()
        print(f"數據已儲存到: {self.filename}")
    
    def log_frame(self, timestamp, metrics, drawer_status):
        """
        記錄單一幀的數據
        
        Args:
            timestamp: 時間戳（秒）
            metrics: 深度指標字典
            drawer_status: 抽屜狀態字串
        """
        if not self.is_logging:
            return
        
        data_point = {
            'timestamp': timestamp,
            'drawer_status': drawer_status,
            **metrics
        }
        
        self.data_buffer.append(data_point)
    
    def write_to_csv(self):
        """將緩衝區數據寫入 CSV 檔案"""
        if not self.data_buffer:
            print("沒有數據可寫入")
            return
        
        # 獲取所有欄位名稱
        fieldnames = list(self.data_buffer[0].keys())
        
        try:
            with open(self.filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.data_buffer)
            
            print(f"成功寫入 {len(self.data_buffer)} 筆數據")
            
        except Exception as e:
            print(f"寫入 CSV 失敗: {str(e)}")


class DrawerStateDetector:
    """
    抽屜狀態偵測器（最簡化版本）
    直接基於 intensity 判斷，不做複雜轉換
    """
    
    def __init__(self, threshold_open, threshold_closed, min_state_duration=5):
        """
        初始化狀態偵測器
        
        核心概念：直接使用 intensity_mean (0-255)
        - intensity 越高 → 距離越近 → 抽屜關閉
        - intensity 越低 → 距離越遠 → 抽屜打開
        
        Args:
            threshold_closed: 閉合狀態閾值 (intensity > 此值為閉合) - 應為較高值（如150）
            threshold_open: 開啟狀態閾值 (intensity < 此值為開啟) - 應為較低值（妀80）
            min_state_duration: 狀態變更前需要持續的最小幀數（防止瞬間抖動）
        
        閾值邏輯：threshold_closed > threshold_open
        """
        # 驗證閾值順序
        if threshold_closed <= threshold_open:
            raise ValueError(
                f"閾值順序錯誤: threshold_closed({threshold_closed}) 必須大於 "
                f"threshold_open({threshold_open})。\n"
                f"物理意義: closed=高intensity(近距離), open=低intensity(遠距離)"
            )
        
        self.threshold_open = threshold_open
        self.threshold_closed = threshold_closed
        self.min_state_duration = min_state_duration
        
        # 狀態追蹤
        self.current_state = "未知"
        self.state_counter = 0
        self.pending_state = None
        
    def update(self, intensity_value):
        """
        更新狀態（基於 intensity 值）
        
        Args:
            intensity_value: 當前 intensity 平均值 (0-255)
            
        Returns:
            str: 當前抽屜狀態
        """
        # 根據閾值判斷新狀態
        # intensity 高 = 近距離 = 抽屜關閉
        # intensity 低 = 遠距離 = 抽屜打開
        if intensity_value > self.threshold_closed:
            new_state = "完全閉合"
        elif intensity_value > self.threshold_open:
            new_state = "閉合中"
        else:
            new_state = "完全開啟"
        
        # 狀態變更邏輯（需要持續一定幀數才確認變更）
        if new_state != self.current_state:
            if self.pending_state == new_state:
                self.state_counter += 1
                if self.state_counter >= self.min_state_duration:
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
    
    def update_thresholds(self, threshold_open, threshold_closed):
        """動態更新閾值"""
        self.threshold_open = threshold_open
        self.threshold_closed = threshold_closed
    
    def reset(self):
        """重置狀態偵測器"""
        self.current_state = "未知"
        self.state_counter = 0
        self.pending_state = None


# 使用範例
if __name__ == "__main__":
    # 測試深度分析器
    analyzer = DepthAnalyzer()
    
    # 模擬數據：遠處（低強度）vs 近處（高強度）
    far_intensity = np.full((80, 80), 40)  # 遠處地板
    near_intensity = np.full((80, 80), 160)  # 近處抽屜
    
    print("=== 深度分析測試 ===")
    print("\n遠處（地板）:")
    far_metrics = analyzer.calculate_depth_metrics(far_intensity, use_transform=True)
    print(f"  強度平均: {far_metrics['intensity_mean']:.2f}")
    print(f"  深度指標: {far_metrics['mean']:.4f}")
    
    print("\n近處（抽屜）:")
    near_metrics = analyzer.calculate_depth_metrics(near_intensity, use_transform=True)
    print(f"  強度平均: {near_metrics['intensity_mean']:.2f}")
    print(f"  深度指標: {near_metrics['mean']:.4f}")
    
    # 設定校準基準
    print("\n=== 校準測試 ===")
    analyzer.set_calibration_baseline(far_intensity, distance=300.0)
    
    rel_dist = analyzer.estimate_relative_distance_change(near_intensity)
    print(f"相對距離變化: {rel_dist:.2f}x (1.0 = 校準位置)")
    print(f"估算距離: {300.0 / rel_dist:.2f} mm")
