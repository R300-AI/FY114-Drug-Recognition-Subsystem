# 架构重构说明 - 物理层/显示层分离

## 重构概述
从复杂的多级滤波架构，重构为更清晰的物理层/显示层分离架构。

## 设计原则

### 物理层 (DrawerStateDetector)
- **职责**：基于原始物理数据直接判断状态
- **处理方式**：
  - 阈值比较（depth_metric vs. threshold_open/closed）
  - 基本状态持续确认（min_state_duration）
  - **不做复杂滤波**
- **优势**：保证数据的物理意义，简单可靠

### 显示层 (Time Series Chart)
- **职责**：在时间序列图表上进行视觉平滑
- **处理方式**：
  - 移动平均（moving average）
  - 可配置窗口大小（smoothing_window）
  - 可选显示原始数据对比（show_raw_data）
- **优势**：提升视觉效果，不影响物理判断

## 配置结构

### 物理层参数 (analysis)
```yaml
analysis:
  use_depth_transform: true    # 使用物理模型（1/√intensity）
  min_state_duration: 5        # 状态持续确认帧数
  history_size: 500           # 历史数据保存数量
```

### 显示层参数 (display)
```yaml
display:
  smoothing_window: 10        # 移动平均窗口大小
  show_raw_data: false        # 是否同时显示原始数据
```

## 调优建议

### 低噪声环境
- `min_state_duration`: 3-5
- `smoothing_window`: 5-10
- 响应时间：0.4-1.0 秒

### 高噪声环境（0.5秒周期噪声）
- `min_state_duration`: 8-10
- `smoothing_window`: 15-20
- 响应时间：1.0-2.0 秒

## 代码改动

### 1. DrawerStateDetector 简化
**文件**: `utils/depth_analysis.py`

**之前**: 7个参数（threshold_open, threshold_closed, filter_window, min_state_duration, ema_alpha, use_median_filter, state_lock_frames）

**现在**: 3个参数（threshold_open, threshold_closed, min_state_duration）

### 2. 显示层平滑
**文件**: `drawer_monitor.py`

**新增**: `moving_average()` 函数

**修改**: `update_chart()` 方法，应用移动平均平滑

### 3. UI更新
**文件**: `drawer_monitor.py`

**移除**:
- 滤波窗口大小控制
- EMA平滑系数控制
- 状态锁定帧数控制
- 中值滤波开关

**新增**:
- 显示层平滑窗口控制
- 原始数据显示开关

## 优势对比

### 旧架构问题
- ❌ 过度工程化（5级滤波流水线）
- ❌ 参数复杂，难以调优
- ❌ 物理意义被复杂滤波掩盖
- ❌ 代码耦合度高

### 新架构优势
- ✅ 清晰的职责分离
- ✅ 参数简单，容易理解
- ✅ 保留数据物理意义
- ✅ 代码解耦，易于维护

## 性能影响
- 状态判断响应：**无变化**（物理层直接判断）
- 视觉平滑效果：**可配置**（display.smoothing_window）
- CPU占用：**略微降低**（减少了多级滤波计算）

## 迁移指南

### 从旧配置迁移
旧配置中的滤波参数需要映射到新结构：

| 旧参数 | 新参数 | 映射关系 |
|--------|--------|----------|
| filter_window | display.smoothing_window | 直接映射 |
| min_state_duration | analysis.min_state_duration | 直接映射 |
| ema_alpha | - | 移除（由移动平均替代） |
| use_median_filter | - | 移除 |
| state_lock_frames | - | 移除 |

### 推荐配置
针对0.5秒周期噪声：
```yaml
analysis:
  min_state_duration: 8
display:
  smoothing_window: 15
```

## 测试验证
1. 物理层：直接观察状态变更日志，验证阈值判断正确性
2. 显示层：调整smoothing_window，观察图表平滑效果
3. 对比：启用show_raw_data，对比原始/平滑曲线

## 后续改进
- [ ] 添加自适应平滑窗口（根据噪声水平自动调整）
- [ ] 支持多种平滑算法（如Savitzky-Golay滤波）
- [ ] 性能监控（FPS、延迟统计）
