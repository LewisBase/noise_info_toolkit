# -*- coding: utf-8 -*-
"""
@DATE: 2026-02-14 21:00:00
@Author: Liu Hengjiang
@File: test/test_phase2.py
@Software: vscode
@Description:
        Phase 2 单元测试 - TimeHistory和Session管理
"""

import pytest
import numpy as np
from datetime import datetime
from acoustics import Signal

# Test imports
from app.core.dose_calculator import DoseCalculator, DoseStandard
from app.core.time_history_processor import (
    TimeHistoryProcessor, 
    SecondMetrics, 
    aggregate_session_metrics
)
from app.core.session_manager import (
    SessionManager,
    SessionConfig,
    SessionState,
    session_registry
)


class TestDoseCalculator:
    """测试剂量计算器"""
    
    def test_calculate_dose_increment(self):
        """测试单秒剂量增量计算"""
        calc = DoseCalculator()
        
        # Test NIOSH: 85 dBA for 1 second
        dose = calc.calculate_dose_increment(85.0, 1.0, DoseStandard.NIOSH)
        expected = 100.0 * (1.0/3600) / 8.0  # 100 * (1s/3600) / 8h
        assert abs(dose - expected) < 0.0001
        
        # Test with 0 dBA (should give very small dose due to threshold=0)
        dose_zero = calc.calculate_dose_increment(0.0, 1.0, DoseStandard.NIOSH)
        assert dose_zero < 0.0001  # Very small value due to floating point precision
    
    def test_calculate_twa(self):
        """测试TWA计算"""
        calc = DoseCalculator()
        profile = DoseCalculator.get_profile("NIOSH")
        
        # 100% dose should give criterion level
        twa = calc.calculate_twa(100.0, profile)
        assert abs(twa - 85.0) < 0.1
        
        # 200% dose
        twa_200 = calc.calculate_twa(200.0, profile)
        assert twa_200 > 85.0
    
    def test_calculate_lex(self):
        """测试LEX,8h计算"""
        calc = DoseCalculator()
        profile = DoseCalculator.get_profile("EU_ISO")
        
        # 100% dose should give criterion level
        lex = calc.calculate_lex(100.0, profile)
        assert abs(lex - 85.0) < 0.1


class TestTimeHistoryProcessor:
    """测试时间历程处理器"""
    
    def test_calculate_second_metrics(self):
        """测试单秒指标计算"""
        processor = TimeHistoryProcessor()
        
        # Create 1 second of 1kHz sine wave at 80 dB
        sr = 48000
        t = np.linspace(0, 1, sr)
        # Generate sine wave with specific amplitude for ~80 dB SPL
        amplitude = 0.2  # This will give us a reasonable dB level
        sine_wave = amplitude * np.sin(2 * np.pi * 1000 * t)
        
        metrics = processor._calculate_second_metrics(
            sine_wave, sr, datetime.utcnow(), 1.0)
        
        assert metrics is not None
        assert metrics.LAeq > 0
        assert metrics.LCeq > 0
        assert metrics.LZeq > 0
        assert metrics.duration_s == 1.0
    
    def test_process_signal_per_second(self):
        """测试信号按秒处理"""
        processor = TimeHistoryProcessor()
        
        # Create 3 seconds of test signal
        sr = 48000
        duration = 3
        t = np.linspace(0, duration, sr * duration)
        amplitude = 0.2
        sine_wave = amplitude * np.sin(2 * np.pi * 1000 * t)
        
        signal = Signal(sine_wave, sr)
        results = processor.process_signal_per_second(signal)
        
        assert len(results) == 3
        for i, metrics in enumerate(results):
            assert metrics.duration_s == 1.0
            assert metrics.LAeq > 0


