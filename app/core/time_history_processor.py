# -*- coding: utf-8 -*-
"""
@DATE: 2026-02-14 20:00:00
@Author: Liu Hengjiang
@File: app/core/time_history_processor.py
@Software: vscode
@Description:
        时间历程数据处理器
        实现每秒数据处理并存储到TimeHistory表
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from acoustics import Signal
from acoustics.standards.iec_61672_1_2013 import (
    time_averaged_sound_level,
    average
)
from acoustics.standards.iso_tr_25417_2007 import (
    sound_pressure_level
)
from acoustics.standards.iso_tr_25417_2007 import (
    peak_sound_pressure_level,
    equivalent_sound_pressure_level
)
from scipy.stats import kurtosis

from app.core.dose_calculator import DoseCalculator, DoseStandard
from app.utils import logger


@dataclass
class SecondMetrics:
    """单秒钟的指标数据"""
    timestamp: datetime
    duration_s: float
    
    # Sound levels
    LAeq: float
    LCeq: float
    LZeq: float
    LAFmax: Optional[float] = None
    LZpeak: Optional[float] = None
    LCpeak: Optional[float] = None
    
    # Dose increments
    dose_frac_niosh: float = 0.0
    dose_frac_osha_pel: float = 0.0
    dose_frac_osha_hca: float = 0.0
    dose_frac_eu_iso: float = 0.0
    
    # Quality control
    overload_flag: bool = False
    underrange_flag: bool = False
    wearing_state: bool = True
    
    # Kurtosis - 直接计算的峰度值（向后兼容）
    kurtosis_total: Optional[float] = None       # Z加权（原始信号）峰度
    kurtosis_a_weighted: Optional[float] = None  # A加权峰度
    kurtosis_c_weighted: Optional[float] = None  # C加权峰度
    
    # 1/3倍频程频段数据（9个频段：63Hz-16kHz）
    # 频段SPL（用于秒级累加得到分钟级频谱）
    freq_63hz_spl: Optional[float] = None
    freq_125hz_spl: Optional[float] = None
    freq_250hz_spl: Optional[float] = None
    freq_500hz_spl: Optional[float] = None
    freq_1khz_spl: Optional[float] = None
    freq_2khz_spl: Optional[float] = None
    freq_4khz_spl: Optional[float] = None
    freq_8khz_spl: Optional[float] = None
    freq_16khz_spl: Optional[float] = None
    
    # 频段原始矩统计量 S1-S4（用于精确合成频段峰度，根据规范4.X.6）
    # 63Hz频段
    freq_63hz_n: int = 0
    freq_63hz_s1: float = 0.0
    freq_63hz_s2: float = 0.0
    freq_63hz_s3: float = 0.0
    freq_63hz_s4: float = 0.0
    # 125Hz频段
    freq_125hz_n: int = 0
    freq_125hz_s1: float = 0.0
    freq_125hz_s2: float = 0.0
    freq_125hz_s3: float = 0.0
    freq_125hz_s4: float = 0.0
    # 250Hz频段
    freq_250hz_n: int = 0
    freq_250hz_s1: float = 0.0
    freq_250hz_s2: float = 0.0
    freq_250hz_s3: float = 0.0
    freq_250hz_s4: float = 0.0
    # 500Hz频段
    freq_500hz_n: int = 0
    freq_500hz_s1: float = 0.0
    freq_500hz_s2: float = 0.0
    freq_500hz_s3: float = 0.0
    freq_500hz_s4: float = 0.0
    # 1kHz频段
    freq_1khz_n: int = 0
    freq_1khz_s1: float = 0.0
    freq_1khz_s2: float = 0.0
    freq_1khz_s3: float = 0.0
    freq_1khz_s4: float = 0.0
    # 2kHz频段
    freq_2khz_n: int = 0
    freq_2khz_s1: float = 0.0
    freq_2khz_s2: float = 0.0
    freq_2khz_s3: float = 0.0
    freq_2khz_s4: float = 0.0
    # 4kHz频段
    freq_4khz_n: int = 0
    freq_4khz_s1: float = 0.0
    freq_4khz_s2: float = 0.0
    freq_4khz_s3: float = 0.0
    freq_4khz_s4: float = 0.0
    # 8kHz频段
    freq_8khz_n: int = 0
    freq_8khz_s1: float = 0.0
    freq_8khz_s2: float = 0.0
    freq_8khz_s3: float = 0.0
    freq_8khz_s4: float = 0.0
    # 16kHz频段
    freq_16khz_n: int = 0
    freq_16khz_s1: float = 0.0
    freq_16khz_s2: float = 0.0
    freq_16khz_s3: float = 0.0
    freq_16khz_s4: float = 0.0
    
    # 峰度计算的原始矩统计量 S1-S4 (根据规范 4.X.3)
    # 用于跨时段合成峰度值
    n_samples: int = 0           # 样本数 n
    sum_x: float = 0.0           # S1 = Σx_k
    sum_x2: float = 0.0          # S2 = Σx_k²
    sum_x3: float = 0.0          # S3 = Σx_k³
    sum_x4: float = 0.0          # S4 = Σx_k⁴
    beta_kurtosis: Optional[float] = None  # 基于原始矩计算的峰度 β


class TimeHistoryProcessor:
    """时间历程数据处理器 - 处理每秒音频数据"""
    
    # 过载阈值 (dB)
    OVERLOAD_THRESHOLD = 140.0
    # 欠载阈值 (dB)
    UNDERRANGE_THRESHOLD = 30.0
    
    def __init__(self, 
                 reference_pressure: float = 20e-6,
                 callback: Optional[Callable[[SecondMetrics], None]] = None):
        """
        初始化处理器
        
        Args:
            reference_pressure: 参考声压 (Pa)
            callback: 每秒钟数据处理完成后的回调函数
        """
        self.reference_pressure = reference_pressure
        self.callback = callback
        self.dose_calculator = DoseCalculator()
    
    @staticmethod
    def calculate_kurtosis_from_moments(n: int, s1: float, s2: float, s3: float, s4: float) -> Optional[float]:
        """
        根据原始矩统计量计算峰度 β (根据规范 4.X.3)
        
        公式:
        - µ = S1 / n
        - m2 = S2/n - µ²
        - m4 = S4/n - 4µ·S3/n + 6µ²·S2/n - 3µ⁴
        - β = m4 / m2²
        
        Args:
            n: 样本数
            s1: S1 = Σx_k
            s2: S2 = Σx_k²
            s3: S3 = Σx_k³
            s4: S4 = Σx_k⁴
            
        Returns:
            float: 峰度值 β，如果计算无效则返回 None
        """
        if n <= 0:
            return None
        
        # 计算均值 µ = S1 / n
        mu = s1 / n
        
        # 计算二阶中心矩 m2 = S2/n - µ²
        m2 = s2 / n - mu ** 2
        
        # 边界条件：m2 必须为正 (根据规范 4.X.5.3)
        if m2 <= 0:
            return None
        
        # 计算四阶中心矩 m4 = S4/n - 4µ·S3/n + 6µ²·S2/n - 3µ⁴
        m4 = (s4 / n 
              - 4 * mu * (s3 / n) 
              + 6 * (mu ** 2) * (s2 / n) 
              - 3 * (mu ** 4))
        
        # 计算峰度 β = m4 / m2²
        beta = m4 / (m2 ** 2)
        
        return beta
    
    def _calculate_kurtosis_from_moments(self, n: int, s1: float, s2: float, s3: float, s4: float) -> Optional[float]:
        """实例方法包装，调用静态方法"""
        return self.calculate_kurtosis_from_moments(n, s1, s2, s3, s4)
    
    def _calculate_third_octave_metrics(self, signal: Signal) -> tuple:
        """
        计算1/3倍频程频段指标
        
        返回:
            (freq_spl_dict, freq_moments_dict): 频段SPL和原始矩统计量字典
            freq_moments_dict格式: {频段名: (n, s1, s2, s3, s4)}
        """
        try:
            # 获取1/3倍频程数据
            center_freqs, octaves = signal.third_octaves()
            
            # 定义关心的频段索引（对应63Hz-16kHz）
            # third_octaves()返回的索引：8=63Hz, 11=125Hz, 14=250Hz, 17=500Hz
            # 20=1kHz, 23=2kHz, 26=4kHz, 29=8kHz, 32=16kHz
            freq_indices = [8, 11, 14, 17, 20, 23, 26, 29, 32]
            freq_names = ['63Hz', '125Hz', '250Hz', '500Hz', '1kHz', '2kHz', '4kHz', '8kHz', '16kHz']
            
            freq_spl_dict = {}
            freq_moments_dict = {}
            
            for idx, name in zip(freq_indices, freq_names):
                if idx < len(octaves):
                    s_octave = octaves[idx]
                    octave_data = s_octave.values
                    
                    # 计算频段SPL（1秒平均）
                    try:
                        _, spl = time_averaged_sound_level(
                            pressure=octave_data,
                            sample_frequency=signal.fs,
                            averaging_time=1.0,  # 1秒平均
                            reference_pressure=self.reference_pressure
                        )
                        freq_spl_dict[name] = round(spl, 2)
                    except Exception as e:
                        logger.warning(f"Failed to calculate SPL for {name}: {e}")
                        freq_spl_dict[name] = None
                    
                    # 计算频段原始矩统计量 S1-S4（用于后续精确合成频段峰度）
                    try:
                        n = len(octave_data)
                        s1 = np.sum(octave_data)
                        s2 = np.sum(octave_data ** 2)
                        s3 = np.sum(octave_data ** 3)
                        s4 = np.sum(octave_data ** 4)
                        freq_moments_dict[name] = (n, s1, s2, s3, s4)
                    except Exception as e:
                        logger.warning(f"Failed to calculate moments for {name}: {e}")
                        freq_moments_dict[name] = (0, 0.0, 0.0, 0.0, 0.0)
                else:
                    freq_spl_dict[name] = None
                    freq_moments_dict[name] = (0, 0.0, 0.0, 0.0, 0.0)
            
            return freq_spl_dict, freq_moments_dict
            
        except Exception as e:
            logger.error(f"Error calculating third octave metrics: {e}")
            # 返回空字典，使用默认值
            freq_names = ['63Hz', '125Hz', '250Hz', '500Hz', '1kHz', '2kHz', '4kHz', '8kHz', '16kHz']
            return {name: None for name in freq_names}, {name: (0, 0.0, 0.0, 0.0, 0.0) for name in freq_names}
    
    def process_signal_per_second(self, 
                                   signal: Signal, 
                                   start_time: Optional[datetime] = None) -> List[SecondMetrics]:
        """
        按秒处理音频信号
        
        Args:
            signal: acoustics.Signal 对象
            start_time: 开始时间，默认为当前时间
            
        Returns:
            List[SecondMetrics]: 每秒钟的指标列表
        """
        if start_time is None:
            start_time = datetime.utcnow()
        
        results = []
        sr = signal.fs
        total_samples = len(signal.values)
        samples_per_second = int(sr)
        
        # 计算总秒数
        total_seconds = int(np.ceil(total_samples / samples_per_second))
        
        logger.info(f"Processing {total_seconds} seconds of audio at {sr}Hz")
        
        for second_idx in range(total_seconds):
            # 提取当前秒的样本
            start_sample = second_idx * samples_per_second
            end_sample = min((second_idx + 1) * samples_per_second, total_samples)
            
            if start_sample >= total_samples:
                break
            
            second_data = signal.values[start_sample:end_sample]
            
            # 计算当前秒的指标
            metrics = self._calculate_second_metrics(
                second_data, 
                sr, 
                start_time + timedelta(seconds=second_idx),
                duration=(end_sample - start_sample) / sr
            )
            
            results.append(metrics)
            
            # 调用回调函数
            if self.callback:
                self.callback(metrics)
        
        logger.info(f"Processed {len(results)} seconds of time history data")
        return results
    
    def _calculate_second_metrics(self, 
                                   data: np.ndarray, 
                                   sr: int, 
                                   timestamp: datetime,
                                   duration: float) -> SecondMetrics:
        """
        计算单秒钟的各项指标
        
        Args:
            data: 音频样本
            sr: 采样率
            timestamp: 时间戳
            duration: 实际时长（秒）
            
        Returns:
            SecondMetrics: 单秒钟的指标
        """
        s = Signal(data, sr)
        
        # Calculate equivalent sound levels
        LAeq = equivalent_sound_pressure_level(
            s.weigh("A").values, reference_pressure=self.reference_pressure)
        LCeq = equivalent_sound_pressure_level(
            s.weigh("C").values, reference_pressure=self.reference_pressure)
        LZeq = equivalent_sound_pressure_level(
            s.values, reference_pressure=self.reference_pressure)
        
        # Calculate peak levels
        try:
            LZpeak = peak_sound_pressure_level(
                s.values, reference_pressure=self.reference_pressure)
            LCpeak = peak_sound_pressure_level(
                s.weigh("C").values, reference_pressure=self.reference_pressure)
        except Exception as e:
            logger.warning(f"Failed to calculate peak levels: {e}")
            LZpeak = LZeq + 10.0  # Estimate
            LCpeak = LCeq + 10.0
        
        # Calculate LAFmax (fast time-weighted max)
        try:
            fast_avg = average(
                data=s.weigh("A").values,
                sample_frequency=sr,
                averaging_time=0.125  # 125ms fast
            )
            LAFmax = np.max(fast_avg) if len(fast_avg) > 0 else LAeq
        except Exception as e:
            logger.warning(f"Failed to calculate LAFmax: {e}")
            LAFmax = LAeq
        
        # Calculate kurtosis using scipy (backward compatible)
        try:
            kurtosis_total = kurtosis(s.values, fisher=False)
            kurtosis_a = kurtosis(s.weigh("A").values, fisher=False)
            kurtosis_c = kurtosis(s.weigh("C").values, fisher=False)
        except Exception:
            kurtosis_total = 3.0
            kurtosis_a = 3.0
            kurtosis_c = 3.0
        
        # Calculate raw moment statistics S1-S4 for aggregation (根据规范 4.X.3)
        # 使用 Z 加权（原始）信号进行计算，保证后续跨时段合成的一致性
        n_samples = len(s.values)
        sum_x = np.sum(s.values)           # S1 = Σx_k
        sum_x2 = np.sum(s.values ** 2)     # S2 = Σx_k²
        sum_x3 = np.sum(s.values ** 3)     # S3 = Σx_k³
        sum_x4 = np.sum(s.values ** 4)     # S4 = Σx_k⁴
        
        # 根据规范 4.X.3 计算峰度 β
        beta_kurtosis = self._calculate_kurtosis_from_moments(
            n_samples, sum_x, sum_x2, sum_x3, sum_x4
        )
        
        # Calculate dose increments for each second
        # For 1-second interval
        dose_frac_niosh = self.dose_calculator.calculate_dose_increment(
            LAeq, 1.0, DoseStandard.NIOSH)
        dose_frac_osha_pel = self.dose_calculator.calculate_dose_increment(
            LAeq, 1.0, DoseStandard.OSHA_PEL)
        dose_frac_osha_hca = self.dose_calculator.calculate_dose_increment(
            LAeq, 1.0, DoseStandard.OSHA_HCA)
        dose_frac_eu_iso = self.dose_calculator.calculate_dose_increment(
            LAeq, 1.0, DoseStandard.EU_ISO)
        
        # Calculate 1/3 octave band metrics (频段分析)
        freq_spl_dict, freq_moments_dict = self._calculate_third_octave_metrics(s)
        
        # Quality control checks
        overload_flag = LZpeak > self.OVERLOAD_THRESHOLD
        underrange_flag = LAeq < self.UNDERRANGE_THRESHOLD
        
        # Wearing state detection (simplified)
        # In real implementation, this could use pattern recognition
        wearing_state = LAeq > 40.0  # Simple threshold-based detection
        
        return SecondMetrics(
            timestamp=timestamp,
            duration_s=duration,
            LAeq=round(LAeq, 2),
            LCeq=round(LCeq, 2),
            LZeq=round(LZeq, 2),
            LAFmax=round(LAFmax, 2) if LAFmax else None,
            LZpeak=round(LZpeak, 2) if LZpeak else None,
            LCpeak=round(LCpeak, 2) if LCpeak else None,
            dose_frac_niosh=round(dose_frac_niosh, 6),
            dose_frac_osha_pel=round(dose_frac_osha_pel, 6),
            dose_frac_osha_hca=round(dose_frac_osha_hca, 6),
            dose_frac_eu_iso=round(dose_frac_eu_iso, 6),
            overload_flag=overload_flag,
            underrange_flag=underrange_flag,
            wearing_state=wearing_state,
            kurtosis_total=round(kurtosis_total, 2),
            kurtosis_a_weighted=round(kurtosis_a, 2),
            kurtosis_c_weighted=round(kurtosis_c, 2),
            n_samples=n_samples,
            sum_x=float(sum_x),
            sum_x2=float(sum_x2),
            sum_x3=float(sum_x3),
            sum_x4=float(sum_x4),
            beta_kurtosis=round(beta_kurtosis, 4) if beta_kurtosis is not None else None,
            # 1/3倍频程频段SPL
            freq_63hz_spl=freq_spl_dict.get('63Hz'),
            freq_125hz_spl=freq_spl_dict.get('125Hz'),
            freq_250hz_spl=freq_spl_dict.get('250Hz'),
            freq_500hz_spl=freq_spl_dict.get('500Hz'),
            freq_1khz_spl=freq_spl_dict.get('1kHz'),
            freq_2khz_spl=freq_spl_dict.get('2kHz'),
            freq_4khz_spl=freq_spl_dict.get('4kHz'),
            freq_8khz_spl=freq_spl_dict.get('8kHz'),
            freq_16khz_spl=freq_spl_dict.get('16kHz'),
            # 1/3倍频程频段原始矩统计量 S1-S4（用于精确合成频段峰度）
            freq_63hz_n=freq_moments_dict.get('63Hz', (0, 0.0, 0.0, 0.0, 0.0))[0],
            freq_63hz_s1=freq_moments_dict.get('63Hz', (0, 0.0, 0.0, 0.0, 0.0))[1],
            freq_63hz_s2=freq_moments_dict.get('63Hz', (0, 0.0, 0.0, 0.0, 0.0))[2],
            freq_63hz_s3=freq_moments_dict.get('63Hz', (0, 0.0, 0.0, 0.0, 0.0))[3],
            freq_63hz_s4=freq_moments_dict.get('63Hz', (0, 0.0, 0.0, 0.0, 0.0))[4],
            freq_125hz_n=freq_moments_dict.get('125Hz', (0, 0.0, 0.0, 0.0, 0.0))[0],
            freq_125hz_s1=freq_moments_dict.get('125Hz', (0, 0.0, 0.0, 0.0, 0.0))[1],
            freq_125hz_s2=freq_moments_dict.get('125Hz', (0, 0.0, 0.0, 0.0, 0.0))[2],
            freq_125hz_s3=freq_moments_dict.get('125Hz', (0, 0.0, 0.0, 0.0, 0.0))[3],
            freq_125hz_s4=freq_moments_dict.get('125Hz', (0, 0.0, 0.0, 0.0, 0.0))[4],
            freq_250hz_n=freq_moments_dict.get('250Hz', (0, 0.0, 0.0, 0.0, 0.0))[0],
            freq_250hz_s1=freq_moments_dict.get('250Hz', (0, 0.0, 0.0, 0.0, 0.0))[1],
            freq_250hz_s2=freq_moments_dict.get('250Hz', (0, 0.0, 0.0, 0.0, 0.0))[2],
            freq_250hz_s3=freq_moments_dict.get('250Hz', (0, 0.0, 0.0, 0.0, 0.0))[3],
            freq_250hz_s4=freq_moments_dict.get('250Hz', (0, 0.0, 0.0, 0.0, 0.0))[4],
            freq_500hz_n=freq_moments_dict.get('500Hz', (0, 0.0, 0.0, 0.0, 0.0))[0],
            freq_500hz_s1=freq_moments_dict.get('500Hz', (0, 0.0, 0.0, 0.0, 0.0))[1],
            freq_500hz_s2=freq_moments_dict.get('500Hz', (0, 0.0, 0.0, 0.0, 0.0))[2],
            freq_500hz_s3=freq_moments_dict.get('500Hz', (0, 0.0, 0.0, 0.0, 0.0))[3],
            freq_500hz_s4=freq_moments_dict.get('500Hz', (0, 0.0, 0.0, 0.0, 0.0))[4],
            freq_1khz_n=freq_moments_dict.get('1kHz', (0, 0.0, 0.0, 0.0, 0.0))[0],
            freq_1khz_s1=freq_moments_dict.get('1kHz', (0, 0.0, 0.0, 0.0, 0.0))[1],
            freq_1khz_s2=freq_moments_dict.get('1kHz', (0, 0.0, 0.0, 0.0, 0.0))[2],
            freq_1khz_s3=freq_moments_dict.get('1kHz', (0, 0.0, 0.0, 0.0, 0.0))[3],
            freq_1khz_s4=freq_moments_dict.get('1kHz', (0, 0.0, 0.0, 0.0, 0.0))[4],
            freq_2khz_n=freq_moments_dict.get('2kHz', (0, 0.0, 0.0, 0.0, 0.0))[0],
            freq_2khz_s1=freq_moments_dict.get('2kHz', (0, 0.0, 0.0, 0.0, 0.0))[1],
            freq_2khz_s2=freq_moments_dict.get('2kHz', (0, 0.0, 0.0, 0.0, 0.0))[2],
            freq_2khz_s3=freq_moments_dict.get('2kHz', (0, 0.0, 0.0, 0.0, 0.0))[3],
            freq_2khz_s4=freq_moments_dict.get('2kHz', (0, 0.0, 0.0, 0.0, 0.0))[4],
            freq_4khz_n=freq_moments_dict.get('4kHz', (0, 0.0, 0.0, 0.0, 0.0))[0],
            freq_4khz_s1=freq_moments_dict.get('4kHz', (0, 0.0, 0.0, 0.0, 0.0))[1],
            freq_4khz_s2=freq_moments_dict.get('4kHz', (0, 0.0, 0.0, 0.0, 0.0))[2],
            freq_4khz_s3=freq_moments_dict.get('4kHz', (0, 0.0, 0.0, 0.0, 0.0))[3],
            freq_4khz_s4=freq_moments_dict.get('4kHz', (0, 0.0, 0.0, 0.0, 0.0))[4],
            freq_8khz_n=freq_moments_dict.get('8kHz', (0, 0.0, 0.0, 0.0, 0.0))[0],
            freq_8khz_s1=freq_moments_dict.get('8kHz', (0, 0.0, 0.0, 0.0, 0.0))[1],
            freq_8khz_s2=freq_moments_dict.get('8kHz', (0, 0.0, 0.0, 0.0, 0.0))[2],
            freq_8khz_s3=freq_moments_dict.get('8kHz', (0, 0.0, 0.0, 0.0, 0.0))[3],
            freq_8khz_s4=freq_moments_dict.get('8kHz', (0, 0.0, 0.0, 0.0, 0.0))[4],
            freq_16khz_n=freq_moments_dict.get('16kHz', (0, 0.0, 0.0, 0.0, 0.0))[0],
            freq_16khz_s1=freq_moments_dict.get('16kHz', (0, 0.0, 0.0, 0.0, 0.0))[1],
            freq_16khz_s2=freq_moments_dict.get('16kHz', (0, 0.0, 0.0, 0.0, 0.0))[2],
            freq_16khz_s3=freq_moments_dict.get('16kHz', (0, 0.0, 0.0, 0.0, 0.0))[3],
            freq_16khz_s4=freq_moments_dict.get('16kHz', (0, 0.0, 0.0, 0.0, 0.0))[4],
        )
    
    def process_wav_file(self, 
                         file_path: str, 
                         start_time: Optional[datetime] = None) -> List[SecondMetrics]:
        """
        处理WAV文件并按秒返回指标
        
        Args:
            file_path: WAV文件路径
            start_time: 开始时间
            
        Returns:
            List[SecondMetrics]: 每秒钟的指标列表
        """
        import librosa
        import warnings
        
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                y, sr = librosa.load(file_path, sr=None)
        except Exception as e:
            raise RuntimeError(f"Failed to load audio file {file_path}: {str(e)}")
        
        signal = Signal(y, sr)
        return self.process_signal_per_second(signal, start_time)


def aggregate_session_metrics(time_history: List[SecondMetrics], 
                               profile: DoseStandard = DoseStandard.NIOSH) -> Dict:
    """
    聚合会话级指标
    
    Args:
        time_history: 时间历程数据列表
        profile: 剂量计算标准
        
    Returns:
        Dict: 会话汇总指标
    """
    if not time_history:
        return {}
    
    # Get dose column based on profile
    dose_map = {
        DoseStandard.NIOSH: 'dose_frac_niosh',
        DoseStandard.OSHA_PEL: 'dose_frac_osha_pel',
        DoseStandard.OSHA_HCA: 'dose_frac_osha_hca',
        DoseStandard.EU_ISO: 'dose_frac_eu_iso',
    }
    dose_attr = dose_map.get(profile, 'dose_frac_niosh')
    
    # Calculate total duration
    total_duration_h = sum(m.duration_s for m in time_history) / 3600.0
    
    # Calculate total dose
    total_dose = sum(getattr(m, dose_attr, 0.0) for m in time_history)
    
    # Calculate overall LAeq
    # LAeq_total = 10 * log10( (1/n) * sum(10^(LAeq_i/10)) )
    laeq_values = [m.LAeq for m in time_history]
    if laeq_values:
        laeq_total = 10 * np.log10(np.mean([10**(la/10) for la in laeq_values]))
    else:
        laeq_total = 0.0
    
    # Calculate TWA and LEX,8h
    calculator = DoseCalculator()
    twa = calculator.calculate_twa(total_dose, profile)
    lex_8h = calculator.calculate_lex(total_dose, profile)
    
    # Find peak max
    peak_values = [m.LZpeak for m in time_history if m.LZpeak is not None]
    peak_max = max(peak_values) if peak_values else 0.0
    
    # Count events (overloads)
    overload_count = sum(1 for m in time_history if m.overload_flag)
    underrange_count = sum(1 for m in time_history if m.underrange_flag)
    
    return {
        'total_duration_h': round(total_duration_h, 4),
        'total_dose_pct': round(total_dose, 4),
        'LAeq_T': round(laeq_total, 2),
        'TWA': round(twa, 2),
        'LEX_8h': round(lex_8h, 2),
        'peak_max_dB': round(peak_max, 2),
        'overload_count': overload_count,
        'underrange_count': underrange_count,
        'total_seconds': len(time_history)
    }
