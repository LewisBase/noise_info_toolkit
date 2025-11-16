from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
import asyncio
from typing import List

from app.core import AudioProcessingTaskManager
from app.database import DatabaseManager, ProcessingResult
from app.utils import logger

# Global variables for background tasks
task_manager = None
current_watch_directory = "./audio_files"  # 默认目录
db_manager = DatabaseManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global task_manager
    
    # Initialize and start background tasks
    logger.info("Starting background tasks...")
    task_manager = AudioProcessingTaskManager(watch_directory=current_watch_directory)
    # Removed setting results storage since we'll use database
    
    # Start monitoring
    await task_manager.start_monitoring()
    
    yield
    
    # Cleanup on shutdown
    logger.info("Stopping background tasks...")
    if task_manager:
        await task_manager.stop_monitoring()

app = FastAPI(lifespan=lifespan, title="Noise Info Toolkit API", version="1.0.0")

@app.get("/")
async def root():
    return {"message": "Noise Info Toolkit API", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "monitoring": task_manager.is_monitoring if task_manager else False}

@app.post("/change_watch_directory")
async def change_watch_directory(new_directory: str):
    """动态更改监控目录"""
    global task_manager, current_watch_directory
    
    # 停止当前监控
    if task_manager:
        await task_manager.stop_monitoring()
    
    # 更新目录并重启监控
    current_watch_directory = new_directory
    task_manager = AudioProcessingTaskManager(current_watch_directory)
    # Removed setting results storage since we'll use database
    await task_manager.start_monitoring()
    
    return {"message": f"监控目录已更改为: {new_directory}"}

@app.get("/latest_metrics")
async def get_latest_metrics():
    """获取最新的处理结果"""
    # Get latest result from database
    db = next(db_manager.get_db())
    try:
        latest_result = db.query(ProcessingResult).order_by(
            ProcessingResult.timestamp.desc()
        ).first()
        
        if latest_result:
            # Convert to dictionary format
            result_dict = {
                "id": latest_result.id,
                "file_path": latest_result.file_path,
                "timestamp": latest_result.timestamp.isoformat(),
                "metrics": {}
            }
            
            # Add metrics to result
            for metric in latest_result.metrics:
                if metric.metric_type == "numeric":
                    result_dict["metrics"][metric.metric_name] = metric.metric_value
                elif metric.metric_type == "spectrum":
                    # Reconstruct spectrum data
                    spectrum_data = {}
                    for data_point in metric.spectrum_data:
                        spectrum_data[data_point.frequency] = data_point.value
                    result_dict["metrics"][metric.metric_name] = spectrum_data
            return result_dict
        return {}
    finally:
        db.close()

@app.get("/all_metrics")
async def get_all_metrics():
    """获取所有处理结果"""
    db = next(db_manager.get_db())
    try:
        results = db.query(ProcessingResult).order_by(
            ProcessingResult.timestamp.asc()
        ).all()
        
        results_list = []
        for result in results:
            result_dict = {
                "id": result.id,
                "file_path": result.file_path,
                "timestamp": result.timestamp.isoformat(),
                "metrics": {}
            }
            
            # Add metrics to result
            for metric in result.metrics:
                if metric.metric_type == "numeric":
                    result_dict["metrics"][metric.metric_name] = metric.metric_value
                elif metric.metric_type == "spectrum":
                    # Reconstruct spectrum data
                    spectrum_data = {}
                    for data_point in metric.spectrum_data:
                        spectrum_data[data_point.frequency] = data_point.value
                    result_dict["metrics"][metric.metric_name] = spectrum_data
                    
            results_list.append(result_dict)
            
        return results_list
    finally:
        db.close()

@app.get("/status")
async def get_status():
    """提供系统状态信息"""
    return {
        "status": "running" if task_manager and task_manager.is_monitoring else "stopped",
        "watch_directory": task_manager.watch_directory if task_manager else "./audio_files"
    }