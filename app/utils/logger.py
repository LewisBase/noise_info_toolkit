# -*- coding: utf-8 -*-
"""
@DATE: 2025-11-11 22:05:20
@Author: Liu Hengjiang
@File: app\\utils\\logger.py
@Software: vscode
@Description:
        日志配置
"""

from loguru import logger
from pathlib import Path


def formatter(record):
    # 确保 extra 中有默认值
    record["extra"].setdefault("request_id", "-")
    return (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level:<8}</level> | "
        "{name:<30}:{line:<4} | "
        "{extra[request_id]:<22} | "
        "<level>{message}</level>\n"
    )
    
    
def setup_logger():
    # 当前文件路径
    current_file = Path(__file__).resolve()
    
    # 项目根目录（假设结构：src/utils/logger_config.py）
    project_root = current_file.parent.parent.parent  # 向上三级：utils → src → project_root
    
    # 日志文件路径
    log_file = project_root / "log" / "noise_toolkit.log"
    
    # 创建目录
    log_file.parent.mkdir(exist_ok=True)
    if not log_file.parent.exists():
        log_file.parent.mkdir(parents=True, exist_ok=True)
        print(f"创建日志目录: {log_file.parent}")
    logger.remove()

    logger.add(
        sink=str(log_file),  # 转为字符串
        format=formatter,
        level="DEBUG",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        enqueue=True
    )

    logger.add(
        sink=lambda msg: print(msg, end=''),
        format=formatter,
        level="DEBUG",
        colorize=True
    )

    return logger

logger = setup_logger()
