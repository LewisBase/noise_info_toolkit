# 噪声信息工具箱：代码质量、潜在缺陷与 Windows 部署适配分析

- **分析日期**：2026-11-15
- **分析对象**：`noise_info_toolkit` 当前工作区代码（不含 `venv`、`.git`）
- **分析方式**：全量源码审阅 + 依赖元数据核对 + 关键路径最小复现 + 静态检查
- **说明**：本次分析在 Linux 工作区完成；Windows 专有行为（Tk、SMB、服务账户、Defender、注册表等）属于静态/配置层面的判断，需在目标 Windows 机器上按本文验收清单复核。运行时复现使用了 `numpy`、`acoustics`、FastAPI、SQLAlchemy 等真实库，并对 `librosa`/日志等做了最小桩替换，复现结论已标注。

> **后续落地**：基于 C++ 项目对照的分阶段改造方案见 [`field_deployment_optimization_plan.md`](./field_deployment_optimization_plan.md)。

---

## 0. 结论摘要

**总体判断：项目是一个功能设想完整、领域模型较清晰的科研/工程原型，但当前版本不适合直接部署到生产或正式测量环境。** 主要问题不是“某个小 bug”，而是**依赖不可复现、关键数据链路存在静默错误、长录音处理会耗尽内存、事件检测实际未接通、以及缺少校准与运维基础设施**。

如果目标是在全新 Windows 机器上“先跑起来并产出可信数据”，至少要先解决下面 9 个 P0 问题：

| 编号 | P0 阻断项 | 后果 |
|---|---|---|
| P0-1 | `requirements.txt` 缺少 `loguru`、`watchdog`，且完全未锁版本 | 按 README 安装后后端在 import 阶段直接失败 |
| P0-2 | 未锁 `numpy`/`scipy`：最新 SciPy 1.18 已移除 `acoustics` 依赖的 `sph_harm`，最新 NumPy 2 下 `third_octaves` 也报错；`librosa 1.0.x` 又要求 `numpy>=2.1` | “装得上、跑不了”：`import acoustics` 可能直接失败，或 1/3 倍频程计算运行时抛 `TypeError` |
| P0-3 | 默认监控目录 `./audio_files` 不在仓库中，启动时也不创建 | 全新克隆后 `uvicorn main:app` 因 `FileNotFoundError` 启动失败 |
| P0-4 | `TimeHistoryProcessor` 对 `time_averaged_sound_level()` 返回的 ndarray 调用 `round(..., 2)` | **每秒 9 个 1/3 倍频程 SPL 全部为 `None`**，频谱/热力图永远空白，且只记 warning 不报错 |
| P0-5 | `/latest_metrics` 无结果时返回 `None`；且 `file_dir` 过滤条件与入库字段不一致 | 无数据时 500；使用绝对监控目录后永远查不到最新结果 |
| P0-6 | `/all_metrics` 把 ISO 字符串直接与 SQLite `DateTime` 比较 | 当天记录永远查不到；叠加本地时间/UTC 混用，时间筛选整体错位 |
| P0-7 | 静音/恒定信号会产生 `-inf`/`NaN`，最终导致 API 500 | 一个静音文件就可能让会话/时间历程接口返回 500；`NaN` 入库还会变成 NULL |
| P0-8 | 没有校准/灵敏度/ADC 量程处理，TDMS 被归一化到 `[-1,1]` 后当作 Pa | 所有 dB 值只是“相对满量程”的假声压级，剂量、TWA、LEX、QC 标志均不可用于合规测量 |
| P0-9 | 整段音频 `Signal.third_octaves()` 会生成 34×N 的 float64 矩阵（详细分析见 P1-1） | 10 分钟 48 kHz 文件约需 7.8 GB，1 小时约 47 GB；长录音必然 OOM，且当前每条文件都会走这条路 |

另外有 3 个“部署即踩”的工程问题：

- **Windows 服务/无桌面环境下 `streamlit_app.py` 在 import 时执行 `tk.Tk()`**，可能直接失败；即使成功，文件夹对话框也弹在服务器上，远程浏览器用户无法使用。
- **文件处理运行在 watchdog 的 observer 线程里**，`Observer.stop()/join()` 会等待当前文件处理完；切换目录或停止服务可能挂起数十分钟到数小时（已用 watchdog 实验复现 join 等待 handler）。
- **事件检测（Phase 3）实际上没有接通**：`EventProcessor.process_audio_chunk()` 在主流程中从未被调用，且正常结束的事件不会加入 `self.events`，因此 `/session/{id}/events` 永远为空。

**最短可部署路径**：先修 P0 + 锁定 Python 3.11/`numpy<2` 依赖组合 + 创建运行目录并改为绝对路径 + 修正 SPL/查询/非有限值 + 明确“未校准则只输出相对 dBFS” + 对长文件改为分块/禁用整段频谱；然后再做服务化和验收测试。不要在当前代码上直接接真实测量任务。

---

## 1. 项目结构与数据流

### 1.1 规模

- Python 源码约 **8,343 行**（不含 `venv`）。
- 最大文件：`app/database/database.py` 959 行、`streamlit_app.py` 951 行、`app/core/time_history_processor.py` 595 行、`app/core/summary_processor.py` 561 行、`app/core/background_tasks.py` 465 行。
- 测试 9 个文件、约 1,500 行，但缺少可重复的集成测试与 CI。

### 1.2 实际数据流

```
TDMS 文件
  └─ watchdog on_created（只监听 .tdms）
       └─ AudioProcessingTaskManager._on_audio_file_detected（在 observer 线程内）
            ├─ TDMSConverter.convert_tdms_to_wav → temp_*.wav
            ├─ TimeHistoryProcessor.process_signal_per_second
            │    ├─ SessionManager.process_second
            │    ├─ DatabaseManager.save_time_history（每秒一次 commit）
            │    └─ SummaryProcessor.add_second_metrics（分钟汇聚仅写日志）
            ├─ EventProcessor（创建并 start，但从未喂数据）
            ├─ AudioProcessor.process_wav_file（整段音频再算一遍，内存/CPU 大头）
            └─ DatabaseManager.save_processing_result（每个 metric 一次 commit）
```

前端 Streamlit 通过 HTTP 轮询 `/latest_metrics`、`/all_metrics`、`/session/*`，**没有 WebSocket**；`ConnectionManager` 是未使用的死代码，README 中的 `/ws` 路由不存在。

### 1.3 与文档的偏差

README/AGENTS 中多处描述超前于实现：

- 声称支持 WAV 监控：实际 `AudioFileMonitor` 只监听 `.tdms`（`app/core/background_tasks.py:30`）。
- 声称支持 WebSocket：`main.py` 无 `@app.websocket`，`ConnectionManager` 无调用方。
- 声称支持 94/114 dB 声校准、NTP/GPS 对时：没有对应代码，`Metadata` 表虽有校准字段但从未写入。
- 声称 Phase 3 事件检测“已完成”：主流程未调用 `process_audio_chunk`，事件不会入库。
- 声称分钟级汇聚已保存：`_save_aggregated_metrics()` 只记录日志（`app/core/background_tasks.py:303-316`）。
- `.devcontainer/devcontainer.json` 启动的是不存在的 `noise_info_toolkit.py`，不是 `streamlit_app.py`。

这些偏差会直接误导部署人员，属于需要优先修正的“文档即配置”问题。

---

## 2. 代码质量评估

### 2.1 优点

- **领域拆分基本合理**：`core` / `database` / `models` / `utils` 分层清楚；`DoseCalculator`、`SecondMetrics`、`AggregatedMetrics` 等模型表达力较好。
- **剂量与峰度公式有文档、有单元测试**：`test_dose_calculator.py`、`test_kurtosis_aggregation.py` 对核心数学做了验证，这是项目中质量最高的部分。
- **部分类型注解和 dataclass 使用得当**：`SecondMetrics`、`SessionMetrics` 可读性较好。
- **日志使用 loguru，带轮转和保留策略**；比裸 `print` 进了一步。
- **README 内容较完整**（虽然部分超前），对理解设计意图有帮助。

### 2.2 主要质量问题

