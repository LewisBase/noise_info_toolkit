# -*- coding: utf-8 -*-
"""
@DATE: 2026-02-13 22:00:00
@Author: Liu Hengjiang
@File: app/core/dose_calculator.py
@Software: vscode
@Description:
        噪声剂量计算器模块
        支持 NIOSH、OSHA_PEL、OSHA_HCA、EU_ISO 等多种标准
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum


class DoseStandard(Enum):
    """剂量计算标准枚举"""
    NIOSH = "NIOSH"
    OSHA_PEL = "OSHA_PEL"
    OSHA_HCA = "OSHA_HCA"
    EU_ISO = "EU_ISO"


@dataclass
class DoseProfile:
    """
    剂量计算标准配置类
    
    Attributes:
        name: 标准名称
        criterion_level: 准则级 (dBA)
        exchange_rate: 交换率 (dB)
        threshold: 阈值 (dBA)，低于此值不计入剂量
        reference_duration: 参考时长 (小时)，通常为8小时
        description: 标准描述
    """
    name: str
    criterion_level: float  # Lc (dBA)
    exchange_rate: float     # ER (dB)
    threshold: float = 0.0   # LT (dBA)
    reference_duration: float = 8.0  # Tref (hours)
    description: str = ""
    
    def __post_init__(self):
        if not self.description:
            self.description = f"{self.name}: {self.criterion_level}dBA/{self.exchange_rate}dB/{self.reference_duration}h"


class DoseCalculator:
    """
    噪声剂量计算器
    
    支持多种职业噪声暴露标准的剂量计算，包括：
    - NIOSH (85 dBA / 3 dB / 8h)
    - OSHA_PEL (90 dBA / 5 dB / 8h)  
    - OSHA_HCA (85 dBA / 5 dB / 8h)
    - EU_ISO (85 dBA / 3 dB / 8h)
    
    计算公式：
    - 允许时间: T = Tref / 2^((L - Lc) / ER)
    - 剂量增量: Dose%_inc = 100 × (dt/Tref) × 2^((LAeq - Lc) / ER)
    - TWA: NIOSH/ISO: 10×log10(Dose%/100) + Lc; OSHA: 16.61×log10(Dose%/100) + Lc
    - LEX,8h: 10×log10(Dose%/100) + Lc
    """
    
    @classmethod
    def _resolve_profile(cls, profile) -> DoseProfile:
        """
        将 DoseStandard 枚举或字符串转换为 DoseProfile 对象
        
        Args:
            profile: DoseProfile, DoseStandard, or str
            
        Returns:
            DoseProfile: 剂量计算标准配置
        """
        if isinstance(profile, DoseProfile):
            return profile
        if isinstance(profile, DoseStandard):
            return cls.PROFILES[profile.value]
        if isinstance(profile, str):
            return cls.PROFILES.get(profile, cls.PROFILES[DoseStandard.NIOSH.value])
        raise ValueError(f"Invalid profile type: {type(profile)}")
    
    # 预定义标准配置
    PROFILES: Dict[str, DoseProfile] = {
        DoseStandard.NIOSH.value: DoseProfile(
            name=DoseStandard.NIOSH.value,
            criterion_level=85.0,
            exchange_rate=3.0,
            threshold=0.0,
            reference_duration=8.0,
            description="NIOSH标准: 85dBA准则级, 3dB交换率, 8小时参考时长"
        ),
        DoseStandard.OSHA_PEL.value: DoseProfile(
            name=DoseStandard.OSHA_PEL.value,
            criterion_level=90.0,
            exchange_rate=5.0,
            threshold=0.0,
            reference_duration=8.0,
            description="OSHA_PEL标准: 90dBA准则级, 5dB交换率, 8小时参考时长"
        ),
        DoseStandard.OSHA_HCA.value: DoseProfile(
            name=DoseStandard.OSHA_HCA.value,
            criterion_level=85.0,
            exchange_rate=5.0,
            threshold=0.0,
            reference_duration=8.0,
            description="OSHA_HCA标准: 85dBA准则级, 5dB交换率, 8小时参考时长"
        ),
        DoseStandard.EU_ISO.value: DoseProfile(
            name=DoseStandard.EU_ISO.value,
            criterion_level=85.0,
            exchange_rate=3.0,
            threshold=0.0,
            reference_duration=8.0,
            description="EU_ISO标准: 85dBA准则级, 3dB交换率, 8小时参考时长"
        ),
    }
    
    @classmethod
    def get_profile(cls, standard: str) -> DoseProfile:
        """
        获取指定标准的配置
        
        Args:
            standard: 标准名称 (NIOSH/OSHA_PEL/OSHA_HCA/EU_ISO)
            
        Returns:
            DoseProfile: 剂量计算配置
            
        Raises:
            ValueError: 如果标准名称不存在
        """
        if standard not in cls.PROFILES:
            available = ", ".join(cls.PROFILES.keys())
            raise ValueError(f"未知标准: {standard}. 可用标准: {available}")
        return cls.PROFILES[standard]
    
    @classmethod
    def get_all_profiles(cls) -> Dict[str, DoseProfile]:
        """获取所有预定义标准配置"""
        return cls.PROFILES.copy()
    
    @classmethod
    def calculate_allowed_time(cls, laeq: float, profile: DoseProfile) -> float:
        """
        计算给定声级下的允许暴露时间
        
        公式: T = Tref / 2^((L - Lc) / ER)
        
        Args:
            laeq: A计权等效声级 (dBA)
            profile: 剂量计算标准配置
            
        Returns:
            float: 允许暴露时间 (小时)
        """
        if laeq < profile.threshold:
            return float('inf')  # 低于阈值，无限时间
        
        # T = Tref / 2^((L - Lc) / ER)
        exponent = (laeq - profile.criterion_level) / profile.exchange_rate
        allowed_time = profile.reference_duration / (2 ** exponent)
        return allowed_time
    
    @classmethod
    def calculate_dose_increment(cls, laeq: float, duration_s: float, 
                                  profile) -> float:
        """
        计算单个时间段的剂量增量
        
        公式: Dose% = 100 × (dt/Tref) × 2^((L - Lc) / ER)
        
        Args:
            laeq: A计权等效声级 (dBA)
            duration_s: 持续时间 (秒)
            profile: DoseProfile, DoseStandard, or str
            
        Returns:
            float: 剂量增量 (%)
        """
        p = cls._resolve_profile(profile)
        
        if laeq < p.threshold:
            return 0.0
        
        duration_h = duration_s / 3600.0
        
        # Dose% = 100 × (dt/Tref) × 2^((L-Lc)/ER)
        exponent = (laeq - p.criterion_level) / p.exchange_rate
        dose_increment = 100.0 * (duration_h / p.reference_duration) * (2 ** exponent)
        
        return dose_increment
    
    @classmethod
    def calculate_total_dose(cls, measurements: List[Tuple[float, float]], 
                             profile: DoseProfile) -> float:
        """
        计算多个时间段的累计剂量
        
        Args:
            measurements: 测量数据列表，每个元素为 (LAeq_dB, duration_s)
            profile: 剂量计算标准配置
            
        Returns:
            float: 累计剂量 (%)
        """
        total_dose = 0.0
        for laeq, duration_s in measurements:
            total_dose += cls.calculate_dose_increment(laeq, duration_s, profile)
        return total_dose
    
    @classmethod
    def calculate_twa(cls, total_dose_pct: float, profile) -> float:
        """
        从总剂量计算时间加权平均声级 (TWA)
        
        公式:
        - NIOSH/ISO: TWA = 10 × log10(Dose%/100) + Lc
        - OSHA: TWA = 16.61 × log10(Dose%/100) + Lc
        
        Args:
            total_dose_pct: 总剂量 (%)
            profile: DoseProfile, DoseStandard, or str
            
        Returns:
            float: TWA (dBA)
        """
        if total_dose_pct <= 0:
            return 0.0
        
        p = cls._resolve_profile(profile)
        
        if p.name.startswith("OSHA"):
            # OSHA使用特殊系数 16.61
            twa = 16.61 * np.log10(total_dose_pct / 100.0) + p.criterion_level
        else:
            # NIOSH和ISO使用系数 10
            twa = 10.0 * np.log10(total_dose_pct / 100.0) + p.criterion_level
        
        return twa
    
    @classmethod
    def calculate_lex(cls, total_dose_pct: float, profile) -> float:
        """
        计算日噪声暴露级 (LEX,8h 或 Lep'd)
        
        公式: LEX,8h = 10 × log10(Dose%/100) + Lc
        
        Args:
            total_dose_pct: 总剂量 (%)
            profile: DoseProfile, DoseStandard, or str
            
        Returns:
            float: LEX,8h (dBA)
        """
        if total_dose_pct <= 0:
            return 0.0
        
        p = cls._resolve_profile(profile)
        lex = 10.0 * np.log10(total_dose_pct / 100.0) + p.criterion_level
        return lex
    
    @classmethod
    def calculate_dose_from_lex(cls, lex: float, profile: DoseProfile) -> float:
        """
        从 LEX,8h 反算剂量百分比
        
        公式: Dose% = 100 × 10^((LEX,8h - Lc) / 10)
        
        Args:
            lex: LEX,8h (dBA)
            profile: 剂量计算标准配置
            
        Returns:
            float: 剂量 (%)
        """
        dose = 100.0 * (10 ** ((lex - profile.criterion_level) / 10.0))
        return dose
    
    @classmethod
    def calculate_all_metrics(cls, laeq: float, duration_s: float, 
                              profile: DoseProfile) -> Dict[str, float]:
        """
        计算所有相关指标
        
        Args:
            laeq: A计权等效声级 (dBA)
            duration_s: 持续时间 (秒)
            profile: 剂量计算标准配置
            
        Returns:
            Dict: 包含 dose_pct, twa, lex, allowed_time_h 的字典
        """
        dose_pct = cls.calculate_dose_increment(laeq, duration_s, profile)
        allowed_time_h = cls.calculate_allowed_time(laeq, profile)
        
        # 对于单帧，TWA和LEX等于输入声级
        twa = laeq if duration_s >= profile.reference_duration * 3600 else None
        lex = laeq if duration_s >= profile.reference_duration * 3600 else None
        
        return {
            "dose_pct": dose_pct,
            "dose_fraction": dose_pct / 100.0,
            "twa": twa,
            "lex": lex,
            "allowed_time_h": allowed_time_h,
        }
    
    @classmethod
    def calculate_multi_standard(cls, laeq: float, duration_s: float) -> Dict[str, Dict[str, float]]:
        """
        使用所有标准计算剂量指标
        
        Args:
            laeq: A计权等效声级 (dBA)
            duration_s: 持续时间 (秒)
            
        Returns:
            Dict: 各标准的计算结果
        """
        results = {}
        for standard_name, profile in cls.PROFILES.items():
            results[standard_name] = cls.calculate_all_metrics(laeq, duration_s, profile)
        return results


# 便捷函数接口
def calculate_noise_dose(laeq: float, duration_h: float, 
                         standard: str = "NIOSH") -> float:
    """
    便捷函数：计算噪声剂量
    
    Args:
        laeq: A计权等效声级 (dBA)
        duration_h: 持续时间 (小时)
        standard: 标准名称 (NIOSH/OSHA_PEL/OSHA_HCA/EU_ISO)
        
    Returns:
        float: 剂量 (%)
    """
    profile = DoseCalculator.get_profile(standard)
    duration_s = duration_h * 3600.0
    return DoseCalculator.calculate_dose_increment(laeq, duration_s, profile)


def calculate_twa_from_dose(total_dose_pct: float, standard: str = "NIOSH") -> float:
    """
    便捷函数：从剂量计算TWA
    
    Args:
        total_dose_pct: 总剂量 (%)
        standard: 标准名称
        
    Returns:
        float: TWA (dBA)
    """
    profile = DoseCalculator.get_profile(standard)
    return DoseCalculator.calculate_twa(total_dose_pct, profile)


def get_standard_info(standard: str) -> Dict:
    """
    获取标准详细信息
    
    Args:
        standard: 标准名称
        
    Returns:
        Dict: 标准配置信息
    """
    profile = DoseCalculator.get_profile(standard)
    return {
        "name": profile.name,
        "criterion_level_dBA": profile.criterion_level,
        "exchange_rate_dB": profile.exchange_rate,
        "threshold_dBA": profile.threshold,
        "reference_duration_h": profile.reference_duration,
        "description": profile.description,
    }
