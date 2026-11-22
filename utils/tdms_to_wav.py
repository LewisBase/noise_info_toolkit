# -*- coding: utf-8 -*-
"""
@DATE: 2026-04-04
@Author: Liu Hengjiang
@File: utils/tdms_to_wav.py
@Description:
    TDMS转WAV命令行工具入口
    提供简单易用的命令行界面
"""

import sys
from pathlib import Path

# 添加项目根目录到路径（如果需要导入utils模块）
current_dir = Path(__file__).parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from utils.tdms_converter import TDMSConverter, main

if __name__ == "__main__":
    sys.exit(main())