| 维度 | 现状 | 影响 |
|---|---|---|
| 单一事实来源 | 9 个频段 × 5 个矩统计量 = 45 个字段，在 `SecondMetrics`、`AggregatedMetrics`、`TimeHistory` 模型、`save_time_history()`、`get_time_history()`、`background_tasks.py` 中重复出现 | 改一个频段要改 5~6 处；复制粘贴错误会静默污染数据 |
| 死代码/重复实现 | `ConnectionManager`、`utils/tdms_converter.py`（与 `app/core/tdms_converter.py` 重复）、`task_utils`、`helpers`、`config.py`、`AudioProcessingTaskManager.processing_callback`、`executor`、`get_session_dose_summary`、`get_history_results`、`Metadata`/`Config` 表 | 维护者难以判断哪条路径是真实生效的；安全/行为修复容易改错副本 |
| 异常处理 | 大量 `except Exception` 只记日志后继续/返回空；`_calculate_third_octave_metrics` 捕获异常后把 9 个 SPL 全置 `None`；`main.py` 把错误包成 HTTP 200 + `code:500` | 真实故障被“看起来成功”掩盖；SPL 全空这种问题可以长期不被发现 |
| 时间语义 | `datetime.now()`（ProcessingResult、EventLog）与 `datetime.utcnow()`（TimeHistory、Session）混用；ISO 字符串无时区后缀 | 同一 UI 中“文件历史”和“TimeHistory”相差 8 小时（中国时区）；`all_metrics` 时间筛选错位 |
| 路径语义 | `./Database`、`./audio_files`、`./audio_events` 相对 CWD；`file_dir` 存父路径，查询用 `Path(watch).name` | Windows 服务 CWD 为 `System32` 时写错位置或权限失败；绝对监控目录下查询永远不匹配 |
| 单位语义 | TDMS 归一化到 `[-1,1]` 后直接当 Pa；没有灵敏度/量程/校准 | dB 值不可信；QC 阈值（140/30/40 dB）失去物理意义 |
| 依赖管理 | `requirements.txt` 16 行全部无版本；缺 `loguru`、`watchdog`；`librosa 1.0` 与 `acoustics` 冲突 | 无法复现构建；全新机器安装结果不可预测 |
| 测试 | 测试不隔离（写生产 DB）、`comprehensive_test.py` 参数个数错误、WebSocket 测试测不存在路由；无 API/文件监控/TDMS 转换测试 | 回归保护不足；上述 SPL、32 kHz、空数据等问题都逃过了测试 |
| 工程化 | 无 `pyproject.toml`、无 lint/type 配置、无 CI、无 Alembic 迁移、无锁文件 | 无法保证“新环境可复现”；数据库升级会失败 |
| 文档 | README/AGENTS 与实现不一致；`.devcontainer` 指向错误文件 | 新人和部署人员会被误导 |

### 2.3 静态检查结果

- `python -m py_compile`：全部文件语法通过（两个 docstring 有 `\m` 转义 `SyntaxWarning`，不影响运行）。
- `pyflakes`：约 60 处未使用 import/变量；未发现明显的未定义名字。说明“能 import 的模块基本完整”，但也说明死代码较多。
- 没有 `ruff`/`mypy`/`pytest.ini`/`pyproject.toml`，无法在 CI 中约束风格和类型。

### 2.4 测试质量

- **好的部分**：`test_dose_calculator.py`、`test_kurtosis_aggregation.py` 有明确断言，覆盖剂量公式和 S1–S4 合成。
- **问题**：
  - `test/test_phase2.py` 只断言 `LAeq > 0`，没有断言峰值、频段 SPL、静音、非有限值。
  - `test/test_phase3.py` 只测 `EventDetector`/`RingBuffer` 单元，不测 `EventProcessor` 与主流程的集成；因此“事件检测从未被调用”不会被发现。
  - `test/test_database.py` 直接使用 `DatabaseManager()`，写入当前工作目录的生产 `Database/noise_info.db`，无临时库/清理。
  - `test/comprehensive_test.py:86` 调用 `AudioProcessingTaskManager("./test_audio_files", db_manager)`，但构造函数只接收一个参数（`background_tasks.py:28`），该测试必然 `TypeError`。
  - `test/create_test_tdms.py:51` 写 `../audio_files/test_signal.tdms`；从项目根目录按 README 执行时会写到项目**上一级**，不是 `./audio_files`。
  - `test/test_websocket_route.py` 检查 `/ws`，但 `main.py` 没有该路由，测试必然失败；`test/websocket_test.py` 依赖未列入 requirements 的 `websocket-client`。
  - 没有 Windows CI；没有 API 端点测试；没有“静音/短文件/32 kHz/绝对路径/NAS 路径”测试。

---

## 3. 潜在 Bug 清单

> 严重级别：**P0** = 阻断部署或导致数据不可信/不可用；**P1** = 功能错误、可靠性/性能问题；**P2** = 可维护性/体验问题。

### 3.1 P0：部署与数据链路阻断

#### P0-1 全新安装无法启动：缺少 `loguru`、`watchdog`

- **位置**：`requirements.txt`；`app/utils/logger.py:11,61`；`app/core/file_monitor.py:8`；`main.py:11-14`。
- **现象**：`pip install -r requirements.txt` 成功，但 `uvicorn main:app` 在 import `app.core` 时先 import `app.utils.logger`，`import loguru` 立即 `ModuleNotFoundError`；即使补上 loguru，启动监控时 `watchdog` 也会缺失。
- **根因**：直接依赖未列入 requirements；项目也没有 `pyproject.toml`/锁文件。
- **修复**：补齐直接依赖并锁版本；加 `pip check` 到安装流程。
- **证据**：静态核对 requirements 全文，无 `loguru`、无 `watchdog`。

#### P0-2 依赖组合不可行：最新 SciPy/NumPy 与 `acoustics 0.2.6` 不兼容，`librosa 1.0` 又要求 `numpy>=2.1`

- **位置**：`requirements.txt` 的 `librosa`、`numpy`、`scipy`、`acoustics`；导入链在 `app/core/audio_processor.py:18`，运行点在 `app/core/audio_processor.py:60` 和 `app/core/time_history_processor.py:224` 的 `Signal.third_octaves()`。
- **现象（两类失败模式，取决于默认解析到的 SciPy 版本；并叠加 librosa 的 NumPy 下限冲突）**：
  1. **最新 SciPy 1.18.x**：`acoustics/__init__.py` 顶部 `import acoustics.directivity`，后者执行
     `from scipy.special import sph_harm`；SciPy 1.18 已移除 `sph_harm`（改为 `sph_harm_y`），因此
     `import acoustics` 直接 `ImportError: cannot import name 'sph_harm' from 'scipy.special'`。
     这意味着后端在 import `app.core` 时就会失败，不是“运行时算错”。
  2. **SciPy 1.16.x + NumPy 2.5.x**：`acoustics` 可以 import，但 `Signal.third_octaves()` 在
     `scipy.signal._filter_design.lp2bp_zpk` 内执行 `float(wo)`，`wo` 是长度 1 的 ndarray，NumPy 2 下抛
     `TypeError: only 0-dimensional arrays can be converted to Python scalars`。
  3. 与此同时，`pip install` 默认解析到 `librosa 1.0.1`（要求 `numpy>=2.1`）和 `numpy 2.5.x`；若强行把
     `numpy` 锁到 1.26，`librosa 1.0.1` 又无法安装，必须同时把 `librosa` 降到 0.11.x。
- **根因**：`acoustics` 最后发布于 2022 年，同时依赖已移除的 SciPy API 和 NumPy 1.x 的标量转换行为；`librosa` 1.0 又抬高了 NumPy 下限；requirements 完全未约束，pip 会把最新版全部拉进来。
- **修复（建议组合）**：Python 3.11 x64 + `numpy==1.26.4` + `scipy==1.13.1` + `librosa==0.11.0` + `numba==0.61.2` + `acoustics==0.2.6`；安装后执行 `pip check`，并跑一个 `import acoustics` + `Signal.third_octaves()` 烟测。
- **证据**：
  - `numpy 2.5.4 + scipy 1.16.3 + acoustics 0.2.6`：`third_octaves()` 抛上述 `TypeError`；
  - `numpy 2.5.4 + scipy 1.18.1 + acoustics 0.2.6`：`import acoustics` 即因 `sph_harm` 失败；
  - `numpy 1.26.4 + scipy 1.16.3`：同一调用返回形状 `(34, 48000)`；
  - 另：`pip install acoustics` 会自动拉入最新 `numpy 2.5.4/scipy 1.18.1/pandas 3.1.1/numba 0.65`，其中 `numba 0.65` 又要求 `numpy<2.5`，进一步证明“不锁版本不可用”。

#### P0-3 默认监控目录不存在，后端启动即失败

- **位置**：`main.py:35`、`main.py:44-47`；`app/core/file_monitor.py:49-50`。
- **现象**：仓库中没有 `audio_files/`（`git ls` 确认），`AudioFileMonitor.start_monitoring()` 在目录不存在时 `raise FileNotFoundError`，`lifespan` 启动失败，uvicorn 退出。
- **根因**：目录依赖用户预先创建，但 README 的“快速开始”没有这一步；Streamlit 端虽然会 `mkdir`，但通常后端先启动，且前后端 CWD 可能不同。
- **修复**：启动时 `Path(watch_dir).mkdir(parents=True, exist_ok=True)`；或在仓库放 `.gitkeep` 并文档说明；启动失败要给明确提示而不是直接退出。
- **证据**：`ls -d audio_files` 不存在；代码路径静态确认。

#### P0-4 每秒钟的 1/3 倍频程 SPL 全部为 `None`

- **位置**：`app/core/time_history_processor.py:242-248`。
- **代码**：
  ```python
  _, spl = time_averaged_sound_level(...)
  freq_spl_dict[name] = round(spl, 2)
  ```
  `acoustics` 的 `time_averaged_sound_level()` 返回的是 `(time_array, level_array)`，`spl` 是形如 `array([47.30])` 的 ndarray；`round(ndarray, 2)` 会抛
  `TypeError: type numpy.ndarray doesn't define __round__ method`。
