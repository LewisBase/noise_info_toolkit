# -*- coding: utf-8 -*-
"""
@DATE: 2026-02-15 12:00:00
@Author: Liu Hengjiang
@File: test/test_phase3.py
@Software: vscode
@Description:
        Phase 3 单元测试 - 事件检测和环形缓冲
"""

import pytest
import numpy as np
from datetime import datetime
import tempfile
import os

from app.core.event_detector import (
    EventDetector, EventInfo, TriggerType, SlidingWindowCalculator
)
from app.core.ring_buffer import RingBuffer, MultiChannelRingBuffer
from app.core.event_processor import EventProcessor, BatchEventProcessor


class TestSlidingWindowCalculator:
    """测试滑动窗口计算器"""
    
    def test_init(self):
        """测试初始化"""
        calc = SlidingWindowCalculator(window_duration_s=0.125, sample_rate=48000)
        assert calc.window_duration_s == 0.125
        assert calc.sample_rate == 48000
        assert calc.window_samples == 6000  # 0.125 * 48000
    
    def test_add_sample_window_not_full(self):
        """测试窗口未满时返回None"""
        calc = SlidingWindowCalculator(window_duration_s=0.125, sample_rate=48000)
        
        # 添加少量样本
        for _ in range(100):
            result = calc.add_sample(1.0)
            assert result is None
    
    def test_add_sample_window_full(self):
        """测试窗口满后返回Leq"""
        calc = SlidingWindowCalculator(window_duration_s=0.125, sample_rate=48000)
        
        # 添加足够样本填满窗口
        result = None
        for _ in range(6000):  # 窗口大小
            result = calc.add_sample(1.0)  # 1 Pa
        
        assert result is not None
        assert result > 0  # 应该返回一个正的分贝值
    
    def test_reset(self):
        """测试重置"""
        calc = SlidingWindowCalculator(window_duration_s=0.125, sample_rate=48000)
        
        # 填满窗口
        for _ in range(6000):
            calc.add_sample(1.0)
        
        # 重置
        calc.reset()
        
        # 再次添加样本应该返回None
        result = calc.add_sample(1.0)
        assert result is None


class TestEventDetector:
    """测试事件检测器"""
    
    def test_init(self):
        """测试初始化"""
        detector = EventDetector(
            leq_threshold=90.0,
            peak_threshold=130.0,
            debounce_s=0.5
        )
        
        assert detector.leq_threshold == 90.0
        assert detector.peak_threshold == 130.0
        assert detector.debounce_s == 0.5
        assert not detector.is_in_event
        assert detector.event_counter == 0
    
    def test_peak_trigger(self):
        """测试峰值触发"""
        detector = EventDetector(peak_threshold=100.0)
        
        # 创建触发峰值的样本
        timestamp = datetime.now()
        
        # 第一个样本触发峰值
        event_info = None
        for i in range(1000):
            # 使用超过阈值的声压 (100 dB = 2 Pa)
            sample = 2.1 if i == 500 else 0.001
            event_info = detector.process_sample(sample, sample, timestamp, "test_session")
            if event_info:
                break
        
        assert event_info is not None or detector.is_in_event
    
    def test_debounce(self):
        """测试去抖动"""
        detector = EventDetector(peak_threshold=100.0, debounce_s=1.0)
        
        timestamp1 = datetime.now()
        
        # 触发第一个事件
        for i in range(1000):
            sample = 2.1 if i == 500 else 0.001
            detector.process_sample(sample, sample, timestamp1, "test_session")
        
        first_count = detector.event_counter
        
        # 立即尝试触发第二个事件（应该被去抖动阻止）
        timestamp2 = datetime.now()
        for i in range(1000):
            sample = 2.1 if i == 500 else 0.001
            detector.process_sample(sample, sample, timestamp2, "test_session")
        
        # 事件计数不应该增加
        assert detector.event_counter == first_count
    
    def test_event_lifecycle(self):
        """测试完整的事件生命周期"""
        detector = EventDetector(peak_threshold=100.0)
        
        start_time = datetime.now()
        
        # 开始事件
        detector._start_event(start_time, "test_session", TriggerType.PEAK, 110.0, 105.0)
        
        assert detector.is_in_event
        assert detector.event_counter == 1
        assert detector.current_event_info is not None
        
        # 更新事件
        detector._update_event(115.0, 108.0)
        
        # 结束事件
        end_time = datetime.now()
        event_info = detector._end_event(end_time)
        
        assert not detector.is_in_event
        assert event_info is not None
        assert event_info.lzpeak_db == 115.0  # 最大值
    
    def test_get_stats(self):
        """测试获取统计信息"""
        detector = EventDetector()
        stats = detector.get_stats()
        
        assert 'total_events' in stats
        assert 'is_in_event' in stats
        assert 'thresholds' in stats


