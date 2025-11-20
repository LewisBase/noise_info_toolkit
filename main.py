import json
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from typing import List

from app.models import WatchDirectoryRequest, WatchDirectoryResponse, MetricsRequest, MetricsResponse
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

    logger.info("Starting background tasks...")
    task_manager = AudioProcessingTaskManager(
        watch_directory=current_watch_directory)
    # Start monitoring
    await task_manager.start_monitoring()
    yield

    # Cleanup on shutdown
    logger.info("Stopping background tasks...")
    if task_manager:
        await task_manager.stop_monitoring()

app = FastAPI(lifespan=lifespan,
              title="Noise Info Toolkit API", version="1.0.0")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    处理请求参数验证错误
    """
    # 缓存请求体避免重复读取
    try:
        body = await request.body()
        body_json = json.loads(body.decode("utf-8"))
        logger.error(
            f"Request body: {json.dumps(body_json, ensure_ascii=False, indent=2)}")
    except:
        # 如果无法解析JSON，直接以UTF-8字符串形式记录
        body_str = body.decode("utf-8", errors="replace")
        logger.error(f"Request body: {body_str}")

    logger.error(f"422 Validation Error - Request URL: {request.url}")
    logger.error(f"Validation errors: {exc.errors()}")

    # 返回结构化的422响应而不是直接抛出异常
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "body": body.decode() if isinstance(body, bytes) else str(body)
        }
    )


@app.get("/")
async def root():
    return {"message": "Noise Info Toolkit API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "monitoring": task_manager.is_monitoring if task_manager else False}


@app.post("/change_watch_directory", response_model=WatchDirectoryResponse)
async def change_watch_directory(new_directory: WatchDirectoryRequest):
    """动态更改监控目录"""
    global task_manager, current_watch_directory
    # 停止当前监控
    if task_manager:
        await task_manager.stop_monitoring()
    # 更新目录并重启监控
    current_watch_directory = new_directory.watch_directory
    logger.info(f"Changing watch directory to: {current_watch_directory}")
    task_manager = AudioProcessingTaskManager(current_watch_directory)
    # Removed setting results storage since we'll use database
    await task_manager.start_monitoring()
    return WatchDirectoryResponse(message=f"监控目录已更改为: {new_directory}")


@app.post("/latest_metrics", response_model=MetricsResponse)
async def get_latest_metrics(request_channel: MetricsRequest):
    """获取最新的处理结果"""
    # Get latest result from database
    db = next(db_manager.get_db())
    try:
        latest_result = db.query(ProcessingResult).where(
            ProcessingResult.file_dir == str(Path(current_watch_directory).name) and
            ProcessingResult.file_name.startswith(request_channel.microphone_channel)
            ).order_by(
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
            return MetricsResponse(code=200, data=result_dict, message="成功获取最新处理结果")
    except Exception as e:
        return MetricsResponse(code=500, data={}, message=f"获取最新处理结果失败: {str(e)}")
    finally:
        db.close()


@app.post("/all_metrics", response_model=MetricsResponse)
async def get_all_metrics(request_channel: MetricsRequest):
    """获取所有处理结果"""
    db = next(db_manager.get_db())
    try:
        results = db.query(ProcessingResult).where(
            ProcessingResult.file_name.startswith(request_channel.microphone_channel) and 
            ProcessingResult.timestamp >= request_channel.start_time if request_channel.start_time else True
            ).order_by(
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
            return MetricsResponse(code=200, data=results_list, message="成功获取所有处理结果")
    except Exception as e:
        return MetricsResponse(code=500, data=[], message=f"获取所有处理结果失败:{e}")
    finally:
        db.close()


@app.get("/status")
async def get_status():
    """提供系统状态信息"""
    return {
        "status": "running" if task_manager and task_manager.is_monitoring else "stopped",
        "watch_directory": task_manager.watch_directory if task_manager else "./audio_files"
    }
