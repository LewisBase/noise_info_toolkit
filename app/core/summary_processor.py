# -*- coding: utf-8 -*-
"""
@DATE: 2026-04-06 10:00:00
@Author: Liu Hengjiang
@File: app/core/summary_processor.py
@Software: vscode
@Description:
        时段数据汇聚处理器
        实现秒级数据到时段级数据的汇聚计算
        支持峰度的跨时段合成（根据规范 4.X.6）
"""

import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Callable
from dataclasses import dataclass
from enum import Enum

from app.core.time_history_processor import SecondMetrics, TimeHistoryProcessor
from app.utils import logger


class AggregationLevel(Enum):
    """汇聚级别"""
    SECOND = 1
    MINUTE = 60
    FIVE_MINUTES = 300
    TEN_MINUTES = 600
    FIFTEEN_MINUTES = 900
    THIRTY_MINUTES = 1800
    HOUR = 3600


@dataclass
class AggregatedMetrics:
    """时段汇聚后的指标数据"""
    # 时间信息
    start_time: datetime
    end_time: datetime
    duration_s: float
    sample_count: int  # 包含的秒数
    
    # 声级指标（能量平均）
    LAeq: float
    LCeq: float
    LZeq: float
    LZpeak: float
    LCpeak: float
    
    # 剂量累计
    dose_frac_niosh: float
    dose_frac_osha_pel: float
    dose_frac_osha_hca: float
    dose_frac_eu_iso: float
    
    # 峰度（根据规范 4.X.6 合成）
    beta_kurtosis: Optional[float] = None  # 基于 S1-S4 合成的峰度
    
    # 原始矩统计量（用于进一步向上聚合）
    n_samples: int = 0             # 总样本数 N = Σn_i
    sum_x: float = 0.0             # S1^(total) = ΣS1,i
    sum_x2: float = 0.0            # S2^(total) = ΣS2,i
    sum_x3: float = 0.0            # S3^(total) = ΣS3,i
    sum_x4: float = 0.0            # S4^(total) = ΣS4,i
    
    # 1/3倍频程频段SPL（能量平均聚合）
    freq_63hz_spl: Optional[float] = None
    freq_125hz_spl: Optional[float] = None
    freq_250hz_spl: Optional[float] = None
    freq_500hz_spl: Optional[float] = None
    freq_1khz_spl: Optional[float] = None
    freq_2khz_spl: Optional[float] = None
    freq_4khz_spl: Optional[float] = None
    freq_8khz_spl: Optional[float] = None
    freq_16khz_spl: Optional[float] = None
    
    # 1/3倍频程频段峰度（基于S1-S4合成，根据规范4.X.6）
    freq_63hz_kurtosis: Optional[float] = None
    freq_125hz_kurtosis: Optional[float] = None
    freq_250hz_kurtosis: Optional[float] = None
    freq_500hz_kurtosis: Optional[float] = None
    freq_1khz_kurtosis: Optional[float] = None
    freq_2khz_kurtosis: Optional[float] = None
    freq_4khz_kurtosis: Optional[float] = None
    freq_8khz_kurtosis: Optional[float] = None
    freq_16khz_kurtosis: Optional[float] = None
    
    # 1/3倍频程频段原始矩统计量（用于进一步向上聚合）
    freq_63hz_n: int = 0; freq_63hz_s1: float = 0.0; freq_63hz_s2: float = 0.0; freq_63hz_s3: float = 0.0; freq_63hz_s4: float = 0.0
    freq_125hz_n: int = 0; freq_125hz_s1: float = 0.0; freq_125hz_s2: float = 0.0; freq_125hz_s3: float = 0.0; freq_125hz_s4: float = 0.0
    freq_250hz_n: int = 0; freq_250hz_s1: float = 0.0; freq_250hz_s2: float = 0.0; freq_250hz_s3: float = 0.0; freq_250hz_s4: float = 0.0
    freq_500hz_n: int = 0; freq_500hz_s1: float = 0.0; freq_500hz_s2: float = 0.0; freq_500hz_s3: float = 0.0; freq_500hz_s4: float = 0.0
    freq_1khz_n: int = 0; freq_1khz_s1: float = 0.0; freq_1khz_s2: float = 0.0; freq_1khz_s3: float = 0.0; freq_1khz_s4: float = 0.0
    freq_2khz_n: int = 0; freq_2khz_s1: float = 0.0; freq_2khz_s2: float = 0.0; freq_2khz_s3: float = 0.0; freq_2khz_s4: float = 0.0
    freq_4khz_n: int = 0; freq_4khz_s1: float = 0.0; freq_4khz_s2: float = 0.0; freq_4khz_s3: float = 0.0; freq_4khz_s4: float = 0.0
    freq_8khz_n: int = 0; freq_8khz_s1: float = 0.0; freq_8khz_s2: float = 0.0; freq_8khz_s3: float = 0.0; freq_8khz_s4: float = 0.0
    freq_16khz_n: int = 0; freq_16khz_s1: float = 0.0; freq_16khz_s2: float = 0.0; freq_16khz_s3: float = 0.0; freq_16khz_s4: float = 0.0
    
    # 质量控制
    valid_flag: bool = True
    artifact_flag: bool = False
    overload_count: int = 0
    underrange_count: int = 0
    valid_seconds: int = 0         # 有效秒数