- **现象**：异常被 `except` 捕获，只写 `logger.warning("Failed to calculate SPL for 63Hz: ...")`，然后 `freq_spl_dict[name] = None`。因此 **9 个频段 SPL 全部为 `None`**，`TimeHistory.freq_*_spl` 全为 NULL，前端频谱图/热力图永远空白。频段 S1–S4 矩统计量仍能算出来，所以“峰度”看起来正常，掩盖了 SPL 缺失。
- **修复**：`spl = float(np.atleast_1d(spl)[0])`，并检查 `np.isfinite`；为 `_calculate_third_octave_metrics` 增加单元测试（断言 `freq_63hz_spl is not None`）。
- **证据**：已用 48 kHz 噪声复现，9 个频段全部 `None`，warning 原文为 `type numpy.ndarray doesn't define __round__ method`。

#### P0-5 `/latest_metrics` 在无数据时 500；绝对监控目录下永远查不到数据

- **位置**：`main.py:114-151`（尤其 120-126、147）；`app/database/database.py:152-157`。
- **问题 A（无返回）**：函数只有在 `if latest_result:` 内 `return`；没有结果时函数自然结束返回 `None`，而 `response_model=MetricsResponse` 不是 Optional → FastAPI 响应校验失败 → **500**（已用最小 FastAPI 复现）。前端随后只看到“没有可用数据”，但日志是 500。
- **问题 B（过滤条件不一致）**：入库 `file_dir = str(Path(file_path).parent)`，查询用
  `ProcessingResult.file_dir == str(Path(current_watch_directory).name)`。
  - 默认 `./audio_files` 时二者都是 `audio_files`，能匹配；
  - 一旦用户在界面选择绝对目录（例如 `D:\NoiseData`），入库为 `D:\NoiseData`，而查询值是 `NoiseData`，永远不匹配；
  - Windows 路径大小写不敏感，但 SQL `==` 大小写敏感，`C:\Noise` 与 `c:\noise` 也会失配。
- **修复**：无结果返回 `404` 或 `code=200,data={}` 的明确空响应；统一存/查同一路径表示（建议存 `file_dir` 为规范化绝对路径，查询同值），或直接按 `file_name`/`session_id` 查询。
- **证据**：路径匹配用 `PureWindowsPath` 复现：`watch.name=NoiseData`，`file_dir=D:\NoiseData`，不相等。

#### P0-6 `/all_metrics` 时间筛选：当天记录永远查不到

- **位置**：`main.py:165-168`；`app/models/request_schemas.py:38`；`streamlit_app.py:185-187`、`656`。
- **问题**：前端发送 `2026-11-15T20:36:31` 这样的字符串，SQLAlchemy 把字符串直接与 SQLite `DATETIME` 列比较。SQLite 存的是 `2026-11-15 20:36:31.000000`（空格分隔），字符串比较时 `'T'`（0x54）> `' '`（0x20），所以 `'2026-11-15 09:00:00' >= '2026-11-15T10:00:00'` 为 **False**；当天所有记录都被排除，只有“日期更晚”的记录才会通过。
- **叠加问题**：前端 `start_time` 是本地时间，数据库部分字段是 UTC，二者又差 8 小时。
- **修复**：请求模型用 `datetime` 类型，SQLAlchemy 绑定 `datetime`；统一存 UTC/带时区，前端按本地时区转换；不要用字符串比较日期时间。
- **证据**：用 SQLAlchemy 2.0 + SQLite 复现：字符串查询返回 `[]`，`datetime` 查询返回正确行；SQLite 原生比较也验证了 `'T'` 与空格排序问题。

#### P0-7 静音/恒定信号会产生 `-inf`/`NaN`，最终导致 API 500

- **位置**：`app/core/time_history_processor.py:349-400`；`app/database/database.py:261-315`；`main.py:299-300`；`streamlit_app.py:350-364`。
- **现象**：全零或极安静信号：
  - `equivalent_sound_pressure_level()` 返回 `-inf`；
  - `peak_sound_pressure_level()` 返回 `-inf`；
  - `scipy.stats.kurtosis()` 对常量信号返回 `NaN`；
  - `round(NaN, 2)` 仍是 `NaN`，`round(-inf, 2)` 仍是 `-inf`。
  - SQLite 绑定 `NaN` 会存成 **NULL**（静默丢值），`-inf` 会存成 **REAL -Inf**；
  - FastAPI/Starlette 的 `JSONResponse` 使用 `allow_nan=False`，遇到 `NaN/Inf` 直接抛 `ValueError: Out of range float values are not JSON compliant` → **500**。
- **影响**：一个静音文件就可能让 `/session/current`、`/session/{id}/time_history`、`/latest_metrics` 返回 500；同时 `-inf` 进入图表/统计。
- **修复**：在计算层统一钳制/标记：低于可测下限时用 `None` 或规定的最小值（如 0 dB），并加 `np.isfinite` 检查；数据库入库前拒绝/转换非有限值；`convert_to_serializable()` 增加非有限值清洗。
- **证据**：已复现 `LAeq=-inf`、`LZpeak=-inf`、`kurtosis=nan`；`JSONResponse({'x': -inf})` 抛 `ValueError`；SQLite 绑定 `NaN` 读出为 `None`。

#### P0-8 没有校准/单位换算，dB 值不是声压级

- **位置**：`app/core/tdms_converter.py:61-77`；`app/core/audio_processor.py:57-100`；`app/core/time_history_processor.py:346-418`。
- **问题**：TDMS 数据被归一化到 `[-1,1]`（或在 int 时除以 dtype 最大值），然后 `acoustics` 把数值当作 **Pa** 计算 SPL。于是：
  - 满量程 1.0 对应约 94 dB SPL，0.1 对应约 74 dB SPL，完全是“相对满量程”的假值；
  - 麦克风灵敏度、前置放大器增益、ADC 输入量程、校准器偏移全部丢失；
  - `overload_flag`（>140 dB）、`underrange_flag`（<30 dB）、`wearing_state`（>40 dB）失去物理意义；
  - 剂量、TWA、LEX、NIOSH/OSHA 判定不可用于合规或科研结论。
- **修复**：从 TDMS 读取灵敏度/量程/单位（或单独的校准文件），把原始 counts/volts 转成 Pa；用 94 dB/1 kHz 校准器求偏移并写入 `Metadata`；没有校准数据时，界面明确显示“dBFS/未校准”，不要标成 dB SPL。
- **证据**：`test/create_test_tdms.py` 写入 `Units: "V"`、信号归一化到 `[-1,1]`；转换器对 float 只按最大值归一化，未使用 `Units`/灵敏度。

### 3.2 P1：功能错误、可靠性与性能

#### P1-1 整段音频频谱分析的内存爆炸

- **位置**：`app/core/audio_processor.py:60`；`acoustics.Signal.third_octaves()`。
- **量级**：`third_octaves()` 返回形状 `(34, N)` 的 float64 数组（48 kHz 下默认 34 个频带，已实测）。
  - 1 分钟：`34 × 2.88M × 8 ≈ 0.78 GB`
  - 10 分钟：`34 × 28.8M × 8 ≈ 7.8 GB`
  - 1 小时：`34 × 172.8M × 8 ≈ 47 GB`
  - 8 小时：约 376 GB
  另外 `librosa.load` 还要把整段音频读成 float32（8 小时约 5.5 GB），`TdmsFile.read` 可能再翻倍，临时 WAV 再占一份。10 分钟以上的文件在 16 GB Windows 机器上就有很高 OOM 风险。
- **修复**：不要对整段文件调用 `third_octaves()`；改为分块/按秒计算频段能量并聚合，或使用 FFT 频域方法；对超长文件限制/拆分；把 `AudioProcessor` 的整段分析从主流程移除或设为可选。
- **证据**：形状 `(34, 48000)` 实测；内存为按 float64 的估算。

#### P1-2 文件处理在 watchdog 线程内，停止/切换目录会阻塞

- **位置**：`app/core/background_tasks.py:121-135`；`app/core/file_monitor.py:56-59`。
- **问题**：`_on_audio_file_detected()` 在 watchdog 的 observer 线程中同步执行整个处理流程。`AudioFileMonitor.stop_monitoring()` 调用 `observer.stop()` + `observer.join()`；join 会等待当前 handler 返回。也就是说：
  - `/change_watch_directory` 会一直等到当前文件处理完；
  - 服务停止/重启可能超时；
  - observer 线程被长时间占用，期间新文件事件只能排队，超过 Windows 变更缓冲区会丢事件。
- **证据**：用 watchdog 实测，handler `sleep(2)` 时 `stop()+join()` 耗时 1.5 s，确认 join 等待 handler。
- **修复**：observer 只负责 `queue.put(path)`；由单独的 `ThreadPoolExecutor(max_workers=1)` 或 `asyncio.Queue` 消费；停止时先停止接收，再按超时等待当前任务，避免阻塞 HTTP/服务管理器。

#### P1-3 没有启动扫描、没有去重、没有文件稳定性检查

