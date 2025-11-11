from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio

from app.core import AudioProcessingTaskManager, ConnectionManager
from app.utils import logger, serialize_processing_results


# Global variables for background tasks
task_manager = None
manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global task_manager
    
    # Initialize and start background tasks
    logger.info("Starting background tasks...")
    task_manager = AudioProcessingTaskManager("./audio_files")
    task_manager.set_processing_callback(on_audio_processed)
    
    # Start monitoring
    await task_manager.start_monitoring()
    
    yield
    
    # Cleanup on shutdown
    logger.info("Stopping background tasks...")
    if task_manager:
        await task_manager.stop_monitoring()

app = FastAPI(lifespan=lifespan, title="Noise Info Toolkit API", version="1.0.0")

async def on_audio_processed(file_path: str, results: dict):
    """Callback function for processed audio files"""
    logger.info(f"Audio file processed: {file_path}")
    
    # Serialize results
    serialized_results = serialize_processing_results(file_path, results)
    
    # Broadcast results to all connected WebSocket clients
    await manager.broadcast(serialized_results)

@app.get("/")
async def root():
    return {"message": "Noise Info Toolkit API", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "monitoring": task_manager.is_monitoring if task_manager else False}

@app.get("/websocket-info")
async def websocket_info():
    """提供WebSocket连接信息"""
    return {
        "websocket_endpoint": "/ws",
        "description": "WebSocket endpoint for real-time audio processing updates",
        "connection_example": "ws://localhost:8000/ws",
        "status": "active" if task_manager and task_manager.is_monitoring else "inactive"
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo received data back to client
            await manager.send_personal_message(f"Received: {data}", websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)