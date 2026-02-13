# 个人噪声剂量计数据分析平台 (Noise Info Toolkit)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B.svg)](https://streamlit.io/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 项目简介

本项目是基于《个人噪声剂量计总体技术白皮书》构建的**噪声数据分析平台**，支持对职业性噪声暴露数据的标准化处理、实时分析和可视化展示。

平台采用 **"个人噪声剂量计 + 标准化数据结构 + ETL 管线"** 的技术架构，旨在：
- 提供统一的 TimeHistory / EventLog / Metadata / Profiles 数据模型与 ETL 规范
- 支持峰度 β (Kurtosis) 等复杂噪声指标的计算与分析
- 为职业性噪声性听力损失 (NIHL) 风险评估与标准修订提供数据基础设施

## 核心功能

### 1. 数据处理能力
- **TDMS 文件支持**：自动检测和处理 TDMS 格式的噪声信号文件
- **实时文件监控**：监控指定目录中的新音频文件并自动处理
- **多通道分析**：支持 CH1、CH2 等多通道数据同时处理

### 2. 噪声指标计算
- **等效声级**：LAeq、LCeq、LZeq（支持 NIOSH、OSHA、EU/ISO 等多种剂量档）
- **峰值声压级**：LZpeak、LCpeak（真峰值检测）
- **时间加权声级**：LAFmax、LASmax（Fast/Slow 加权）
- **频谱分析**：1/3倍频程频谱计算
- **峰度指标**：超额峰度 β 计算（支持复杂噪声风险模型）
- **剂量与 TWA**：基于不同标准的剂量百分比和时间加权平均值

### 3. 数据标准化
遵循白皮书定义的 **3+1 数据表结构**：
- **TimeHistory**：时间历程表（1s 粒度，含 LAeq、LCeq、LZpeak、剂量增量等）
- **EventLog**：事件表（冲击噪声事件，含 β、LAE、音频路径等）
- **Metadata**：元数据表（仪器信息、校准记录、采样参数等）
- **Profiles**：剂量档参数表（NIOSH、OSHA_PEL、OSHA_HCA、EU_ISO 等）

### 4. 可视化与交互
- **实时监控**：当前噪声指标、1/3倍频程频谱、时间历程图
- **历史数据查询**：按时间范围、文件、通道筛选
- **系统状态监控**：后端健康检查、目录信息、连接诊断

## 技术架构

### 后端 (FastAPI)
```
TDMS/WAV 文件 → FileMonitor → AudioProcessor → Database
                                    ↓
                              WebSocket/API ← Streamlit 前端
```

- **Web 框架**：FastAPI + Uvicorn (ASGI)
- **数据库**：SQLite + SQLAlchemy ORM
- **音频处理**：librosa、soundfile、acoustics
- **科学计算**：numpy、pandas、scipy
- **文件监控**：watchdog
- **TDMS 处理**：nptdms

### 前端 (Streamlit)
- **界面框架**：Streamlit
- **数据可视化**：plotly
- **实时通信**：REST API + WebSocket

### 数据流
1. `AudioFileMonitor` 监控目录检测到新文件
2. `TDMSConverter` 将 TDMS 转换为 WAV 格式
3. `AudioProcessor` 计算各类噪声指标
4. `DatabaseManager` 按 3+1 表结构保存到 SQLite
5. `Streamlit` 前端通过 API 获取数据展示

## 快速开始

### 环境要求
- Python 3.11+
- Windows/Linux/macOS

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动服务

**方式 1：分别启动**

```bash
# 启动后端 (端口 8000)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 启动前端 (端口 8501)
streamlit run streamlit_app.py
```

**方式 2：使用启动脚本**

```bash
python start_server.py
```

### 访问应用

- **前端界面**：http://localhost:8501
- **后端 API 文档**：http://localhost:8000/docs
- **后端健康检查**：http://localhost:8000/health

## 项目结构

