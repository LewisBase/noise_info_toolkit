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
- **会话管理**：测量会话创建、TimeHistory 每秒数据查看、累计剂量跟踪
- **系统状态监控**：后端健康检查、目录信息、连接诊断

### 5. 会话管理 (Session)
平台采用**会话机制**来组织和管理噪声测量数据，每个会话代表一次完整的测量过程：
- **自动创建会话**：处理音频文件时自动创建新会话
- **实时剂量累计**：会话期间实时计算并累计噪声剂量
- **TimeHistory 存储**：每秒保存一条测量记录（LAeq、LZpeak、剂量增量等）
- **会话摘要**：结束时自动生成摘要（总时长、平均声级、TWA、总剂量等）

### 6. 事件检测 (Event Detection)
根据白皮书要求实现冲击噪声事件检测：
- **触发条件**：
  - 声级触发：LZeq_125 ≥ 90-95 dB（125ms窗口）
  - 峰值触发：LCpeak ≥ 130 dB
  - 斜率触发：ΔLZeq ≥ 10 dB/50ms
- **去抖动机制**：避免重复触发，默认间隔0.5秒
- **环形缓冲**：12秒缓冲（2秒pre-trigger + 8秒post-trigger）
- **事件音频**：自动保存事件前后的音频片段（WAV格式）
- **EventLog**：记录事件的起止时间、峰值、SEL、峰度等指标

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

---

## 会话机制使用指南

### 什么是会话 (Session)

**会话**是平台的核心概念，代表一次完整的噪声暴露测量过程。每个会话具有唯一的 ID，用于关联该次测量的所有数据：
- **TimeHistory**：每秒的声级和剂量数据
- **ProcessingResult**：整体噪声指标（Leq、频谱等）
- **SessionSummary**：会话级别的汇总统计

### Streamlit 前端中的会话机制

#### 1. 工作原理

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   用户操作      │────▶│   后端处理      │────▶│   数据存储      │
│                 │     │                 │     │                 │
│ • 新建会话      │     │ • 创建Session   │     │ • Session表     │
│ • 放入音频文件  │     │ • 每秒处理      │     │ • TimeHistory表 │
│ • 停止会话      │     │ • 计算剂量      │     │ • Processing表  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                                               │
         │              ┌─────────────────┐             │
         └─────────────▶│  Streamlit展示  │◀────────────┘
                        │                 │
                        │ • 实时监控图表  │
                        │ • 会话管理列表  │
                        │ • 历史数据查询  │
                        └─────────────────┘
```

#### 2. 使用流程

**步骤 1：创建会话**
- 在 Streamlit 侧边栏点击 **"🟢 新建会话"**
- 系统会创建一个 RUNNING 状态的会话
- 侧边栏显示当前会话 ID（前 8 位）和已处理秒数

**步骤 2：处理音频文件**
- 将 TDMS 或 WAV 文件放入监控目录
- 后台自动检测并处理文件
- **实时监控**标签页显示每秒的 TimeHistory 数据：
  - LAeq 每秒变化曲线
  - LZpeak 每秒变化曲线
  - NIOSH/OSHA 剂量累计曲线

**步骤 3：查看会话数据**
- **实时监控**页：显示当前/最新会话的每秒数据
- **会话管理**标签页：
  - 查看所有历史会话列表
  - 点击任意会话查看详细 TimeHistory
  - 声级时间历程图表
  - 剂量累计曲线

**步骤 4：停止会话**
- 点击 **"🔴 停止会话"** 结束当前测量
- 系统自动保存 SessionSummary
- 会话状态变为 STOPPED

#### 3. 注意事项

⚠️ **重要提示**

| 注意事项 | 说明 |
|---------|------|
| **会话自动创建** | 如果不手动创建会话，处理音频文件时也会**自动创建**新会话 |
| **单活动会话** | 同一时刻只能有一个 RUNNING 状态的会话，新建会话会自动停止旧会话 |
| **数据分离** | 每个会话的数据独立存储，停止后无法继续添加数据到该会话 |
| **实时监控显示逻辑** | 优先显示 RUNNING 会话；如无，则显示最新的 STOPPED 会话 |
| **刷新数据** | TimeHistory 图表不会自动刷新，需点击"刷新TimeHistory数据"按钮或切换标签页 |
| **会话时长** | 长时间测量（>8小时）会产生大量 TimeHistory 记录，查询可能较慢 |

#### 4. 界面功能详解

**侧边栏会话管理**
```
测量会话管理
├── 🟢 会话运行中: abc12345...  ← 当前活动会话ID
│   └── 已处理: 3600 秒         ← 实时更新的处理秒数
│   └── NIOSH剂量: 45.2300%     ← 实时累计剂量
├── [🟢 新建会话] [🔴 停止会话]  ← 控制按钮
```

**实时监控页 - TimeHistory 区域**
```
⏱️ TimeHistory 每秒数据 (Session)
├── 显示当前活动会话: abc12345... (状态: running)
├── 总记录数 | 平均 LAeq | 最大 LZpeak | NIOSH总剂量
├── LAeq 每秒变化曲线图
├── LZpeak 每秒变化曲线图
└── 剂量累计曲线 (NIOSH vs OSHA)
```

**会话管理标签页**
```
📊 会话管理 (Sessions)
├── 当前活动会话              ← 显示 RUNNING 会话详情
│   ├── 会话ID、状态、标准
│   ├── TimeHistory 图表
│   └── 刷新按钮
├── 历史会话列表              ← 所有会话的摘要表格
│   ├── 会话ID | 标准 | 开始时间 | 总时长 | TWA | 总剂量
│   └── 点击查看任意会话详情
└── 查看会话详情              ← 选择会话后的详细数据
    ├── 统计指标卡片
    ├── 声级时间历程图
    └── 完整数据表格