class SummaryProcessor:
    """
    时段数据汇聚处理器
    
    根据规范 4.X.6，实现秒级原始矩统计量到时段级峰度的合成计算。
    核心原则：不得通过对秒级峰度值简单平均来生成时段峰度，
    必须通过对秒级原始矩统计块 (S1-S4) 进行累加后重新计算。
    """
    
    def __init__(self, aggregation_seconds: int = 60):
        """
        初始化汇聚处理器
        
        Args:
            aggregation_seconds: 汇聚时段长度（秒），默认 60 秒（1 分钟）
        """
        self.aggregation_seconds = aggregation_seconds
        self._buffer: List[SecondMetrics] = []
        self._callback: Optional[Callable[[AggregatedMetrics], None]] = None
        
        # 统计信息
        self._total_processed_seconds = 0
        self._total_aggregated_windows = 0
    
    def set_callback(self, callback: Callable[[AggregatedMetrics], None]):
        """设置时段汇聚完成后的回调函数"""
        self._callback = callback
    
    def add_second_metrics(self, metrics: SecondMetrics) -> Optional[AggregatedMetrics]:
        """
        添加单秒数据，当积累到指定时段时进行汇聚
        
        Args:
            metrics: 单秒指标数据
            
        Returns:
            AggregatedMetrics: 当积累到完整时段时返回汇聚结果，否则返回 None
        """
        self._buffer.append(metrics)
        self._total_processed_seconds += 1
        
        # 检查是否达到汇聚条件
        if len(self._buffer) >= self.aggregation_seconds:
            return self._flush_buffer()
        return None
    
    def flush_remaining(self) -> Optional[AggregatedMetrics]:
        """
        强制汇聚缓冲区中剩余的数据
        
        Returns:
            AggregatedMetrics: 如果有剩余数据则返回汇聚结果，否则返回 None
        """
        if len(self._buffer) > 0:
            return self._flush_buffer(force=True)
        return None
    
    def _flush_buffer(self, force: bool = False) -> AggregatedMetrics:
        """
        汇聚缓冲区中的数据
        
        Args:
            force: 是否强制汇聚（即使不足指定时段）
            
        Returns:
            AggregatedMetrics: 汇聚后的指标
        """
        if not self._buffer:
            return None
        
        # 计算汇聚结果
        aggregated = self._aggregate_metrics(self._buffer)
        
        # 清空缓冲区
        self._buffer = []
        self._total_aggregated_windows += 1
        
        # 调用回调
        if self._callback:
            self._callback(aggregated)
        
        return aggregated
    
    def _aggregate_metrics(self, seconds_data: List[SecondMetrics]) -> AggregatedMetrics:
        """
        汇聚秒级数据到时时段级数据
        
        根据规范 4.X.6：
        1. 对秒级原始矩统计块 (n_i, S1,i, S2,i, S3,i, S4,i) 进行累加
        2. 基于累加后的统计量重新计算峰度
        
        Args:
            seconds_data: 秒级数据列表
            
        Returns:
            AggregatedMetrics: 汇聚后的时段指标
        """
        if not seconds_data:
            raise ValueError("Empty seconds data")
        
        # 时间信息
        start_time = min(s.timestamp for s in seconds_data)
        end_time = max(s.timestamp for s in seconds_data)
        duration_s = sum(s.duration_s for s in seconds_data)
        sample_count = len(seconds_data)
        
        # === 根据规范 4.X.6.2 合成原始矩统计量 ===
        # N = Σn_i
        n_samples = sum(s.n_samples for s in seconds_data)
        
        # S1^(total) = ΣS1,i
        sum_x = sum(s.sum_x for s in seconds_data)
        
        # S2^(total) = ΣS2,i
        sum_x2 = sum(s.sum_x2 for s in seconds_data)
        
        # S3^(total) = ΣS3,i
        sum_x3 = sum(s.sum_x3 for s in seconds_data)
        
        # S4^(total) = ΣS4,i
        sum_x4 = sum(s.sum_x4 for s in seconds_data)
        
        # === 根据规范 4.X.6.2 重新计算峰度 ===
        beta_kurtosis = TimeHistoryProcessor.calculate_kurtosis_from_moments(
            n_samples, sum_x, sum_x2, sum_x3, sum_x4
        )
        
        # === 声级指标的能量平均 ===
        # LAeq_total = 10 * log10( (1/n) * Σ(10^(LAeq_i/10)) )
        laeq_values = [s.LAeq for s in seconds_data if s.LAeq is not None]
        LAeq = self._energy_average(laeq_values) if laeq_values else 0.0
        
        lceq_values = [s.LCeq for s in seconds_data if s.LCeq is not None]
        LCeq = self._energy_average(lceq_values) if lceq_values else 0.0
        
        lzeq_values = [s.LZeq for s in seconds_data if s.LZeq is not None]
        LZeq = self._energy_average(lzeq_values) if lzeq_values else 0.0
        
        # 峰值取最大值
        lzpeak_values = [s.LZpeak for s in seconds_data if s.LZpeak is not None]
        LZpeak = max(lzpeak_values) if lzpeak_values else 0.0
        
        lcpeak_values = [s.LCpeak for s in seconds_data if s.LCpeak is not None]
        LCpeak = max(lcpeak_values) if lcpeak_values else 0.0
        
        # === 剂量累计 ===
        dose_frac_niosh = sum(s.dose_frac_niosh for s in seconds_data)
        dose_frac_osha_pel = sum(s.dose_frac_osha_pel for s in seconds_data)
        dose_frac_osha_hca = sum(s.dose_frac_osha_hca for s in seconds_data)
        dose_frac_eu_iso = sum(s.dose_frac_eu_iso for s in seconds_data)
        
        # === 1/3倍频程频段SPL聚合（能量平均） ===
        freq_spl_63hz = self._energy_average([s.freq_63hz_spl for s in seconds_data if s.freq_63hz_spl is not None])
        freq_spl_125hz = self._energy_average([s.freq_125hz_spl for s in seconds_data if s.freq_125hz_spl is not None])
        freq_spl_250hz = self._energy_average([s.freq_250hz_spl for s in seconds_data if s.freq_250hz_spl is not None])
        freq_spl_500hz = self._energy_average([s.freq_500hz_spl for s in seconds_data if s.freq_500hz_spl is not None])
        freq_spl_1khz = self._energy_average([s.freq_1khz_spl for s in seconds_data if s.freq_1khz_spl is not None])
        freq_spl_2khz = self._energy_average([s.freq_2khz_spl for s in seconds_data if s.freq_2khz_spl is not None])
        freq_spl_4khz = self._energy_average([s.freq_4khz_spl for s in seconds_data if s.freq_4khz_spl is not None])
        freq_spl_8khz = self._energy_average([s.freq_8khz_spl for s in seconds_data if s.freq_8khz_spl is not None])
        freq_spl_16khz = self._energy_average([s.freq_16khz_spl for s in seconds_data if s.freq_16khz_spl is not None])
        
        # === 1/3倍频程频段峰度聚合（基于S1-S4合成，根据规范4.X.6） ===
        # 累加频段原始矩统计量
        def _aggregate_freq_moments(attr_n, attr_s1, attr_s2, attr_s3, attr_s4):
            """聚合频段的S1-S4，返回(n_total, s1_total, s2_total, s3_total, s4_total, beta)"""
            n_total = sum(getattr(s, attr_n) for s in seconds_data)
            s1_total = sum(getattr(s, attr_s1) for s in seconds_data)
            s2_total = sum(getattr(s, attr_s2) for s in seconds_data)
            s3_total = sum(getattr(s, attr_s3) for s in seconds_data)
            s4_total = sum(getattr(s, attr_s4) for s in seconds_data)
            beta = TimeHistoryProcessor.calculate_kurtosis_from_moments(n_total, s1_total, s2_total, s3_total, s4_total)
            return n_total, s1_total, s2_total, s3_total, s4_total, beta
        
        # 63Hz频段
        freq_63hz_n, freq_63hz_s1, freq_63hz_s2, freq_63hz_s3, freq_63hz_s4, freq_kurt_63hz = _aggregate_freq_moments(
            'freq_63hz_n', 'freq_63hz_s1', 'freq_63hz_s2', 'freq_63hz_s3', 'freq_63hz_s4')
        # 125Hz频段
        freq_125hz_n, freq_125hz_s1, freq_125hz_s2, freq_125hz_s3, freq_125hz_s4, freq_kurt_125hz = _aggregate_freq_moments(
            'freq_125hz_n', 'freq_125hz_s1', 'freq_125hz_s2', 'freq_125hz_s3', 'freq_125hz_s4')
        # 250Hz频段
        freq_250hz_n, freq_250hz_s1, freq_250hz_s2, freq_250hz_s3, freq_250hz_s4, freq_kurt_250hz = _aggregate_freq_moments(
            'freq_250hz_n', 'freq_250hz_s1', 'freq_250hz_s2', 'freq_250hz_s3', 'freq_250hz_s4')
        # 500Hz频段
        freq_500hz_n, freq_500hz_s1, freq_500hz_s2, freq_500hz_s3, freq_500hz_s4, freq_kurt_500hz = _aggregate_freq_moments(
            'freq_500hz_n', 'freq_500hz_s1', 'freq_500hz_s2', 'freq_500hz_s3', 'freq_500hz_s4')
        # 1kHz频段
        freq_1khz_n, freq_1khz_s1, freq_1khz_s2, freq_1khz_s3, freq_1khz_s4, freq_kurt_1khz = _aggregate_freq_moments(
            'freq_1khz_n', 'freq_1khz_s1', 'freq_1khz_s2', 'freq_1khz_s3', 'freq_1khz_s4')
        # 2kHz频段
        freq_2khz_n, freq_2khz_s1, freq_2khz_s2, freq_2khz_s3, freq_2khz_s4, freq_kurt_2khz = _aggregate_freq_moments(
            'freq_2khz_n', 'freq_2khz_s1', 'freq_2khz_s2', 'freq_2khz_s3', 'freq_2khz_s4')
        # 4kHz频段
        freq_4khz_n, freq_4khz_s1, freq_4khz_s2, freq_4khz_s3, freq_4khz_s4, freq_kurt_4khz = _aggregate_freq_moments(
            'freq_4khz_n', 'freq_4khz_s1', 'freq_4khz_s2', 'freq_4khz_s3', 'freq_4khz_s4')
        # 8kHz频段
        freq_8khz_n, freq_8khz_s1, freq_8khz_s2, freq_8khz_s3, freq_8khz_s4, freq_kurt_8khz = _aggregate_freq_moments(
            'freq_8khz_n', 'freq_8khz_s1', 'freq_8khz_s2', 'freq_8khz_s3', 'freq_8khz_s4')
        # 16kHz频段
        freq_16khz_n, freq_16khz_s1, freq_16khz_s2, freq_16khz_s3, freq_16khz_s4, freq_kurt_16khz = _aggregate_freq_moments(
            'freq_16khz_n', 'freq_16khz_s1', 'freq_16khz_s2', 'freq_16khz_s3', 'freq_16khz_s4')
        
        # === 质量控制统计 ===
        overload_count = sum(1 for s in seconds_data if s.overload_flag)
        underrange_count = sum(1 for s in seconds_data if s.underrange_flag)
        valid_seconds = sum(1 for s in seconds_data if s.wearing_state)
        
        # 有效性判断：有效秒数超过 50% 且无明显伪噪声
        valid_flag = valid_seconds >= (sample_count * 0.5)
        
        return AggregatedMetrics(
            start_time=start_time,
            end_time=end_time,
            duration_s=duration_s,
            sample_count=sample_count,
            LAeq=round(LAeq, 2),
            LCeq=round(LCeq, 2),
            LZeq=round(LZeq, 2),
            LZpeak=round(LZpeak, 2),
            LCpeak=round(LCpeak, 2),
            dose_frac_niosh=round(dose_frac_niosh, 6),
            dose_frac_osha_pel=round(dose_frac_osha_pel, 6),
            dose_frac_osha_hca=round(dose_frac_osha_hca, 6),
            dose_frac_eu_iso=round(dose_frac_eu_iso, 6),
            beta_kurtosis=round(beta_kurtosis, 4) if beta_kurtosis is not None else None,
            n_samples=n_samples,
            sum_x=sum_x,
            sum_x2=sum_x2,
            sum_x3=sum_x3,
            sum_x4=sum_x4,
            # 1/3倍频程频段SPL
            freq_63hz_spl=round(freq_spl_63hz, 2) if freq_spl_63hz else None,
            freq_125hz_spl=round(freq_spl_125hz, 2) if freq_spl_125hz else None,
            freq_250hz_spl=round(freq_spl_250hz, 2) if freq_spl_250hz else None,
            freq_500hz_spl=round(freq_spl_500hz, 2) if freq_spl_500hz else None,
            freq_1khz_spl=round(freq_spl_1khz, 2) if freq_spl_1khz else None,
            freq_2khz_spl=round(freq_spl_2khz, 2) if freq_spl_2khz else None,
            freq_4khz_spl=round(freq_spl_4khz, 2) if freq_spl_4khz else None,
            freq_8khz_spl=round(freq_spl_8khz, 2) if freq_spl_8khz else None,
            freq_16khz_spl=round(freq_spl_16khz, 2) if freq_spl_16khz else None,
            # 1/3倍频程频段峰度
            freq_63hz_kurtosis=round(freq_kurt_63hz, 2) if freq_kurt_63hz else None,
            freq_125hz_kurtosis=round(freq_kurt_125hz, 2) if freq_kurt_125hz else None,
            freq_250hz_kurtosis=round(freq_kurt_250hz, 2) if freq_kurt_250hz else None,
            freq_500hz_kurtosis=round(freq_kurt_500hz, 2) if freq_kurt_500hz else None,
            freq_1khz_kurtosis=round(freq_kurt_1khz, 2) if freq_kurt_1khz else None,
            freq_2khz_kurtosis=round(freq_kurt_2khz, 2) if freq_kurt_2khz else None,
            freq_4khz_kurtosis=round(freq_kurt_4khz, 2) if freq_kurt_4khz else None,
            freq_8khz_kurtosis=round(freq_kurt_8khz, 2) if freq_kurt_8khz else None,
            freq_16khz_kurtosis=round(freq_kurt_16khz, 2) if freq_kurt_16khz else None,
            # 1/3倍频程频段原始矩统计量（用于进一步向上聚合）
            freq_63hz_n=freq_63hz_n, freq_63hz_s1=freq_63hz_s1, freq_63hz_s2=freq_63hz_s2, freq_63hz_s3=freq_63hz_s3, freq_63hz_s4=freq_63hz_s4,
            freq_125hz_n=freq_125hz_n, freq_125hz_s1=freq_125hz_s1, freq_125hz_s2=freq_125hz_s2, freq_125hz_s3=freq_125hz_s3, freq_125hz_s4=freq_125hz_s4,
            freq_250hz_n=freq_250hz_n, freq_250hz_s1=freq_250hz_s1, freq_250hz_s2=freq_250hz_s2, freq_250hz_s3=freq_250hz_s3, freq_250hz_s4=freq_250hz_s4,
            freq_500hz_n=freq_500hz_n, freq_500hz_s1=freq_500hz_s1, freq_500hz_s2=freq_500hz_s2, freq_500hz_s3=freq_500hz_s3, freq_500hz_s4=freq_500hz_s4,
            freq_1khz_n=freq_1khz_n, freq_1khz_s1=freq_1khz_s1, freq_1khz_s2=freq_1khz_s2, freq_1khz_s3=freq_1khz_s3, freq_1khz_s4=freq_1khz_s4,
            freq_2khz_n=freq_2khz_n, freq_2khz_s1=freq_2khz_s1, freq_2khz_s2=freq_2khz_s2, freq_2khz_s3=freq_2khz_s3, freq_2khz_s4=freq_2khz_s4,
            freq_4khz_n=freq_4khz_n, freq_4khz_s1=freq_4khz_s1, freq_4khz_s2=freq_4khz_s2, freq_4khz_s3=freq_4khz_s3, freq_4khz_s4=freq_4khz_s4,
            freq_8khz_n=freq_8khz_n, freq_8khz_s1=freq_8khz_s1, freq_8khz_s2=freq_8khz_s2, freq_8khz_s3=freq_8khz_s3, freq_8khz_s4=freq_8khz_s4,
            freq_16khz_n=freq_16khz_n, freq_16khz_s1=freq_16khz_s1, freq_16khz_s2=freq_16khz_s2, freq_16khz_s3=freq_16khz_s3, freq_16khz_s4=freq_16khz_s4,
            valid_flag=valid_flag,
            overload_count=overload_count,
            underrange_count=underrange_count,
            valid_seconds=valid_seconds
        )
    
    @staticmethod
    def _energy_average(db_values: List[float]) -> float:
        """
        计算声级的能量平均
        
        LAeq_avg = 10 * log10( mean(10^(L/10)) )
        
        Args:
            db_values: 声级值列表 (dB)
            
        Returns:
            float: 能量平均声级
        """
        if not db_values:
            return 0.0
        
        # 转换为能量域，求平均，再转回 dB
        energy_values = [10 ** (l / 10) for l in db_values]
        mean_energy = np.mean(energy_values)
        
        if mean_energy <= 0:
            return 0.0
        
        return 10 * np.log10(mean_energy)
    
    def get_stats(self) -> Dict:
        """获取处理统计信息"""
        return {
            "total_processed_seconds": self._total_processed_seconds,
            "total_aggregated_windows": self._total_aggregated_windows,
            "aggregation_seconds": self.aggregation_seconds,
            "buffer_size": len(self._buffer)
        }
    
    def reset_stats(self):
        """重置统计信息"""
        self._total_processed_seconds = 0
        self._total_aggregated_windows = 0


