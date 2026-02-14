# -*- coding: utf-8 -*-
"""
@DATE: 2026-02-14 20:15:00
@Author: Liu Hengjiang
@File: app/core/session_manager.py
@Software: vscode
@Description:
        Session管理器
        管理测量会话的生命周期、实时剂量累计和状态跟踪
"""

import uuid
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock

from app.core.dose_calculator import DoseCalculator, DoseStandard
from app.core.time_history_processor import SecondMetrics, aggregate_session_metrics
from app.utils import logger


class SessionState(Enum):
    """会话状态"""
    IDLE = "idle"           # 空闲
    RUNNING = "running"     # 运行中
    PAUSED = "paused"       # 暂停
    STOPPED = "stopped"     # 已停止
    ERROR = "error"         # 错误


@dataclass
class SessionConfig:
    """会话配置"""
    profile: DoseStandard = DoseStandard.NIOSH  # 默认使用NIOSH标准
    device_id: Optional[str] = None
    operator: Optional[str] = None
    organization: Optional[str] = None
    worker_role: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class SessionMetrics:
    """会话实时指标（累计值）"""
    # Timing
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    last_update_time: Optional[datetime] = None
    total_duration_s: float = 0.0
    
    # Current second metrics
    current_LAeq: float = 0.0
    current_LCeq: float = 0.0
    current_LZeq: float = 0.0
    current_LZpeak: float = 0.0
    
    # Cumulative dose for all standards
    cumulative_dose_niosh: float = 0.0
    cumulative_dose_osha_pel: float = 0.0
    cumulative_dose_osha_hca: float = 0.0
    cumulative_dose_eu_iso: float = 0.0
    
    # Current TWA (based on selected profile)
    current_TWA: float = 0.0
    current_LEX_8h: float = 0.0
    
    # Peak tracking
    max_peak_dB: float = 0.0
    
    # Quality control
    overload_count: int = 0
    underrange_count: int = 0
    not_wearing_count: int = 0
    
    # Event count
    event_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'last_update_time': self.last_update_time.isoformat() if self.last_update_time else None,
            'total_duration_s': round(self.total_duration_s, 2),
            'current_LAeq': round(self.current_LAeq, 2),
            'current_LCeq': round(self.current_LCeq, 2),
            'current_LZeq': round(self.current_LZeq, 2),
            'current_LZpeak': round(self.current_LZpeak, 2),
            'cumulative_dose_niosh': round(self.cumulative_dose_niosh, 4),
            'cumulative_dose_osha_pel': round(self.cumulative_dose_osha_pel, 4),
            'cumulative_dose_osha_hca': round(self.cumulative_dose_osha_hca, 4),
            'cumulative_dose_eu_iso': round(self.cumulative_dose_eu_iso, 4),
            'current_TWA': round(self.current_TWA, 2),
            'current_LEX_8h': round(self.current_LEX_8h, 2),
            'max_peak_dB': round(self.max_peak_dB, 2),
            'overload_count': self.overload_count,
            'underrange_count': self.underrange_count,
            'not_wearing_count': self.not_wearing_count,
            'event_count': self.event_count,
        }


