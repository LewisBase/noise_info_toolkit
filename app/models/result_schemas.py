# -*- coding: utf-8 -*-
"""
@DATE: 2025-11-17 23:43:22
@Author: Liu Hengjiang
@File: app\models\\result_schemas.py
@Software: vscode
@Description:
        计算结果Schema
"""

from pydantic import BaseModel
from typing import List, Dict, Optional, Any


class FrequencyData(BaseModel):
    """Frequency data model"""
    # Using Dict[str, Any] since the actual keys depend on the frequency bands
    frequency_bands: Dict[str, Any] = {}
    
    
class ProcessingResultSchema(BaseModel):
    """Schema for audio processing results"""
    file_dir: str
    file_path: str
    sampling_rate: Optional[float] = None
    duration: Optional[float] = None
    channels: Optional[int] = None
    leq: Optional[float] = None
    laeq: Optional[float] = None
    lceq: Optional[float] = None
    peak_spl: Optional[float] = None
    peak_aspl: Optional[float] = None
    peak_cspl: Optional[float] = None
    total_kurtosis: Optional[float] = None
    a_weighted_kurtosis: Optional[float] = None
    c_weighted_kurtosis: Optional[float] = None
    frequency_spl: FrequencyData = FrequencyData()
    frequency_kurtosis: FrequencyData = FrequencyData()