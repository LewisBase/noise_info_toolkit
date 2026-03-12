# -*- coding: utf-8 -*-
"""
@DATE: 2026-02-15 10:00:00
@Author: Liu Hengjiang
@File: app/core/event_detector.py
@Software: vscode
@Description:
        冲击噪声事件检测器
        支持声级触发、峰值触发、斜率触发三种模式
"""

import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Callable, Tuple
from dataclasses import dataclass
from enum import Enum
from collections import deque

from app.utils import logger


class TriggerType(Enum):
    """事件触发类型"""
    LEQ = "leq"           # 声级触发
    PEAK = "peak"        # 峰值触发
    SLOPE = "slope"      # 斜率触发
    UNKNOWN = "unknown"  # 未知


@dataclass
class EventInfo:
    """事件信息数据类"""
    event_id: str
    session_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_s: float = 0.0
    trigger_type: TriggerType = TriggerType.UNKNOWN
    
    # 声级指标
    lzpeak_db: float = 0.0
    lcpeak_db: float = 0.0
    laeq_event_db: float = 0.0
    sel_lae_db: float = 0.0
    
    # 峰度
    beta_excess_z: Optional[float] = None
    
    # 音频文件
    audio_file_path: Optional[str] = None
    pretrigger_s: float = 2.0
    posttrigger_s: float = 8.0
    
    # 备注
    notes: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'event_id': self.event_id,
            'session_id': self.session_id,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_s': self.duration_s,
            'trigger_type': self.trigger_type.value,
            'lzpeak_db': round(self.lzpeak_db, 2),
            'lcpeak_db': round(self.lcpeak_db, 2),
            'laeq_event_db': round(self.laeq_event_db, 2),
            'sel_lae_db': round(self.sel_lae_db, 2),
            'beta_excess_z': round(self.beta_excess_z, 2) if self.beta_excess_z else None,
            'audio_file_path': self.audio_file_path,
        }


class SlidingWindowCalculator:
    """滑动窗口计算器 - 用于计算LZeq_125等"""
    
    def __init__(self, window_duration_s: float = 0.125, sample_rate: int = 48000):
        """
        初始化滑动窗口计算器
        
        Args:
            window_duration_s: 窗口时长（秒），默认125ms
            sample_rate: 采样率
        """
        self.window_duration_s = window_duration_s
        self.sample_rate = sample_rate
        self.window_samples = int(window_duration_s * sample_rate)
        self.buffer = deque(maxlen=self.window_samples)
        
    def add_sample(self, sample: float) -> Optional[float]:
        """
        添加样本并返回当前窗口的等效声级
        
        Args:
            sample: 声压样本值 (Pa)
            
        Returns:
            float: 当前窗口的Leq (dB)，如果窗口未满则返回None
        """
        self.buffer.append(sample)
        
        if len(self.buffer) < self.window_samples:
            return None
        
        # 计算窗口内的等效声级
        # Leq = 10 * log10( (1/n) * sum(p_i^2) / p0^2 )
        samples = np.array(self.buffer)
        p_rms = np.sqrt(np.mean(samples ** 2))
        
        # 参考声压 20 μPa
        p0 = 20e-6
        leq_db = 20 * np.log10(p_rms / p0) if p_rms > 0 else 0
        
        return leq_db
    
    def reset(self):
        """重置缓冲区"""
        self.buffer.clear()