```
noise_info_toolkit/
├── app/                          # 主应用包
│   ├── core/                     # 核心处理模块
│   │   ├── audio_processor.py    # 音频处理核心 (AudioProcessor)
│   │   ├── background_tasks.py   # 后台任务管理
│   │   ├── connection_manager.py # WebSocket 连接管理
│   │   ├── file_monitor.py       # 文件监控模块
│   │   └── tdms_converter.py     # TDMS 转换模块
│   ├── database/                 # 数据库模块
│   │   ├── database.py           # 数据库操作
│   │   └── models.py             # SQLAlchemy 模型
│   ├── models/                   # Pydantic 模型
│   │   ├── request_schemas.py    # 请求参数
│   │   └── result_schemas.py     # 响应结果
│   └── utils/                    # 工具函数
├── audio_files/                  # 默认监控目录
├── Database/                     # SQLite 数据库存储
├── log/                          # 日志文件
├── test/                         # 测试脚本
├── main.py                       # FastAPI 主入口
├── streamlit_app.py              # Streamlit 前端
├── config.py                     # 应用配置
└── requirements.txt              # Python 依赖
```

## 数据规范

### TimeHistory 表结构（每秒一行）
| 字段 | 说明 |
|------|------|
| session_id | 会话标识 |
| timestamp_utc | UTC 时间戳 |
| LAeq_dB | A计权等效声级 |
| LCeq_dB | C计权等效声级 |
| LZeq_dB | Z计权等效声级 |
| LAFmax_dB | Fast加权最大声级 |
| LZpeak_dB | Z计权峰值声压级 |
| LCpeak_dB | C计权峰值声压级 |
| dose_frac | 剂量增量分数 |
| wearing_state | 佩戴状态 |

### EventLog 表结构（每事件一行）
| 字段 | 说明 |
|------|------|
| event_id | 事件标识 |
| start_time_utc | 开始时间 |
| duration_s | 持续时间 |
| LZpeak_dB | 峰值声压级 |
| LAeq_event_dB | 事件 A 计权等效声级 |
| beta_excess_event_Z | Z 计权超额峰度 |
| audio_file_path | 关联音频文件路径 |

### Profiles 剂量档定义
- **NIOSH**: 85 dBA / 3 dB 交换率 / 8h 参考
- **OSHA_PEL**: 90 dBA / 5 dB 交换率
- **OSHA_HCA**: 85 dBA / 5 dB 交换率
- **EU_ISO**: 符合 ISO 9612 的欧洲标准档

## 校准与质控

- **声校准**：支持 94/114 dB @ 1kHz 标准声源校准
- **过载检测**：overload_flag 标记，β 与剂量分析中自动排除过载帧
- **欠载检测**：underrange_flag 标记，评估对 LEX,8h 的贡献
- **时钟同步**：支持 NTP/GPS 对时，保证多设备时间对齐

## 典型应用场景

1. **钢铁、矿山、机械加工**：个人噪声暴露连续监测
2. **冲压、爆破、武器射击**：高峰度/冲击噪声环境分析
3. **大规模队列研究**：上千工人、多工种、多班次的噪声暴露数据库构建
4. **Equal Energy + Equal Kurtosis 假说验证**：为 ISO 1999 标准修订提供证据

## 开发计划

| 阶段 | 目标 |
|------|------|
| **Phase 1** | 研究级原型机：完整硬件平台与基础固件，ETL 数据链打通 |
| **Phase 2** | 测量级优化：频响补偿、β 固件化、预一致性测试 |
| **Phase 3** | 认证与量产：IEC 61252/61672 型式试验、云端平台、量产工艺 |

## 参考标准

- [IEC 61252](https://webstore.iec.ch/publication/6138) - Personal sound exposure meters
- [IEC 61672-1/-2](https://webstore.iec.ch/searchform&q=61672) - Sound level meters
- [ISO 9612](https://www.iso.org/standard/46346.html) - 职业噪声暴露测量与评价
- ANSI S1.4 / S1.25 - 声级计标准
- [NIOSH REL](https://www.cdc.gov/niosh/docs/1998-126/default.html) - 85 dBA / 3 dB / 8h
- [OSHA PEL/HCA](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.95) - 职业噪声暴露限值

## 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 联系方式

- **项目维护者**：刘恒江 (Liu Hengjiang)
- **单位**：浙江省疾病预防控制中心职业卫生所
- **邮箱**：[待补充]

## 致谢

本项目基于《个人噪声剂量计总体技术白皮书 v1.0》开发，感谢白皮书编写团队的技术指导。

---

**核心理念**：把个人噪声剂量计变成"可计算、可扩展、可验证"的数据平台，而不仅仅是一块仪表。
