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
from typing import List, Dict, Optional, Any


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
