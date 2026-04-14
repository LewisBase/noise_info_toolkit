"""
Database operations for noise info toolkit
"""
import os
import json
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import create_engine, func, and_, Integer
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
                          device_id: str = None,
                          # Kurtosis metrics
                          kurtosis_total: float = None,
                          kurtosis_a_weighted: float = None,
                          kurtosis_c_weighted: float = None,
                          beta_kurtosis: float = None,
                          # Raw moment statistics for aggregation
                          n_samples: int = 0,
                          sum_x: float = 0.0,
                          sum_x2: float = 0.0,
                          sum_x3: float = 0.0,
                          sum_x4: float = 0.0,
                          # Validity flags
                          valid_flag: bool = True,
                          artifact_flag: bool = False,
                          # 1/3倍频程频段SPL
                          freq_63hz_spl: float = None,
                          freq_125hz_spl: float = None,
                          freq_250hz_spl: float = None,
                          freq_500hz_spl: float = None,
                          freq_1khz_spl: float = None,
                          freq_2khz_spl: float = None,
                          freq_4khz_spl: float = None,
                          freq_8khz_spl: float = None,
                          freq_16khz_spl: float = None,
                          # 1/3倍频程频段原始矩统计量 S1-S4
                          freq_63hz_n: int = 0, freq_63hz_s1: float = 0.0, freq_63hz_s2: float = 0.0, freq_63hz_s3: float = 0.0, freq_63hz_s4: float = 0.0,
                          freq_125hz_n: int = 0, freq_125hz_s1: float = 0.0, freq_125hz_s2: float = 0.0, freq_125hz_s3: float = 0.0, freq_125hz_s4: float = 0.0,
                          freq_250hz_n: int = 0, freq_250hz_s1: float = 0.0, freq_250hz_s2: float = 0.0, freq_250hz_s3: float = 0.0, freq_250hz_s4: float = 0.0,
                          freq_500hz_n: int = 0, freq_500hz_s1: float = 0.0, freq_500hz_s2: float = 0.0, freq_500hz_s3: float = 0.0, freq_500hz_s4: float = 0.0,
                          freq_1khz_n: int = 0, freq_1khz_s1: float = 0.0, freq_1khz_s2: float = 0.0, freq_1khz_s3: float = 0.0, freq_1khz_s4: float = 0.0,
                          freq_2khz_n: int = 0, freq_2khz_s1: float = 0.0, freq_2khz_s2: float = 0.0, freq_2khz_s3: float = 0.0, freq_2khz_s4: float = 0.0,
                          freq_4khz_n: int = 0, freq_4khz_s1: float = 0.0, freq_4khz_s2: float = 0.0, freq_4khz_s3: float = 0.0, freq_4khz_s4: float = 0.0,
                          freq_8khz_n: int = 0, freq_8khz_s1: float = 0.0, freq_8khz_s2: float = 0.0, freq_8khz_s3: float = 0.0, freq_8khz_s4: float = 0.0,
                          freq_16khz_n: int = 0, freq_16khz_s1: float = 0.0, freq_16khz_s2: float = 0.0, freq_16khz_s3: float = 0.0, freq_16khz_s4: float = 0.0,
                          **kwargs) -> int:
        """Save time history record with kurtosis aggregation support"""
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
                # Kurtosis metrics
                kurtosis_total=kurtosis_total,
                kurtosis_a_weighted=kurtosis_a_weighted,
                kurtosis_c_weighted=kurtosis_c_weighted,
                beta_kurtosis=beta_kurtosis,
                # Raw moment statistics
                n_samples=n_samples,
                sum_x=sum_x,
                sum_x2=sum_x2,
                sum_x3=sum_x3,
                sum_x4=sum_x4,
                # Validity flags
                valid_flag=valid_flag,
                artifact_flag=artifact_flag,
                # 1/3倍频程频段SPL
                freq_63hz_spl=freq_63hz_spl,
                freq_125hz_spl=freq_125hz_spl,
                freq_250hz_spl=freq_250hz_spl,
                freq_500hz_spl=freq_500hz_spl,
                freq_1khz_spl=freq_1khz_spl,
                freq_2khz_spl=freq_2khz_spl,
                freq_4khz_spl=freq_4khz_spl,
                freq_8khz_spl=freq_8khz_spl,
                freq_16khz_spl=freq_16khz_spl,
                # 1/3倍频程频段原始矩统计量 S1-S4
                freq_63hz_n=freq_63hz_n, freq_63hz_s1=freq_63hz_s1, freq_63hz_s2=freq_63hz_s2, freq_63hz_s3=freq_63hz_s3, freq_63hz_s4=freq_63hz_s4,
                freq_125hz_n=freq_125hz_n, freq_125hz_s1=freq_125hz_s1, freq_125hz_s2=freq_125hz_s2, freq_125hz_s3=freq_125hz_s3, freq_125hz_s4=freq_125hz_s4,
                freq_250hz_n=freq_250hz_n, freq_250hz_s1=freq_250hz_s1, freq_250hz_s2=freq_250hz_s2, freq_250hz_s3=freq_250hz_s3, freq_250hz_s4=freq_250hz_s4,
                freq_500hz_n=freq_500hz_n, freq_500hz_s1=freq_500hz_s1, freq_500hz_s2=freq_500hz_s2, freq_500hz_s3=freq_500hz_s3, freq_500hz_s4=freq_500hz_s4,
                freq_1khz_n=freq_1khz_n, freq_1khz_s1=freq_1khz_s1, freq_1khz_s2=freq_1khz_s2, freq_1khz_s3=freq_1khz_s3, freq_1khz_s4=freq_1khz_s4,
                freq_2khz_n=freq_2khz_n, freq_2khz_s1=freq_2khz_s1, freq_2khz_s2=freq_2khz_s2, freq_2khz_s3=freq_2khz_s3, freq_2khz_s4=freq_2khz_s4,
                freq_4khz_n=freq_4khz_n, freq_4khz_s1=freq_4khz_s1, freq_4khz_s2=freq_4khz_s2, freq_4khz_s3=freq_4khz_s3, freq_4khz_s4=freq_4khz_s4,
                freq_8khz_n=freq_8khz_n, freq_8khz_s1=freq_8khz_s1, freq_8khz_s2=freq_8khz_s2, freq_8khz_s3=freq_8khz_s3, freq_8khz_s4=freq_8khz_s4,
                freq_16khz_n=freq_16khz_n, freq_16khz_s1=freq_16khz_s1, freq_16khz_s2=freq_16khz_s2, freq_16khz_s3=freq_16khz_s3, freq_16khz_s4=freq_16khz_s4,
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
    
    # ==================== TimeHistory Operations ====================
    
    def save_time_history_batch(self, session_id: str, 
                                 records: List[Dict[str, Any]]) -> int:
        """
        批量保存时间历程记录
        
        Args:
            session_id: 会话ID
            records: 时间历程记录列表
            
        Returns:
            int: 保存的记录数
        """
        db = self.SessionLocal()
        try:
            db_records = []
            for record in records:
                db_record = TimeHistory(
                    session_id=session_id,
                    device_id=record.get('device_id'),
                    timestamp_utc=record.get('timestamp'),
                    duration_s=record.get('duration_s', 1.0),
                    LAeq_dB=record.get('LAeq'),
                    LCeq_dB=record.get('LCeq'),
                    LZeq_dB=record.get('LZeq'),
                    LAFmax_dB=record.get('LAFmax'),
                    LZpeak_dB=record.get('LZpeak'),
                    LCpeak_dB=record.get('LCpeak'),
                    dose_frac_niosh=record.get('dose_frac_niosh', 0.0),
                    dose_frac_osha_pel=record.get('dose_frac_osha_pel', 0.0),
                    dose_frac_osha_hca=record.get('dose_frac_osha_hca', 0.0),
                    dose_frac_eu_iso=record.get('dose_frac_eu_iso', 0.0),
                    wearing_state=record.get('wearing_state', True),
                    overload_flag=record.get('overload_flag', False),
                    underrange_flag=record.get('underrange_flag', False),
                    # 频段数据
                    freq_63hz_spl=record.get('freq_63hz_spl'),
                    freq_125hz_spl=record.get('freq_125hz_spl'),
                    freq_250hz_spl=record.get('freq_250hz_spl'),
                    freq_500hz_spl=record.get('freq_500hz_spl'),
                    freq_1khz_spl=record.get('freq_1khz_spl'),
                    freq_2khz_spl=record.get('freq_2khz_spl'),
                    freq_4khz_spl=record.get('freq_4khz_spl'),
                    freq_8khz_spl=record.get('freq_8khz_spl'),
                    freq_16khz_spl=record.get('freq_16khz_spl'),
                    # 频段原始矩统计量 S1-S4
                    freq_63hz_n=record.get('freq_63hz_n', 0), freq_63hz_s1=record.get('freq_63hz_s1', 0.0), freq_63hz_s2=record.get('freq_63hz_s2', 0.0), freq_63hz_s3=record.get('freq_63hz_s3', 0.0), freq_63hz_s4=record.get('freq_63hz_s4', 0.0),
                    freq_125hz_n=record.get('freq_125hz_n', 0), freq_125hz_s1=record.get('freq_125hz_s1', 0.0), freq_125hz_s2=record.get('freq_125hz_s2', 0.0), freq_125hz_s3=record.get('freq_125hz_s3', 0.0), freq_125hz_s4=record.get('freq_125hz_s4', 0.0),
                    freq_250hz_n=record.get('freq_250hz_n', 0), freq_250hz_s1=record.get('freq_250hz_s1', 0.0), freq_250hz_s2=record.get('freq_250hz_s2', 0.0), freq_250hz_s3=record.get('freq_250hz_s3', 0.0), freq_250hz_s4=record.get('freq_250hz_s4', 0.0),
                    freq_500hz_n=record.get('freq_500hz_n', 0), freq_500hz_s1=record.get('freq_500hz_s1', 0.0), freq_500hz_s2=record.get('freq_500hz_s2', 0.0), freq_500hz_s3=record.get('freq_500hz_s3', 0.0), freq_500hz_s4=record.get('freq_500hz_s4', 0.0),
                    freq_1khz_n=record.get('freq_1khz_n', 0), freq_1khz_s1=record.get('freq_1khz_s1', 0.0), freq_1khz_s2=record.get('freq_1khz_s2', 0.0), freq_1khz_s3=record.get('freq_1khz_s3', 0.0), freq_1khz_s4=record.get('freq_1khz_s4', 0.0),
                    freq_2khz_n=record.get('freq_2khz_n', 0), freq_2khz_s1=record.get('freq_2khz_s1', 0.0), freq_2khz_s2=record.get('freq_2khz_s2', 0.0), freq_2khz_s3=record.get('freq_2khz_s3', 0.0), freq_2khz_s4=record.get('freq_2khz_s4', 0.0),
                    freq_4khz_n=record.get('freq_4khz_n', 0), freq_4khz_s1=record.get('freq_4khz_s1', 0.0), freq_4khz_s2=record.get('freq_4khz_s2', 0.0), freq_4khz_s3=record.get('freq_4khz_s3', 0.0), freq_4khz_s4=record.get('freq_4khz_s4', 0.0),
                    freq_8khz_n=record.get('freq_8khz_n', 0), freq_8khz_s1=record.get('freq_8khz_s1', 0.0), freq_8khz_s2=record.get('freq_8khz_s2', 0.0), freq_8khz_s3=record.get('freq_8khz_s3', 0.0), freq_8khz_s4=record.get('freq_8khz_s4', 0.0),
                    freq_16khz_n=record.get('freq_16khz_n', 0), freq_16khz_s1=record.get('freq_16khz_s1', 0.0), freq_16khz_s2=record.get('freq_16khz_s2', 0.0), freq_16khz_s3=record.get('freq_16khz_s3', 0.0), freq_16khz_s4=record.get('freq_16khz_s4', 0.0),
                )
                db_records.append(db_record)
            
            db.bulk_save_objects(db_records)
            db.commit()
            logger.info(f"Saved {len(db_records)} time history records for session {session_id}")
            return len(db_records)
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving time history batch: {e}")
            raise
        finally:
            db.close()
    
    def get_time_history(self, session_id: str, 
                         start_time: Optional[datetime] = None,
                         end_time: Optional[datetime] = None,
                         limit: int = 10000) -> List[Dict[str, Any]]:
        """
        获取时间历程数据
        
        Args:
            session_id: 会话ID
            start_time: 开始时间
            end_time: 结束时间
            limit: 最大返回记录数
            
        Returns:
            List[Dict]: 时间历程数据列表
        """
        db = self.SessionLocal()
        try:
            query = db.query(TimeHistory).filter(TimeHistory.session_id == session_id)
            
            if start_time:
                query = query.filter(TimeHistory.timestamp_utc >= start_time)
            if end_time:
                query = query.filter(TimeHistory.timestamp_utc <= end_time)
            
            records = query.order_by(TimeHistory.timestamp_utc.asc()).limit(limit).all()
            
            return [
                {
                    'id': r.id,
                    'timestamp': r.timestamp_utc.isoformat(),
                    'duration_s': r.duration_s,
                    'LAeq_dB': r.LAeq_dB,
                    'LCeq_dB': r.LCeq_dB,
                    'LZeq_dB': r.LZeq_dB,
                    'LAFmax_dB': r.LAFmax_dB,
                    'LZpeak_dB': r.LZpeak_dB,
                    'LCpeak_dB': r.LCpeak_dB,
                    'dose_frac_niosh': r.dose_frac_niosh,
                    'dose_frac_osha_pel': r.dose_frac_osha_pel,
                    'dose_frac_osha_hca': r.dose_frac_osha_hca,
                    'dose_frac_eu_iso': r.dose_frac_eu_iso,
                    'wearing_state': r.wearing_state,
                    'overload_flag': r.overload_flag,
                    'underrange_flag': r.underrange_flag,
                    # Kurtosis metrics (新增)
                    'kurtosis_total': r.kurtosis_total,
                    'kurtosis_a_weighted': r.kurtosis_a_weighted,
                    'kurtosis_c_weighted': r.kurtosis_c_weighted,
                    'beta_kurtosis': r.beta_kurtosis,
                    # Raw moment statistics (新增)
                    'n_samples': r.n_samples,
                    'sum_x': r.sum_x,
                    'sum_x2': r.sum_x2,
                    'sum_x3': r.sum_x3,
                    'sum_x4': r.sum_x4,
                    # Validity flags (新增)
                    'valid_flag': r.valid_flag,
                    'artifact_flag': r.artifact_flag,
                    # 1/3倍频程频段SPL (新增)
                    'freq_63hz_spl': r.freq_63hz_spl,
                    'freq_125hz_spl': r.freq_125hz_spl,
                    'freq_250hz_spl': r.freq_250hz_spl,
                    'freq_500hz_spl': r.freq_500hz_spl,
                    'freq_1khz_spl': r.freq_1khz_spl,
                    'freq_2khz_spl': r.freq_2khz_spl,
                    'freq_4khz_spl': r.freq_4khz_spl,
                    'freq_8khz_spl': r.freq_8khz_spl,
                    'freq_16khz_spl': r.freq_16khz_spl,
                    # 1/3倍频程频段原始矩统计量 S1-S4 (新增)
                    'freq_63hz_n': r.freq_63hz_n, 'freq_63hz_s1': r.freq_63hz_s1, 'freq_63hz_s2': r.freq_63hz_s2, 'freq_63hz_s3': r.freq_63hz_s3, 'freq_63hz_s4': r.freq_63hz_s4,
                    'freq_125hz_n': r.freq_125hz_n, 'freq_125hz_s1': r.freq_125hz_s1, 'freq_125hz_s2': r.freq_125hz_s2, 'freq_125hz_s3': r.freq_125hz_s3, 'freq_125hz_s4': r.freq_125hz_s4,
                    'freq_250hz_n': r.freq_250hz_n, 'freq_250hz_s1': r.freq_250hz_s1, 'freq_250hz_s2': r.freq_250hz_s2, 'freq_250hz_s3': r.freq_250hz_s3, 'freq_250hz_s4': r.freq_250hz_s4,
                    'freq_500hz_n': r.freq_500hz_n, 'freq_500hz_s1': r.freq_500hz_s1, 'freq_500hz_s2': r.freq_500hz_s2, 'freq_500hz_s3': r.freq_500hz_s3, 'freq_500hz_s4': r.freq_500hz_s4,
                    'freq_1khz_n': r.freq_1khz_n, 'freq_1khz_s1': r.freq_1khz_s1, 'freq_1khz_s2': r.freq_1khz_s2, 'freq_1khz_s3': r.freq_1khz_s3, 'freq_1khz_s4': r.freq_1khz_s4,
                    'freq_2khz_n': r.freq_2khz_n, 'freq_2khz_s1': r.freq_2khz_s1, 'freq_2khz_s2': r.freq_2khz_s2, 'freq_2khz_s3': r.freq_2khz_s3, 'freq_2khz_s4': r.freq_2khz_s4,
                    'freq_4khz_n': r.freq_4khz_n, 'freq_4khz_s1': r.freq_4khz_s1, 'freq_4khz_s2': r.freq_4khz_s2, 'freq_4khz_s3': r.freq_4khz_s3, 'freq_4khz_s4': r.freq_4khz_s4,
                    'freq_8khz_n': r.freq_8khz_n, 'freq_8khz_s1': r.freq_8khz_s1, 'freq_8khz_s2': r.freq_8khz_s2, 'freq_8khz_s3': r.freq_8khz_s3, 'freq_8khz_s4': r.freq_8khz_s4,
                    'freq_16khz_n': r.freq_16khz_n, 'freq_16khz_s1': r.freq_16khz_s1, 'freq_16khz_s2': r.freq_16khz_s2, 'freq_16khz_s3': r.freq_16khz_s3, 'freq_16khz_s4': r.freq_16khz_s4,
                }
                for r in records
            ]
        except Exception as e:
            logger.error(f"Error getting time history: {e}")
            return []
        finally:
            db.close()
    
    def get_time_history_summary(self, session_id: str) -> Dict[str, Any]:
        """
        获取时间历程汇总统计
        
        Args:
            session_id: 会话ID
            
        Returns:
            Dict: 汇总统计信息
        """
        db = self.SessionLocal()
        try:
            result = db.query(
                func.count(TimeHistory.id).label('count'),
                func.sum(TimeHistory.duration_s).label('total_duration'),
                func.min(TimeHistory.timestamp_utc).label('start_time'),
                func.max(TimeHistory.timestamp_utc).label('end_time'),
                func.avg(TimeHistory.LAeq_dB).label('avg_laeq'),
                func.min(TimeHistory.LAeq_dB).label('min_laeq'),
                func.max(TimeHistory.LAeq_dB).label('max_laeq'),
                func.max(TimeHistory.LZpeak_dB).label('max_lzpeak'),
                func.sum(TimeHistory.dose_frac_niosh).label('total_dose_niosh'),
                func.sum(TimeHistory.dose_frac_osha_pel).label('total_dose_osha_pel'),
                func.sum(TimeHistory.dose_frac_osha_hca).label('total_dose_osha_hca'),
                func.sum(TimeHistory.dose_frac_eu_iso).label('total_dose_eu_iso'),
                func.sum(TimeHistory.overload_flag.cast(Integer)).label('overload_count'),
                func.sum(TimeHistory.underrange_flag.cast(Integer)).label('underrange_count'),
            ).filter(TimeHistory.session_id == session_id).first()
            
            if result and result.count > 0:
                return {
                    'session_id': session_id,
                    'record_count': result.count,
                    'total_duration_s': result.total_duration or 0,
                    'start_time': result.start_time.isoformat() if result.start_time else None,
                    'end_time': result.end_time.isoformat() if result.end_time else None,
                    'avg_laeq': round(result.avg_laeq, 2) if result.avg_laeq else 0,
                    'min_laeq': round(result.min_laeq, 2) if result.min_laeq else 0,
                    'max_laeq': round(result.max_laeq, 2) if result.max_laeq else 0,
                    'max_lzpeak': round(result.max_lzpeak, 2) if result.max_lzpeak else 0,
                    'total_dose': {
                        'NIOSH': round(result.total_dose_niosh or 0, 4),
                        'OSHA_PEL': round(result.total_dose_osha_pel or 0, 4),
                        'OSHA_HCA': round(result.total_dose_osha_hca or 0, 4),
                        'EU_ISO': round(result.total_dose_eu_iso or 0, 4),
                    },
                    'overload_count': result.overload_count or 0,
                    'underrange_count': result.underrange_count or 0,
                }
            return {'session_id': session_id, 'record_count': 0}
        except Exception as e:
            logger.error(f"Error getting time history summary: {e}")
            return {'session_id': session_id, 'error': str(e)}
        finally:
            db.close()
    
    # ==================== SessionSummary Operations ====================
    
    def save_session_summary(self, session_id: str, 
                             profile_name: str,
                             start_time: datetime,
                             end_time: Optional[datetime],
                             total_duration_h: float,
                             laeq_t: float,
                             lex_8h: float,
                             total_dose_pct: float,
                             twa: float,
                             peak_max_db: float,
                             events_count: int = 0,
                             overload_count: int = 0,
                             underrange_count: int = 0,
                             **kwargs) -> int:
        """
        保存会话摘要
        
        Returns:
            int: 记录ID
        """
        db = self.SessionLocal()
        try:
            # Check if session summary already exists
            existing = db.query(SessionSummary).filter(
                SessionSummary.session_id == session_id).first()
            
            if existing:
                # Update existing
                existing.end_time_utc = end_time
                existing.total_duration_h = total_duration_h
                existing.LAeq_T = laeq_t
                existing.LEX_8h = lex_8h
                existing.total_dose_pct = total_dose_pct
                existing.TWA = twa
                existing.peak_max_dB = peak_max_db
                existing.events_count = events_count
                existing.overload_count = overload_count
                existing.underrange_count = underrange_count
                db.commit()
                logger.info(f"Updated session summary for {session_id}")
                return existing.id
            else:
                # Create new
                summary = SessionSummary(
                    session_id=session_id,
                    profile_name=profile_name,
                    start_time_utc=start_time,
                    end_time_utc=end_time,
                    total_duration_h=total_duration_h,
                    LAeq_T=laeq_t,
                    LEX_8h=lex_8h,
                    total_dose_pct=total_dose_pct,
                    TWA=twa,
                    peak_max_dB=peak_max_db,
                    events_count=events_count,
                    overload_count=overload_count,
                    underrange_count=underrange_count,
                    **kwargs
                )
                db.add(summary)
                db.commit()
                db.refresh(summary)
                logger.info(f"Created session summary for {session_id}")
                return summary.id
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving session summary: {e}")
            raise
        finally:
            db.close()
    
    def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话摘要"""
        db = self.SessionLocal()
        try:
            summary = db.query(SessionSummary).filter(
                SessionSummary.session_id == session_id).first()
            
            if summary:
                return {
                    'id': summary.id,
                    'session_id': summary.session_id,
                    'profile_name': summary.profile_name,
                    'start_time': summary.start_time_utc.isoformat() if summary.start_time_utc else None,
                    'end_time': summary.end_time_utc.isoformat() if summary.end_time_utc else None,
                    'total_duration_h': summary.total_duration_h,
                    'LAeq_T': summary.LAeq_T,
                    'LEX_8h': summary.LEX_8h,
                    'total_dose_pct': summary.total_dose_pct,
                    'TWA': summary.TWA,
                    'peak_max_dB': summary.peak_max_dB,
                    'events_count': summary.events_count,
                    'overload_count': summary.overload_count,
                    'underrange_count': summary.underrange_count,
                }
            return None
        except Exception as e:
            logger.error(f"Error getting session summary: {e}")
            return None
        finally:
            db.close()
    
    def list_sessions(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """列出所有会话摘要"""
        db = self.SessionLocal()
        try:
            summaries = db.query(SessionSummary).order_by(
                SessionSummary.start_time_utc.desc()).offset(offset).limit(limit).all()
            
            return [
                {
                    'session_id': s.session_id,
                    'profile_name': s.profile_name,
                    'start_time': s.start_time_utc.isoformat() if s.start_time_utc else None,
                    'end_time': s.end_time_utc.isoformat() if s.end_time_utc else None,
                    'total_duration_h': s.total_duration_h,
                    'LAeq_T': s.LAeq_T,
                    'TWA': s.TWA,
                    'total_dose_pct': s.total_dose_pct,
                    'events_count': s.events_count,
                }
                for s in summaries
            ]
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            return []
        finally:
            db.close()
    
    # ==================== EventLog Operations ====================
    
    def save_event(self, session_id: str, event_id: str,
                   start_time: datetime, end_time: Optional[datetime],
                   duration_s: float, trigger_type: str,
                   lzpeak_db: float, lcpeak_db: float,
                   laeq_event_db: float, sel_lae_db: float,
                   beta_excess_z: Optional[float] = None,
                   audio_file_path: Optional[str] = None,
                   pretrigger_s: float = 2.0, posttrigger_s: float = 8.0,
                   notes: Optional[str] = None) -> int:
        """
        保存事件记录
        
        Returns:
            int: 记录ID
        """
        from app.database.models import EventLog
        
        db = self.SessionLocal()
        try:
            event = EventLog(
                session_id=session_id,
                event_id=event_id,
                start_time_utc=start_time,
                end_time_utc=end_time,
                duration_s=duration_s,
                trigger_type=trigger_type,
                LZpeak_dB=lzpeak_db,
                LCpeak_dB=lcpeak_db,
                LAeq_event_dB=laeq_event_db,
                SEL_LAE_dB=sel_lae_db,
                beta_excess_event_Z=beta_excess_z,
                audio_file_path=audio_file_path,
                pretrigger_s=pretrigger_s,
                posttrigger_s=posttrigger_s,
                notes=notes
            )
            db.add(event)
            db.commit()
            db.refresh(event)
            
            logger.info(f"Saved event: {event_id} for session {session_id}")
            return event.id
        except Exception as e:
            db.rollback()
            logger.error(f"Error saving event: {e}")
            raise
        finally:
            db.close()
    
    def get_events(self, session_id: Optional[str] = None,
                   limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """
        获取事件列表
        
        Args:
            session_id: 会话ID（可选，为None则返回所有事件）
            limit: 限制数量
            offset: 偏移量
            
        Returns:
            List[Dict]: 事件列表
        """
        from app.database.models import EventLog
        
        db = self.SessionLocal()
        try:
            query = db.query(EventLog)
            
            if session_id:
                query = query.filter(EventLog.session_id == session_id)
            
            events = query.order_by(
                EventLog.start_time_utc.desc()).offset(offset).limit(limit).all()
            
            return [
                {
                    'id': e.id,
                    'session_id': e.session_id,
                    'event_id': e.event_id,
                    'start_time': e.start_time_utc.isoformat() if e.start_time_utc else None,
                    'end_time': e.end_time_utc.isoformat() if e.end_time_utc else None,
                    'duration_s': e.duration_s,
                    'trigger_type': e.trigger_type,
                    'lzpeak_db': e.LZpeak_dB,
                    'lcpeak_db': e.LCpeak_dB,
                    'laeq_event_db': e.LAeq_event_dB,
                    'sel_lae_db': e.SEL_LAE_dB,
                    'beta_excess_z': e.beta_excess_event_Z,
                    'audio_file_path': e.audio_file_path,
                    'pretrigger_s': e.pretrigger_s,
                    'posttrigger_s': e.posttrigger_s,
                    'notes': e.notes,
                }
                for e in events
            ]
        except Exception as e:
            logger.error(f"Error getting events: {e}")
            return []
        finally:
            db.close()
    
    def get_event_summary(self, session_id: str) -> Dict[str, Any]:
        """
        获取事件统计摘要
        
        Args:
            session_id: 会话ID
            
        Returns:
            Dict: 事件统计信息
        """
        from app.database.models import EventLog
        from sqlalchemy import func
        
        db = self.SessionLocal()
        try:
            result = db.query(
                func.count(EventLog.id).label('count'),
                func.avg(EventLog.duration_s).label('avg_duration'),
                func.max(EventLog.LZpeak_dB).label('max_lzpeak'),
                func.max(EventLog.LCpeak_dB).label('max_lcpeak'),
                func.avg(EventLog.LAeq_event_dB).label('avg_laeq'),
                func.count(EventLog.trigger_type).filter(
                    EventLog.trigger_type == 'peak').label('peak_count'),
                func.count(EventLog.trigger_type).filter(
                    EventLog.trigger_type == 'leq').label('leq_count'),
                func.count(EventLog.trigger_type).filter(
                    EventLog.trigger_type == 'slope').label('slope_count'),
            ).filter(EventLog.session_id == session_id).first()
            
            if result:
                return {
                    'session_id': session_id,
                    'total_events': result.count or 0,
                    'avg_duration_s': round(result.avg_duration, 3) if result.avg_duration else 0,
                    'max_lzpeak_db': round(result.max_lzpeak, 2) if result.max_lzpeak else 0,
                    'max_lcpeak_db': round(result.max_lcpeak, 2) if result.max_lcpeak else 0,
                    'avg_laeq_event_db': round(result.avg_laeq, 2) if result.avg_laeq else 0,
                    'trigger_type_counts': {
                        'peak': result.peak_count or 0,
                        'leq': result.leq_count or 0,
                        'slope': result.slope_count or 0,
                    }
                }
            return {'session_id': session_id, 'total_events': 0}
        except Exception as e:
            logger.error(f"Error getting event summary: {e}")
            return {'session_id': session_id, 'error': str(e)}
        finally:
            db.close()