- **位置**：`app/core/file_monitor.py:18-27`；`app/core/background_tasks.py:121-135`。
- **问题**：
  - 服务停止期间放入的文件不会被处理（没有启动时扫描 `audio_files`）；
  - `on_created` 后只 `sleep(0.1)`，大文件/慢速复制时 TDMS 还没写完就开始读，导致解析失败；
  - 没有“文件大小/修改时间稳定 N 秒”的检查；
  - 只处理 `on_created`，不处理 `on_moved`；如果 DAQ 先写 `.tmp` 再重命名为 `.tdms`（常见原子写），文件永远不会被处理；
  - 没有按 `(path, size, mtime)` 去重，重启后可能重复处理/重复入库；
  - `recursive=False`，按日期/通道建子目录时不会监控。
- **修复**：启动扫描 + 文件稳定性轮询 + `on_moved`/`on_closed` + 处理状态表（唯一约束）+ 可选递归；对失败文件重试/隔离。

#### P1-4 扩展名大小写、WAV 支持与 README 不一致

- **位置**：`app/core/background_tasks.py:30`；`app/core/file_monitor.py:22-23`。
- **问题**：`file_extensions=[".tdms"]`，`endswith(ext)` 区分大小写；`.TDMS` 不会触发；README 声称支持 WAV，但监控不监听 `.wav`。
- **修复**：统一 `path.suffix.lower()`；按产品需求决定是否监听 `.wav`；文档与代码同步。

#### P1-5 TDMS 采样率回退与 `wf_increment` 缺失

- **位置**：`app/core/tdms_converter.py:19,52-58`；对比 `utils/tdms_converter.py:106-108`。
- **问题**：主转换器只识别 `SampleRate`/`sample_rate`，不识别 NI 常见的 `wf_increment`（采样间隔），缺失时静默用 **44100**。若实际是 51200/48000/25600，时间轴、频率轴、声级全部错误。独立转换器 `utils/tdms_converter.py` 反而识别 `wf_increment`，两份实现行为不一致。
- **修复**：主转换器读取 `wf_increment`、`wf_start_time`、`NI_Sample_Rate` 等属性；无法确定采样率时拒绝处理并报错，不要猜 44100。

#### P1-6 只取第一个 group/第一个 channel，多通道被丢弃

- **位置**：`app/core/tdms_converter.py:40-50`；`librosa.load(..., mono=True)` 默认。
- **问题**：多通道 TDMS 只转换第一个通道；WAV 多通道又被 librosa 混成单声道；前端“CH1/CH2”只是文件名前缀筛选，不是真正的通道选择。
- **修复**：按通道拆分/输出多文件，或读取所有通道并保留 channel 维度；文件名/元数据中记录通道；前端按真实通道查询。

#### P1-7 每秒一次数据库 commit，性能差且可能丢数据

- **位置**：`app/core/background_tasks.py:234-237`；`app/database/database.py:261-315`。
- **问题**：8 小时录音 = 28,800 次 `commit`；每次 fsync 在 Windows + Defender 下可能几十毫秒，累计数分钟到数十分钟。`save_time_history_batch()` 已实现但从未使用。`_save_time_history_record` 捕获异常只记日志，数据库锁/磁盘满时直接丢秒数据。
- **修复**：批量插入（如每 60 秒/500 行）、WAL、`busy_timeout`、失败重试/落盘队列；`save_time_history_batch` 接入主流程。

#### P1-8 SQLite 并发/锁/WAL/迁移缺失

- **位置**：`app/database/database.py:24-36`。
- **问题**：`check_same_thread=False`，但未设置 `timeout`、WAL、`busy_timeout`；主进程 + `AudioProcessingTaskManager` 各自创建 `DatabaseManager`（两个 engine/连接池），HTTP 读与后台写并发时容易出现 `database is locked`；`Base.metadata.create_all()` 不会给已有表加列，旧数据库升级会 `no such column`。
- **修复**：单例 engine；SQLite `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout=30000`；写操作串行化；引入 Alembic/版本化迁移；升级前备份。

#### P1-9 时间语义混乱（本地时间 vs UTC）

- **位置**：`app/database/database.py:156`（`datetime.now()`）；`app/core/time_history_processor.py:290`（`datetime.utcnow()`）；`app/core/session_manager.py:150,190`（`utcnow`）；`app/core/event_processor.py:127,152`（`now`，字段却叫 `_utc`）。
- **问题**：同一数据库里两套时间基准；前端 `pd.to_datetime` 把无时区 ISO 当本地时间显示；上海时区下 TimeHistory 曲线整体早 8 小时；会话开始/结束时间也不对。
- **修复**：统一 `datetime.now(timezone.utc)`（带 tzinfo），数据库存 UTC；API 返回带 `Z`/偏移；前端 `utc=True` 后 `tz_convert("Asia/Shanghai")`；旧数据迁移时明确基准。

#### P1-10 会话摘要只在优雅停止时保存

- **位置**：`app/core/background_tasks.py:60-72`、`432-465`；`main.py:312-324`。
- **问题**：自动会话的 `SessionSummary` 只在 `stop_monitoring()` 或手动 stop 时写入；服务崩溃/断电/被服务管理器强杀时，`TimeHistory` 有数据但 `SessionSummary` 没有，`/session/list` 为空，重启后 `/session/current` 404，历史会话在 UI 中“消失”。`session_registry` 还保存所有 `SessionManager` 及其 `time_history` 列表，长期运行会内存增长。
- **修复**：定期（如每分钟）落盘摘要；或从 `TimeHistory` 动态聚合会话；`session_registry` 定期清理；每个文件/每天明确 session 边界。

#### P1-11 前端侧边栏会周期性重启监控

- **位置**：`streamlit_app.py:64-68`。
- **问题**：`audio_directory` 是本次渲染的输入值，`st.session_state.audio_directory` 仍是默认值；只要用户改过文本框，每次 rerun 都会满足 `!=`，于是每次自动刷新都 POST `/change_watch_directory`。后端每次都会 stop 旧监控 → 创建新 `AudioProcessingTaskManager`/`DatabaseManager` → 停止当前会话。结果是监控反复中断、会话碎片化、engine/线程泄漏。
- **修复**：用 `on_change` 回调只触发一次；成功后将值写回 `st.session_state.audio_directory`；不要在渲染路径里做副作用。

#### P1-12 自动刷新用 `sleep + st.rerun`，阻塞整个页面

- **位置**：`streamlit_app.py:327-329`。
- **问题**：Streamlit 每次 rerun 会执行所有 tab 的函数体；在实时 tab 里 `time.sleep(refresh_interval); st.rerun()` 会让整个脚本睡眠，用户操作被延迟；`st.rerun` 后再睡，形成“大部分时间在睡”的循环。所有 tab 还会同时发起大量 HTTP 请求。
- **修复**：用 `st.fragment(run_every=...)`（Streamlit ≥1.37）或 `streamlit-autorefresh`；只刷新需要的区域；加缓存/超时。

#### P1-13 事件检测未接通且正常事件不会入库

- **位置**：`app/core/background_tasks.py:216-225`；`app/core/event_processor.py:135-182,191-238`。
- **问题**：
  - 主流程只 `EventProcessor(...).start()`，从未调用 `process_audio_chunk()`；只有 `BatchEventProcessor.process_file()` 调用（`event_processor.py:343`）。
  - 即使接上，`_on_event_end()` 不向 `self.events` 追加；`_finish_event_recording()` 需要 `self.events[-1]`，于是正常结束的事件直接被丢弃。
  - `process_audio_chunk()` 逐样本 Python 循环，并在每个样本上重建 `np.array(deque)`，性能不可用。
  - `LCpeak` 直接复用 Z 计权样本（`sample_c=sample`），没有 C 计权；`beta_excess_z` 固定写 3.0。
  - 阈值默认按 Pa 设计，而输入是归一化值，触发条件没有物理意义。
- **修复**：要么明确标记 Phase 3 未完成并关闭 `enable_event_detection`；要么做向量化滑窗、正确追加事件、独立 C 计权、校准阈值，并加入集成测试。

#### P1-14 WebSocket 功能缺失

- **位置**：`app/core/connection_manager.py`；`main.py`；`README.md`。
- **问题**：`ConnectionManager` 没有任何调用方；`main.py` 无 `/ws`；前端完全靠 HTTP 轮询；`test_websocket_route.py` 必然失败。
- **修复**：要么实现 `/ws`（连接管理、心跳、广播），要么删除 `ConnectionManager` 和 WebSocket 测试/文档，明确“轮询”架构。

#### P1-15 数据库部分写入与清理孤儿

- **位置**：`app/database/database.py:146-219,442-461`。
- **问题**：`save_processing_result()` 先 commit 主记录，再在 metric 循环里逐个 commit；如果中途某个值 `float()` 失败，已提交的主记录和部分 metric 会留下（`rollback()` 只能回滚当前事务）。`cleanup_history()` 只删 `ProcessingResult`，没有删 `ProcessingMetric`/`SpectrumData`；外键未启用/无级联，产生孤儿数据。
- **修复**：整个结果在一个事务中提交；启用 `PRAGMA foreign_keys=ON` 并加级联，或显式删除子表；对 metric 值做类型/有限性校验。

#### P1-16 前端格式化与查询的细节错误

