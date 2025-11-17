"""
Database operations for noise info toolkit
"""
import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from app.database.models import Base, ProcessingResult, ProcessingMetric, SpectrumData, Config
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
    
    def get_db(self):
        """Get database session"""
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    def save_processing_result(self, file_path: str, file_dir: str, metrics: Dict[str, Any]) -> int:
        """Save processing result to database"""
        db = self.SessionLocal()
        try:
            # Create processing result
            db_result = ProcessingResult(
                file_path=file_path,
                file_dir=file_dir,
                timestamp=datetime.now()
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
                    for freq, value in metric_value.items():
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