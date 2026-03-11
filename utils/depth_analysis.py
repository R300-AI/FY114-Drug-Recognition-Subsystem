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
        
        Args:
            intensity_values: numpy array，8-bit 像素值（反射光強度）
            
        Returns:
            相對深度指標（值越大表示距離越遠）
        """
        # 避免除以零
        intensity_values = np.clip(intensity_values, 1, 255)
        
        # 根據公式：相對距離 ∝ 1 / √(反射光強度)
        relative_depth = 1.0 / np.sqrt(intensity_values.astype(np.float32))
        
        return relative_depth
    
    def calculate_depth_metrics(self, intensity_roi, use_transform=False):
        """
        計算深度指標
        
        Args:
            intensity_roi: numpy array，ROI 區域的像素值
            use_transform: 是否使用深度轉換（根據物理特性）
            
        Returns:
            dict，包含各種深度統計指標
        """
        if use_transform:
            # 使用物理模型轉換
            depth_values = self.intensity_to_relative_depth(intensity_roi)
        else:
            # 直接使用強度值（較簡單，但不符合物理特性）
            depth_values = intensity_roi.astype(np.float32)
        
        metrics = {
            'mean': np.mean(depth_values),
            'median': np.median(depth_values),
            'std': np.std(depth_values),
            'min': np.min(depth_values),
            'max': np.max(depth_values),
            'percentile_10': np.percentile(depth_values, 10),
            'percentile_90': np.percentile(depth_values, 90),
            'range': np.max(depth_values) - np.min(depth_values),
        }
        
        # 添加原始強度統計（用於參考）
        metrics['intensity_mean'] = np.mean(intensity_roi)
        metrics['intensity_median'] = np.median(intensity_roi)
        
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
    抽屜狀態偵測器
    使用多級濾波和狀態機來提高判斷穩定性，有效抑制噪聲
    """
    
    def __init__(self, threshold_open, threshold_closed, 
                 filter_window=10, min_state_duration=8,
                 ema_alpha=0.3, use_median_filter=True,
                 state_lock_frames=15):
        """
        初始化狀態偵測器
        
        Args:
            threshold_open: 開啟狀態閾值（depth_metric > 此值為開啟）
            threshold_closed: 閉合狀態閾值（depth_metric < 此值為閉合）
            filter_window: 移動平均/中值濾波窗口大小（建議 8-15）
            min_state_duration: 狀態變更前需要持續的最小幀數（建議 6-10）
            ema_alpha: 指數移動平均的平滑係數（0.1-0.5，越小越平滑）
            use_median_filter: 是否使用中值濾波去除尖峰噪聲
            state_lock_frames: 狀態變更後的鎖定幀數（防止快速回跳）
        """
        self.threshold_open = threshold_open
        self.threshold_closed = threshold_closed
        self.filter_window = filter_window
        self.min_state_duration = min_state_duration
        self.ema_alpha = ema_alpha
        self.use_median_filter = use_median_filter
        self.state_lock_frames = state_lock_frames
        
        # 數據歷史（使用 deque 提高效率）
        self.raw_history = deque(maxlen=filter_window)
        self.filtered_history = deque(maxlen=filter_window)
        
        # 狀態追蹤
        self.current_state = "未知"
        self.state_counter = 0
        self.pending_state = None
        self.state_lock_counter = 0  # 狀態鎖定計數器
        
        # EMA 狀態
        self.ema_value = None
        
    def update(self, depth_value):
        """
        更新狀態（多級濾波 + 增強狀態穩定）
        
        Args:
            depth_value: 當前深度指標值
            
        Returns:
            str: 當前抽屜狀態
        """
        # 第一級：原始數據記錄
        self.raw_history.append(depth_value)
        
        # 第二級：中值濾波（去除尖峰噪聲）
        if self.use_median_filter and len(self.raw_history) >= 3:
            # 使用最近 3-5 個值做中值濾波
            recent_values = list(self.raw_history)[-min(5, len(self.raw_history)):]
            median_filtered = np.median(recent_values)
        else:
            median_filtered = depth_value
        
        # 第三級：指數移動平均（EMA，平滑長期趨勢）
        if self.ema_value is None:
            self.ema_value = median_filtered
        else:
            self.ema_value = (self.ema_alpha * median_filtered + 
                             (1 - self.ema_alpha) * self.ema_value)
        
        # 第四級：移動平均（最終平滑）
        self.filtered_history.append(self.ema_value)
        filtered_value = np.mean(list(self.filtered_history))
        
        # 狀態鎖定機制（剛變更狀態後鎖定一段時間）
        if self.state_lock_counter > 0:
            self.state_lock_counter -= 1
            return self.current_state  # 鎖定期間不改變狀態
        
        # 根據閾值判斷新狀態
        # 物理原理：抽屉開啟（遠）→ 強度低 → depth_metric 高
        #           抽屉閉合（近）→ 強度高 → depth_metric 低
        if filtered_value > self.threshold_open:
            new_state = "完全開啟"  # 高值，距離遠
        elif filtered_value > self.threshold_closed:
            new_state = "閉合中"  # 中間值
        else:
            new_state = "完全閉合"  # 低值，距離近
        
        # 增強的狀態變更邏輯（需要持續一定幀數才確認變更）
        if new_state != self.current_state:
            if self.pending_state == new_state:
                self.state_counter += 1
                if self.state_counter >= self.min_state_duration:
                    # 確認狀態變更
                    old_state = self.current_state
                    self.current_state = new_state
                    self.state_counter = 0
                    self.pending_state = None
                    # 啟動狀態鎖定（防止快速回跳）
                    self.state_lock_counter = self.state_lock_frames
                    print(f"[狀態變更] {old_state} → {new_state} (濾波值: {filtered_value:.4f})")
            else:
                # 新的待處理狀態
                self.pending_state = new_state
                self.state_counter = 1
        else:
            # 狀態維持不變，重置待處理狀態
            self.pending_state = None
            self.state_counter = 0
        
        return self.current_state
    
    def get_filtered_value(self):
        """獲取當前濾波後的值（用於調試）"""
        if len(self.filtered_history) > 0:
            return np.mean(list(self.filtered_history))
        return None
    
    def update_thresholds(self, threshold_open, threshold_closed):
        """動態更新閾值"""
        self.threshold_open = threshold_open
        self.threshold_closed = threshold_closed
    
    def reset(self):
        """重置狀態偵測器"""
        self.raw_history.clear()
        self.filtered_history.clear()
        self.current_state = "未知"
        self.state_counter = 0
        self.pending_state = None
        self.state_lock_counter = 0
        self.ema_value = None


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