- **位置**：`streamlit_app.py` 多处。
- **问题**：
  - `metrics_data.get("leq", "N/A")` 若值为 `None`，`f"{None:.2f}"` 抛 `TypeError`（DB 可能因 NaN 存 NULL）。
  - `record.get("file_path","").split("/")[-1]` 在 Windows 反斜杠路径上会显示完整路径。
  - `end_date` 选择后完全未使用，日期范围筛选是假功能。
  - 平均 LAeq 用算术平均 `th_df['LAeq_dB'].mean()`，不是能量平均。
  - `st.plotly_chart(..., width="stretch")` 与 `use_container_width=True` 混用；`st.dataframe(..., width="stretch", use_container_width=True)` 同时传两个参数，版本升级时容易告警/报错。
  - `fetch_latest_metrics`/`fetch_history_metrics` 没有 timeout，后端卡住时页面无限等待。
  - `print(backend_url)`、`print(hist_df)` 污染服务端日志。
- **修复**：统一空值处理（`pd.isna`）、`Path(...).name`、用 `end_date` 过滤、能量平均、统一 Streamlit 宽度 API 并锁版本、加 timeout、删除 print。

### 3.3 P2：可维护性与体验

- `app/core/background_tasks.py:253` 用 `datetime.utcnow()`，Python 3.12 起弃用，建议改 `datetime.now(timezone.utc)`。
- `AudioProcessor` 的 `np.arange(8, 35, 3)` 依赖 acoustics 内部 34 个频带的默认布局；在 32 kHz/25.6 kHz 下 `len(octaves)` 只有 32/31，最后一个索引 32 越界 → `IndexError`（已复现）。应通过中心频率查找/遍历，而不是硬编码索引。
- `TimeHistory` 45 个频段矩字段、`save_time_history()` 超长参数列表，建议改为 JSON 列或子表。
- `SessionResponse` 的 `class Config`、`ProcessingResultSchema` 的可变默认值属于 Pydantic v1 风格/v2 兼容细节，建议统一 v2 写法。
- 日志级别默认 DEBUG 且逐秒打印，生产日志会很大；建议由环境变量控制。
- `logger.add(..., enqueue=True)` 在受限账户/沙箱中可能因 `multiprocessing` 信号量权限失败（本机沙箱实测 `PermissionError`）；Windows 服务账户下要验证，必要时提供 `enqueue=False` 回退。
- `app/utils/helpers.py` 是空文件；`app/utils/task_utils.py` 未被主流程使用。
- `.vscode/launch.json` 的 `--reload` 只适合开发，不应作为部署方式。
- `.devcontainer` 启动错误文件；`README` 与 `AGENTS.md` 的结构/功能描述过期。
- 没有 LICENSE、CHANGELOG、`.env.example`、部署脚本。

---

## 4. 数据正确性与标准符合性

这一节比“代码风格”更重要：**当前输出不能直接当作声压级使用**。

### 4.1 校准与单位链

需要明确并实现完整链路：

```
ADC counts / volts
  → 去除偏置
  → 除以麦克风灵敏度（mV/Pa）与前置放大增益
  → 得到 Pa
  → 应用校准器偏移（94 dB @ 1 kHz）
  → A/C/Z 计权
  → Leq/LAeq/LCeq/Lpeak
```

当前代码从第一步直接跳到“归一化波形当 Pa”，缺少中间环节。README 的“支持 94/114 dB 校准”没有实现，`Metadata` 表的 `mic_sensitivity_mV_Pa`、`calibration_level_dB` 等字段从未写入。

**部署前必须确认**：
- TDMS 中是否包含 `wf_start_time`、`wf_increment`、`unit_string`、灵敏度/量程属性；
- 是否有独立的校准文件/校准记录；
- 没有校准时，产品界面是否明确显示“未校准/相对 dBFS”，禁止显示为 dB SPL；
- 用 94 dB 和 114 dB 校准器做两点验证，并记录偏差；
- 计量合规场景还需要确认滤波器是否符合 IEC 61260 class 1、时间计权是否符合 IEC 61672，`acoustics` 的 Butterworth 实现不自动等于标准级。

### 4.2 采样率与时间基准

- 主转换器不识别 `wf_increment`，缺失时默认 44100（`app/core/tdms_converter.py:19,52-58`）；这会让 48 kHz/51.2 kHz 文件的时间轴和频率轴整体错误。
- `TimeHistory` 的 `timestamp` 是**处理时刻**（`datetime.utcnow()`），不是录音时刻；排队处理多个文件时，时间线与实际录音错位。应使用 TDMS 的 `wf_start_time` + 样本索引。
- `ProcessingResult.timestamp` 用本地 `datetime.now()`，`TimeHistory` 用 UTC，二者不可直接比较/联合展示。

### 4.3 剂量/峰度/事件

- 剂量公式本身（`DoseCalculator`）有测试，公式实现看起来合理；但输入 LAeq 未校准，剂量结果不可用。
- NIOSH/OSHA 的阈值、交换率、参考时长需要按目标标准再确认；当前所有 profile `threshold=0`，是否符合所选标准的“阈值以下不计入”需要逐条核对。
- `calculate_twa()`/`calculate_lex()` 对 `dose<=0` 返回 `0.0`，而数学上应为 `-inf` 或“无暴露”；UI 显示 0 dBA 会误导。
- 峰度 S1–S4 的合成算法有测试，思路正确；但 `valid_flag`/`artifact_flag` 计算出来后没有用于排除无效秒，README 声称“自动排除过载帧”未实现。
- 事件检测的阈值、C 计权、事件指标（SEL、β）目前都是简化/占位实现，不能作为冲击噪声结论。

### 4.4 建议的“可信度分级”

在修复前，建议产品明确三种模式：

1. **未校准/相对模式**：只输出相对电平（dBFS），禁止标 dB SPL，禁止剂量结论。
2. **单点校准模式**：94 dB 校准器偏移，输出近似 dB SPL，标注不确定度。
3. **合规模式**：完整灵敏度/频响/量程/校准记录 + 标准级滤波器 + 质控，才允许用于职业卫生判定。

当前代码最多只能算第 1 种，但 UI/README 呈现得像第 3 种，这是最大的“质量风险”。

---

## 5. 性能与容量评估

| 项目 | 现状/估算 | 风险 |
|---|---|---|
| 整段 `third_octaves` 内存 | 34×N float64；10 min ≈ 7.8 GB，1 h ≈ 47 GB | 长录音 OOM/被系统杀死 |
| `librosa.load` | 整段 float32；8 h ≈ 5.5 GB | 与上者叠加 |
| `TdmsFile.read` | 一次性读所有 group/channel；可能 float64 | 8 h 可达 11 GB+ |
| 临时 WAV | float32，8 h ≈ 5.5 GB | 磁盘占用；NAS 上更慢 |
| 每秒滤波 | 34 个 IIR + A/C 计权，每秒 48k 样本 | 可能显著慢于实时，积压文件 |
| 每秒 DB commit | 28,800 次/8 h | Windows+Defender 下数分钟到数十分钟 |
| TimeHistory 行数 | 31.5M/年 | SQLite 查询/备份/清理压力 |
| 前端 time_history | 默认 10,000 上限，8 h 有 28,800 秒 | 图表截断；JSON 很大 |
| 前端轮询 | 所有 tab 每次 rerun 都请求 | 多用户时后端压力大 |
| 会话内存 | `SessionManager.time_history` + `session_registry` 永不清理 | 长期运行内存增长 |

**建议**：
- 对 TDMS 使用 `TdmsFile.open()` + 分块 `read_data()`；对 WAV 用 `soundfile.blocks()`。
- 以“秒/块”为单位计算频段能量，累加到分钟/小时；不要对整段文件建 34×N 矩阵。
- 限制单文件时长/大小（例如 >30 min 拒绝或拆分），或改为流式处理。
- 批量写库 + WAL + 单写线程；前端分页/降采样，不要一次拉 10,000 行。
- 在目标 Windows 机器上用真实 1 h/8 h 文件做内存和耗时基准，不要只测 10 s 测试文件。

---

## 6. 安全评估

| 问题 | 说明 | 建议 |
|---|---|---|
| 无认证 | `/change_watch_directory`、`/session/*`、`/all_metrics` 全部匿名可访问 | 至少 API Key/JWT；或只绑定 127.0.0.1，由带认证的反向代理暴露 |
| 任意路径 | 可把监控目录改成任意本地路径，读取其中 `.tdms` 并回显路径 | 白名单根目录、规范化/拒绝 UNC 根/系统目录、最小权限账户 |
| 网络暴露 | `start_server.py` 绑定 `0.0.0.0:8000`；Streamlit 默认可能被 LAN 访问 | 默认 localhost；需要 LAN 时加防火墙 + TLS + 认证 |
| 日志隐私 | 422 handler 记录完整请求体；文件路径进入日志 | 脱敏、限制日志级别/保留期 |
| 无 TLS | HTTP 明文 | IIS/Nginx/Caddy 反向代理 + 证书；不要让 8000 直接出网 |
| 无 CORS 策略 | 目前无浏览器直连；未来加前端需明确 allowlist | 仅在需要时配置 CORSMiddleware |
| 运行账户 | 若用管理员/LocalSystem 运行，路径变更影响大 | 专用低权限服务账户；数据目录 ACL |
| 录音内容 | 噪声录音可能包含语音等个人信息 | 访问控制、加密（BitLocker）、保留/删除策略、告知/同意 |

