"""
Database models for noise info toolkit
"""
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import json
from datetime import datetime
from typing import Dict, Any, Optional

Base = declarative_base()


class DoseProfile(Base):
    """Dose calculation profile model"""
    __tablename__ = "dose_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    profile_name = Column(String(50), unique=True, index=True)  # NIOSH, OSHA_PEL, etc.
    criterion_level_dBA = Column(Float, default=85.0)           # 准则级
    exchange_rate_dB = Column(Float, default=3.0)               # 交换率
    threshold_dBA = Column(Float, default=0.0)                  # 阈值
    reference_duration_h = Column(Float, default=8.0)           # 参考时长
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class ProcessingResult(Base):
    """Processing result model"""
    __tablename__ = "processing_result"
    
    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, index=True)
    file_dir = Column(String, index=True)
    file_name = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.now)
    
    # Session information
    session_id = Column(String(100), index=True, nullable=True)
    device_id = Column(String(100), nullable=True)
    
    # Relationship with metrics
    metrics = relationship("ProcessingMetric", back_populates="result")


class ProcessingMetric(Base):
    """Processing metric model"""
    __tablename__ = "processing_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    result_id = Column(Integer, ForeignKey('processing_result.id'), index=True)
    metric_name = Column(String, index=True)
    metric_value = Column(Float)
    metric_type = Column(String)  # 'numeric' or 'spectrum'
    
    # Relationship with result
    result = relationship("ProcessingResult", back_populates="metrics")
    
    # Relationship with spectrum data
    spectrum_data = relationship("SpectrumData", back_populates="metric")


class SpectrumData(Base):
    """Spectrum data model"""
    __tablename__ = "spectrum_data"

    id = Column(Integer, primary_key=True, index=True)
    metric_id = Column(Integer, ForeignKey('processing_metrics.id'), index=True)
    frequency = Column(String)
    value = Column(Float)
    # Relationship with metric
    metric = relationship("ProcessingMetric", back_populates="spectrum_data")


class TimeHistory(Base):
    """Time history data model - stores per-second metrics"""
    __tablename__ = "time_history"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True)
    device_id = Column(String(100), index=True, nullable=True)
    profile_name = Column(String(50), index=True, nullable=True)
    timestamp_utc = Column(DateTime, index=True)
    
    # Time interval
    duration_s = Column(Float, default=1.0)
    
    # Sound levels
    LAeq_dB = Column(Float)
    LCeq_dB = Column(Float)
    LZeq_dB = Column(Float)
    LAFmax_dB = Column(Float, nullable=True)
    LZpeak_dB = Column(Float)
    LCpeak_dB = Column(Float)
    
    # Dose increments for different standards
    dose_frac_niosh = Column(Float, default=0.0)
    dose_frac_osha_pel = Column(Float, default=0.0)
    dose_frac_osha_hca = Column(Float, default=0.0)
    dose_frac_eu_iso = Column(Float, default=0.0)
    
    # Quality control flags
    wearing_state = Column(Boolean, default=True)
    overload_flag = Column(Boolean, default=False)
    underrange_flag = Column(Boolean, default=False)
    
    # Environmental data (optional)
    temp_C = Column(Float, nullable=True)
    humidity_pct = Column(Float, nullable=True)
    pressure_hPa = Column(Float, nullable=True)


class EventLog(Base):
    """Event log model - stores impulsive noise events"""
    __tablename__ = "event_log"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True)
    event_id = Column(String(100), index=True)
    
    # Timing
    start_time_utc = Column(DateTime)
    end_time_utc = Column(DateTime)
    duration_s = Column(Float)
    
    # Trigger information
    trigger_type = Column(String(50))  # 'leq', 'peak', 'slope'
    
    # Sound levels
    LZpeak_dB = Column(Float)
    LCpeak_dB = Column(Float)
    LAeq_event_dB = Column(Float)
    SEL_LAE_dB = Column(Float)  # Sound Exposure Level
    
    # Kurtosis
    beta_excess_event_Z = Column(Float, nullable=True)
    
    # Audio file
    audio_file_path = Column(String(500), nullable=True)
    pretrigger_s = Column(Float, default=2.0)
    posttrigger_s = Column(Float, default=8.0)
    
    # Notes
    notes = Column(Text, nullable=True)


class SessionSummary(Base):
    """Session summary model - stores aggregated data per session"""
    __tablename__ = "session_summary"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True, unique=True)
    profile_name = Column(String(50), index=True)
    
    # Timing
    start_time_utc = Column(DateTime)
    end_time_utc = Column(DateTime, nullable=True)
    total_duration_h = Column(Float)
    
    # Overall metrics
    LAeq_T = Column(Float)  # Overall LAeq for entire session
    LEX_8h = Column(Float)  # Daily noise exposure level
    total_dose_pct = Column(Float)  # Total dose percentage
    TWA = Column(Float)  # Time Weighted Average
    
    # Peak levels
    peak_max_dB = Column(Float)
    LCpeak_max_dB = Column(Float, nullable=True)
    
    # Event statistics
    events_count = Column(Integer, default=0)
    
    # Quality control
    overload_count = Column(Integer, default=0)
    underrange_count = Column(Integer, default=0)
    
    # Metadata reference
    metadata_id = Column(Integer, ForeignKey('metadata.id'), nullable=True)


class Metadata(Base):
    """Metadata model - stores session metadata"""
    __tablename__ = "metadata"
    
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(100), index=True, unique=True)
    
    # Basic info
    start_time_utc = Column(DateTime)
    end_time_utc = Column(DateTime, nullable=True)
    organization = Column(String(200), nullable=True)
    operator = Column(String(100), nullable=True)
    worker_role = Column(String(100), nullable=True)
    
    # Device info
    device_model = Column(String(100), nullable=True)
    device_serial = Column(String(100), nullable=True)
    mic_type = Column(String(100), nullable=True)
    mic_diameter_inch = Column(Float, nullable=True)
    mic_sensitivity_mV_Pa = Column(Float, nullable=True)
    
    # Sampling parameters
    sampling_rate_Hz = Column(Integer, default=48000)
    bit_depth = Column(Integer, default=24)
    
    # Calibration
    calibration_level_dB = Column(Float, nullable=True)
    calibration_time_utc = Column(DateTime, nullable=True)
    post_cal_level_dB = Column(Float, nullable=True)
    
    # Standards
    compliance_standards = Column(String(200), nullable=True)
    data_format_version = Column(String(20), default="1.0")
    
    # Notes
    notes = Column(Text, nullable=True)


class Config(Base):
    """Configuration model"""
    __tablename__ = "config"
    
    key = Column(String, primary_key=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
