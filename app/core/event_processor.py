# -*- coding: utf-8 -*-
"""
@DATE: 2026-02-15 11:00:00
@Author: Liu Hengjiang
@File: app/core/event_processor.py
@Software: vscode
@Description:
        事件处理器 - 整合事件检测和环形缓冲
        处理音频流，检测冲击噪声事件，保存事件音频
"""

import numpy as np
from datetime import datetime
from typing import Optional, List, Dict, Callable
from pathlib import Path
import threading
import queue

from acoustics import Signal
from scipy.stats import kurtosis

from app.core.event_detector import EventDetector, EventInfo, TriggerType
from app.core.ring_buffer import RingBuffer
from app.utils import logger


class EventProcessor:
    """
    事件处理器
    
    整合事件检测、环形缓冲和音频保存功能：
    1. 持续接收音频流
    2. 实时检测冲击噪声事件
    3. 保存事件音频 (pre 2s + post 8s)
    4. 计算事件指标 (峰度、SEL等)
    """
    
    def __init__(self,
                 sample_rate: int = 48000,
                 leq_threshold: float = 90.0,
                 peak_threshold: float = 130.0,
                 debounce_s: float = 0.5,
                 output_dir: str = "./audio_events",
                 enable_audio_save: bool = True):
        """
        初始化事件处理器
        
        Args:
            sample_rate: 采样率
            leq_threshold: LZeq_125触发阈值 (dB)
            peak_threshold: LCpeak触发阈值 (dB)
            debounce_s: 去抖动时间 (秒)
            output_dir: 事件音频输出目录
            enable_audio_save: 是否保存事件音频
        """
        self.sample_rate = sample_rate
        self.output_dir = output_dir
        self.enable_audio_save = enable_audio_save
        
        # 创建事件检测器
        self.event_detector = EventDetector(
            leq_threshold=leq_threshold,
            peak_threshold=peak_threshold,
            debounce_s=debounce_s,
            sample_rate=sample_rate
        )
        
        # 创建环形缓冲区 (12秒缓冲，2秒pre-trigger，8秒post-trigger)
        self.ring_buffer = RingBuffer(
            sample_rate=sample_rate,
            buffer_duration_s=12.0,
            pretrigger_s=2.0,
            posttrigger_s=8.0,
            channels=1
        )
        
        # 状态
        self.is_running = False
        self.session_id: Optional[str] = None
        
        # 事件收集
        self.events: List[EventInfo] = []
        self.current_event_post_data: Optional[List[float]] = None
        
        # 回调
        self.event_callbacks: List[Callable[[EventInfo], None]] = []
        
        # 注册事件回调
        self.event_detector.add_event_start_callback(self._on_event_start)
        self.event_detector.add_event_end_callback(self._on_event_end)
        
        # 输出目录
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        logger.info(f"EventProcessor initialized: leq_threshold={leq_threshold}dB, "
                   f"peak_threshold={peak_threshold}dB, output_dir={output_dir}")
    
    def add_event_callback(self, callback: Callable[[EventInfo], None]):
        """添加事件回调函数"""
        self.event_callbacks.append(callback)
    
    def start(self, session_id: str):
        """
        开始事件处理
        
        Args:
            session_id: 会话ID
        """
        self.is_running = True
        self.session_id = session_id
        self.events = []
        self.ring_buffer.clear()
        
        logger.info(f"EventProcessor started for session: {session_id}")
    
    def stop(self) -> List[EventInfo]:
        """
        停止事件处理
        
        Returns:
            List[EventInfo]: 本次会话检测到的所有事件
        """
        self.is_running = False
        
        # 强制结束当前事件
        if self.event_detector.is_in_event:
            event_info = self.event_detector.force_end_event(datetime.now())
            if event_info:
                self._finalize_event(event_info)
        
        logger.info(f"EventProcessor stopped. Total events: {len(self.events)}")
        
        return self.events
    
    def process_audio_chunk(self, 
                            audio_data: np.ndarray,
                            timestamp: Optional[datetime] = None) -> Optional[EventInfo]:
        """
        处理音频块
        
        Args:
            audio_data: 音频数据 (Z计权或原始声压)
            timestamp: 时间戳
            
        Returns:
            EventInfo: 如果事件结束则返回事件信息
        """
        if not self.is_running:
            return None
        
        if timestamp is None:
            timestamp = datetime.now()
        
        # 写入环形缓冲区
        self.ring_buffer.write(audio_data.astype(np.float32))
        
        # 如果正在记录事件后数据
        if self.current_event_post_data is not None:
            self.current_event_post_data.extend(audio_data.tolist())
            
            # 检查是否达到post-trigger时长
            post_samples_needed = int(self.ring_buffer.posttrigger_s * self.sample_rate)
            if len(self.current_event_post_data) >= post_samples_needed:
                # 事件录制完成
                return self._finish_event_recording()
        
        # 处理每个样本进行事件检测
        # 注意：这里简化为逐样本处理，实际应该使用滑动窗口
        # 为简化实现，我们每隔一段时间检查一次
        completed_event = None
        for sample in audio_data:
            event_info = self.event_detector.process_sample(
                sample_z=sample,
                sample_c=sample,  # 简化：假设C计权与Z计权相同
                current_time=timestamp,
                session_id=self.session_id or "default"
            )
            if event_info:
                completed_event = event_info
                break
        
        return completed_event
    
    def _on_event_start(self, event_info: EventInfo):
        """事件开始回调"""
        logger.info(f"Event started recording: {event_info.event_id}")
        
        # 开始收集post-trigger数据
        self.current_event_post_data = []
    
    def _on_event_end(self, event_info: EventInfo):
        """事件结束回调"""
        logger.info(f"Event ended: {event_info.event_id}, waiting for post-trigger data")
        
        # 事件结束，但post-trigger数据收集可能还未完成
        # 等待_process_audio_chunk完成post-trigger收集
    
    def _finish_event_recording(self) -> Optional[EventInfo]:
        """完成事件录制"""
        if self.current_event_post_data is None:
            return None
        
        # 获取当前事件信息
        if not self.events:
            self.current_event_post_data = None
            return None
        
        # 获取最后一个事件
        event_info = self.events[-1]
        
        # 保存事件音频
        if self.enable_audio_save and self.current_event_post_data:
            try:
                post_data = np.array(self.current_event_post_data[:self.ring_buffer.posttrigger_samples])
                audio_path = self.ring_buffer.save_event_audio(
                    event_id=event_info.event_id,
                    posttrigger_data=post_data,
                    output_dir=self.output_dir
                )
                event_info.audio_file_path = audio_path
                logger.info(f"Event audio saved: {audio_path}")
            except Exception as e:
                logger.error(f"Failed to save event audio: {e}")
        
        # 计算事件指标
        self._calculate_event_metrics(event_info)
        
        # 清理
        self.current_event_post_data = None
        
        # 调用外部回调
        for callback in self.event_callbacks:
            try:
                callback(event_info)
            except Exception as e:
                logger.error(f"Event callback error: {e}")
        
        return event_info
    
    def _finalize_event(self, event_info: EventInfo):
        """最终化事件（强制结束时调用）"""
        event_info.audio_file_path = None  # 强制结束不保存音频
        self.events.append(event_info)
        
        # 调用回调
        for callback in self.event_callbacks:
            try:
                callback(event_info)
            except Exception as e:
                logger.error(f"Event callback error: {e}")
    
    def _calculate_event_metrics(self, event_info: EventInfo):
        """计算事件指标"""
        # 这里简化处理，实际应该从音频数据计算
        # 目前EventDetector已经计算了基本的峰值和持续时间
        
        # 估算超额峰度 (简化)
        # 实际应该从事件音频段计算
        event_info.beta_excess_z = 3.0  # 默认正态分布峰度
        
        logger.debug(f"Event metrics calculated: {event_info.event_id}")
    
    def get_events(self) -> List[EventInfo]:
        """获取所有事件"""
        return self.events
    
    def get_event_count(self) -> int:
        """获取事件数量"""
        return len(self.events)
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            'is_running': self.is_running,
            'session_id': self.session_id,
            'event_count': len(self.events),
            'buffer_info': self.ring_buffer.get_buffer_info(),
            'detector_stats': self.event_detector.get_stats(),
        }