---

## 7. 全新 Windows 环境部署适配

### 7.1 目标环境建议

- **OS**：Windows 10/11 x64 或 Windows Server 2019+；启用最新更新。
- **CPU/RAM**：4 核起；**16 GB 起，建议 32 GB**（当前整段分析内存开销大）。
- **磁盘**：系统盘 + 独立数据盘（SSD）；音频数据按 2–3 倍日增量预留；不要用 OneDrive/网络盘存 DB/log/temp。
- **Python**：**3.11.x 64 位**（不要 3.13；3.12 可用但必须锁 `librosa<1.0`、`numpy<2`）。
- **权限**：专用本地服务账户，非管理员；对 `C:\NoiseToolkit` 与数据目录有修改权限；对 NAS 共享有读权限。
- **时间**：设置 `China Standard Time`，配置 NTP；关闭睡眠/休眠；禁用 Windows Update 在测量时段自动重启。

### 7.2 依赖矩阵（建议起点，需在目标机验证）

| 包 | 建议 | 原因 |
|---|---|---|
| Python | 3.11.9 x64 | 3.13 没有 `numpy 1.26` 轮子；3.12 可用但注意 librosa |
| numpy | **1.26.4** | `acoustics 0.2.6` 在 NumPy 2 下 `third_octaves` 报错 |
| scipy | 1.13.1 | 与 numpy 1.26 兼容；1.18 已移除 `acoustics` 依赖的 `sph_harm`，不能用最新版 |
| librosa | **0.11.0** | `librosa 1.0.x` 要求 `numpy>=2.1`，与 acoustics 冲突 |
| numba | 0.61.2 | 支持 numpy 1.26；librosa 依赖 |
| llvmlite | 0.44.0 | numba 0.61.2 配套 |
| acoustics | **0.2.6** | 项目 API 依赖；已停止维护，必须锁 |
| soundfile | 0.14.0 | 读写 WAV；Windows wheel 自带 libsndfile |
| nptdms | 1.14.0 | TDMS 读取；Python≥3.11 |
| watchdog | 7.1.0 | 文件监控；**当前 requirements 缺失** |
| loguru | 0.8.0 | 日志；**当前 requirements 缺失** |
| fastapi | 0.136.x | 需要 Pydantic 2 |
| pydantic | 2.x | `model_dump()` 需要 v2；`config.py` 需改 `pydantic-settings` |
| streamlit | 1.49–1.67，锁定 | `width="stretch"` 需较新版本；`use_container_width` 已弃用 |
| pandas | 2.3.x | 与 numpy 1.26 兼容 |
| plotly | 6.x | 图表 |
| sqlalchemy | 2.0.x | ORM |
| pyfunctional | 1.5.0 | 代码使用 `functional.seq` |
| matplotlib | 3.10.x | acoustics 依赖；服务模式设 `MPLBACKEND=Agg` |
| tabulate / six / dill | 随依赖 | acoustics/pyfunctional 传递依赖 |
| pytest | 8.x/9.x | 开发/验收测试，不要进生产依赖 |

**关键**：不要直接 `pip install -r requirements.txt`。先生成 `requirements-win.txt` 并锁定；在目标 Windows 上 `pip check` + 烟测后再部署。

### 7.3 安装步骤（PowerShell / cmd 示例）

```powershell
# 0) 系统准备
Set-TimeZone -Id "China Standard Time"
w32tm /resync
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

# 1) 安装 Python 3.11 x64 到 C:\Python311（勾选 pip；如保留 tkinter 则勾选 tcl/tk）
#    安装 Microsoft Visual C++ 2015-2022 Redistributable (x64)（多数 wheel 需要）

# 2) 目录（短、ASCII、非 Program Files、非 OneDrive/NAS）
New-Item -ItemType Directory -Force C:\NoiseToolkit
New-Item -ItemType Directory -Force C:\NoiseToolkit\audio_files
New-Item -ItemType Directory -Force C:\NoiseToolkit\Database
New-Item -ItemType Directory -Force C:\NoiseToolkit\log
New-Item -ItemType Directory -Force C:\NoiseToolkit\audio_events
New-Item -ItemType Directory -Force C:\NoiseToolkit\temp

# 3) 虚拟环境
py -3.11 -m venv C:\NoiseToolkit\.venv
C:\NoiseToolkit\.venv\Scripts\python -m pip install -U pip wheel

# 4) 依赖（先准备 requirements-win.txt）
C:\NoiseToolkit\.venv\Scripts\pip install -r C:\NoiseToolkit\requirements-win.txt
C:\NoiseToolkit\.venv\Scripts\pip check
```

**离线安装**（目标机无外网时，在有网的同架构 Windows 机器上准备 wheelhouse）：

```powershell
py -3.11 -m pip download -r requirements-win.txt -d wheelhouse `
  --only-binary=:all: --platform win_amd64 --python-version 311 `
  --implementation cp --abi cp311
# acoustics 只有 sdist，需要单独构建 wheel（并准备 flit_core）
py -3.11 -m pip wheel acoustics==0.2.6 -w wheelhouse
# 目标机：
py -3.11 -m pip install --no-index --find-links=C:\NoiseToolkit\wheelhouse -r requirements-win.txt
```

**安装后烟测**：

```powershell
C:\NoiseToolkit\.venv\Scripts\python -c "import numpy, scipy, librosa, acoustics, soundfile, nptdms, watchdog, loguru, streamlit, fastapi, sqlalchemy; print('numpy', numpy.__version__)"
C:\NoiseToolkit\.venv\Scripts\python -c "import numpy as np; from acoustics import Signal; s=Signal(np.random.randn(48000),48000); print(s.third_octaves()[1].shape)"
# 期望输出形状 (34, 48000)；若 TypeError 说明 numpy/ acoustics 组合仍不对
```

### 7.4 配置项（建议新增）

当前 `config.py` 不可用（`from pydantic import BaseSettings` 在 Pydantic 2 下直接 ImportError）。建议改为 `pydantic-settings` 并至少支持：

```
APP_HOST=127.0.0.1
APP_PORT=8000
WATCH_DIR=C:\NoiseToolkit\audio_files
DB_PATH=C:\NoiseToolkit\Database\noise_info.db
LOG_DIR=C:\NoiseToolkit\log
EVENT_DIR=C:\NoiseToolkit\audio_events
TEMP_DIR=C:\NoiseToolkit\temp
BACKEND_URL=http://127.0.0.1:8000
TIMEZONE=Asia/Shanghai
CALIBRATION_FILE=C:\NoiseToolkit\config\calibration.json
MAX_FILE_DURATION_S=1800
```

所有路径使用 `Path(__file__).resolve().parent` 或环境变量，**不要依赖 CWD**。

### 7.5 目录/路径/权限

- **安装目录**：`C:\NoiseToolkit`（短、ASCII、可写）；不要放 `Program Files`（DB/log 写入需要权限），不要放 OneDrive（同步锁），不要从 NAS 直接运行 Python（导入慢、锁不可靠）。
- **数据目录**：`D:\NoiseData` 或 UNC `\\nas\share\noise`；DB/log/temp 必须本地。
- **服务账户**：对安装目录和数据目录 `Modify`；对 NAS 共享 `Read`；不要在服务账户下依赖映射盘符（服务会话看不到用户映射），用 UNC。
- **ACL**：限制普通用户写权限，避免误删/篡改。

### 7.6 服务化（NSSM 示例）

> 先修掉 `tk.Tk()`、`--reload`、相对路径、`audio_files` 创建等问题，否则服务化只会把启动失败隐藏到日志里。

```powershell
# 下载 nssm.exe 放到 C:\NoiseToolkit\tools\nssm.exe
$nssm = "C:\NoiseToolkit\tools\nssm.exe"

# 后端（必须单 worker：全局 task_manager + SQLite + 文件监控）
& $nssm install NoiseBackend C:\NoiseToolkit\.venv\Scripts\python.exe
& $nssm set NoiseBackend AppParameters "-m uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1"
& $nssm set NoiseBackend AppDirectory C:\NoiseToolkit
& $nssm set NoiseBackend AppStdout C:\NoiseToolkit\log\backend-stdout.log
& $nssm set NoiseBackend AppStderr C:\NoiseToolkit\log\backend-stderr.log
& $nssm set NoiseBackend AppExit Default Restart
& $nssm set NoiseBackend AppRestartDelay 5000
& $nssm start NoiseBackend

# 前端
& $nssm install NoiseFrontend C:\NoiseToolkit\.venv\Scripts\python.exe
& $nssm set NoiseFrontend AppParameters "-m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false"
& $nssm set NoiseFrontend AppDirectory C:\NoiseToolkit
& $nssm set NoiseFrontend AppStdout C:\NoiseToolkit\log\frontend-stdout.log
& $nssm set NoiseFrontend AppStderr C:\NoiseToolkit\log\frontend-stderr.log
& $nssm set NoiseFrontend AppExit Default Restart
& $nssm set NoiseFrontend AppRestartDelay 5000
& $nssm start NoiseFrontend
```

