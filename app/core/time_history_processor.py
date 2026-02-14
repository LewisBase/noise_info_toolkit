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
    
    # Kurtosis
    kurtosis_total: Optional[float] = None
    kurtosis_a_weighted: Optional[float] = None


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
        
        # Calculate kurtosis
        try:
            kurtosis_total = kurtosis(s.values, fisher=False)
            kurtosis_a = kurtosis(s.weigh("A").values, fisher=False)
        except Exception:
            kurtosis_total = 3.0
            kurtosis_a = 3.0
        
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
            kurtosis_a_weighted=round(kurtosis_a, 2)
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
