# -*- coding: utf-8 -*-
"""
@DATE: 2025-11-17 22:36:37
@Author: Liu Hengjiang
@File: app\models\schemas.py
@Software: vscode
@Description:
        接口参数模型定义
"""

from pydantic import BaseModel
from typing import List, Dict, Union, Any
from app.models.result_schemas import ProcessingResultSchema


class WatchDirectoryRequest(BaseModel):
    """WatchDirectoryRequest
    请求参数模型
    """

    watch_directory: str

    
class WatchDirectoryResponse(BaseModel):
    """WatchDirectoryResponse
    响应参数模型
    """
    message: str


class MetricsRequest(BaseModel):
    """MetricsResponse
    请求参数模型
    """
    microphone_channel: str = "CH1"
    start_time: Union[str, None] = None


class MetricsResponse(BaseModel):
    """MetricsResponse
    响应参数模型
    """
    code: int
    message: str
    data: Union[List[dict],Dict[str, Any]]