**Task Scheduler 替代方案**：触发器“启动时”，操作指向 `.venv\Scripts\python.exe`，参数如上，“起始于”设为 `C:\NoiseToolkit`，勾选“不管用户是否登录都运行”“失败时重新启动”。**不要**在“起始于”留空，否则 CWD 可能是 `System32`。

**必须单 worker**：`--workers >1` 会让每个进程各自启动一个 watchdog，重复处理同一文件、重复写 DB；当前架构不是多进程安全的。

### 7.7 网络、防火墙、反向代理

- 若前端和后端在同一台机器：都绑定 `127.0.0.1`，只对需要访问 UI 的网段开放 8501。
- 若前端在用户机器、后端在服务器：后端绑定内网地址，仅允许前端主机访问 8000；不要直接暴露公网。
- 防火墙示例（仅私网/域网络）：

```powershell
New-NetFirewallRule -DisplayName "Noise Toolkit UI" -Direction Inbound `
  -Protocol TCP -LocalPort 8501 -Action Allow -Profile Private,Domain
```

- 生产建议：IIS（ARR + URL Rewrite + WebSocket）或 Nginx/Caddy 反向代理，启用 TLS、Windows 认证/OIDC、访问日志；Streamlit 的 `server.enableCORS`/`enableXsrfProtection` 不要在没有代理保护时随意关闭。
- API 文档 `/docs` 也要保护；`/change_watch_directory` 不应匿名可用。

### 7.8 NAS / UNC / Defender / 索引器

- **不要**把 SQLite DB 放在 SMB/NAS：网络文件系统的锁语义不可靠，可能损坏；DB 放本地 SSD。
- 监控 NAS 时用 UNC 路径，并给服务账户共享/NTFS 权限；服务账户看不到用户映射盘符。
- Windows 的 `ReadDirectoryChangesW` 在部分 NAS/SMB 实现上不可靠；建议对网络目录使用 `watchdog.observers.polling.PollingObserver`，或让 DAQ 先写本地再原子移动到监控目录。
- DAQ 写文件建议 `.tmp` → 关闭 → 重命名为 `.tdms`；当前代码不处理 `on_moved`，需要补。
- Defender 实时扫描会锁文件/拖慢 WAL；如策略允许，排除数据目录（不要排除整个 Python 环境）：

```powershell
Add-MpPreference -ExclusionPath "C:\NoiseToolkit\audio_files"
Add-MpPreference -ExclusionPath "C:\NoiseToolkit\Database"
Add-MpPreference -ExclusionPath "C:\NoiseToolkit\audio_events"
Add-MpPreference -ExclusionPath "C:\NoiseToolkit\temp"
```

- 排除 Windows Search 索引器对数据目录的索引，避免锁和磁盘占用。

### 7.9 编码、长路径、时区、电源

```powershell
# UTF-8，减少中文/特殊字符日志的编码问题（服务环境变量也要设）
setx PYTHONUTF8 1 /M
setx PYTHONIOENCODING utf-8 /M
# Matplotlib/Numba 缓存放到可写目录（服务账户）
setx MPLBACKEND Agg /M
setx MPLCONFIGDIR C:\NoiseToolkit\temp\mpl /M
setx NUMBA_CACHE_DIR C:\NoiseToolkit\temp\numba /M

# 长路径（需重启；仍建议路径 < 260）
New-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem `
  -Name LongPathsEnabled -Value 1 -PropertyType DWord -Force

# 时区/NTP
Set-TimeZone -Id "China Standard Time"
w32tm /config /manualpeerlist:"ntp.aliyun.com" /syncfromflags:manual /reliable:yes /update
Restart-Service w32time
w32tm /query /status
```

- 中文路径/文件名：`nptdms` 用 Python `open` 通常没问题；`soundfile`/`libsndfile` 在 Windows 非 ASCII 路径上历史上有兼容问题。**部署前用真实中文路径测试**；保守做法是项目/数据目录用 ASCII。
- 电源：关闭睡眠/休眠/硬盘休眠/USB 选择性挂起；给 DAQ 与主机配 UPS；设置 Windows Update 活动时间，避免测量中重启。

### 7.10 数据迁移、备份、保留

- **迁移旧 DB**：先停服务；用 `sqlite3 noise_info.db ".backup ..."` 备份；检查 schema 是否有 `TimeHistory` 新列（`freq_*`/`sum_x*`/`beta_kurtosis` 等）。`Base.metadata.create_all()` 不会补列，旧库直接启动会在插入时 `no such column`。需要 Alembic 或一次性迁移脚本。
- **路径迁移**：旧库 `file_path` 可能是 Linux 路径/相对路径；迁移后 UI 的文件名/目录过滤可能失效。建议新增 `file_name`/`session_id` 查询，弱化 `file_dir` 依赖。
- **备份**：

```powershell
# 停服务后或使用 SQLite backup API；不要直接复制正在写的 .db + -wal
C:\NoiseToolkit\.venv\Scripts\python -c "import sqlite3; src=sqlite3.connect(r'C:\NoiseToolkit\Database\noise_info.db'); dst=sqlite3.connect(r'D:\Backup\noise_info.db'); src.backup(dst); dst.close(); src.close()"
```

- 每日备份 DB + 音频索引；每周离线副本；定期做**恢复演练**。
- **保留**：`TimeHistory` 31.5M 行/年；制定按月归档/删除策略；`cleanup_history()` 目前只删主表，需先修孤儿问题；音频文件按项目/日期归档。

### 7.11 上线验收测试清单

在**全新 Windows 虚拟机**上按顺序执行，全部通过才可上线：

**A. 安装与启动**
- [ ] 只用 Windows + Python 3.11 + wheelhouse 完成安装；`pip check` 无冲突。
- [ ] 烟测 `Signal.third_octaves()` 返回 `(34, N)`，无 `TypeError`。
- [ ] 启动后端；`GET /health` 200，`monitoring=true`；`GET /status` 正常。
- [ ] 启动前端；浏览器可访问；无 Tk 报错（或已移除 tkinter）。

**B. 基本数据链路**
- [ ] 放入 `CH1_*.tdms`（48 kHz、10 s）；等待处理；`/latest_metrics` 200 且 `data.metrics.leq/laeq` 非空。
- [ ] `TimeHistory` 9 个 `freq_*_spl` 非 NULL（修复 P0-4 后）。
- [ ] 前端实时频谱、TimeHistory 曲线、剂量曲线有数据。
- [ ] 检查 `processing_result`、`processing_metrics`、`spectrum_data`、`time_history` 行数与内容。

**C. 边界与错误**
- [ ] 44.1 kHz、48 kHz 正常；32 kHz/25.6 kHz 不崩溃（高频段可为空）。
- [ ] 静音文件：API 不 500；DB 无非有限值；UI 显示“低于下限”。
- [ ] 空目录/无结果：`/latest_metrics` 返回 404/空数据，不是 500。
- [ ] 绝对监控目录 `D:\NoiseData` 下 `/latest_metrics` 仍能查到。
- [ ] `start_time` 设为“今天”时 `/all_metrics` 能返回今天记录。

**D. 文件与路径**
- [ ] 慢速复制的大 TDMS 不会被半截解析；有稳定性检查/重试。
- [ ] `.tmp` 重命名为 `.tdms` 能被处理（`on_moved`）。
- [ ] `.TDMS` 大小写能被识别（若产品需要）。
- [ ] 中文路径、长路径（<260）可读写；`soundfile`/`librosa` 正常。
- [ ] NAS/UNC 路径可监控；服务账户有权限；SQLite 不在 NAS 上。
- [ ] 服务重启后，停机期间放入的文件能被扫描并处理，且不重复。

**E. 可靠性与性能**
- [ ] 处理 1 小时/8 小时文件的内存/耗时在预算内；或已改为分块/限制时长。
- [ ] 处理中停止服务/切换目录不会长时间挂起（目标 <30 s）。
- [ ] 两个文件同时到达时串行处理、不重复、不丢。
- [ ] 断电/强杀后重启：无重复记录；TimeHistory 可查；会话摘要可恢复/重建。
- [ ] 连续运行 24 h：内存不持续增长；日志轮转；DB 大小可控。

**F. 计量与安全**
- [ ] 94 dB/114 dB 校准器验证；偏差在可接受范围；无校准时 UI 明确标注。
- [ ] 端口扫描：8000 不对公网/LAN 开放；8501 仅授权网段；TLS/认证生效。
- [ ] `/change_watch_directory` 不能指向未授权目录。
- [ ] 备份可恢复；旧库迁移脚本验证。

### 7.12 上线前“一键检查”脚本建议

```powershell
$ErrorActionPreference = "Stop"
$py = "C:\NoiseToolkit\.venv\Scripts\python.exe"
& $py -c "import numpy, acoustics, librosa; print('numpy', numpy.__version__)"
& $py -c "import numpy as np; from acoustics import Signal; print(Signal(np.random.randn(48000),48000).third_octaves()[1].shape)"
& $py -m pip check
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8501 -UseBasicParsing | Select-Object StatusCode
Get-Service NoiseBackend, NoiseFrontend
```