```

#### 5. API 端点

后端提供以下会话管理 API：

```
POST /session/create          # 创建新会话
POST /session/stop            # 停止当前会话
GET  /session/current         # 获取当前会话状态
GET  /session/list            # 列出所有会话
GET  /session/{id}            # 获取会话摘要
GET  /session/{id}/time_history         # 获取每秒数据
GET  /session/{id}/time_history/summary # 获取统计汇总
```

完整的 API 文档可在启动后端后访问：http://localhost:8000/docs

## 项目结构

```
noise_info_toolkit/
├── app/                          # 主应用包
│   ├── core/                     # 核心处理模块
│   │   ├── audio_processor.py    # 音频处理核心 (AudioProcessor)
│   │   ├── background_tasks.py   # 后台任务管理
│   │   ├── connection_manager.py # WebSocket 连接管理
│   │   ├── dose_calculator.py    # 剂量计算模块 (Phase 1)
│   │   ├── event_detector.py     # 事件检测器 (Phase 3)
│   │   ├── event_processor.py    # 事件处理器 (Phase 3)
│   │   ├── file_monitor.py       # 文件监控模块
│   │   ├── ring_buffer.py        # 环形缓冲区 (Phase 3)
│   │   ├── session_manager.py    # 会话管理器 (Phase 2)
│   │   ├── tdms_converter.py     # TDMS 转换模块
│   │   └── time_history_processor.py  # 时间历程处理器 (Phase 2)
│   ├── database/                 # 数据库模块
│   │   ├── database.py           # 数据库操作
│   │   └── models.py             # SQLAlchemy 模型
│   ├── models/                   # Pydantic 模型
│   │   ├── request_schemas.py    # 请求参数
│   │   └── result_schemas.py     # 响应结果
│   └── utils/                    # 工具函数
├── audio_files/                  # 默认监控目录
├── audio_events/                 # 事件音频存储目录 (Phase 3)
├── Database/                     # SQLite 数据库存储
├── log/                          # 日志文件
├── test/                         # 测试脚本
│   ├── test_dose_calculator.py   # 剂量计算测试
│   ├── test_phase2.py            # Phase 2 测试
│   └── test_phase3.py            # Phase 3 测试
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
| event_id | 事件唯一标识 (如 EVT-ABC123XYZ) |
| session_id | 所属会话标识 |
| start_time_utc | 事件开始时间 (UTC) |
| end_time_utc | 事件结束时间 (UTC) |
| duration_s | 事件持续时间 (秒) |
| trigger_type | 触发类型 (leq/peak/slope) |
| LZpeak_dB | Z计权峰值声压级 (dB) |
| LCpeak_dB | C计权峰值声压级 (dB) |
| LAeq_event_dB | 事件期间的LAeq (dB) |
| SEL_LAE_dB | 声暴露级 (Sound Exposure Level) |
| beta_excess_event_Z | Z计权超额峰度 β |
| audio_file_path | 事件音频文件路径 (pre 2s + post 8s) |
| pretrigger_s | 触发前录制时长 (默认 2s) |
| posttrigger_s | 触发后录制时长 (默认 8s) |
| notes | 备注 |

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

## 开发计划与进度

| 阶段 | 目标 | 状态 |
|------|------|------|
| **Phase 1** | 噪声剂量计算：Dose%、TWA、LEX,8h 多标准支持 (NIOSH/OSHA/EU_ISO) | ✅ 已完成 |
| **Phase 2** | 时间历程数据：TimeHistory 每秒存储、Session 会话管理、实时剂量累计 | ✅ 已完成 |
| **Phase 3** | 事件检测：冲击噪声检测、环形缓冲、EventLog 事件记录 | ✅ 已完成 |
| **Phase 4** | 认证与量产：IEC 61252/61672 型式试验、云端平台、量产工艺 | 📋 规划中 |