class TestSessionManager:
    """测试会话管理器"""
    
    def test_session_lifecycle(self):
        """测试会话生命周期"""
        config = SessionConfig(profile=DoseStandard.NIOSH)
        session = SessionManager(config=config)
        
        # Test initial state
        assert session.state == SessionState.IDLE
        
        # Test start
        session.start()
        assert session.state == SessionState.RUNNING
        assert session.metrics.start_time is not None
        
        # Test pause
        session.pause()
        assert session.state == SessionState.PAUSED
        
        # Test resume
        session.resume()
        assert session.state == SessionState.RUNNING
        
        # Test stop
        session.stop()
        assert session.state == SessionState.STOPPED
        assert session.metrics.end_time is not None
    
    def test_process_second(self):
        """测试处理单秒数据"""
        config = SessionConfig(profile=DoseStandard.NIOSH)
        session = SessionManager(config=config)
        session.start()
        
        # Create a mock SecondMetrics
        metrics = SecondMetrics(
            timestamp=datetime.utcnow(),
            duration_s=1.0,
            LAeq=85.0,
            LCeq=87.0,
            LZeq=90.0,
            dose_frac_niosh=0.003472,  # ~100% / 8h = 0.003472% per second
            dose_frac_osha_pel=0.002174,
            dose_frac_osha_hca=0.002174,
            dose_frac_eu_iso=0.003472,
        )
        
        session.process_second(metrics)
        
        assert session.metrics.total_duration_s == 1.0
        assert session.metrics.cumulative_dose_niosh > 0
        assert len(session.time_history) == 1
    
    def test_get_summary(self):
        """测试获取会话摘要"""
        config = SessionConfig(profile=DoseStandard.NIOSH)
        session = SessionManager(config=config)
        session.start()
        
        # Add some mock data
        for i in range(5):
            metrics = SecondMetrics(
                timestamp=datetime.utcnow(),
                duration_s=1.0,
                LAeq=80.0 + i,
                LCeq=82.0 + i,
                LZeq=85.0 + i,
                dose_frac_niosh=0.001,
                dose_frac_osha_pel=0.0005,
                dose_frac_osha_hca=0.0005,
                dose_frac_eu_iso=0.001,
            )
            session.process_second(metrics)
        
        summary = session.get_summary()
        
        assert summary['session_id'] == session.session_id
        assert summary['total_seconds_processed'] == 5
        assert 'metrics' in summary
        assert 'profile_summary' in summary


class TestSessionRegistry:
    """测试会话注册表"""
    
    def test_create_and_get_session(self):
        """测试创建和获取会话"""
        registry = session_registry
        
        # Clear existing sessions for test
        for sid in list(registry._sessions.keys()):
            registry.remove_session(sid)
        
        # Create session
        config = SessionConfig(profile=DoseStandard.NIOSH)
        session = registry.create_session(config=config)
        
        assert session.session_id in registry._sessions
        
        # Get session
        retrieved = registry.get_session(session.session_id)
        assert retrieved == session
        
        # Cleanup
        registry.remove_session(session.session_id)
    
    def test_list_sessions(self):
        """测试列出会话"""
        registry = session_registry
        
        # Clear existing sessions for test
        for sid in list(registry._sessions.keys()):
            registry.remove_session(sid)
        
        # Create a few sessions
        for _ in range(3):
            registry.create_session()
        
        sessions = registry.list_sessions()
        assert len(sessions) == 3
        
        # Cleanup
        for sid in list(registry._sessions.keys()):
            registry.remove_session(sid)


def test_aggregate_session_metrics():
    """测试会话指标聚合"""
    # Create mock time history
    time_history = []
    for i in range(10):
        metrics = SecondMetrics(
            timestamp=datetime.utcnow(),
            duration_s=1.0,
            LAeq=80.0 + i * 2,  # 80, 82, 84, ...
            LCeq=82.0 + i * 2,
            LZeq=85.0 + i * 2,
            LZpeak=90.0 + i * 2,
            dose_frac_niosh=0.001,
            dose_frac_osha_pel=0.0005,
            dose_frac_osha_hca=0.0005,
            dose_frac_eu_iso=0.001,
        )
        time_history.append(metrics)
    
    result = aggregate_session_metrics(time_history, DoseStandard.NIOSH)
    
    assert result['total_seconds'] == 10
    assert result['total_duration_h'] > 0
    assert result['total_dose_pct'] > 0
    assert result['peak_max_dB'] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