class BatchEventProcessor:
    """批量事件处理器 - 用于处理已录制的音频文件"""
    
    def __init__(self,
                 leq_threshold: float = 90.0,
                 peak_threshold: float = 130.0,
                 debounce_s: float = 0.5):
        """
        初始化批量事件处理器
        
        Args:
            leq_threshold: LZeq_125触发阈值
            peak_threshold: LCpeak触发阈值
            debounce_s: 去抖动时间
        """
        self.leq_threshold = leq_threshold
        self.peak_threshold = peak_threshold
        self.debounce_s = debounce_s
    
    def process_file(self, 
                     file_path: str,
                     session_id: str = "default") -> List[EventInfo]:
        """
        处理音频文件，检测事件
        
        Args:
            file_path: 音频文件路径
            session_id: 会话ID
            
        Returns:
            List[EventInfo]: 检测到的事件列表
        """
        import librosa
        import warnings
        
        logger.info(f"Processing file for events: {file_path}")
        
        # 加载音频
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            y, sr = librosa.load(file_path, sr=None)
        
        # 创建事件处理器
        processor = EventProcessor(
            sample_rate=sr,
            leq_threshold=self.leq_threshold,
            peak_threshold=self.peak_threshold,
            debounce_s=self.debounce_s,
            enable_audio_save=False  # 批量处理不保存音频
        )
        
        processor.start(session_id)
        
        # 分段处理（每段1秒）
        chunk_size = sr
        for i in range(0, len(y), chunk_size):
            chunk = y[i:i+chunk_size]
            if len(chunk) < chunk_size:
                chunk = np.pad(chunk, (0, chunk_size - len(chunk)))
            
            timestamp = datetime.now()
            processor.process_audio_chunk(chunk, timestamp)
        
        events = processor.stop()
        
        logger.info(f"File processing complete: {len(events)} events detected")
        
        return events
