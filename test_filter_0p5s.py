"""
測試 0.5 秒周期噪聲的濾波效果
模擬實際環境中的高頻週期性波動
"""
import numpy as np
import matplotlib.pyplot as plt
from utils.depth_analysis import DrawerStateDetector

print("=== 測試 0.5 秒周期噪聲濾波 ===\n")

# 模擬參數
FPS = 8  # QUARTER 模式約 8 FPS
NOISE_PERIOD = 0.5  # 噪聲周期（秒）
NOISE_PERIOD_FRAMES = int(FPS * NOISE_PERIOD)  # 約 4 幀
TOTAL_SECONDS = 10
TOTAL_FRAMES = FPS * TOTAL_SECONDS

print(f"模擬設定：")
print(f"  FPS: {FPS}")
print(f"  噪聲周期: {NOISE_PERIOD} 秒 ({NOISE_PERIOD_FRAMES} 幀)")
print(f"  總時長: {TOTAL_SECONDS} 秒 ({TOTAL_FRAMES} 幀)")
print()

# 初始化兩種濾波器配置
print("配置對比：")
print()

# 舊配置（較弱濾波）
detector_old = DrawerStateDetector(
    threshold_open=0.08,
    threshold_closed=0.06,
    filter_window=10,
    min_state_duration=8,
    ema_alpha=0.3,
    use_median_filter=True,
    state_lock_frames=15
)
print("舊配置（方案 B）:")
print("  filter_window=10, min_duration=8, ema_alpha=0.3, lock=15")

# 新配置（強化濾波，針對 0.5 秒周期）
detector_new = DrawerStateDetector(
    threshold_open=0.08,
    threshold_closed=0.06,
    filter_window=15,
    min_state_duration=10,
    ema_alpha=0.2,
    use_median_filter=True,
    state_lock_frames=20
)
print("新配置（方案 A - 0.5秒周期優化）:")
print("  filter_window=15, min_duration=10, ema_alpha=0.2, lock=20")
print()

# 生成測試數據：閉合狀態 + 0.5秒周期噪聲
print("生成測試數據：完全閉合狀態（depth_metric 約 0.05）")
print("              + 0.5秒周期正弦波噪聲（幅度 +/-0.012）")
print()

time_points = np.arange(TOTAL_FRAMES) / FPS
base_value = 0.05  # 完全閉合的真實值
noise_amplitude = 0.012  # 噪聲幅度（會導致穿越閾值）
noise_frequency = 1 / NOISE_PERIOD  # 2 Hz

# 生成含噪聲數據
noisy_data = base_value + noise_amplitude * np.sin(2 * np.pi * noise_frequency * time_points)
# 添加隨機白噪聲
noisy_data += np.random.normal(0, 0.003, TOTAL_FRAMES)

# 記錄濾波結果
states_old = []
states_new = []
filtered_old = []
filtered_new = []

print("開始濾波測試...")
print("-" * 60)

for i, value in enumerate(noisy_data):
    state_old = detector_old.update(value)
    state_new = detector_new.update(value)
    
    states_old.append(state_old)
    states_new.append(state_new)
    
    # 獲取濾波後的值
    filtered_old.append(detector_old.get_filtered_value() or value)
    filtered_new.append(detector_new.get_filtered_value() or value)
    
    # 每秒顯示一次
    if (i + 1) % FPS == 0:
        sec = (i + 1) // FPS
        print(f"秒 {sec}: 原始={value:.4f} | 舊濾波={filtered_old[-1]:.4f} ({state_old}) | 新濾波={filtered_new[-1]:.4f} ({state_new})")

print("-" * 60)
print()

# 統計狀態變更次數
def count_state_changes(states):
    changes = 0
    for i in range(1, len(states)):
        if states[i] != states[i-1]:
            changes += 1
    return changes

changes_old = count_state_changes(states_old)
changes_new = count_state_changes(states_new)

print("=== 結果統計 ===")
print(f"舊配置：")
print(f"  狀態變更次數: {changes_old}")
print(f"  最終狀態: {states_old[-1]}")
print(f"  平均濾波值: {np.mean(filtered_old[-20:]):.4f}")
print()
print(f"新配置（0.5秒周期優化）：")
print(f"  狀態變更次數: {changes_new}")
print(f"  最終狀態: {states_new[-1]}")
print(f"  平均濾波值: {np.mean(filtered_new[-20:]):.4f}")
print()

# 理想結果分析
print("理想結果：")
print("  狀態變更次數: 1 次（未知 -> 完全閉合）")
print("  最終狀態: 完全閉合")
print("  平均濾波值: 約 0.050（接近真實值 0.05）")
print()

improvement = (changes_old - changes_new) / changes_old * 100 if changes_old > 0 else 0
print(f"改善程度: {improvement:.1f}%")
print()

# 繪製對比圖
plt.figure(figsize=(14, 8))

# 子圖 1：原始數據與濾波結果
plt.subplot(2, 1, 1)
plt.plot(time_points, noisy_data, 'gray', alpha=0.3, linewidth=0.8, label='原始數據（含噪聲）')
plt.plot(time_points, filtered_old, 'orange', linewidth=1.5, label='舊配置濾波結果')
plt.plot(time_points, filtered_new, 'blue', linewidth=2, label='新配置濾波結果（0.5秒優化）')
plt.axhline(y=0.08, color='r', linestyle='--', alpha=0.5, label='開啟閾值 (0.08)')
plt.axhline(y=0.06, color='g', linestyle='--', alpha=0.5, label='閉合閾值 (0.06)')
plt.axhline(y=0.05, color='k', linestyle=':', alpha=0.5, label='真實值 (0.05)')
plt.xlabel('時間（秒）')
plt.ylabel('Depth Metric')
plt.title('0.5 秒周期噪聲濾波效果對比', fontsize=14, fontweight='bold')
plt.legend(loc='upper right')
plt.grid(True, alpha=0.3)
plt.ylim(0.03, 0.09)

# 子圖 2：狀態時間軸
plt.subplot(2, 1, 2)
state_map = {"未知": 0, "完全閉合": 1, "閉合中": 2, "完全開啟": 3}
states_old_numeric = [state_map.get(s, 0) for s in states_old]
states_new_numeric = [state_map.get(s, 0) for s in states_new]

plt.plot(time_points, states_old_numeric, 'o-', color='orange', markersize=3, label=f'舊配置（變更{changes_old}次）')
plt.plot(time_points, states_new_numeric, 's-', color='blue', markersize=3, label=f'新配置（變更{changes_new}次）')
plt.yticks([0, 1, 2, 3], ["未知", "完全閉合", "閉合中", "完全開啟"])
plt.xlabel('時間（秒）')
plt.ylabel('狀態')
plt.title('狀態切換對比（越少越穩定）', fontsize=12)
plt.legend(loc='upper right')
plt.grid(True, alpha=0.3, axis='x')

plt.tight_layout()
plt.savefig('filter_comparison_0p5s.png', dpi=150)
print("圖表已儲存至: filter_comparison_0p5s.png")
print()

# 最終評估
print("=== 最終評估 ===")
if changes_new <= 2:
    print("[OK] 新配置表現優秀：狀態穩定，幾乎無誤報")
elif changes_new <= 5:
    print("[Good] 新配置表現良好：偶有誤報，但已大幅改善")
else:
    print("[Warning] 新配置仍需優化：建議使用方案 C（超穩定配置）")

if changes_new < changes_old:
    print(f"[OK] 相較舊配置改善 {improvement:.1f}%")
else:
    print("[Info] 與舊配置相當")
