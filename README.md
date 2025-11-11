# 噪声信息工具箱

一个用于处理和分析噪声信号的工具箱，支持TDMS格式文件的实时监控和分析。

## 功能特性

1. **TDMS文件支持**：自动检测和处理TDMS格式的噪声信号文件
2. **实时监控**：监控指定目录中的新音频文件并自动处理
3. **噪声分析**：计算各种噪声指标，包括：
   - 等效声级 (Leq, LAeq, LCeq)
   - 峰值声压级
   - 1/3倍频程频谱
   - 峭度指标
4. **可视化展示**：使用Streamlit创建交互式前端界面
5. **WebSocket通信**：实时将处理结果推送到前端

## 安装依赖

```bash
pip install -r requirements.txt
```

## 项目结构

```
noise_info_toolkit/
├── app/
│   ├── core/
│   │   ├── audio_processor.py     # 音频处理核心模块
│   │   ├── background_tasks.py    # 后台任务管理
│   │   ├── connection_manager.py  # WebSocket连接管理
│   │   ├── file_monitor.py        # 文件监控模块
│   │   └── tdms_converter.py      # TDMS到WAV转换模块
│   ├── utils/
│   │   └── task_utils.py          # 任务工具函数
│   └── main.py                    # FastAPI主应用
├── audio_files/                   # 音频文件目录
├── streamlit_app.py               # Streamlit前端应用
└── requirements.txt               # 项目依赖
```

## 使用方法

### 1. 启动后端服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. 启动前端界面

```bash
streamlit run streamlit_app.py
```

### 3. 使用流程

1. 将TDMS格式的噪声信号文件放入`audio_files`目录
2. 系统会自动检测新文件并进行处理
3. 打开Streamlit前端界面查看实时分析结果
4. 可以在界面中修改监控目录和连接设置

## TDMS文件处理

系统支持自动将TDMS格式文件转换为WAV格式并进行噪声分析。转换过程包括：
- 读取TDMS文件中的音频数据
- 提取采样率信息
- 转换为标准WAV格式
- 进行噪声指标计算

## 实时监控

系统使用文件系统监控来检测新文件：
- 支持WAV和TDMS格式文件
- 自动处理新添加的文件
- 通过WebSocket实时推送结果到前端

## 前端功能

Streamlit前端提供以下功能：
- 实时监控面板显示当前噪声指标
- 1/3倍频程频谱图
- 声级时间历程图
- 历史数据分析
- 系统状态监控
- 可配置的监控目录和连接设置