class MultiLevelAggregator:
    """
    多级汇聚器
    
    支持从秒级 → 分钟级 → 更高级别的逐级汇聚
    """
    
    def __init__(self):
        self.levels: Dict[AggregationLevel, SummaryProcessor] = {}
        self._current_level = AggregationLevel.SECOND
    
    def add_level(self, level: AggregationLevel, 
                  callback: Optional[Callable[[AggregatedMetrics], None]] = None):
        """
        添加汇聚级别
        
        Args:
            level: 汇聚级别
            callback: 该级别汇聚完成后的回调函数
        """
        processor = SummaryProcessor(aggregation_seconds=level.value)
        if callback:
            processor.set_callback(callback)
        self.levels[level] = processor
        
        logger.info(f"Added aggregation level: {level.name} ({level.value}s)")
    
    def process_second(self, metrics: SecondMetrics) -> Dict[AggregationLevel, Optional[AggregatedMetrics]]:
        """
        处理单秒数据，触发所有级别的汇聚
        
        Args:
            metrics: 单秒指标
            
        Returns:
            Dict: 各级别汇聚结果（如果该级别完成汇聚）
        """
        results = {}
        
        for level, processor in self.levels.items():
            result = processor.add_second_metrics(metrics)
            if result is not None:
                results[level] = result
        
        return results
    
    def flush_all(self) -> Dict[AggregationLevel, Optional[AggregatedMetrics]]:
        """
        强制汇聚所有级别的剩余数据
        
        Returns:
            Dict: 各级别汇聚结果
        """
        results = {}
        
        for level, processor in self.levels.items():
            result = processor.flush_remaining()
            if result is not None:
                results[level] = result
        
        return results


