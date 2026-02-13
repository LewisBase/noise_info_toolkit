"""
Database operations for noise info toolkit
"""
import os
import json
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import create_engine, func, and_
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from app.database.models import (
    Base, ProcessingResult, ProcessingMetric, SpectrumData, Config,
    DoseProfile, TimeHistory, EventLog, SessionSummary, Metadata
)
from app.utils import logger


class DatabaseManager:
    """Database manager for noise info toolkit"""
    
    def __init__(self, database_url: str = None):
        # Create Database directory if it doesn't exist
        db_dir = "./Database"
        if not os.path.exists(db_dir):
            os.makedirs(db_dir)
        
        if database_url is None:
            database_url = f"sqlite:///{db_dir}/noise_info.db"
        
        self.database_url = database_url
        self.engine = create_engine(database_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Initialize default dose profiles
        self._init_dose_profiles()
    
    def _init_dose_profiles(self):
        """Initialize default dose profiles if not exists"""
        db = self.SessionLocal()
        try:
            # Check if profiles already exist
            existing = db.query(DoseProfile).count()
            if existing == 0:
                # Create default profiles
                profiles = [
                    DoseProfile(
                        profile_name="NIOSH",
                        criterion_level_dBA=85.0,
                        exchange_rate_dB=3.0,
                        threshold_dBA=0.0,
                        reference_duration_h=8.0,
                        description="NIOSH标准: 85dBA准则级, 3dB交换率, 8小时参考时长"
                    ),
                    DoseProfile(
                        profile_name="OSHA_PEL",
                        criterion_level_dBA=90.0,
                        exchange_rate_dB=5.0,
                        threshold_dBA=0.0,
                        reference_duration_h=8.0,
                        description="OSHA_PEL标准: 90dBA准则级, 5dB交换率, 8小时参考时长"
                    ),
                    DoseProfile(
                        profile_name="OSHA_HCA",
                        criterion_level_dBA=85.0,
                        exchange_rate_dB=5.0,
                        threshold_dBA=0.0,
                        reference_duration_h=8.0,
                        description="OSHA_HCA标准: 85dBA准则级, 5dB交换率, 8小时参考时长"
                    ),
                    DoseProfile(
                        profile_name="EU_ISO",
                        criterion_level_dBA=85.0,
                        exchange_rate_dB=3.0,
                        threshold_dBA=0.0,
                        reference_duration_h=8.0,
                        description="EU_ISO标准: 85dBA准则级, 3dB交换率, 8小时参考时长"
                    ),
                ]
                for profile in profiles:
                    db.add(profile)
                db.commit()
                logger.info("Initialized default dose profiles")
        except Exception as e:
            db.rollback()
            logger.error(f"Error initializing dose profiles: {e}")
        finally:
            db.close()
    
    def get_db(self):
        """Get database session"""
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    def get_dose_profiles(self) -> List[Dict[str, Any]]:
        """Get all dose profiles"""
        db = self.SessionLocal()
        try:
            profiles = db.query(DoseProfile).all()
            return [
                {
                    "id": p.id,
                    "profile_name": p.profile_name,
                    "criterion_level_dBA": p.criterion_level_dBA,
                    "exchange_rate_dB": p.exchange_rate_dB,
                    "threshold_dBA": p.threshold_dBA,
                    "reference_duration_h": p.reference_duration_h,
                    "description": p.description
                }
                for p in profiles
            ]
        except Exception as e:
            logger.error(f"Error getting dose profiles: {e}")
            return []
        finally:
            db.close()
    
    def get_dose_profile(self, profile_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific dose profile by name"""
        db = self.SessionLocal()
        try:
            profile = db.query(DoseProfile).filter(DoseProfile.profile_name == profile_name).first()
            if profile:
                return {
                    "id": profile.id,
                    "profile_name": profile.profile_name,
                    "criterion_level_dBA": profile.criterion_level_dBA,
                    "exchange_rate_dB": profile.exchange_rate_dB,
                    "threshold_dBA": profile.threshold_dBA,
                    "reference_duration_h": profile.reference_duration_h,
                    "description": profile.description
                }
            return None
        except Exception as e:
            logger.error(f"Error getting dose profile: {e}")
            return None
        finally:
            db.close()
    
    def save_processing_result(self, file_path: str, metrics: Dict[str, Any], 
                               session_id: str = None) -> int:
        """Save processing result to database"""
        db = self.SessionLocal()
        try:
            # Create processing result
            db_result = ProcessingResult(
                file_path=file_path,
                file_dir=str(Path(file_path).parent),
                file_name=str(Path(file_path).name),
                timestamp=datetime.now(),
                session_id=session_id or str(uuid.uuid4()),
            )
            db.add(db_result)
            db.commit()
            db.refresh(db_result)
            
            result_id = db_result.id
            
            # Save metrics
            for metric_name, metric_value in metrics.items():
                if isinstance(metric_value, dict):
                    # This is spectrum data
                    db_metric = ProcessingMetric(
                        result_id=result_id,
                        metric_name=metric_name,
                        metric_type="spectrum"
                    )
                    db.add(db_metric)
                    db.commit()
                    db.refresh(db_metric)
                    
                    # Save spectrum data
                    for freq, value in metric_value["frequency_bands"].items():
                        # Ensure value is a scalar
                        if hasattr(value, '__len__') and not isinstance(value, str):
                            # If it's an array, take the first element
                            scalar_value = float(value[0]) if len(value) > 0 else 0.0
                        else:
                            scalar_value = float(value)
                            
                        spectrum_data = SpectrumData(
                            metric_id=db_metric.id,
                            frequency=str(freq),
                            value=scalar_value
                        )
                        db.add(spectrum_data)
                else:
                    # This is numeric data
                    # Ensure metric_value is a scalar
                    if hasattr(metric_value, '__len__') and not isinstance(metric_value, str):
                        # If it's an array, take the first element
                        scalar_value = float(metric_value[0]) if len(metric_value) > 0 else 0.0
                    else:
                        scalar_value = float(metric_value)
                        
                    db_metric = ProcessingMetric(
                        result_id=result_id,
                        metric_name=metric_name,
                        metric_value=scalar_value,
                        metric_type="numeric"
                    )
                    db.add(db_metric)
            
            db.commit()
            logger.info(f"Saved processing result for {file_path} with ID {result_id}")
            return result_id
        except Exception as e:
            db.rollback()
            error_msg = f"{type(e).__name__}: {str(e) if str(e) else repr(e)}"
            logger.error(f"Error saving processing result: {error_msg}")
            raise
        finally:
            db.close()
    
    def save_time_history(self, session_id: str, timestamp_utc: datetime,
                          laeq: float, lceq: float, lzpeak: float, lcpeak: float,
                          dose_fracs: Dict[str, float], duration_s: float = 1.0,
                          device_id: str = None, **kwargs) -> int:
        """Save time history record"""
        db = self.SessionLocal()
        try:
            record = TimeHistory(
                session_id=session_id,
                device_id=device_id,
                timestamp_utc=timestamp_utc,
                duration_s=duration_s,
                LAeq_dB=laeq,
                LCeq_dB=lceq,
                LZpeak_dB=lzpeak,
                LCpeak_dB=lcpeak,
                dose_frac_niosh=dose_fracs.get("NIOSH", 0.0),
                dose_frac_osha_pel=dose_fracs.get("OSHA_PEL", 0.0),
                dose_frac_osha_hca=dose_fracs.get("OSHA_HCA", 0.0),
                dose_frac_eu_iso=dose_fracs.get("EU_ISO", 0.0),
                **kwargs
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving time history: {e}")
            raise
        finally:
            db.close()
    
    def get_session_dose_summary(self, session_id: str) -> Dict[str, Any]:
        """Get cumulative dose summary for a session"""
        db = self.SessionLocal()
        try:
            # Calculate total dose for each standard
            result = db.query(
                func.sum(TimeHistory.dose_frac_niosh).label('total_niosh'),
                func.sum(TimeHistory.dose_frac_osha_pel).label('total_osha_pel'),
                func.sum(TimeHistory.dose_frac_osha_hca).label('total_osha_hca'),
                func.sum(TimeHistory.dose_frac_eu_iso).label('total_eu_iso'),
                func.count(TimeHistory.id).label('record_count'),
                func.sum(TimeHistory.duration_s).label('total_duration_s'),
                func.avg(TimeHistory.LAeq_dB).label('avg_laeq'),
                func.max(TimeHistory.LZpeak_dB).label('max_lzpeak'),
                func.max(TimeHistory.LCpeak_dB).label('max_lcpeak')
            ).filter(TimeHistory.session_id == session_id).first()
            
            if result and result.record_count > 0:
                return {
                    "session_id": session_id,
                    "record_count": result.record_count,
                    "total_duration_s": result.total_duration_s or 0,
                    "total_duration_h": (result.total_duration_s or 0) / 3600.0,
                    "dose": {
                        "NIOSH": result.total_niosh or 0.0,
                        "OSHA_PEL": result.total_osha_pel or 0.0,
                        "OSHA_HCA": result.total_osha_hca or 0.0,
                        "EU_ISO": result.total_eu_iso or 0.0,
                    },
                    "avg_laeq": result.avg_laeq or 0.0,
                    "max_lzpeak": result.max_lzpeak or 0.0,
                    "max_lcpeak": result.max_lcpeak or 0.0,
                }
            return {
                "session_id": session_id,
                "record_count": 0,
                "total_duration_s": 0,
                "total_duration_h": 0,
                "dose": {"NIOSH": 0.0, "OSHA_PEL": 0.0, "OSHA_HCA": 0.0, "EU_ISO": 0.0},
                "avg_laeq": 0.0,
                "max_lzpeak": 0.0,
                "max_lcpeak": 0.0,
            }
        except Exception as e:
            logger.error(f"Error getting session dose summary: {e}")
            return {}
        finally:
            db.close()
    
    def get_latest_result(self) -> Optional[Dict[str, Any]]:
        """Get the latest processing result"""
        db = self.SessionLocal()
        try:
            # Get the latest result
            latest_result = db.query(ProcessingResult).order_by(ProcessingResult.timestamp.desc()).first()
            
            if not latest_result:
                return None
            
            # Get metrics for this result
            metrics_data = self._get_metrics_for_result(db, latest_result.id)
            
            return {
                "id": latest_result.id,
                "file_path": latest_result.file_path,
                "session_id": latest_result.session_id,
                "timestamp": latest_result.timestamp.isoformat(),
                "metrics": metrics_data
            }
        except Exception as e:
            logger.error(f"Error getting latest result: {e}")
            return None
        finally:
            db.close()
    
    def get_history_results(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Get history processing results"""
        db = self.SessionLocal()
        try:
            # Get history results
            history_results = db.query(ProcessingResult).order_by(
                ProcessingResult.timestamp.desc()).offset(offset).limit(limit).all()
            
            results = []
            for result in history_results:
                metrics_data = self._get_metrics_for_result(db, result.id)
                results.append({
                    "id": result.id,
                    "file_path": result.file_path,
                    "session_id": result.session_id,
                    "timestamp": result.timestamp.isoformat(),
                    "metrics": metrics_data
                })
            
            return results
        except Exception as e:
            logger.error(f"Error getting history results: {e}")
            return []
        finally:
            db.close()
    
    def _get_metrics_for_result(self, db, result_id: int) -> Dict[str, Any]:
        """Get metrics for a specific result"""
        metrics = {}
        
        # Get all metrics for this result
        db_metrics = db.query(ProcessingMetric).filter(ProcessingMetric.result_id == result_id).all()
        
        for metric in db_metrics:
            if metric.metric_type == "numeric":
                metrics[metric.metric_name] = metric.metric_value
            elif metric.metric_type == "spectrum":
                # Get spectrum data
                spectrum_data = db.query(SpectrumData).filter(SpectrumData.metric_id == metric.id).all()
                spectrum_dict = {data.frequency: data.value for data in spectrum_data}
                metrics[metric.metric_name] = spectrum_dict
        
        return metrics
    
    def cleanup_history(self, days_old: int = 30) -> int:
        """Clean up old history data"""
        db = self.SessionLocal()
        try:
            # Calculate the cutoff date
            cutoff_date = datetime.now().replace(tzinfo=None) - timedelta(days=days_old)
            
            # Delete old results
            deleted_count = db.query(ProcessingResult).filter(
                ProcessingResult.timestamp < cutoff_date).delete()
            
            db.commit()
            logger.info(f"Cleaned up {deleted_count} old records")
            return deleted_count
        except Exception as e:
            db.rollback()
            logger.error(f"Error cleaning up history: {e}")
            return 0
        finally:
            db.close()
