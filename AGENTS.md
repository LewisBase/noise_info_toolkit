# AGENTS.md - Noise Info Toolkit

**回答语言**: 始终使用中文进行回答。

本文档为AI编程助手提供项目背景、架构信息和开发指南。

## 项目概述

**噪声信息工具箱 (Noise Info Toolkit)** 是一个用于处理和分析噪声信号的工具箱，支持TDMS格式文件的实时监控和分析。

### 核心功能

1. **TDMS文件支持**：自动检测和处理TDMS格式的噪声信号文件
2. **实时监控**：监控指定目录中的新音频文件并自动处理
3. **噪声分析**：计算各种噪声指标，包括：
   - 等效声级 (Leq, LAeq, LCeq)
   - 峰值声压级
   - 1/3倍频程频谱
   - 峰度指标
4. **可视化展示**：使用Streamlit创建交互式前端界面
5. **WebSocket通信**：实时将处理结果推送到前端

## 技术栈

- **后端框架**：FastAPI + Uvicorn
- **前端框架**：Streamlit
- **数据库**：SQLite + SQLAlchemy ORM
- **音频处理**：librosa, soundfile, acoustics
- **科学计算**：numpy, pandas, scipy
- **数据可视化**：plotly
- **文件监控**：watchdog
- **TDMS处理**：nptdms
- **日志记录**：loguru

## 项目结构

```
noise_info_toolkit/
├── app/                          # 主应用包
│   ├── __init__.py               # FastAPI应用包标记
│   ├── core/                     # 核心处理模块
│   │   ├── __init__.py           # 导出核心类
│   │   ├── audio_processor.py    # 音频处理核心模块 (AudioProcessor)
│   │   ├── background_tasks.py   # 后台任务管理 (AudioProcessingTaskManager)
│   │   ├── connection_manager.py # WebSocket连接管理 (ConnectionManager)
│   │   ├── file_monitor.py       # 文件监控模块 (AudioFileMonitor)
│   │   └── tdms_converter.py     # TDMS到WAV转换模块 (TDMSConverter)
│   ├── database/                 # 数据库模块
│   │   ├── __init__.py           # 导出数据库类
│   │   ├── database.py           # 数据库操作 (DatabaseManager)
│   │   └── models.py             # SQLAlchemy模型定义
│   ├── models/                   # Pydantic模型定义
│   │   ├── __init__.py           # 导出所有schema
│   │   ├── request_schemas.py    # 请求参数模型
│   │   └── result_schemas.py     # 响应结果模型
│   └── utils/                    # 工具函数
│       ├── __init__.py           # 导出工具函数
│       ├── helpers.py            # 辅助函数
│       ├── logger.py             # 日志配置 (loguru)
│       └── task_utils.py         # 任务工具函数
├── audio_files/                  # 默认音频文件监控目录
├── Database/                     # SQLite数据库存储目录
├── log/                          # 日志文件目录
├── test/                         # 测试脚本
│   ├── test_database.py          # 数据库功能测试
│   ├── create_test_tdms.py       # 创建测试TDMS文件
│   ├── test_websocket_route.py   # WebSocket路由测试
│   ├── websocket_client.py       # WebSocket客户端测试
│   └── comprehensive_test.py     # 综合测试
├── main.py                       # FastAPI主应用入口
├── streamlit_app.py              # Streamlit前端应用
├── start_server.py               # 服务启动脚本
├── config.py                     # 应用配置 (Pydantic Settings)
├── requirements.txt              # Python依赖
└── README.md                     # 项目说明文档
```

## 架构说明

### 后端架构 (FastAPI)

**主入口**: `main.py`
- 使用 `lifespan` 上下文管理器管理后台任务生命周期
- 全局异常处理 (RequestValidationError)
- RESTful API 端点:
  - `GET /` - 根端点
  - `GET /health` - 健康检查
  - `POST /change_watch_directory` - 更改监控目录
  - `POST /latest_metrics` - 获取最新处理结果
  - `POST /all_metrics` - 获取所有历史结果
  - `GET /status` - 获取系统状态

**核心处理流程**:
1. `AudioProcessingTaskManager` 启动文件监控
2. `AudioFileMonitor` (基于watchdog) 检测新文件
3. `TDMSConverter` 将TDMS文件转换为WAV格式
4. `AudioProcessor` 计算噪声指标 (使用acoustics库)
5. `DatabaseManager` 保存处理结果到SQLite

### 前端架构 (Streamlit)

**主入口**: `streamlit_app.py`
- 三个主要标签页：
  1. **实时监控**: 显示当前噪声指标、1/3倍频程频谱、时间历程图
  2. **历史数据**: 上传文件分析和历史记录展示
  3. **系统状态**: 后端服务健康检查和目录信息