def aggregate_from_moment_blocks(blocks: List[Tuple[int, float, float, float, float]]) -> Optional[float]:
    """
    从多个矩统计块合成峰度（纯函数，便于测试）
    
    根据规范 4.X.6.2：
    - 输入: [(n_i, S1,i, S2,i, S3,i, S4,i), ...]
    - 输出: 合成后的峰度值 β
    
    Args:
        blocks: 矩统计块列表，每个块为 (n, s1, s2, s3, s4)
        
    Returns:
        float: 合成后的峰度值，如果无效则返回 None
    """
    if not blocks:
        return None
    
    # 累加统计量
    n_total = sum(b[0] for b in blocks)
    s1_total = sum(b[1] for b in blocks)
    s2_total = sum(b[2] for b in blocks)
    s3_total = sum(b[3] for b in blocks)
    s4_total = sum(b[4] for b in blocks)
    
    # 计算合成峰度
    return TimeHistoryProcessor.calculate_kurtosis_from_moments(
        n_total, s1_total, s2_total, s3_total, s4_total
    )


def compare_kurtosis_methods(signal_data: np.ndarray, 
                             sample_rate: int = 48000) -> Dict:
    """
    比较直接计算和分块合成两种峰度计算方法的结果
    
    用于验证规范 4.X.11.1 的一致性要求。
    
    Args:
        signal_data: 音频信号数据
        sample_rate: 采样率
        
    Returns:
        Dict: 包含两种方法和差异的对比结果
    """
    from scipy.stats import kurtosis
    
    # 路径 A：直接计算整段信号的峰度
    kurtosis_direct = kurtosis(signal_data, fisher=False)
    
    # 路径 B：分块计算后合成
    samples_per_second = sample_rate
    total_samples = len(signal_data)
    total_seconds = int(np.ceil(total_samples / samples_per_second))
    
    blocks = []
    for i in range(total_seconds):
        start = i * samples_per_second
        end = min((i + 1) * samples_per_second, total_samples)
        second_data = signal_data[start:end]
        
        if len(second_data) > 0:
            n = len(second_data)
            s1 = np.sum(second_data)
            s2 = np.sum(second_data ** 2)
            s3 = np.sum(second_data ** 3)
            s4 = np.sum(second_data ** 4)
            blocks.append((n, s1, s2, s3, s4))
    
    # 合成峰度
    kurtosis_aggregated = aggregate_from_moment_blocks(blocks)
    
    # 计算差异
    if kurtosis_aggregated is not None:
        difference = abs(kurtosis_direct - kurtosis_aggregated)
        relative_error = difference / kurtosis_direct if kurtosis_direct != 0 else 0
    else:
        difference = None
        relative_error = None
    
    return {
        "kurtosis_direct": float(kurtosis_direct),
        "kurtosis_aggregated": kurtosis_aggregated,
        "difference": difference,
        "relative_error": relative_error,
        "consistent": relative_error < 0.01 if relative_error is not None else False  # 1% 容差
    }
