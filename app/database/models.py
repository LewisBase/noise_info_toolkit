"""
Database models for noise info toolkit
"""
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import json
from datetime import datetime
from typing import Dict, Any, Optional

Base = declarative_base()

class ProcessingResult(Base):
    """Processing result model"""
    __tablename__ = "processing_result"
    
    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, index=True)
    file_dir = Column(String, index=True)
    file_name = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.now)
    
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

class Config(Base):
    """Configuration model"""
    __tablename__ = "config"
    
    key = Column(String, primary_key=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)