- 支持多通道选择 (CH1, CH2)
- 目录选择对话框 (tkinter)

### 数据流

```
TDMS/WAV文件 → FileMonitor → BackgroundTask → TDMSConverter → AudioProcessor → Database
                                                    ↓
                                              Streamlit Frontend ← REST API
```

## 数据库模型

使用SQLAlchemy ORM，SQLite数据库位于 `./Database/noise_info.db`。

### 表结构

1. **processing_result** - 处理结果主表
   - id, file_path, file_dir, file_name, timestamp

2. **processing_metrics** - 处理指标表
   - id, result_id, metric_name, metric_value, metric_type ('numeric'|'spectrum')

3. **spectrum_data** - 频谱数据表
   - id, metric_id, frequency, value

4. **config** - 配置表
   - key, value, updated_at

## 开发指南

### 环境设置

```bash
# 安装依赖
pip install -r requirements.txt
```

### 启动开发服务器

**方式1: 使用uvicorn命令**
```bash
# 启动后端 (端口8000)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 启动前端 (端口8501)
streamlit run streamlit_app.py
```

**方式2: 使用启动脚本**
```bash
# 启动后端
python start_server.py
```

### 调试配置

VS Code调试配置已包含在 `.vscode/launch.json`:
- **Python 调试程序: FastAPI** - 调试FastAPI后端
- **Python: 当前文件** - 调试当前Python文件

### 创建测试数据

```bash
# 创建测试TDMS文件
python test/create_test_tdms.py
```

### 日志查看

日志文件位置: `./log/noise_toolkit.log`
- 使用loguru记录
- 每日轮转 (rotation="00:00")
- 保留7天 (retention="7 days")
- 同时输出到文件和控制台

## 代码规范

### 文件头模板

```python
# -*- coding: utf-8 -*-
"""
@DATE: YYYY-MM-DD HH:mm:ss
@Author: Liu Hengjiang
@File: 文件路径
@Software: vscode
@Description:
        文件描述
"""
```

### 命名规范

- **类名**: PascalCase (如 `AudioProcessor`, `DatabaseManager`)
- **函数/方法**: snake_case (如 `process_wav_file`, `save_processing_result`)
- **常量**: UPPER_SNAKE_CASE
- **私有方法**: 单下划线前缀 (如 `_on_audio_file_detected`)

### 类型注解

- 使用Python类型注解
- 复杂类型使用 `typing` 模块 (如 `Dict[str, Any]`, `Optional[float]`)
- Pydantic模型用于请求/响应验证

## 测试策略

测试脚本位于 `test/` 目录，采用手动测试方式：

1. **test_database.py**: 测试数据库CRUD操作
2. **create_test_tdms.py**: 生成测试TDMS文件
3. **test_websocket_route.py**: 测试WebSocket路由
4. **websocket_client.py**: WebSocket客户端测试
5. **comprehensive_test.py**: 综合功能测试

运行测试:
```bash
python test/test_database.py
python test/create_test_tdms.py
```

## 部署说明

### 本地部署

1. 确保Python 3.11+ 环境
2. 安装依赖: `pip install -r requirements.txt`
3. 创建 `audio_files` 目录或使用现有目录
4. 启动后端: `python start_server.py`
5. 启动前端: `streamlit run streamlit_app.py`

### DevContainer支持

项目包含 `.devcontainer/devcontainer.json`，支持在GitHub Codespaces或VS Code Dev Containers中开发：
- 基础镜像: Python 3.11
- 自动安装依赖
- 端口转发: 8501 (Streamlit)

## 安全注意事项

1. **文件上传**: 当前版本只监控本地目录，不接收网络文件上传
2. **路径遍历**: 监控目录通过API动态更改，需确保路径合法性
3. **数据库**: 使用SQLite本地文件，无需额外认证
4. **CORS**: 开发环境未配置CORS限制，生产环境需根据需求配置

## 常见问题

### TDMS文件转换失败

- 检查nptdms库版本兼容性
- 确认TDMS文件包含有效的采样率属性
- 查看日志文件获取详细错误信息

### 数据库锁定错误

SQLite在并发写入时可能出现锁定错误。系统使用单线程线程池 (`max_workers=1`) 避免此问题。

### 前端无法连接后端

- 确认后端服务运行在8000端口
- 检查防火墙设置
- 使用侧边栏"诊断后端配置"按钮测试连接

## 依赖说明

主要依赖版本 (requirements.txt):
- fastapi - Web框架
- uvicorn - ASGI服务器
- streamlit - 前端界面
- sqlalchemy - ORM
- librosa - 音频处理
- acoustics - 声学计算标准
- nptdms - TDMS文件处理
- loguru - 日志记录