class TestRingBuffer:
    """测试环形缓冲区"""
    
    def test_init(self):
        """测试初始化"""
        buffer = RingBuffer(
            sample_rate=48000,
            buffer_duration_s=12.0,
            pretrigger_s=2.0,
            posttrigger_s=8.0
        )
        
        assert buffer.sample_rate == 48000
        assert buffer.buffer_size == 576000  # 48000 * 12
        assert buffer.pretrigger_samples == 96000  # 48000 * 2
        assert buffer.posttrigger_samples == 384000  # 48000 * 8
    
    def test_write(self):
        """测试写入"""
        buffer = RingBuffer(sample_rate=48000, buffer_duration_s=1.0)
        
        samples = np.ones(1000, dtype=np.float32)
        written = buffer.write(samples)
        
        assert written == 1000
        assert buffer.write_index == 1000
    
    def test_write_wraparound(self):
        """测试环绕写入"""
        buffer = RingBuffer(sample_rate=48000, buffer_duration_s=1.0)
        
        # 先填满缓冲区
        samples1 = np.ones(48000, dtype=np.float32)
        buffer.write(samples1)
        
        # 再写入更多数据（触发环绕）
        samples2 = np.ones(1000, dtype=np.float32)
        written = buffer.write(samples2)
        
        assert written == 1000
        assert buffer.write_index == 1000  # 环绕后
        assert buffer.is_full
    
    def test_get_pretrigger_data(self):
        """测试获取触发前数据"""
        buffer = RingBuffer(
            sample_rate=1000,
            buffer_duration_s=2.0,
            pretrigger_s=0.5
        )
        
        # 写入足够数据
        samples = np.arange(2000, dtype=np.float32)
        buffer.write(samples)
        
        # 获取触发前数据
        pre_data = buffer.get_pretrigger_data()
        
        assert len(pre_data) == 500  # 0.5s * 1000Hz
    
    def test_get_pretrigger_data_wraparound(self):
        """测试环绕情况下的触发前数据获取"""
        buffer = RingBuffer(
            sample_rate=1000,
            buffer_duration_s=1.0,
            pretrigger_s=0.5
        )
        
        # 填满并环绕
        samples1 = np.arange(1000, dtype=np.float32)
        buffer.write(samples1)
        
        samples2 = np.arange(800, 1600, dtype=np.float32)
        buffer.write(samples2)
        
        # 获取触发前数据（应该正确处理环绕）
        pre_data = buffer.get_pretrigger_data()
        
        assert len(pre_data) == 500
    
    def test_save_event_audio(self):
        """测试保存事件音频"""
        with tempfile.TemporaryDirectory() as tmpdir:
            buffer = RingBuffer(
                sample_rate=1000,
                buffer_duration_s=2.0,
                pretrigger_s=0.5,
                posttrigger_s=1.0
            )
            
            # 写入数据
            samples = np.sin(2 * np.pi * 100 * np.arange(2000) / 1000).astype(np.float32)
            buffer.write(samples)
            
            # 创建触发后数据
            post_data = np.sin(2 * np.pi * 100 * np.arange(1000) / 1000).astype(np.float32)
            
            # 保存
            filepath = buffer.save_event_audio("TEST_EVENT", post_data, tmpdir)
            
            assert os.path.exists(filepath)
            assert filepath.endswith(".wav")
    
    def test_clear(self):
        """测试清空缓冲区"""
        buffer = RingBuffer(sample_rate=48000, buffer_duration_s=1.0)
        
        # 写入数据
        samples = np.ones(1000, dtype=np.float32)
        buffer.write(samples)
        
        # 清空
        buffer.clear()
        
        assert buffer.write_index == 0
        assert not buffer.is_full
        assert buffer.total_written == 0


class TestMultiChannelRingBuffer:
    """测试多通道环形缓冲区"""
    
    def test_init(self):
        """测试初始化"""
        buffer = MultiChannelRingBuffer(
            sample_rate=48000,
            num_channels=2
        )
        
        assert buffer.sample_rate == 48000
        assert buffer.num_channels == 2
        assert len(buffer.buffers) == 2
    
    def test_write_multichannel(self):
        """测试多通道写入"""
        buffer = MultiChannelRingBuffer(
            sample_rate=1000,
            num_channels=2
        )
        
        # 创建多通道数据 (1000, 2)
        samples = np.random.randn(1000, 2).astype(np.float32)
        written = buffer.write(samples)
        
        assert written == 1000


class TestEventProcessor:
    """测试事件处理器"""
    
    def test_init(self):
        """测试初始化"""
        processor = EventProcessor(
            sample_rate=48000,
            leq_threshold=90.0,
            peak_threshold=130.0
        )
        
        assert processor.sample_rate == 48000
        assert not processor.is_running
        assert processor.event_detector is not None
        assert processor.ring_buffer is not None
    
    def test_start_stop(self):
        """测试启动和停止"""
        processor = EventProcessor()
        
        processor.start("test_session")
        assert processor.is_running
        assert processor.session_id == "test_session"
        
        events = processor.stop()
        assert not processor.is_running
        assert isinstance(events, list)
    
    def test_add_event_callback(self):
        """测试添加事件回调"""
        processor = EventProcessor()
        
        callback_called = False
        def test_callback(event_info):
            nonlocal callback_called
            callback_called = True
        
        processor.add_event_callback(test_callback)
        assert len(processor.event_callbacks) == 1


class TestBatchEventProcessor:
    """测试批量事件处理器"""
    
    def test_init(self):
        """测试初始化"""
        processor = BatchEventProcessor(
            leq_threshold=90.0,
            peak_threshold=130.0
        )
        
        assert processor.leq_threshold == 90.0
        assert processor.peak_threshold == 130.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