---

## 8. 修复路线图

### 第 0 阶段：部署阻断（1–3 天）

1. 建立 `requirements-win.txt` 并锁定 Python 3.11/`numpy 1.26`/`librosa 0.11`/`acoustics 0.2.6`；补 `loguru`、`watchdog`；`pip check`。
2. 启动时创建 `audio_files`/`Database`/`log`/`audio_events`/`temp`；所有路径改为绝对路径/环境变量。
3. 修 `round(spl, 2)`；加频段 SPL 单元测试。
4. 修 `/latest_metrics` 空返回与 `file_dir` 过滤；统一 `file_dir` 表示。
5. 修 `/all_metrics` 用 `datetime` 绑定，统一 UTC。
6. 加非有限值清洗（计算层 + 入库层 + JSON 层）。
7. 移除/隔离 `tk.Tk()`；目录选择改为文本输入或浏览器端方案。
8. 明确校准策略：没有校准就输出“未校准/相对 dBFS”，不要标 dB SPL。

### 第 1 阶段：数据可信与稳定（1–2 周）

9. TDMS 读取 `wf_increment`/`wf_start_time`/单位/灵敏度；多通道；采样率不确定时拒绝处理。
10. 把整段 `third_octaves` 改为分块/按秒聚合；限制单文件时长；用真实长文件做基准。
11. 文件监控改为“observer 入队 + 单 worker 处理”；加 `on_moved`/稳定性/启动扫描/去重/重试。
12. SQLite：单例 engine、WAL、`busy_timeout`、批量写、事务化 `save_processing_result`、迁移脚本、清理孤儿。
13. 时间统一 UTC；前端本地化显示；旧数据迁移说明。
14. 会话摘要定期落盘或从 TimeHistory 重建；`session_registry` 清理。
15. 修前端侧边栏重启循环、自动刷新、空值格式化、Windows 路径显示、`all_metrics` 日期范围。

### 第 2 阶段：功能与运维（2–4 周）

16. 事件检测：向量化、接通主流程、正确追加事件、独立 C 计权、校准阈值；否则删除/关闭并修改文档。
17. WebSocket：实现或删除；统一“轮询/推送”架构。
18. 认证/TLS/反向代理/防火墙/路径白名单/最小权限。
19. 服务化脚本、健康检查、告警、备份/保留/恢复演练。
20. Windows CI + pytest 集成测试（临时 DB、临时目录、静音/32 kHz/绝对路径/长文件）。

### 第 3 阶段：工程质量（持续）

21. 拆分 45 个频段字段为 JSON/子表；统一单一时序模型。
22. 删除重复转换器/死代码；补 `pyproject.toml`、ruff、mypy、预提交。
23. 文档与实现对齐；补 LICENSE/CHANGELOG/.env.example；更新 `.devcontainer`。

---

## 9. 附录

### 9.1 关键复现证据

1. **NumPy 2 / SciPy 1.18 + acoustics 0.2.6**
   - 环境 A：`numpy 2.5.4`、`scipy 1.16.3`、`acoustics 0.2.6`（源码导入）。
     调用 `Signal(np.random.randn(48000), 48000).third_octaves()` →
     `TypeError: only 0-dimensional arrays can be converted to Python scalars`（`scipy.signal._filter_design.lp2bp_zpk`）。
   - 环境 B：`numpy 2.5.4`、`scipy 1.18.1`、`acoustics 0.2.6`（`pip install acoustics` 实际拉取的组合）。
     `import acoustics` 即失败：
     `ImportError: cannot import name 'sph_harm' from 'scipy.special'`（`acoustics/directivity.py`）。
   - 对照：`numpy 1.26.4` + `scipy 1.16.3` 下返回 `(34, 48000)`；推荐 `scipy==1.13.1`（仍含 `sph_harm`）作为起点，需在目标机复验。
   - 另一个佐证：上述 `pip install acoustics` 还自动拉入 `numba 0.65.0`，其要求 `numpy<2.5`，与已安装的 `numpy 2.5.4` 冲突；说明不锁版本的解析结果本身就不自洽。

2. **每秒频段 SPL 全为 None**
   - 调用：`TimeHistoryProcessor()._calculate_third_octave_metrics(Signal(noise, 48000))`。
   - 结果：9 个频段全部 `None`；warning：`type numpy.ndarray doesn't define __round__ method`。
   - 对照：`time_averaged_sound_level()` 返回 `(array([0.]), array([47.30]))`。

3. **静音信号非有限值**
   - `_calculate_second_metrics(zeros, 48000, ...)` → `LAeq=-inf`、`LZpeak=-inf`、`kurtosis=nan`。
   - `fastapi.responses.JSONResponse({'x': -inf})` → `ValueError: Out of range float values are not JSON compliant`。
   - SQLite：`NaN` 绑定读出 `NULL`；`-inf` 存为 `REAL`。

4. **低采样率 IndexError**
   - `AudioProcessor.process_wav_file()` 在 `fs=48000/44100` 成功；`fs=32000` 抛
     `IndexError: index 32 is out of bounds for axis 0 with size 32`；`fs=25600` 同样。
   - 原因：`np.arange(8, 35, 3)` 的最后一个索引 32 超出 `third_octaves()` 在低采样率下 purge 后的频带数。

5. **`/latest_metrics` 空结果 500**
   - FastAPI `response_model` 非 Optional，函数返回 `None`；`TestClient` 得到 500。

6. **SQLite 字符串日期比较**
   - SQLAlchemy 2.0 + SQLite：`WHERE ts >= '2026-11-15T10:00:00'` 返回 `[]`；绑定 `datetime(2026,11,15,10)` 返回正确行。
   - 原生 SQLite：`'2026-11-15 09:00:00' >= '2026-11-15T10:00:00'` 为 False（'T' > ' '）。

7. **路径过滤**
   - `PureWindowsPath(r'D:\NoiseData').name == 'NoiseData'`，而 `file_dir` 为 `D:\NoiseData` → 不匹配。

8. **watchdog 停止等待 handler**
   - handler `sleep(2)`；`Observer.stop(); join()` 在约 1.5 s 后返回（等待 handler 结束）。

9. **`config.py` 与 Pydantic 2**
   - `python -c "import config"` → `PydanticImportError: BaseSettings has been moved to pydantic-settings`。

### 9.2 建议的 `requirements-win.txt` 起点

> 这是“约束建议”，不是未经测试的最终锁文件。请用 `pip-compile`/`uv lock` 在目标 Windows 3.11 上生成并跑验收。

```text
# Python 3.11.x x64
numpy==1.26.4
scipy==1.13.1
pandas==2.3.3
librosa==0.11.0
numba==0.61.2
llvmlite==0.44.0
soundfile==0.14.0
acoustics==0.2.6
nptdms==1.14.0
watchdog==7.1.0
loguru==0.8.0
fastapi>=0.115,<1
uvicorn>=0.30,<1
pydantic>=2.7,<3
pydantic-settings>=2.0,<3
sqlalchemy>=2.0,<3
streamlit>=1.49,<2
plotly>=5.20,<7
requests>=2.31,<3
python-multipart>=0.0.9
pyfunctional==1.5.0
matplotlib>=3.8,<4
tabulate>=0.9,<1
six>=1.16
dill>=0.3
# dev only
pytest>=8,<10
```

安装后必须在目标 Windows 上确认：
- `pip check` 通过；
- `Signal.third_octaves()` 不报错；
- 32 kHz/25.6 kHz 不崩溃；
- `streamlit` 的 `width="stretch"` 可用。

### 9.3 关键文件索引

- `requirements.txt`：依赖缺失/未锁。
- `config.py`：Pydantic v1 `BaseSettings`，当前死代码且不可 import。
- `main.py`：API、全局状态、`/latest_metrics`、`/all_metrics`。
- `app/core/background_tasks.py`：处理线程、会话、事件、DB 写入。
- `app/core/file_monitor.py`：watchdog 监控。
- `app/core/tdms_converter.py`：TDMS→WAV、采样率/归一化。
- `app/core/audio_processor.py`：整段频谱、内存大头。
- `app/core/time_history_processor.py`：每秒指标、SPL 的 `round` bug。
- `app/core/summary_processor.py`：分钟/多级聚合、未持久化。
- `app/core/event_processor.py` / `event_detector.py`：事件检测未接通。
- `app/database/database.py` / `models.py`：SQLite、时间、字段重复。
- `streamlit_app.py`：Tk、自动刷新、侧边栏重启、格式化。
- `test/*`：测试缺口与损坏的测试。
- `README.md` / `AGENTS.md` / `.devcontainer/devcontainer.json`：文档漂移。

---

**最终建议**：把当前版本定位为“研发原型”，先按第 0 阶段修复并在一台全新 Windows 虚拟机上完成 7.11 的验收，再考虑接入真实测量。若目标包含职业卫生/合规结论，校准、滤波器标准符合性和数据审计链必须先于任何 UI/功能开发完成。