class SessionManager:
    """
    Session管理器
    
    管理一个测量会话的生命周期：
    - 开始/暂停/停止会话
    - 实时累计剂量
    - 质量控制和事件计数
    """
    
    def __init__(self, 
                 session_id: Optional[str] = None,
                 config: Optional[SessionConfig] = None):
        """
        初始化Session管理器
        
        Args:
            session_id: 会话ID，默认为自动生成UUID
            config: 会话配置
        """
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.config = config or SessionConfig()
        self.state = SessionState.IDLE
        self.metrics = SessionMetrics()
        self.time_history: List[SecondMetrics] = []
        
        self._lock = Lock()
        self._dose_calculator = DoseCalculator()
        self._callbacks: List[Callable[[SecondMetrics], None]] = []
        
        logger.info(f"SessionManager initialized: session_id={self.session_id}")
    
    def add_callback(self, callback: Callable[[SecondMetrics], None]):
        """添加每秒钟数据处理后的回调函数"""
        self._callbacks.append(callback)
    
    def start(self) -> 'SessionManager':
        """开始会话"""
        with self._lock:
            if self.state == SessionState.RUNNING:
                logger.warning(f"Session {self.session_id} is already running")
                return self
            
            self.state = SessionState.RUNNING
            self.metrics.start_time = datetime.utcnow()
            self.metrics.last_update_time = self.metrics.start_time
            
            logger.info(f"Session {self.session_id} started at {self.metrics.start_time}")
        
        return self
    
    def pause(self) -> 'SessionManager':
        """暂停会话"""
        with self._lock:
            if self.state != SessionState.RUNNING:
                logger.warning(f"Cannot pause session {self.session_id}: not running")
                return self
            
            self.state = SessionState.PAUSED
            logger.info(f"Session {self.session_id} paused")
        
        return self
    
    def resume(self) -> 'SessionManager':
        """恢复会话"""
        with self._lock:
            if self.state != SessionState.PAUSED:
                logger.warning(f"Cannot resume session {self.session_id}: not paused")
                return self
            
            self.state = SessionState.RUNNING
            self.metrics.last_update_time = datetime.utcnow()
            logger.info(f"Session {self.session_id} resumed")
        
        return self
    
    def stop(self) -> 'SessionManager':
        """停止会话"""
        with self._lock:
            if self.state == SessionState.STOPPED:
                logger.warning(f"Session {self.session_id} is already stopped")
                return self
            
            self.state = SessionState.STOPPED
            self.metrics.end_time = datetime.utcnow()
            
            logger.info(f"Session {self.session_id} stopped at {self.metrics.end_time}")
            logger.info(f"  Total duration: {self.metrics.total_duration_s:.1f}s")
            logger.info(f"  Total dose (NIOSH): {self.metrics.cumulative_dose_niosh:.4f}%")
        
        return self
    
    def process_second(self, metrics: SecondMetrics) -> 'SessionManager':
        """
        处理一秒钟的数据
        
        Args:
            metrics: 单秒钟的指标
        """
        with self._lock:
            if self.state != SessionState.RUNNING:
                return self
            
            # Update timing
            self.metrics.last_update_time = datetime.utcnow()
            self.metrics.total_duration_s += metrics.duration_s
            
            # Update current second metrics
            self.metrics.current_LAeq = metrics.LAeq
            self.metrics.current_LCeq = metrics.LCeq
            self.metrics.current_LZeq = metrics.LZeq
            self.metrics.current_LZpeak = metrics.LZpeak or 0.0
            
            # Accumulate dose for all standards
            self.metrics.cumulative_dose_niosh += metrics.dose_frac_niosh
            self.metrics.cumulative_dose_osha_pel += metrics.dose_frac_osha_pel
            self.metrics.cumulative_dose_osha_hca += metrics.dose_frac_osha_hca
            self.metrics.cumulative_dose_eu_iso += metrics.dose_frac_eu_iso
            
            # Calculate TWA based on selected profile
            dose_map = {
                DoseStandard.NIOSH: self.metrics.cumulative_dose_niosh,
                DoseStandard.OSHA_PEL: self.metrics.cumulative_dose_osha_pel,
                DoseStandard.OSHA_HCA: self.metrics.cumulative_dose_osha_hca,
                DoseStandard.EU_ISO: self.metrics.cumulative_dose_eu_iso,
            }
            current_dose = dose_map.get(self.config.profile, self.metrics.cumulative_dose_niosh)
            
            self.metrics.current_TWA = self._dose_calculator.calculate_twa(
                current_dose, self.config.profile)
            self.metrics.current_LEX_8h = self._dose_calculator.calculate_lex(
                current_dose, self.config.profile)
            
            # Update peak tracking
            if metrics.LZpeak and metrics.LZpeak > self.metrics.max_peak_dB:
                self.metrics.max_peak_dB = metrics.LZpeak
            
            # Quality control counters
            if metrics.overload_flag:
                self.metrics.overload_count += 1
            if metrics.underrange_flag:
                self.metrics.underrange_count += 1
            if not metrics.wearing_state:
                self.metrics.not_wearing_count += 1
            
            # Store in time history
            self.time_history.append(metrics)
        
        # Call callbacks (outside lock)
        for callback in self._callbacks:
            try:
                callback(metrics)
            except Exception as e:
                logger.error(f"Callback error: {e}")
        
        return self
    
    def get_current_metrics(self) -> SessionMetrics:
        """获取当前指标（复制）"""
        with self._lock:
            # Return a copy
            import copy
            return copy.copy(self.metrics)
    
    def get_summary(self) -> Dict[str, Any]:
        """获取会话摘要"""
        with self._lock:
            summary = {
                'session_id': self.session_id,
                'state': self.state.value,
                'config': {
                    'profile': self.config.profile.value,
                    'device_id': self.config.device_id,
                    'operator': self.config.operator,
                },
                'metrics': self.metrics.to_dict(),
                'total_seconds_processed': len(self.time_history),
            }
            
            # Add summary for selected profile
            profile_summary = aggregate_session_metrics(
                self.time_history, self.config.profile)
            summary['profile_summary'] = profile_summary
            
            return summary
    
    def get_time_history_df(self) -> Optional[Any]:
        """获取时间历程DataFrame"""
        if not self.time_history:
            return None
        
        import pandas as pd
        
        data = []
        for m in self.time_history:
            data.append({
                'timestamp': m.timestamp,
                'LAeq': m.LAeq,
                'LCeq': m.LCeq,
                'LZeq': m.LZeq,
                'LZpeak': m.LZpeak,
                'dose_niosh': m.dose_frac_niosh,
                'dose_osha_pel': m.dose_frac_osha_pel,
                'dose_osha_hca': m.dose_frac_osha_hca,
                'dose_eu_iso': m.dose_frac_eu_iso,
                'overload': m.overload_flag,
                'underrange': m.underrange_flag,
                'wearing': m.wearing_state,
            })
        
        return pd.DataFrame(data)


class SessionRegistry:
    """会话注册表 - 管理多个会话"""
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._sessions: Dict[str, SessionManager] = {}
        return cls._instance
    
    def create_session(self, 
                       session_id: Optional[str] = None,
                       config: Optional[SessionConfig] = None) -> SessionManager:
        """创建新会话"""
        session = SessionManager(session_id, config)
        self._sessions[session.session_id] = session
        logger.info(f"Session {session.session_id} registered")
        return session
    
    def get_session(self, session_id: str) -> Optional[SessionManager]:
        """获取会话"""
        return self._sessions.get(session_id)
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出所有会话"""
        return [
            {
                'session_id': sid,
                'state': session.state.value,
                'start_time': session.metrics.start_time.isoformat() if session.metrics.start_time else None,
            }
            for sid, session in self._sessions.items()
        ]
    
    def remove_session(self, session_id: str) -> bool:
        """移除会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Session {session_id} removed")
            return True
        return False
    
    def get_active_session(self) -> Optional[SessionManager]:
        """获取当前活动的会话（正在运行的）"""
        for session in self._sessions.values():
            if session.state == SessionState.RUNNING:
                return session
        return None


# Global registry instance
session_registry = SessionRegistry()
