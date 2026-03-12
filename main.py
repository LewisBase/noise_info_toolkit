import json
import asyncio
from pathlib import Path
from typing import Dict, Any
from sqlalchemy import and_
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

from app.models import WatchDirectoryRequest, WatchDirectoryResponse, MetricsRequest, MetricsResponse
from app.core import AudioProcessingTaskManager
from app.database import DatabaseManager, ProcessingResult
from app.utils import logger


def convert_to_serializable(obj):
    """将 numpy 类型转换为 Python 原生类型"""
    import numpy as np
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: convert_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_to_serializable(item) for item in obj]
    return obj


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
            and_(
                ProcessingResult.file_dir == str(Path(current_watch_directory).name),
                ProcessingResult.file_name.startswith(request_channel.microphone_channel)
            )).order_by(
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
        # 构建查询条件
        query_conditions = [
            ProcessingResult.file_name.startswith(request_channel.microphone_channel)
        ]
        
        # 如果提供了开始时间，则添加时间过滤条件
        if request_channel.start_time:
            query_conditions.append(
                ProcessingResult.timestamp >= request_channel.start_time
            )
            
        results = db.query(ProcessingResult).where(
            and_(*query_conditions)
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


# ==================== Session Management APIs ====================

from pydantic import BaseModel
from typing import Optional
from app.core.dose_calculator import DoseStandard

class CreateSessionRequest(BaseModel):
    profile: str = "NIOSH"  # NIOSH, OSHA_PEL, OSHA_HCA, EU_ISO
    device_id: Optional[str] = None
    operator: Optional[str] = None
    organization: Optional[str] = None
    notes: Optional[str] = None

class SessionResponse(BaseModel):
    code: int
    data: Dict[str, Any] = {}
    message: str
    
    class Config:
        arbitrary_types_allowed = True

@app.post("/session/create", response_model=SessionResponse)
async def create_session(request: CreateSessionRequest):
    """创建新的测量会话"""
    try:
        if not task_manager:
            return SessionResponse(code=500, message="任务管理器未初始化")
        
        # Parse profile
        try:
            profile = DoseStandard(request.profile.upper())
        except ValueError:
            return SessionResponse(code=400, message=f"无效的标准: {request.profile}")
        
        session = task_manager.create_session(
            profile=profile,
            device_id=request.device_id,
            operator=request.operator
        )
        
        return SessionResponse(
            code=200,
            data={
                "session_id": session.session_id,
                "state": session.state.value,
                "start_time": session.metrics.start_time.isoformat() if session.metrics.start_time else None,
            },
            message="会话创建成功"
        )
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        return SessionResponse(code=500, message=f"创建会话失败: {str(e)}")


@app.post("/session/stop", response_model=SessionResponse)
async def stop_session():
    """停止当前会话"""
    try:
        if not task_manager:
            return SessionResponse(code=500, message="任务管理器未初始化")
        
        summary = task_manager.stop_current_session()
        if not summary:
            return SessionResponse(code=404, message="没有活动的会话")
        
        return SessionResponse(
            code=200,
            data=summary,
            message="会话已停止"
        )
    except Exception as e:
        logger.error(f"Error stopping session: {e}")
        return SessionResponse(code=500, message=f"停止会话失败: {str(e)}")


@app.get("/session/current", response_model=SessionResponse)
async def get_current_session():
    """获取当前会话状态"""
    try:
        if not task_manager:
            return SessionResponse(code=500, message="任务管理器未初始化")
        
        summary = task_manager.get_current_session_summary()
        if not summary:
            return SessionResponse(code=404, message="没有活动的会话")
        
        # 转换 numpy 类型为 Python 原生类型
        summary = convert_to_serializable(summary)
        
        return SessionResponse(
            code=200,
            data=summary,
            message="获取会话状态成功"
        )
    except Exception as e:
        logger.error(f"Error getting current session: {e}")
        return SessionResponse(code=500, message=f"获取会话状态失败: {str(e)}")


@app.get("/session/list", response_model=SessionResponse)
async def list_sessions(limit: int = 50, offset: int = 0):
    """列出所有会话摘要"""
    try:
        sessions = db_manager.list_sessions(limit=limit, offset=offset)
        return SessionResponse(
            code=200,
            data={"sessions": sessions, "count": len(sessions)},
            message="获取会话列表成功"
        )
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        return SessionResponse(code=500, message=f"获取会话列表失败: {str(e)}")


@app.get("/session/{session_id}", response_model=SessionResponse)
async def get_session_summary(session_id: str):
    """获取指定会话的摘要"""
    try:
        summary = db_manager.get_session_summary(session_id)
        if not summary:
            return SessionResponse(code=404, message="会话不存在")
        
        return SessionResponse(
            code=200,
            data=summary,
            message="获取会话摘要成功"
        )
    except Exception as e:
        logger.error(f"Error getting session summary: {e}")
        return SessionResponse(code=500, message=f"获取会话摘要失败: {str(e)}")


# ==================== TimeHistory APIs ====================

from datetime import datetime as dt

@app.get("/session/{session_id}/time_history", response_model=SessionResponse)
async def get_time_history(
    session_id: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 10000
):
    """获取指定会话的时间历程数据"""
    try:
        # Parse time strings if provided
        start_dt = dt.fromisoformat(start_time) if start_time else None
        end_dt = dt.fromisoformat(end_time) if end_time else None
        
        records = db_manager.get_time_history(
            session_id=session_id,
            start_time=start_dt,
            end_time=end_dt,
            limit=limit
        )
        
        return SessionResponse(
            code=200,
            data={
                "session_id": session_id,
                "record_count": len(records),
                "records": records
            },
            message="获取时间历程数据成功"
        )
    except Exception as e:
        logger.error(f"Error getting time history: {e}")
        return SessionResponse(code=500, message=f"获取时间历程数据失败: {str(e)}")


@app.get("/session/{session_id}/time_history/summary", response_model=SessionResponse)
async def get_time_history_summary(session_id: str):
    """获取指定会话的时间历程汇总统计"""
    try:
        summary = db_manager.get_time_history_summary(session_id)
        return SessionResponse(
            code=200,
            data=summary,
            message="获取时间历程汇总成功"
        )
    except Exception as e:
        logger.error(f"Error getting time history summary: {e}")
        return SessionResponse(code=500, message=f"获取时间历程汇总失败: {str(e)}")


# ==================== Dose Profile APIs ====================

@app.get("/dose_profiles", response_model=SessionResponse)
async def get_dose_profiles():
    """获取所有剂量计算标准配置"""
    try:
        profiles = db_manager.get_dose_profiles()
        return SessionResponse(
            code=200,
            data={"profiles": profiles},
            message="获取剂量标准配置成功"
        )
    except Exception as e:
        logger.error(f"Error getting dose profiles: {e}")
        return SessionResponse(code=500, message=f"获取剂量标准配置失败: {str(e)}")


# ==================== Event Detection APIs (Phase 3) ====================

@app.get("/session/{session_id}/events", response_model=SessionResponse)
async def get_session_events(
    session_id: str,
    limit: int = 100,
    offset: int = 0
):
    """获取指定会话的事件列表"""
    try:
        events = db_manager.get_events(
            session_id=session_id,
            limit=limit,
            offset=offset
        )
        
        return SessionResponse(
            code=200,
            data={
                "session_id": session_id,
                "event_count": len(events),
                "events": events
            },
            message="获取事件列表成功"
        )
    except Exception as e:
        logger.error(f"Error getting events: {e}")
        return SessionResponse(code=500, message=f"获取事件列表失败: {str(e)}")


@app.get("/session/{session_id}/events/summary", response_model=SessionResponse)
async def get_session_events_summary(session_id: str):
    """获取指定会话的事件统计摘要"""
    try:
        summary = db_manager.get_event_summary(session_id)
        return SessionResponse(
            code=200,
            data=summary,
            message="获取事件统计成功"
        )
    except Exception as e:
        logger.error(f"Error getting event summary: {e}")
        return SessionResponse(code=500, message=f"获取事件统计失败: {str(e)}")


@app.get("/events", response_model=SessionResponse)
async def get_all_events(
    limit: int = 100,
    offset: int = 0
):
    """获取所有事件列表（跨会话）"""
    try:
        events = db_manager.get_events(
            session_id=None,
            limit=limit,
            offset=offset
        )
        
        return SessionResponse(
            code=200,
            data={
                "event_count": len(events),
                "events": events
            },
            message="获取所有事件成功"
        )
    except Exception as e:
        logger.error(f"Error getting all events: {e}")
        return SessionResponse(code=500, message=f"获取事件列表失败: {str(e)}")