### Phase 1 详情 (已完成)
- [x] 剂量计算模块 (`dose_calculator.py`)
- [x] 4 种标准支持 (NIOSH/OSHA_PEL/OSHA_HCA/EU_ISO)
- [x] Dose%、TWA、LEX,8h 计算
- [x] 前端剂量显示
- [x] 38 个单元测试

### Phase 2 详情 (已完成)
- [x] TimeHistory 处理器 (`time_history_processor.py`)
- [x] Session 会话管理器 (`session_manager.py`)
- [x] 每秒数据存储 (LAeq/LCeq/LZpeak/剂量增量)
- [x] 会话级剂量累计
- [x] 会话管理 API (创建/停止/查询)
- [x] Streamlit 前端集成
- [x] 11 个单元测试

### Phase 3 详情 (已完成)
- [x] 滑动窗口计算 LZeq_125 (`SlidingWindowCalculator`)
- [x] 事件检测器 (`EventDetector`) - 支持声级/峰值/斜率触发
- [x] 去抖动机制
- [x] 环形缓冲区 (`RingBuffer`) - 12秒缓冲
- [x] 事件音频保存 (pre 2s + post 8s)
- [x] 事件处理器 (`EventProcessor`)
- [x] EventLog 数据库操作
- [x] 事件检测 API (`/session/{id}/events`)
- [x] 22 个单元测试

### Phase 4 详情 (规划中)
- [ ] IEC 61252/61672 型式试验
- [ ] 云端平台对接
- [ ] 多设备数据同步
- [ ] 生产级部署优化

## 会话机制与事件检测使用指南

### 会话管理 (Session)

#### 什么是会话
**会话**是平台的核心概念，代表一次完整的噪声暴露测量过程。每个会话具有唯一的 ID，用于关联该次测量的所有数据：
- **TimeHistory**：每秒的声级和剂量数据
- **ProcessingResult**：整体噪声指标（Leq、频谱等）
- **EventLog**：冲击噪声事件记录
- **SessionSummary**：会话级别的汇总统计

#### 使用流程

**步骤 1：创建会话**
- 在 Streamlit 侧边栏点击 **"🟢 新建会话"**
- 系统会创建一个 RUNNING 状态的会话
- 侧边栏显示当前会话 ID（前 8 位）和已处理秒数

**步骤 2：处理音频文件**
- 将 TDMS 或 WAV 文件放入监控目录
- 后台自动检测并处理文件
- **实时监控**标签页显示每秒的 TimeHistory 数据

**步骤 3：查看会话数据**
- **实时监控**页：显示当前/最新会话的每秒数据
- **会话管理**标签页：查看所有历史会话和详细数据

**步骤 4：停止会话**
- 点击 **"🔴 停止会话"** 结束当前测量
- 系统自动保存 SessionSummary

#### 注意事项
- 同一时刻只能有一个 RUNNING 状态的会话
- 如不手动创建会话，处理文件时会**自动创建**新会话
- 会话停止后无法继续添加数据

### 事件检测 (Event Detection)

#### 工作原理
平台自动检测音频中的冲击噪声事件：

**触发条件**（满足任一即可）：
| 类型 | 阈值 | 说明 |
|------|------|------|
| 声级触发 | LZeq_125 ≥ 90 dB | 125ms窗口Z计权等效声级 |
| 峰值触发 | LCpeak ≥ 130 dB | C计权峰值声压级 |
| 斜率触发 | ΔLZeq ≥ 10 dB/50ms | 声级变化率 |

**去抖动机制**：同一事件多次触发间隔 ≥ 0.5 秒

**环形缓冲**：
- 总缓冲时长：12 秒
- 触发前保留：2 秒 (pre-trigger)
- 触发后录制：8 秒 (post-trigger)

#### 事件音频文件
检测到的事件音频自动保存到 `./audio_events/` 目录：
- 文件名格式：`{event_id}_{timestamp}.wav`
- 包含触发前 2 秒和触发后 8 秒的音频
- 可直接回放分析

#### 查看事件
- 通过 API 获取事件列表：`GET /session/{id}/events`
- 通过 API 获取事件统计：`GET /session/{id}/events/summary`
- 数据库 `EventLog` 表存储所有事件详情

#### 配置参数
如需修改事件检测阈值，可编辑 `app/core/background_tasks.py`：
```python
self.event_processor = EventProcessor(
    sample_rate=sr,
    leq_threshold=90.0,      # 声级触发阈值 (dB)
    peak_threshold=130.0,    # 峰值触发阈值 (dB)
    debounce_s=0.5,          # 去抖动时间 (秒)
    output_dir="./audio_events",
    enable_audio_save=True   # 是否保存事件音频
)
```

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

---

**核心理念**：把个人噪声剂量计变成"可计算、可扩展、可验证"的数据平台，而不仅仅是一块仪表。