class EventDetector:
    """
    冲击噪声事件检测器
    
    根据白皮书要求，支持以下触发条件：
    - 声级触发：LZeq_125 ≥ threshold (默认90-95 dB)
    - 峰值触发：LCpeak ≥ threshold (默认130 dB)
    - 斜率触发：ΔLZeq ≥ threshold (默认10 dB/50ms)
    
    具有去抖动机制，避免重复触发。
    """
    
    # 默认阈值（根据白皮书）
    DEFAULT_LEQ_THRESHOLD = 90.0      # dB
    DEFAULT_PEAK_THRESHOLD = 130.0    # dB
    DEFAULT_SLOPE_THRESHOLD = 10.0    # dB/50ms
    DEFAULT_DEBOUNCE_S = 0.5          # 秒
    
    def __init__(self,
                 leq_threshold: float = DEFAULT_LEQ_THRESHOLD,
                 peak_threshold: float = DEFAULT_PEAK_THRESHOLD,
                 slope_threshold: float = DEFAULT_SLOPE_THRESHOLD,
                 debounce_s: float = DEFAULT_DEBOUNCE_S,
                 sample_rate: int = 48000,
                 reference_pressure: float = 20e-6):
        """
        初始化事件检测器
        
        Args:
            leq_threshold: LZeq_125触发阈值 (dB)
            peak_threshold: LCpeak触发阈值 (dB)
            slope_threshold: 声级变化率触发阈值 (dB/50ms)
            debounce_s: 去抖动时间 (秒)
            sample_rate: 采样率
            reference_pressure: 参考声压 (Pa)
        """
        self.leq_threshold = leq_threshold
        self.peak_threshold = peak_threshold
        self.slope_threshold = slope_threshold
        self.debounce_s = debounce_s
        self.sample_rate = sample_rate
        self.reference_pressure = reference_pressure
        
        # 状态
        self.last_event_time: Optional[datetime] = None
        self.event_counter = 0
        self.is_in_event = False
        self.current_event_info: Optional[EventInfo] = None
        
        # 滑动窗口计算器
        self.leq_125_calculator = SlidingWindowCalculator(0.125, sample_rate)
        
        # 斜率检测历史 (50ms = 2400 samples @ 48kHz)
        self.slope_window_samples = int(0.05 * sample_rate)
        self.leq_history = deque(maxlen=self.slope_window_samples)
        
        # 事件期间的峰值跟踪
        self.event_lzpeak_max = 0.0
        self.event_lcpeak_max = 0.0
        
        # 回调函数
        self.event_start_callbacks: List[Callable[[EventInfo], None]] = []
        self.event_end_callbacks: List[Callable[[EventInfo], None]] = []
        
        logger.info(f"EventDetector initialized: leq_threshold={leq_threshold}dB, "
                   f"peak_threshold={peak_threshold}dB, debounce={debounce_s}s")
    
    def add_event_start_callback(self, callback: Callable[[EventInfo], None]):
        """添加事件开始回调"""
        self.event_start_callbacks.append(callback)
    
    def add_event_end_callback(self, callback: Callable[[EventInfo], None]):
        """添加事件结束回调"""
        self.event_end_callbacks.append(callback)
    
    def _check_debounce(self, current_time: datetime) -> bool:
        """检查去抖动"""
        if self.last_event_time is None:
            return True
        
        elapsed = (current_time - self.last_event_time).total_seconds()
        return elapsed >= self.debounce_s
    
    def _detect_trigger(self, 
                        lzeq_125: float, 
                        lcpeak: float,
                        slope: Optional[float]) -> Tuple[bool, TriggerType]:
        """
        检测是否触发事件
        
        Returns:
            Tuple[触发标志, 触发类型]
        """
        # 检查峰值触发
        if lcpeak >= self.peak_threshold:
            return True, TriggerType.PEAK
        
        # 检查声级触发
        if lzeq_125 >= self.leq_threshold:
            return True, TriggerType.LEQ
        
        # 检查斜率触发
        if slope is not None and slope >= self.slope_threshold:
            return True, TriggerType.SLOPE
        
        return False, TriggerType.UNKNOWN
    
    def process_sample(self,
                       sample_z: float,  # Z计权声压 (Pa)
                       sample_c: float,  # C计权声压 (Pa)
                       current_time: datetime,
                       session_id: str = "default") -> Optional[EventInfo]:
        """
        处理单个样本
        
        Args:
            sample_z: Z计权声压样本 (Pa)
            sample_c: C计权声压样本 (Pa)
            current_time: 当前时间
            session_id: 会话ID
            
        Returns:
            EventInfo: 如果事件结束则返回事件信息，否则返回None
        """
        # 更新滑动窗口
        lzeq_125 = self.leq_125_calculator.add_sample(sample_z)
        
        # 计算峰值 (简单取绝对值最大值)
        lzpeak = 20 * np.log10(abs(sample_z) / self.reference_pressure) if sample_z != 0 else 0
        lcpeak = 20 * np.log10(abs(sample_c) / self.reference_pressure) if sample_c != 0 else 0
        
        # 更新斜率历史
        if lzeq_125 is not None:
            self.leq_history.append(lzeq_125)
        
        # 计算斜率
        slope = None
        if len(self.leq_history) >= self.slope_window_samples:
            slope = self.leq_history[-1] - self.leq_history[0]
        
        # 如果不在事件中，检测是否触发
        if not self.is_in_event:
            triggered, trigger_type = self._detect_trigger(
                lzeq_125 if lzeq_125 else 0, 
                lcpeak, 
                slope
            )
            
            if triggered and self._check_debounce(current_time):
                # 触发新事件
                self._start_event(current_time, session_id, trigger_type, lzpeak, lcpeak)
        else:
            # 在事件中，更新峰值
            self._update_event(lzpeak, lcpeak)
            
            # 检查事件是否结束（声级低于阈值持续一段时间）
            if lzeq_125 is not None and lzeq_125 < self.leq_threshold - 10:  # 滞后10dB
                return self._end_event(current_time)
        
        return None
    
    def _start_event(self,
                     start_time: datetime,
                     session_id: str,
                     trigger_type: TriggerType,
                     lzpeak: float,
                     lcpeak: float):
        """开始新事件"""
        import uuid
        
        self.event_counter += 1
        self.last_event_time = start_time
        self.is_in_event = True
        
        # 初始化峰值
        self.event_lzpeak_max = lzpeak
        self.event_lcpeak_max = lcpeak
        
        # 创建事件信息
        self.current_event_info = EventInfo(
            event_id=f"EVT-{uuid.uuid4().hex[:12].upper()}",
            session_id=session_id,
            start_time=start_time,
            trigger_type=trigger_type,
            lzpeak_db=lzpeak,
            lcpeak_db=lcpeak
        )
        
        logger.info(f"Event started: {self.current_event_info.event_id}, "
                   f"type={trigger_type.value}, lzpeak={lzpeak:.1f}dB")
        
        # 调用回调
        for callback in self.event_start_callbacks:
            try:
                callback(self.current_event_info)
            except Exception as e:
                logger.error(f"Event start callback error: {e}")
    
    def _update_event(self, lzpeak: float, lcpeak: float):
        """更新当前事件的峰值"""
        if lzpeak > self.event_lzpeak_max:
            self.event_lzpeak_max = lzpeak
        if lcpeak > self.event_lcpeak_max:
            self.event_lcpeak_max = lcpeak
    
    def _end_event(self, end_time: datetime) -> EventInfo:
        """结束当前事件"""
        if self.current_event_info is None:
            return None
        
        self.current_event_info.end_time = end_time
        self.current_event_info.duration_s = (
            end_time - self.current_event_info.start_time
        ).total_seconds()
        self.current_event_info.lzpeak_db = self.event_lzpeak_max
        self.current_event_info.lcpeak_db = self.event_lcpeak_max
        
        # 估算事件期间的LAeq (简化处理)
        self.current_event_info.laeq_event_db = self.event_lzpeak_max - 10
        
        # 估算SEL (简化处理: SEL = LAeq + 10*log10(duration))
        if self.current_event_info.duration_s > 0:
            self.current_event_info.sel_lae_db = (
                self.current_event_info.laeq_event_db + 
                10 * np.log10(self.current_event_info.duration_s)
            )
        
        logger.info(f"Event ended: {self.current_event_info.event_id}, "
                   f"duration={self.current_event_info.duration_s:.2f}s, "
                   f"lzpeak_max={self.event_lzpeak_max:.1f}dB")
        
        # 调用回调
        for callback in self.event_end_callbacks:
            try:
                callback(self.current_event_info)
            except Exception as e:
                logger.error(f"Event end callback error: {e}")
        
        # 重置状态
        self.is_in_event = False
        event_info = self.current_event_info
        self.current_event_info = None
        
        return event_info
    
    def force_end_event(self, end_time: datetime) -> Optional[EventInfo]:
        """强制结束当前事件"""
        if self.is_in_event:
            return self._end_event(end_time)
        return None
    
    def get_stats(self) -> Dict:
        """获取检测器统计信息"""
        return {
            'total_events': self.event_counter,
            'is_in_event': self.is_in_event,
            'current_event': self.current_event_info.to_dict() if self.current_event_info else None,
            'thresholds': {
                'leq': self.leq_threshold,
                'peak': self.peak_threshold,
                'slope': self.slope_threshold,
                'debounce_s': self.debounce_s,
            }
        }
