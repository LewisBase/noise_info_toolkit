# 面向实地部署的噪声信息工具箱优化方案

> 对照项目：`/home/lewisbase/github/noise_info_toolkit_gcc`（C++ v3.3.4，以下简称 C++ 项目）  
> 目标项目：`/home/lewisbase/github/noise_info_toolkit`（Python 当前版本）  
> 目标：在 Windows 现场部署前，完成 DSP 正确性、长录音稳定性、数据一致性、可运维性和部署可复现性改造。  
> 关联文档：`doc/code_quality_and_windows_deployment_audit.md`（现有问题清单与复现证据）

> **本版根据最新意见修订**：
> 1. 不再采用“自研 DSP/手写系数”路线；计权、滤波、时间计权全部使用 NumPy/SciPy 标准 API，C++ 仅作为契约/测试参考；
> 2. 默认窗口改为 **10 s 读取/持久化 + 1 s 分析步**（可配置 0.5 s/1 s/10 s/60 s），兼顾内存、吞吐、事件分辨率和 UI 延迟；
> 3. 新增独立的 **Streamlit 可视化交付章节（WP-12）**，覆盖实时、历史、会话/事件、系统状态四页及代码骨架。

---

## 0. 阅读方式与执行原则

这份文档不是“问题列表”，而是**可排期、可验收的改造方案**。每个功能点都给出：

1. 现状与对应文件/行；
2. C++ 项目中的参考实现/设计；
3. Python 的目标接口与代码骨架；
4. 验收测试与通过标准。

执行原则：

- **先保证数据可信，再保证功能完整**：未校准的 dB 值不能进入剂量/合规结论。
- **先替换计算核心，再改 Web/UI**：否则 UI 只是在展示错误数据。
- **单一事实来源**：频段、系数、指标字段、剂量标准只允许一处定义。
- **流式优先**：任何路径都不允许把整段小时级音频读入内存。
- **可回滚**：新旧 DSP 双跑（shadow mode）+ 数据版本号，确认数值一致后再切换。
- **不要在旧 `acoustics` 上继续打补丁**：该库已停止维护，且在 NumPy 2 / SciPy 1.18 下分别出现运行时报错和 import 失败（详见现有审计报告 P0-2）。

---

## 1. 目标与关键决策

### 1.1 部署成功标准

| 维度 | 目标 |
|---|---|
| 正确性 | 1 kHz / 94 dB 纯音：LAeq、LCeq、LZeq = 94 ± 0.5 dB；A/C 计权在 IEC 61672-1 实用频段内达到 Class 1（≤0.7 dB）或明确标注 Class 2 |
| 频段 | 1 kHz 纯音在 1 kHz 频段 = 94 ± 1 dB；其余频段 ≤ 主频段 −15 dB；9 频段 Z 能量和与 LZeq 差 ≤1 dB |
| 长录音 | 8 小时 48 kHz 文件处理峰值内存 ≤500 MB（流式），不随文件时长线性增长 |
| 实时性 | 目标机器上处理速度 ≥ 实时（1 小时文件 ≤1 小时处理；建议 ≥2× 实时） |
| 可靠性 | 断电/重启后不重复、不丢文件；处理中的文件可恢复；停止服务 ≤30 s，不因长文件挂起 |
| 数据 | 每条 TimeHistory 的 9 个频段 SPL 非空；静音/NaN 不导致 500；时间全部 UTC 存储、前端本地化 |
| 异常留存 | 声学/系统异常可查；事件音频覆盖前 5 s + 后 10 s（可配）；调试模式不删除任何原始音频/事件音频；生产删除有 dry-run、宽限期和审计 |
| 计量 | 有校准：dB SPL + 不确定度 + 校准记录；无校准：明确“未校准/相对 dBFS”，禁用剂量结论 |
| 安全 | 默认仅 localhost；LAN 访问必须经认证/TLS；监控目录白名单；API 不再匿名改路径 |
| 部署 | 全新 Windows + 离线 wheelhouse 30 分钟内完成安装；`pip check` 通过；无 Tk/无编译器依赖 |
| 测试 | Windows CI 跑通单元/集成/长文件/状态持久性测试；有真实 TDMS + 94/114 dB 校准器验收记录 |

### 1.2 七个关键决策

**决策 A：用 NumPy/SciPy 标准滤波 API 替代 `acoustics` + `librosa`（不手写滤波器、不移植 C++ 系数）**

- 当前 `acoustics` 承担 A/C 计权、Leq、1/3 倍频程；它已停止维护，且：
  - NumPy 2 下 `third_octaves()` 抛 `TypeError`；
  - SciPy 1.18 下 `import acoustics` 因 `sph_harm` 被移除而失败。
- `librosa` 只用于 `load()`，可以完全由 `soundfile` + `nptdms` 替代；移除后不再需要 `numba/llvmlite`。
- **运行时全部使用 SciPy/NumPy 标准 API**：
  - A/C 计权：用 IEC 61672-1 的模拟零极点，经 `scipy.signal.bilinear_zpk` + `zpk2sos` 设计，`sosfreqz` 在 1 kHz 归一化；
  - 1/3 倍频程：用 `scipy.signal.butter(..., output="sos")` 设计，`sosfilt` 带状态滤波；
  - 时间计权：用 `scipy.signal.lfilter` 一阶指数状态；
  - **不手写 biquad 差分方程，不复制 C++ `weighting/bandpass` 头文件，不做自研系数表**。
- C++ 项目在本文中只作为**算法契约、状态保持和测试判据**的参考；其系数不是 Python 运行时输入。
- 收益：解决 P0-2 依赖死锁、去掉 matplotlib/numba 等大依赖；计算精度交给 SciPy，Python 只负责编排状态和指标。

**决策 B：10 s 读取/持久化窗口 + 1 s 分析步（默认），状态跨子块保持**

- C++ `NoiseProcessor` 已证明：滤波器状态必须跨段保持，否则 20/25 Hz 低频 LAeq 会虚高（C++ v3.3.2 专门修复）。
- **默认窗口策略**（可配置）：
  - `read_window_s = 10.0`：一次从 TDMS/WAV 读 10 s，降低 I/O 和 Python 调用次数；
  - `analysis_step_s = 1.0`：内部切成 10 个 1 s 子块，逐个调用 `process_block()`，保证 LAF/LAS、LAFmax、事件检测有秒级分辨率；
  - `persist_window_s = 10.0`：10 个 1 s 子块聚合为一行 TimeHistory，8 h 约 2,880 行（若按 1 s 存是 28,800 行）。
- **为什么选 10 s 而不是 1 min**：
  - 10 s @ 48 kHz = 480k 样本；A/C + 四路时间计权 + 单频段临时数组约 30–60 MB；1 min 约 6 倍（200–300 MB），且 UI/事件延迟明显变大；
  - 10 s 比 1 s 减少 90% 的 TDMS 读取/聚合调用，DB 行数也降为 1/10；
  - 1 s 分析步保留 LAF/LAS/事件的时间分辨率；10 s 只影响“入库粒度”，不影响声级计算。
  - 若项目/法规要求 1 s 明细，把 `persist_window_s` 配成 1.0 即可；DSP、事件和 UI 不变，只是 DB 行数变为 10 倍。
- 事件检测默认按 1 s 分析步执行；若需要更精确的 D3（500 ms 上升），可把 `analysis_step_s` 调到 0.5 s，仅增加 CPU，不改变 10 s 入库窗口。

**决策 C：单一常量/字段源，滤波器只保留一份 SciPy 设计**

- C++ v3.3.4 已做“删除重复/未归一化的计权系数副本，统一走 `WEIGHTING_TABLE`”。
- Python 需要同样处理：
  - 9 个频段中心频率只在一处定义；
  - A/C 和带通滤波器只在 `app/dsp/filters.py` 中用 SciPy 设计一次，运行时复用（可缓存 `.npz` 加速启动，但缓存内容必须是 SciPy 设计结果，不是手写系数）；
  - `SecondMetrics` 用 `freq_spl[9]` + `freq_moments[9]`，不再复制 45 个字段；
  - 删除 `utils/tdms_converter.py` 与 `app/core/tdms_converter.py` 的重复实现。

**决策 D：计算、采集、存储、展示四层分离**

- 借鉴 C++ 项目“库只做计算、不含存储/文件解析”的边界。
- Python 侧新增：
  - `app/dsp/`：纯计算，无 DB、无文件 I/O；
  - `app/io/`：TDMS 流式读取、校准、文件稳定性；
  - `app/services/`：任务队列、会话、聚合；
  - `app/storage/`：DB/迁移；
  - `app/api/` + `app/web/`：接口与 UI。
- 这样 DSP 可以单独用合成信号做单元测试，也可以与 C++ 参考向量做结果对照；Python 运行时仍只依赖 NumPy/SciPy。

**决策 E：Windows 现场部署以“单进程 + 单写线程 + 本地 SQLite”为基线**

- 后端 `uvicorn --workers 1`；文件处理一个 worker；SQLite WAL + 单写。
- 数据库、日志、临时文件放本地 SSD；音频放本地或 NAS；NAS 监控用 `PollingObserver`，数据库绝不放 NAS。
- 去掉服务端 `tk.Tk()`，远程用户不再触发服务器文件夹对话框。

**决策 F：Streamlit 是交付的一部分，不是附属脚本**

- 四个页面：实时监控、历史数据、会话与事件、系统状态。
- 实时页展示 10 s 窗口的 LAeq/LCeq/LZeq、LAF/LAS、峰值、四标准剂量、1/3 oct、趋势和事件标记；历史页支持日期/通道/会话查询、分页、CSV；事件页支持严重度和音频；状态页展示校准/队列/磁盘/健康。
- 用 `st.fragment(run_every=10)` 局部刷新，`st.sidebar.radio` 按页渲染，避免旧版 `st.tabs` 每次把所有页面/API 都执行；删除 Tk/filedialog。
- 未校准时页面顶部明确警告，剂量/LEX 不可用于合规结论。

**决策 G：异常监测 + 事件前后音频留存，调试期绝不删除**

- 声学异常：过载、LAF 阈值、脉冲、上升率、背景对比，分级为 MINOR/MODERATE/SEVERE；
- 系统异常：文件解析失败、DB 写失败、队列积压、磁盘不足、无数据、校准缺失，进入 `system_events`，不生成音频；
- 事件音频：默认保留事件前 **5 s** + 事件后 **10 s**，单事件最长 60 s；写入 `audio_events/`，文件名/DB 记录/校验和/校准信息完整；
- **调试阶段 `retention_mode=debug`：原始 TDMS/WAV 和事件音频全部保留，不做任何删除**；
- 正式上线 `retention_mode=production`：先 dry-run 预览；只有 job 成功、事件音频已落盘并校验、超过宽限期，才删除源音频；事件音频按保留期保留；所有删除写审计表。

---

## 2. C++ 项目对照：哪些可复用、哪些不能照搬

### 2.1 C++ 已经解决/验证过的能力

| 能力 | C++ 实现 | 对 Python 的价值 |
|---|---|---|
| 流式处理 | `NoiseProcessor::process_segment()`，10 ms/1 s 任意段，状态跨调用保持 | 直接替代整段 `librosa.load` + `acoustics.third_octaves` |
| 状态重置契约 | `NoiseProcessor::reset()`；文档明确“每块新建实例”是错误用法 | Python 必须有 `reset()`，并在文件/会话开始时调用 |
| A/C 计权 | matched-z / 最小二乘系数，IEC 61672-1 Class 1 验证 | 只参考其 IEC 参考表与测试判据；Python 用 `scipy.signal.bilinear_zpk`/`zpk2sos` 现场设计，不移植 C++ 系数 |
| 时间计权 | LAF/LAS/LCF/LCS，指数状态；α=exp(−1/(τfs)) | Python 当前完全缺失，必须补 |
| 1/3 倍频程 | 9 个 persistent biquad + scipy 归一化 + 峰值增益校正 | Python 用 `scipy.signal.butter(..., output="sos")` + `sosfilt` 流式实现；参考其归一化/频段 bug 教训，不复制 biquad |
| 峰度聚合 | `FreqBandMoments` + S1–S4 精确合成 | Python 已有算法，但字段重复；改为数组/JSON |
| 剂量状态 | `DoseState` + `accumulate_dose_frac` / `dose_to_*` 纯函数 | Python 的 SessionManager 混合了状态/DB/汇总，应拆开 |
| 四维事件 | D1 LAF 阈值、D2 LAF−LAS 脉冲、D3 500 ms 上升、D4 5 min 背景；分级 + 严重度 | Python 现有事件检测未接通且只有单一峰值，应整体替换 |
| 聚合 | `aggregate_metrics()` 秒→分钟，能量平均、峰值取最大、S1–S4 累加、事件计数 | Python 的分钟聚合只写日志，应移植并持久化 |
| 测试方法 | 纯音 94 dB、IEC 参考表、状态持久性矩阵、Dose 理论值、端到端 | Python 测试可直接采用这些判据 |

### 2.2 C++ 自身也不能照搬的点

- **只支持 48 kHz**（v3.3.4 收敛）。Python 现场可能遇到 44.1/32/25.6/16 kHz，必须按采样率用 SciPy 重新设计滤波器，并在 Nyquist 不足时把高频段标为 `None`，不能崩溃。
- **`LAFmax = LAeq + 3 dB` 是近似**。Python 应计算时间计权序列的真实最大值。
- **`LAeq = LAS` 是 C++ 的简化**。Python 应按块内 A 加权能量计算 LAeq；LAF/LAS 只作为瞬时时间计权读数。
- **C++ 带通每段 `reset()`**：这会引入瞬态，C++ 自己也有低频/短块问题。Python 应跨块保持带通状态，只在文件/会话开始重置。
- **C++ 频段滤波器是 2 阶 Butterworth**：阻带抑制有限，不能自动宣称 IEC 61260 Class 1。Python 应按 IEC 61260 指标选择 SciPy `butter` 阶数（2/4/6）并用 `sosfreqz`/能量和验证，不为了“对齐 C++”而牺牲阻带。
- **C++ 测试用 `assert()`，Release 下会被 `NDEBUG` 禁用**。Python 用 pytest，不用 assert 作为唯一保障。
- **C++ 不含校准、存储、文件解析**：Python 必须补上游校准和 TDMS 元数据，否则 C++ 的“Pa 输入”假设在 Python 侧不成立。

### 2.3 可复用资产清单

- `tools/regen_weighting_coefficients.py`：IEC A/C 参考表与测试信号，**只作为 Python SciPy 设计的对照 oracle**。
- `tools/regen_bandpass_coefficients.py`：1/3 oct 归一化与 \(|H(f_c)|\) 校验方法，**不作为 Python 运行时系数来源**。
- `include/noise_metrics.hpp`：`FreqBandMoments`、指标字段清单、阈值常量。
- `include/dose_state.hpp`：DoseState 纯函数语义。
- `include/event_detector.hpp` / `src/event_detector.cpp`：四维判定、严重度、回看/背景状态。
- `tests/test_state_persistence_matrix.cpp`：状态保持/错误用法矩阵。
- `tests/test_end_to_end.cpp`、`tests/test_class1_precision.cpp`：验收判据与信号生成方法。
- `docs/THIRD_OCTAVE_BAND_CALCULATION.md`：频段归一化与 +76 dB bug 的根因，避免 Python 重蹈覆辙。
- `docs/DEVELOPMENT_PLAN_v3.3.2.md`：滤波器状态跨段保持的教训。

> 复用代码前先确认 C++ 项目许可证（README 目前写“待定/参考原 Python 项目”）。本方案只复用**算法契约、状态语义和测试判据**，不复用其手写系数/滤波器实现；Python 的数值计算以 NumPy/SciPy 为准。

### 2.4 内存/资源泄漏与重复代码的治理对照

| 泄漏/重复点 | 当前 Python | C++ 做法 | 目标改造 |
|---|---|---|---|
| 整段音频/频谱数组 | `librosa.load` + `third_octaves` 全量 | 10 ms/1 s 流式，零堆分配 | WP-05：10 s 读取窗口 + 1 s 分析步 + 状态保持；内存 O(窗口) |
| 临时 WAV | TDMS→5 GB 级 temp WAV | 无（库不做文件解析） | WP-06：直接读 TDMS 块，取消 temp WAV |
| 会话历史列表 | `SessionManager.time_history` 无限增长 | 业务侧只持 DoseState，指标由调用方处理 | WP-09：DB 存历史；内存只留当前窗口 |
| 会话注册表 | `session_registry._sessions` 永不清理 | 无全局注册表 | WP-09：DB 会话 + 当前会话单例 |
| DB engine | 每个 TaskManager 新建 `DatabaseManager` | 无 DB 层 | WP-08：单例 engine + session context |
| 文件处理线程 | watchdog observer 线程内处理；`join` 等长文件 | 无文件监控 | WP-07：observer 只入队；worker 可停止 |
| 日志队列 | `enqueue=True` 在受限账户可能失败 | 无 | WP-01/13：配置化 `enqueue`，失败回退 |
| Tk 根窗口 | import 时 `tk.Tk()` | 无 UI | WP-12：删除 Tk/filedialog |
| 45 个频段字段 | 多处复制 | `FreqBandMoments` 数组 + `band_moments_ptr` | WP-03：`freq_spl[9]` + `freq_moments[9]` + JSON |
| 两个 TDMS 转换器 | `app/core` 与 `utils` 各一份 | 单一库 | WP-03/06：删除 `utils/tdms_converter.py` |
| 频段/剂量常量 | 多处硬编码 | `WEIGHTING_TABLE`、`DOSE_PROFILES` 单表 | WP-03/04：常量模块 + SciPy 设计缓存（非手写系数） |
| 死代码 | ConnectionManager/executor/callback 等 | 库极简 | WP-03/11：删除或实现，禁止“声称实现” |

> 结论：Python 无法做到 C++ 的“零堆分配”，但可以做到**内存与块大小成正比、与录音时长无关**；这才是现场 8 小时录音真正需要的目标。

---

## 3. 工作包总表

| WP | 内容 | 优先级 | 依赖 | 预估 |
|---|---|---|---|---|
| WP-01 | 配置、目录、启动生命周期 | P0 | — | 1–2 d |
| WP-02 | 依赖精简与锁定、Windows wheelhouse | P0 | — | 1–2 d |
| WP-03 | 领域类型、常量、单一字段源 | P0 | WP-01 | 2–3 d |
| WP-04 | A/C 与 1/3 oct 系数生成/校验 | P0 | WP-03 | 3–5 d |
| WP-05 | 流式 DSP 处理器 | P0 | WP-03/04 | 5–8 d |
| WP-06 | 校准与 TDMS 流式读取 | P0 | WP-05 | 3–5 d |
| WP-07 | 文件监控、任务队列、幂等 | P0 | WP-01/06 | 3–4 d |
| WP-08 | 数据库 schema、迁移、批量写 | P0 | WP-03 | 4–6 d |
| WP-09 | 会话、DoseState、聚合 | P1 | WP-05/08 | 4–6 d |
| WP-10 | 四维事件检测与持久化 | P1 | WP-05/08 | 3–5 d |
| WP-11 | API 重构（v1、错误码、分页、时区） | P1 | WP-08/09 | 3–4 d |
| WP-12 | Streamlit 重构（去 Tk、fragment、校准提示） | P1 | WP-11 | 3–4 d |
| WP-13 | 安全、服务化、备份、监控 | P1 | WP-07/11 | 2–3 d |
| WP-14 | 测试体系、Windows CI、验收 | P0 | 全部 | 3–5 d |
| WP-15 | 异常监测、事件音频捕获、留存与清理 | P0 | WP-05/07/08/10 | 3–4 d |

总计约 45–65 人日；1 人约 8–12 周，2 人并行约 5–7 周。建议先做 WP-01/02/03/04/05 的“垂直切片”，用一个 1 kHz 纯音跑通“TDMS → 流式 DSP → 10 s 入库 → API”，再扩展。

### 3.1 与现有审计问题的对应关系

| 现有问题（审计报告编号） | 对应 WP | 解决方式 |
|---|---|---|
| P0-1 缺 `loguru`/`watchdog`、依赖未锁 | WP-02 | 重写依赖清单 + `pip check` + wheelhouse |
| P0-2 `acoustics`/NumPy 2/SciPy 1.18 冲突 | WP-04/05 | 改用 NumPy/SciPy 标准滤波，删除 acoustics/librosa；不移植 C++ 系数 |
| P0-3 `audio_files` 不存在、相对路径 | WP-01 | `Settings` 绝对路径 + 启动创建目录 |
| P0-4 每秒频段 SPL 全 `None` | WP-05 | 流式频段 SPL；删除 `round(ndarray)` 路径 |
| P0-5 `/latest_metrics` 空返回/file_dir 过滤 | WP-08/11 | 新表 + 正确 404/按 channel 查询 |
| P0-6 `/all_metrics` 字符串日期 | WP-11 | Pydantic datetime + UTC + SQLAlchemy 绑定 |
| P0-7 静音 `-inf/NaN` → 500 | WP-05/08 | `None` 语义 + 入库/JSON 清洗 |
| P0-8 无校准、dB 不可信 | WP-06 | Calibration + 未校准模式 + 校准记录 |
| P0-9 整段 `third_octaves` 内存爆炸 | WP-05 | 10 s 窗口 + 1 s 分析步 + 状态保持 |
| P1-2 watchdog 线程阻塞停止 | WP-07 | observer 只入队 + worker + stop timeout |
| P1-3 无启动扫描/去重/稳定性 | WP-07/08 | jobs 表 + 稳定检测 + 启动扫描 |
| P1-5 TDMS 采样率/`wf_increment` | WP-06 | 读取属性，缺失即报错 |
| P1-7 每秒 commit | WP-08 | 批量写 + WAL |
| P1-9 本地/UTC 混用 | WP-08/11 | 全 UTC + 前端本地化 |
| P1-10 会话摘要只在停止时保存 | WP-09 | 定期 checkpoint + 恢复 |
| P1-11/12 前端重启监控/sleep | WP-12 | `on_change` + `st.fragment` |
| P1-13 事件检测未接通 | WP-10/15 | 四维事件 + 事件音频缓冲 + 事件表 |
| P1-14 WebSocket 缺失 | WP-11/13 | 明确轮询；删除死代码或实现 |
| P1-15 部分写入/孤儿 | WP-08 | 事务 + 外键/级联 + 迁移 |

### 3.2 最小垂直切片（建议第一周就做）

按以下顺序做一个可演示闭环，避免“先改一堆底层却看不到结果”：

1. WP-01 配置/目录；
2. WP-04 仅生成 48 kHz 系数；
3. WP-05 只实现 A/C + LAF/LAS + 总声级 + 1/3 oct；
4. WP-06 仅读单通道 TDMS 的 10 s 窗口，并切成 1 s 子块；
5. WP-08 只建 `jobs`/`sessions`/`time_history` 三张表；
6. WP-11 只做 `/api/v1/metrics/latest` 和 `/health/ready`；
7. 用 1 kHz/94 dB 合成 TDMS 验证：LAeq=94±0.5，`freq_1khz_spl` 非空，API 返回 200。

这个切片通过后，再补会话、事件、聚合、UI 和 Windows 服务化。

---

## 4. 详细实施方案

### WP-01 配置、目录与启动生命周期

**现状问题**

- `config.py` 使用 Pydantic v1 `BaseSettings`，在 Pydantic 2 下直接 `ImportError`，且未被使用。
- `main.py` 在 import 时创建 `DatabaseManager()`；`./Database`、`./audio_files`、`./audio_events` 依赖 CWD。
- 启动时 `audio_files` 不存在 → `FileNotFoundError`，应用退出。
- `task_manager` / `current_watch_directory` 是模块级全局变量。

**目标**

- 新增 `app/config.py`（`pydantic-settings`），所有路径绝对化、创建目录、校验可写。
- `main.py` 的全局变量改为 `app.state.service`，由 lifespan 注入。
- 启动失败给出明确错误（目录不存在、DB 不可写、系数缺失），而不是裸 traceback。

**代码骨架**

```python
# app/config.py
from pathlib import Path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="NIT_",
        extra="ignore",
    )

    app_root: Path = PROJECT_ROOT
    watch_dir: Path = PROJECT_ROOT / "audio_files"
    db_path: Path = PROJECT_ROOT / "Database" / "noise_info.db"
    log_dir: Path = PROJECT_ROOT / "log"
    event_dir: Path = PROJECT_ROOT / "audio_events"
    temp_dir: Path = PROJECT_ROOT / "temp"

    host: str = "127.0.0.1"
    port: int = 8000
    backend_url: str = "http://127.0.0.1:8000"
    timezone: str = "Asia/Shanghai"

    require_calibration: bool = True
    read_window_s: float = 10.0       # 一次读取/处理窗口
    analysis_step_s: float = 1.0      # 内部子块；事件/时间计权分辨率
    persist_window_s: float = 10.0    # TimeHistory 入库粒度
    stable_seconds: float = 2.0
    max_file_bytes: int = 20 * 1024**3
    allowed_watch_roots: list[Path] = Field(default_factory=list)

    # 异常事件音频
    event_pre_s: float = 5.0          # 事件前保留
    event_post_s: float = 10.0        # 事件后保留
    event_max_s: float = 60.0         # 单事件最长（防止无限录制）
    event_min_gap_s: float = 2.0      # 相邻事件最小间隔
    event_audio_subtype: str = "FLOAT"  # FLOAT 保真；可选 PCM_16

    # 录音留存：默认调试模式绝不删除
    retention_mode: str = "debug"     # debug | production
    delete_source_after_days: float = 7.0
    event_retention_days: float = 365.0
    retention_dry_run: bool = True
    trash_dir: Path = PROJECT_ROOT / "trash"

    @model_validator(mode="after")
    def _prepare(self):
        if not (0 < self.analysis_step_s <= self.read_window_s <= 60):
            raise ValueError("require 0 < analysis_step_s <= read_window_s <= 60")
        ratio = self.persist_window_s / self.analysis_step_s
        if abs(ratio - round(ratio)) > 1e-9:
            raise ValueError("persist_window_s must be an integer multiple of analysis_step_s")
        if self.retention_mode not in ("debug", "production"):
            raise ValueError("retention_mode must be debug or production")
        if not (0 <= self.event_pre_s and 0 <= self.event_post_s):
            raise ValueError("event_pre_s/event_post_s must be >= 0")
        if self.event_max_s < self.event_pre_s + self.event_post_s:
            raise ValueError("event_max_s must be >= event_pre_s + event_post_s")
        for p in (self.watch_dir, self.db_path.parent, self.log_dir,
                  self.event_dir, self.temp_dir, self.trash_dir):
            p.mkdir(parents=True, exist_ok=True)
            if not p.is_dir():
                raise ValueError(f"not a directory: {p}")
        return self
```

```python
# app/api/main.py（示意）
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db = Database(settings.db_path)
    service = ProcessingService(settings, db)
    service.start()
    app.state.service = service
    try:
        yield
    finally:
        service.stop(timeout=30)   # 不再 join watchdog handler
```

**验收**

- 在空目录启动：自动创建 5 个目录；`/health/ready` 200。
- 把 `NIT_WATCH_DIR` 指到只读目录：启动失败，日志明确“不可写”，不创建半初始化服务。
- 从 `C:\Windows\System32` 作为 CWD 启动，DB/日志仍落在项目目录。

---

### WP-02 依赖精简与 Windows 可复现安装

**现状问题**

`requirements.txt` 缺 `loguru`/`watchdog`，全部未锁；`numpy 2 + librosa 1.0` 与 `acoustics 0.2.6` 冲突；`acoustics` 在 SciPy 1.18 下 import 失败。

**目标依赖（最终态）**

```
Python 3.11.x x64
fastapi
uvicorn
pydantic>=2
pydantic-settings
sqlalchemy>=2
alembic
numpy==1.26.4        # 建议先锁定目标机验证过的版本；改用 SciPy 后不再受 acoustics 的 NumPy 2 限制
scipy==1.13.1        # 与 numpy 1.26 组合验证；后续可单独升级
soundfile
nptdms
watchdog
loguru
streamlit
plotly
pandas
requests
pytest                   # dev only
```

**移除**：`acoustics`、`librosa`、`numba`、`llvmlite`、`matplotlib`、`pyfunctional`、`openpyxl`、`python-multipart`（确认无表单上传后）。

**过渡态**：如果先不替换 DSP，则临时锁定：

```
numpy==1.26.4
scipy==1.13.1
librosa==0.11.0
numba==0.61.2
acoustics==0.2.6
```

但这只是过渡，最终目标是删除 `acoustics`/`librosa`。

**Windows 安装**

```powershell
py -3.11 -m venv C:\NoiseToolkit\.venv
C:\NoiseToolkit\.venv\Scripts\python -m pip install -U pip wheel
C:\NoiseToolkit\.venv\Scripts\pip install -r C:\NoiseToolkit\requirements-win.txt
C:\NoiseToolkit\.venv\Scripts\pip check
```

离线：

```powershell
py -3.11 -m pip download -r requirements-win.txt -d wheelhouse `
  --only-binary=:all: --platform win_amd64 --python-version 311 `
  --implementation cp --abi cp311
# 纯 Python/源码包（如有）单独 wheel 化
py -3.11 -m pip wheel <sdist> -w wheelhouse
```

**验收**

- 全新 Windows VM 从零安装，`pip check` 无冲突。
- `python -c "import numpy, scipy, soundfile, nptdms, watchdog, loguru, streamlit"` 成功。
- 不再需要编译器、Tk、matplotlib、numba。

---

### WP-03 领域类型、常量与单一字段源

**现状问题**

- `SecondMetrics` / `AggregatedMetrics` / `TimeHistory` 模型 / `save_time_history()` / `get_time_history()` / `background_tasks.py` 中重复 45 个频段矩字段。
- 频段中心频率在 `audio_processor.py`、`time_history_processor.py`、`summary_processor.py` 多处硬编码。
- `FreqBandMoments` 没有独立类型。

**目标**

新增 `app/domain/metrics.py`，对齐 C++ `noise_metrics.hpp`：

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

BAND_CENTERS_HZ = (63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
BAND_NAMES = ("63Hz", "125Hz", "250Hz", "500Hz", "1kHz",
              "2kHz", "4kHz", "8kHz", "16kHz")

@dataclass(slots=True)
class FreqBandMoments:
    n: int = 0
    s1: float = 0.0
    s2: float = 0.0
    s3: float = 0.0
    s4: float = 0.0

@dataclass(slots=True)
class Metrics:
    timestamp_utc: datetime
    duration_s: float
    channel: str

    # 声级
    laeq: Optional[float] = None
    lceq: Optional[float] = None
    lzeq: Optional[float] = None
    laf: Optional[float] = None
    las: Optional[float] = None
    lcf: Optional[float] = None
    lcs: Optional[float] = None
    lafmax: Optional[float] = None
    lasmax: Optional[float] = None
    lcsmax: Optional[float] = None
    lzpeak: Optional[float] = None
    lcpeak: Optional[float] = None
    lapeak: Optional[float] = None

    # 剂量分数（0-1，不是百分比）
    dose_frac_niosh: float = 0.0
    dose_frac_osha_pel: float = 0.0
    dose_frac_osha_hca: float = 0.0
    dose_frac_eu_iso: float = 0.0

    # QC / 事件
    overload: bool = False
    underrange: bool = False
    wearing: bool = True
    valid: bool = True
    artifact: bool = False
    event_type: int = 0          # 0 NONE, 1 MINOR, 2 MODERATE, 3 SEVERE
    event_severity: int = 0

    # 峰度/原始矩（Z）
    kurtosis_total: Optional[float] = None
    kurtosis_a: Optional[float] = None
    kurtosis_c: Optional[float] = None
    beta_kurtosis: Optional[float] = None
    n_samples: int = 0
    s1: float = 0.0
    s2: float = 0.0
    s3: float = 0.0
    s4: float = 0.0

    # 9 频段
    freq_spl: tuple[Optional[float], ...] = (None,) * 9
    freq_moments: tuple[FreqBandMoments, ...] = field(
        default_factory=lambda: tuple(FreqBandMoments() for _ in range(9)))

    # 兼容属性（只读，不再存 45 个字段）
    @property
    def freq_63hz_spl(self): return self.freq_spl[0]
    @property
    def freq_16khz_spl(self): return self.freq_spl[8]
```

**数据库映射**

- `freq_spl_json`：`{"63Hz": 45.2, ...}`；
- `freq_moments_json`：`{"63Hz": [n, s1, s2, s3, s4], ...}`；
- 不再建 45 个列。

**代码清理**

- 删除 `utils/tdms_converter.py`，保留一个 `app/io/tdms.py`；
- 删除 `app/core/connection_manager.py`（无 WebSocket）或真正实现；
- 删除 `app/utils/helpers.py`、未用的 `task_utils`；
- `DoseCalculator.PROFILES` 与数据库 `dose_profiles` 二选一：**代码常量作为唯一源**，DB 只存历史快照/审计，不参与计算。

**验收**

- 全仓库 grep 频段名/中心频率只出现在 `app/domain/constants.py` 和系数 JSON 中。
- `pytest` 中构造 `Metrics` 不需要写 45 个参数。

---

### WP-04 A/C 与 1/3 倍频程：用 SciPy 设计、校验与缓存

**现状问题**

- A/C 计权依赖 `acoustics.Signal.weigh()`；1/3 倍频程依赖 `acoustics.Signal.third_octaves()`，整段滤波、内存 O(34N)。
- 频段 SPL 没有归一化校验；C++ v3.3.0 曾因未归一化导致 +76 dB 频段 bug。
- 之前的方案试图移植 C++ 的 matched-z/手写 biquad 系数；**本版改为全部使用 SciPy 标准滤波 API**，不手写差分方程，也不复制 C++ 头文件。

**目标**

新增 `app/dsp/filters.py`，只做三件事：

1. 用 SciPy 从 IEC 模拟零极点设计 A/C 计权；
2. 用 SciPy 的 `butter` 设计 9 个 1/3 oct 带通；
3. 用 `sosfreqz` 做频响/归一化校验，并缓存设计结果（可选 `.npz`，只为启动加速）。

**A/C 计权：SciPy 标准设计**

```python
# app/dsp/filters.py
import numpy as np
from dataclasses import dataclass
from scipy.signal import bilinear_zpk, zpk2sos, sosfreqz

@dataclass(frozen=True)
class WeightingDesign:
    a_sos: np.ndarray
    a_gain: float
    c_sos: np.ndarray
    c_gain: float
    fs: int

@dataclass(frozen=True)
class BandDesign:
    centers: tuple[float, ...]
    sos: tuple[np.ndarray | None, ...]
    gains: tuple[float | None, ...]
    fs: int

# IEC 61672-1 模拟极点频率 (Hz)
A_POLES = (20.598997, 107.65265, 737.86223, 12194.217)
C_POLES = (20.598997, 12194.217)

def _a_analog_zpk():
    zeros = [0j] * 4
    poles = ([-2 * np.pi * A_POLES[0]] * 2
             + [-2 * np.pi * A_POLES[1]]
             + [-2 * np.pi * A_POLES[2]]
             + [-2 * np.pi * A_POLES[3]] * 2)
    return zeros, poles, 1.0

def _c_analog_zpk():
    zeros = [0j] * 2
    poles = ([-2 * np.pi * C_POLES[0]] * 2
             + [-2 * np.pi * C_POLES[1]] * 2)
    return zeros, poles, 1.0

def design_weighting(fs: int):
    # 全部由 SciPy 完成双线性变换 + SOS 分解
    za, pa, ka = _a_analog_zpk()
    zd, pd, kd = bilinear_zpk(za, pa, ka, fs=fs)
    a_sos = zpk2sos(zd, pd, kd, pairing="nearest")
    _, h = sosfreqz(a_sos, worN=[1000.0], fs=fs)
    a_gain = float(1.0 / abs(h[0]))

    zc, pc, kc = _c_analog_zpk()
    zd, pd, kd = bilinear_zpk(zc, pc, kc, fs=fs)
    c_sos = zpk2sos(zd, pd, kd, pairing="nearest")
    _, h = sosfreqz(c_sos, worN=[1000.0], fs=fs)
    c_gain = float(1.0 / abs(h[0]))
    return WeightingDesign(a_sos, a_gain, c_sos, c_gain, fs)
```

> 这是 SciPy 的标准双线性变换设计，不涉及手写 biquad/系数移植。若某个采样率下高频误差超出目标，只能通过**提高采样率、调整设计方法或明确降级等级**解决，不能再用“手写 correction 系数”硬凑。

**1/3 倍频程：SciPy `butter` + `sosfilt`**

```python
from scipy.signal import butter, sosfreqz

BAND_FACTOR = 2 ** (1 / 6)   # 1/3 oct 上下边频比

def design_bands(fs: int, order: int = 4) -> BandDesign:
    centers = (63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
    sos_list: list[np.ndarray | None] = []
    gain_list: list[float | None] = []
    for fc in centers:
        if fc * BAND_FACTOR >= fs / 2:
            sos_list.append(None)          # Nyquist 不足，明确 None
            gain_list.append(None)
            continue
        low, high = fc / BAND_FACTOR, fc * BAND_FACTOR
        sos = butter(order, [low, high], btype="band",
                     fs=fs, output="sos")
        _, h = sosfreqz(sos, worN=[fc], fs=fs)
        gain = float(1.0 / abs(h[0]))  # 通常≈1；由 SciPy 设计保证
        sos_list.append(sos)
        gain_list.append(gain)
    return BandDesign(centers, tuple(sos_list), tuple(gain_list), fs)
```

- 阶数 `order` 先用 4（比 C++ 2 阶有更好阻带），用 IEC 61260 测试决定是否 2/4/6；**不以“和 C++ 一致”为目标**。
- 每个频段只保留 `(sos, gain)`；`gain` 由 `sosfreqz` 算，不手写。
- 缓存只缓存 SciPy 的输出（`np.savez`），启动时校验 `fs/order/version`；缺缓存就现场设计，不静默用错误系数。

**校验（必须作为启动/CI 门禁）**

```python
# 伪代码：生成/启动时校验
for f, ref in IEC_A_TABLE:
    err = 20*np.log10(abs(h(f))) + 20*np.log10(gain) - ref
assert max(abs(err)) <= 0.7        # Class 1；达不到则记录为 Class 2 并告警

band_94 = band_spl_db(fc=1000, input_spl=94.0)
assert abs(band_94 - 94.0) <= 1.0
band_energy_db = 10*np.log10(sum(10**(x/10) for x in nine_band_spl))
assert abs(band_energy_db - lz_eq) <= 1.0
```

**验收**

- `test_class1_precision`：33 个频点，A/C 最大误差 ≤0.7 dB（实用频段 20 Hz–20 kHz；10/12.5/16 Hz 用长信号单独标注）。
- `test_bandpass_normalization`：1 kHz 正弦 94 dB → 1 kHz 频段 94 ±1 dB；其余频段 ≤ −15 dB 相对。
- `test_band_energy_sum`：9 个 Z 频段能量和与 LZeq 差 ≤1 dB。
- 44.1/48/32/16 kHz 各跑一遍；16 kHz 下 16 kHz 频段返回 `None`，不崩溃。
- 频率响应校验失败时，启动日志必须明确“Class 2/不满足”，不能静默继续。

---

### WP-05 流式 DSP 处理器（核心）

**现状问题**

- `AudioProcessor.process_wav_file()` 整段 `librosa.load` + `acoustics.third_octaves()`，10 分钟约 7.8 GB，1 小时约 47 GB。
- `TimeHistoryProcessor` 每秒用 `acoustics` 滤波，且 SPL 因 `round(ndarray)` 全部为 None。
- 没有 LAF/LAS/LCF/LCS/LAPeak；`LAFmax` 用估计值。
- 滤波器状态没有显式生命周期。

**目标**

新增 `app/dsp/processor.py`：

```python
import numpy as np
from scipy.signal import sosfilt

class SosChain:
    def __init__(self, sos: np.ndarray, gain: float):
        self.sos = np.asarray(sos, dtype=np.float64)
        self.gain = float(gain)
        self.zi = np.zeros((self.sos.shape[0], 2), dtype=np.float64)

    def process(self, x: np.ndarray) -> np.ndarray:
        y, self.zi = sosfilt(self.sos, x, zi=self.zi)
        return y * self.gain

    def reset(self) -> None:
        self.zi.fill(0.0)


def power_to_db(power: float, p_ref: float = 20e-6) -> float | None:
    if power <= 0 or not np.isfinite(power):
        return None
    return float(10.0 * np.log10(power) - 20.0 * np.log10(p_ref))


def peak_to_db(peak: float, p_ref: float = 20e-6) -> float | None:
    if peak <= 0 or not np.isfinite(peak):
        return None
    return float(20.0 * np.log10(peak / p_ref))


def kurtosis_from_moments(n: int, s1: float, s2: float,
                          s3: float, s4: float) -> float | None:
    if n < 2:
        return None
    mu = s1 / n
    m2 = s2 / n - mu * mu
    if not np.isfinite(m2) or m2 <= 1e-30:
        return None
    m4 = s4 / n - 4.0 * mu * s3 / n + 6.0 * mu * mu * s2 / n - 3.0 * mu ** 4
    beta = m4 / (m2 * m2)
    return float(beta) if np.isfinite(beta) and beta >= 0 else None


class StreamingNoiseProcessor:
    def __init__(self, fs: int, weighting: WeightingDesign,
                 bands: BandDesign, calibration: Calibration,
                 thresholds: QcThresholds):
        self.fs = int(fs)
        self.cal = calibration
        self.qc = thresholds
        self._a = SosChain(weighting.a_sos, weighting.a_gain)
        self._c = SosChain(weighting.c_sos, weighting.c_gain)
        self._bands = [None if s is None else SosChain(s, g)
                       for s, g in zip(bands.sos, bands.gains)]
        self._laf_a = 0.0
        self._las_a = 0.0
        self._laf_c = 0.0
        self._las_c = 0.0
        self._alpha_f = float(np.exp(-1.0 / (0.125 * self.fs)))
        self._alpha_s = float(np.exp(-1.0 / (1.0 * self.fs)))

    def reset(self) -> None:
        self._a.reset(); self._c.reset()
        for b in self._bands:
            if b is not None:
                b.reset()
        self._laf_a = self._las_a = self._laf_c = self._las_c = 0.0

    @staticmethod
    def _one_pole(x_sq: np.ndarray, alpha: float,
                  state: float) -> tuple[np.ndarray, float]:
        # y[n] = alpha*y[n-1] + (1-alpha)*x[n]
        # scipy lfilter 的 zi 对应 alpha*y[-1]；单元测试用直接递推校验
        from scipy.signal import lfilter
        y, _ = lfilter([1.0 - alpha], [1.0, -alpha], x_sq,
                       zi=[alpha * state])
        return y, float(y[-1])

    def process_block(self, x: np.ndarray, timestamp_utc: datetime,
                      duration_s: float | None = None) -> Metrics:
        x = np.asarray(x, dtype=np.float64)
        if x.ndim != 1 or x.size == 0:
            raise ValueError("expected non-empty 1-D block")
        n = x.size
        dur = float(duration_s) if duration_s is not None else n / self.fs
        artifact = not np.isfinite(x).all()
        if artifact:
            x = np.where(np.isfinite(x), x, 0.0)

        a = self._a.process(x)
        c = self._c.process(x)
        a2, c2, z2 = a * a, c * c, x * x

        # 时间计权状态（跨块保持）
        laf_a_series, self._laf_a = self._one_pole(a2, self._alpha_f, self._laf_a)
        las_a_series, self._las_a = self._one_pole(a2, self._alpha_s, self._las_a)
        laf_c_series, self._laf_c = self._one_pole(c2, self._alpha_f, self._laf_c)
        las_c_series, self._las_c = self._one_pole(c2, self._alpha_s, self._las_c)

        # 频段（状态跨块保持；不在这里 reset）
        band_spl: list[float | None] = []
        band_moments: list[FreqBandMoments] = []
        for chain in self._bands:
            if chain is None:          # Nyquist 不足的频段
                band_spl.append(None)
                band_moments.append(FreqBandMoments())
                continue
            y = chain.process(x)
            y2 = y * y
            band_spl.append(power_to_db(float(np.mean(y2))))
            band_moments.append(FreqBandMoments(
                n=n, s1=float(y.sum()), s2=float(y2.sum()),
                s3=float((y2 * y).sum()), s4=float((y2 * y2).sum())))

        m = Metrics(
            timestamp_utc=timestamp_utc,
            duration_s=dur,
            channel="",
            laeq=power_to_db(float(np.mean(a2))),
            lceq=power_to_db(float(np.mean(c2))),
            lzeq=power_to_db(float(np.mean(z2))),
            laf=power_to_db(self._laf_a),
            las=power_to_db(self._las_a),
            lcf=power_to_db(self._laf_c),
            lcs=power_to_db(self._las_c),
            lafmax=power_to_db(float(laf_a_series.max())),
            lasmax=power_to_db(float(las_a_series.max())),
            lcsmax=power_to_db(float(las_c_series.max())),
            lzpeak=peak_to_db(float(np.max(np.abs(x)))),
            lcpeak=peak_to_db(float(np.max(np.abs(c)))),
            lapeak=peak_to_db(float(np.max(np.abs(a)))),
            n_samples=n,
            s1=float(x.sum()), s2=float(z2.sum()),
            s3=float((z2*x).sum()), s4=float((z2*z2).sum()),
            freq_spl=tuple(band_spl),
            freq_moments=tuple(band_moments),
        )
        m.beta_kurtosis = kurtosis_from_moments(m.n_samples, m.s1, m.s2, m.s3, m.s4)
        m.kurtosis_total = m.beta_kurtosis
        m.kurtosis_a = kurtosis_from_moments(n, float(a.sum()),
                                             float(a2.sum()),
                                             float((a2*a).sum()),
                                             float((a2*a2).sum()))
        m.kurtosis_c = kurtosis_from_moments(n, float(c.sum()),
                                             float(c2.sum()),
                                             float((c2*c).sum()),
                                             float((c2*c2).sum()))
        m.artifact = artifact
        m.valid = not artifact

        # QC/剂量必须建立在“已校准、单位=Pa”之上；未校准时只输出相对 dBFS
        if self.cal.calibrated:
            m.overload = (m.lzpeak is not None and m.lzpeak > self.qc.overload_db)
            m.underrange = (m.laeq is not None and m.laeq < self.qc.underrange_db)
            m.wearing = (m.laeq is not None and m.laeq > self.qc.wearing_db)
            if m.laeq is not None:
                for std, attr in (
                    (DoseStandard.NIOSH, "dose_frac_niosh"),
                    (DoseStandard.OSHA_PEL, "dose_frac_osha_pel"),
                    (DoseStandard.OSHA_HCA, "dose_frac_osha_hca"),
                    (DoseStandard.EU_ISO, "dose_frac_eu_iso"),
                ):
                    setattr(m, attr,
                            DoseCalculator.calculate_dose_increment(
                                m.laeq, dur, std) / 100.0)
        else:
            m.overload = m.underrange = False
            m.wearing = True
        return m
```

**关键说明**

- `SosChain` 用 SciPy `sosfilt(..., zi=...)`，状态跨子块保持；C++ 只提供“状态必须连续”的契约参考，滤波器实现仍是 SciPy。
- 频段循环中是 `chain.process(x)`，**不要每块 `reset()`**；只在 `reset()`/新文件/新会话时清状态。
- `power_to_db()` 返回 `None` 而不是 `-inf`/`NaN`；从源头避免 API 500。
- `LAFmax/LASmax/LCSmax` 取时间计权序列的最大值，不再用 `LAeq + 3`。
- `LAeq` 用块内能量平均；`LAF/LAS` 是块末瞬时读数。
- **窗口策略**：管线一次读 10 s，切成 10 个 1 s 子块，逐个调用 `process_block()`；每个子块 `n=48000`。A/C 四路时间计权状态跨子块保持；10 个子块聚合为一行 10 s TimeHistory。单频段临时数组约 0.4 MB，整窗峰值约 30–60 MB，内存不随录音时长增长。
- 若需要更精细的事件 D3（500 ms 上升），把 `analysis_step_s` 调到 0.5 s；10 s 读取/入库窗口不变。

**10 s 窗口 → 1 s 子块 → 10 s 入库的管线**

```python
def process_file(source, cal, settings, processor, detector, capture,
                 repo, session_id, channel):
    processor.reset()
    detector.reset()
    step = int(round(settings.analysis_step_s * source.fs))
    for raw, window_start, _ in source.iter_windows(settings.read_window_s):
        pa = cal.to_pa(raw)
        sub = []
        for off in range(0, pa.size, step):
            chunk = pa[off:off + step]
            if chunk.size == 0:
                continue
            ts = window_start + timedelta(seconds=off / source.fs)
            seg = processor.process_block(chunk, ts, chunk.size / source.fs)
            result = detector.check(seg)
            clip = capture.push(chunk, ts, result)
            if clip is not None:
                repo.insert_event(session_id, channel, clip, result)
            sub.append(seg)
        row = aggregate_segments(sub, channel)   # 10 个子块 -> 一行 10 s
        repo.insert_time_history(session_id, row)
    repo.insert_file_result(session_id, processor.summary())  # 可选
    # capture 由 session 级持有；文件结束不 flush，避免截断 post；
    # session 停止或时间戳断档 >2 s 时由上层调用 capture.flush()。
```

> 这样“读 10 s、算 1 s、存 10 s”是同一套状态机：滤波器/时间计权跨 1 s 子块连续，事件检测不失真，DB 行数降为 1/10。

**验收**

- 1 kHz 94 dB：`laeq/lceq/lzeq = 94 ± 0.5`；`laf/las` 稳态也接近 94。
- 同一信号按 10/50/100/1000 ms、1 s、10 s 分块，能量平均差 ≤0.5 dB（状态连续）；若每子块新建 processor，20 Hz 结果应明显偏差（负向测试）。
- 10 s 窗口与 10 × 1 s 子块的 LAeq/LAFmax 与单段 10 s 处理一致（容差 ≤0.2 dB）。
- 静音：所有 dB 字段为 `None`，`artifact` 或 `valid` 正确，不产生 NaN/Inf。
- 1 小时流式处理内存峰值 ≤500 MB（`tracemalloc`/进程 RSS）。

---

### WP-06 校准与 TDMS 流式读取

**现状问题**

- `TDMSConverter` 取第一个 group/第一个 channel，忽略 `wf_increment`/`wf_start_time`/单位/灵敏度，缺失采样率默认 44100。
- 归一化 int/float 后当 Pa；没有校准。
- `TdmsFile.read()` 全量加载，且生成 5 GB 级临时 WAV。
- `librosa.load` 再整段加载。

**目标**

新增 `app/io/tdms.py` + `app/domain/calibration.py`：

```python
@dataclass(frozen=True)
class Calibration:
    name: str
    unit: str                   # "Pa" | "V" | "mV" | "counts"
    pa_per_unit: float
    offset_pa: float = 0.0
    offset_db: float = 0.0
    calibrated: bool = True

    def to_pa(self, raw: np.ndarray) -> np.ndarray:
        return (raw * self.pa_per_unit + self.offset_pa) * (10 ** (self.offset_db / 20))

    @classmethod
    def from_tdms(cls, props: dict) -> "Calibration":
        unit = str(props.get("unit_string") or props.get("NI_UnitDescription") or "Pa")
        sens_mv = props.get("Sensor_Sensitivity") or props.get("mic_sensitivity_mv_pa")
        gain_db = float(props.get("preamp_gain_db", 0.0))
        if unit.lower() == "pa":
            return cls("tdms", "Pa", 1.0, calibrated=True)
        if unit.lower() in ("v", "volt"):
            if not sens_mv:
                return cls("uncalibrated", "V", 1.0, calibrated=False)
            # V -> Pa: 1000 / (mV/Pa) / 10^(gain/20)
            return cls("tdms", "V", 1000.0 / float(sens_mv) / (10**(gain_db/20)),
                       calibrated=True)
        if unit.lower() == "mv":
            if not sens_mv:
                return cls("uncalibrated", "mV", 1.0, calibrated=False)
            return cls("tdms", "mV", 1.0 / float(sens_mv) / (10**(gain_db/20)),
                       calibrated=True)
        return cls("uncalibrated", unit, 1.0, calibrated=False)
```

```python
class TdmsChannelSource:
    def __init__(self, path: Path, group: str | None = None,
                 channel: str | None = None):
        self._tdms = TdmsFile.open(path)
        groups = self._tdms.groups()
        self.group = next((g for g in groups if g.name == group), groups[0])
        channels = self.group.channels()
        self.channel = next((c for c in channels if c.name == channel), channels[0])
        props = self.channel.properties
        self.fs = _read_sample_rate(props)          # wf_increment / SampleRate
        self.start_utc = _read_start_time(props, path)
        self.unit = str(props.get("unit_string") or props.get("NI_UnitDescription") or "Pa")
        self.total = len(self.channel)

    def iter_windows(self, window_s: float = 10.0):
        """一次产出 10 s 原始窗口；管线再切成 1 s 分析子块。"""
        step = max(1, int(round(self.fs * window_s)))
        for off in range(0, self.total, step):
            n = min(step, self.total - off)
            raw = self.channel.read_data(off, n, scaled=True)
            ts = self.start_utc + timedelta(seconds=off / self.fs)
            yield raw, ts, n / self.fs

    def close(self):
        self._tdms.close()
```

**关键点**

- `nptdms.TdmsFile.open()` 是懒加载；`channel.read_data(offset, length, scaled=True)` 是分块接口（nptdms 1.14 已验证存在）。
- 采样率优先级：`wf_increment` → `SampleRate` → `NI_Sample_Rate` → 报错。**绝不默认 44100**。
- 起始时间：`wf_start_time` → `wf_start_offset` → 文件 mtime；统一 UTC。
- 单位：`Pa` 直接使用；`V/mV/counts` 通过校准转 Pa；未知单位进入“未校准/相对”模式。
- 多通道：每个 `(group, channel)` 生成一个 job；session/DB 增加 `channel`。
- **不生成临时 WAV**，直接 `raw → calibration.to_pa → processor.process_block`。
- 文件完整性：处理前 `wait_stable`；如果文件仍被写，重试/延后；不支持“边写边读”时，要求 DAQ 分块写文件或原子重命名。
- **现场建议**：让采集软件按 1 分钟（或固定大小）滚动写 TDMS，关闭后由 watcher 处理；这比“一个 8 小时大文件边写边读”可靠得多。如果必须处理单个长文件，增加 `TdmsTailReader`：轮询文件大小、用 `read_data(offset)` 只读新增完整段、保留半段等待下次；不要在文件未关闭时假设可读。
- **WAV 输入**：如仍需支持 WAV，新增 `WavSource`（`soundfile.SoundFile.blocks()`），复用同一个 `StreamingNoiseProcessor`；不要再用 `librosa.load`。

**验收**

- 合成 TDMS：`wf_increment=1/48000`、`wf_start_time` 已知、两个通道、10 s；读出的 `fs`、`start_utc`、通道数正确。
- 只写 `wf_increment` 不写 `SampleRate`：采样率正确（当前主转换器会错误地 44100）。
- 1 kHz 94 dB 校准信号（Pa）→ LAeq=94；V 单位 + 灵敏度 50 mV/Pa → 正确换算。
- 无校准：`calibrated=False`，API/UI 显示“未校准”，不产生剂量结论。
- 1 小时 TDMS 流式处理内存不随时长增长。

---

### WP-07 文件监控、任务队列与幂等

**现状问题**

- 处理在 watchdog observer 线程内；`Observer.stop()/join()` 等待当前文件处理完，切换目录/停服务可挂起数小时。
- 只处理 `on_created`；不处理 `on_moved`/`on_closed`；`sleep(0.1)` 不足以保证文件写完。
- 无启动扫描、无去重；重启后重复处理或漏处理。

**目标**

新增 `app/services/watcher.py` + `app/services/pipeline.py`：

```python
class EnqueueHandler(FileSystemEventHandler):
    def __init__(self, enqueue): self.enqueue = enqueue
    def on_created(self, e):
        if not e.is_directory: self.enqueue(Path(e.src_path))
    def on_moved(self, e):
        if not e.is_directory: self.enqueue(Path(e.dest_path))
    def on_closed(self, e):
        if not e.is_directory: self.enqueue(Path(e.src_path))
```

```python
def wait_stable(path: Path, stable_s: float = 2.0,
                timeout_s: float = 300.0) -> bool:
    """等待文件大小/mtime 连续 stable_s 秒不变。"""
    deadline = time.monotonic() + timeout_s
    last = None
    last_change = time.monotonic()
    while time.monotonic() < deadline:
        try:
            st = path.stat()
        except FileNotFoundError:
            return False
        sig = (st.st_size, st.st_mtime_ns)
        now = time.monotonic()
        if sig != last:
            last = sig
            last_change = now
        elif now - last_change >= stable_s:
            return True
        time.sleep(0.5)
    return False
```

```python
class ProcessingService:
    def __init__(self, settings, db, queue_size=1000):
        self.settings = settings
        self.db = db
        self._q = queue.Queue(maxsize=queue_size)
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._scan_existing()
        self._observer = make_observer(self.settings.watch_dir)  # NAS -> PollingObserver
        self._observer.schedule(EnqueueHandler(self._enqueue), str(self.settings.watch_dir))
        self._observer.start()
        self._worker.start()

    def _enqueue(self, path):
        if path.suffix.lower() != ".tdms":
            return
        self._q.put(path, timeout=1)

    def _run(self):
        while not self._stop.is_set():
            try:
                path = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if wait_stable(path, self.settings.stable_seconds):
                    self._process(path)
            except Exception as e:
                logger.exception("job failed: %s", path)
                self.db.jobs.mark_failed(path, str(e))

    def stop(self, timeout=30):
        self._stop.set()
        self._observer.stop()
        self._observer.join(timeout=5)   # observer 只入队，不会等 DSP
        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            logger.error("worker still running after %ss", timeout)
```

**任务状态机**

```
pending -> running -> done
                  -> failed -> retry (attempts < 3) -> pending
                  -> quarantined
```

- `jobs` 表唯一约束 `(file_path, channel, size, mtime_ns)`；`claim` 用 `UPDATE ... WHERE status='pending'` 或 `INSERT OR IGNORE`。
- 启动扫描：遍历 watch_dir，按稳定文件/大小/时间插入 pending；`done` 的直接跳过。
- `on_moved` 覆盖 DAQ 的 `.tmp → .tdms` 原子写。
- 停止时只停 observer + worker；**不在 observer 线程里做 DSP**，所以 `join` 不会等长文件。
- NAS 用 `PollingObserver(timeout=5)`；本地用 `Observer`。
- 队列满时拒绝并告警，不能静默丢事件。

**验收**

- 慢速复制 1 GB TDMS：等稳定后再处理，不出现半截解析。
- `.tmp` 重命名为 `.tdms`：能被处理。
- 服务在文件处理中停止：≤30 s 退出；重启后该文件重新排队且不重复入库（job 状态 + 唯一键）。
- 同时放 10 个文件：串行处理，无重复，无丢失。

---

### WP-08 数据库 schema、迁移与批量写

**现状问题**

- EAV `ProcessingResult/ProcessingMetric/SpectrumData` 造成 N+1 查询；`TimeHistory` 100+ 列；45 个频段字段重复；`Base.metadata.create_all()` 无迁移；SQLite 无 WAL/`busy_timeout`；每秒 commit；NaN→NULL、Inf 破坏 JSON。
- `file_dir` 查询与入库不一致；本地/UTC 混用。

**目标 schema**

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 30000;
PRAGMA foreign_keys = ON;

CREATE TABLE schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE calibrations (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  unit TEXT NOT NULL,
  pa_per_unit REAL NOT NULL,
  offset_pa REAL DEFAULT 0,
  offset_db REAL DEFAULT 0,
  calibrated INTEGER NOT NULL,
  certificate TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  profile TEXT NOT NULL,
  device_id TEXT,
  operator TEXT,
  organization TEXT,
  calibration_id INTEGER REFERENCES calibrations(id),
  start_time_utc TEXT NOT NULL,
  end_time_utc TEXT,
  state TEXT NOT NULL,
  total_duration_s REAL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  file_path TEXT NOT NULL,
  channel TEXT NOT NULL,
  file_size INTEGER NOT NULL,
  file_mtime_ns INTEGER NOT NULL,
  session_id TEXT REFERENCES sessions(id),
  status TEXT NOT NULL,
  attempts INTEGER DEFAULT 0,
  last_error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  source_retained INTEGER DEFAULT 1,
  source_deleted_at TEXT,
  UNIQUE(file_path, channel, file_size, file_mtime_ns)
);

CREATE TABLE file_results (
  id INTEGER PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  session_id TEXT REFERENCES sessions(id),
  channel TEXT NOT NULL,
  start_time_utc TEXT,
  duration_s REAL,
  metrics_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE time_history (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  channel TEXT NOT NULL,
  timestamp_utc TEXT NOT NULL,
  duration_s REAL NOT NULL,

  laeq REAL, lceq REAL, lzeq REAL,
  laf REAL, las REAL, lcf REAL, lcs REAL,
  lafmax REAL, lasmax REAL, lcsmax REAL,
  lzpeak REAL, lcpeak REAL, lapeak REAL,

  dose_niosh REAL, dose_osha_pel REAL,
  dose_osha_hca REAL, dose_eu_iso REAL,

  overload INTEGER, underrange INTEGER, wearing INTEGER,
  valid INTEGER, artifact INTEGER,
  event_type INTEGER DEFAULT 0, event_severity INTEGER DEFAULT 0,

  kurtosis_total REAL, kurtosis_a REAL, kurtosis_c REAL,
  beta_kurtosis REAL,
  n_samples INTEGER, s1 REAL, s2 REAL, s3 REAL, s4 REAL,

  freq_spl_json TEXT, freq_moments_json TEXT
);

CREATE INDEX ix_th_session_time ON time_history(session_id, timestamp_utc);
CREATE INDEX ix_th_channel_time ON time_history(channel, timestamp_utc);

CREATE TABLE minute_aggregates (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  channel TEXT NOT NULL,
  start_time_utc TEXT NOT NULL,
  duration_s REAL NOT NULL,
  laeq REAL, lceq REAL, lzeq REAL,
  lafmax REAL, lasmax REAL, lcsmax REAL,
  lzpeak REAL, lcpeak REAL, lapeak REAL,
  dose_niosh REAL, dose_osha_pel REAL,
  dose_osha_hca REAL, dose_eu_iso REAL,
  overload_count INTEGER, underrange_count INTEGER, valid_seconds INTEGER,
  freq_spl_json TEXT, freq_moments_json TEXT,
  event_minor_count INTEGER, event_moderate_count INTEGER,
  event_severe_count INTEGER,
  UNIQUE(session_id, channel, start_time_utc)
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY,
  session_id TEXT REFERENCES sessions(id),
  channel TEXT,
  category TEXT NOT NULL DEFAULT 'acoustic',   -- acoustic | system
  event_type INTEGER NOT NULL,
  severity INTEGER NOT NULL,
  start_time_utc TEXT NOT NULL,
  end_time_utc TEXT,
  duration_s REAL,
  trigger_flags_json TEXT,
  laf_db REAL, las_db REAL,
  impulse_db REAL, rise_db REAL, background_delta_db REAL,
  lzpeak_db REAL, lcpeak_db REAL, lapeak_db REAL,
  audio_start_utc TEXT,
  audio_end_utc TEXT,
  audio_path TEXT,
  audio_sha256 TEXT,
  audio_bytes INTEGER,
  retention_state TEXT DEFAULT 'retained',      -- retained | pending_delete | deleted
  metadata_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX ix_events_session_time ON events(session_id, start_time_utc);
CREATE INDEX ix_events_category ON events(category, severity);

CREATE TABLE system_events (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL,
  severity INTEGER NOT NULL,
  message TEXT NOT NULL,
  context_json TEXT,
  start_utc TEXT NOT NULL,
  end_utc TEXT,
  resolved INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE retention_audit (
  id INTEGER PRIMARY KEY,
  target_path TEXT NOT NULL,
  action TEXT NOT NULL,                         -- preview | trash | delete | skip
  reason TEXT,
  mode TEXT NOT NULL,                           -- debug | production
  dry_run INTEGER NOT NULL,
  bytes INTEGER,
  created_at TEXT NOT NULL
);
```

**关键实现**

- **时间列统一类型**：所有 `*_utc` 列用同一个 `UtcDateTime` TypeDecorator（底层 TEXT，写/读都走同一格式），禁止在查询里把字符串直接和 DateTime 比较；这是现有 P0-6 的根因。

```python
from sqlalchemy.types import TypeDecorator, String
from datetime import datetime, timezone

class UtcDateTime(TypeDecorator):
    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime is not allowed")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return datetime.fromisoformat(value).astimezone(timezone.utc)
```

- `Database` 单例 engine，`connect_args={"timeout": 30}`，`pool_pre_ping=True`；用 `event.listens_for(engine, "connect")` 设置 PRAGMA。
- `session_scope()` contextmanager；一次处理事务内批量插入。
- `insert_time_history_batch(rows)`：每 60 行/每 60 秒 flush；失败重试一次，再落盘 JSONL 兜底。
- 所有时间字段 `timestamp_utc` 用带时区 UTC ISO；前端转换。
- `freq_spl_json`/`freq_moments_json` 用 `json.dumps(..., allow_nan=False)`；写前清洗 `None`。
- **旧库迁移**：Alembic 或一次性脚本；先备份，创建新表，复制旧 `time_history`（低频字段映射，freq 字段转 JSON），旧表保留只读视图；不直接 `create_all` 改旧表。
- 保留旧 API 兼容视图（可选）：`processing_result`/`processing_metrics` 只读视图，给旧前端过渡。

**验收**

- 旧库迁移后行数、时间范围、关键指标一致（抽样比对）。
- 并发读 + 单写：无 `database is locked`；WAL 文件存在。
- 1 小时文件按 10 s 入库约 360 行（若配置 1 s 则 3600 行），最后一行不丢；批量写耗时 <10 s。
- NaN/Inf 不进入 DB；JSON 可解析。

---

### WP-09 会话、DoseState 与聚合

**现状问题**

- `SessionManager` 同时管状态、时间历史列表、回调、汇总；`session_registry` 永不清理。
- `SessionSummary` 只在优雅停止时写入；崩溃后历史会话消失。
- 秒级 commit；分钟聚合只写日志。
- TWA/LEX 对零剂量返回 0 dB，误导。

**目标：移植 C++ `DoseState` 语义**

```python
@dataclass(slots=True)
class DoseState:
    cumulative_dose_frac: float = 0.0
    elapsed_hours: float = 0.0

def accumulate(state: DoseState, dose_frac: float, duration_s: float) -> DoseState:
    if duration_s <= 0:
        return state
    return DoseState(state.cumulative_dose_frac + dose_frac,
                     state.elapsed_hours + duration_s / 3600.0)

def dose_pct(state): return state.cumulative_dose_frac * 100.0

def dose_twa(state, standard):
    if state.elapsed_hours <= 0 or state.cumulative_dose_frac <= 0:
        return None      # UI 显示 “—”
    return DoseCalculator.calculate_twa(dose_pct(state), standard)

def dose_lex8h(state, standard):
    if state.cumulative_dose_frac <= 0:
        return None
    return DoseCalculator.calculate_lex(dose_pct(state), standard)
```

**命名约定（必须统一）**：

- 内部 `Metrics.dose_frac_*`：0–1 的分数，聚合时直接相加；
- DB/API 的 `dose_niosh`/`dose_osha_pel`/...：**0–100 的百分比**，写库时 `frac * 100`；
- Streamlit 显示 `dose_niosh` 时直接加 `%`，不要再乘 100；
- `DoseState.cumulative_dose_frac` 始终是分数，`dose_pct()` 才转百分比。

**SessionService**

- `start(profile, channel, calibration_id, operator, device)` → `sessions` 行 + 4 个 `DoseState`（内存）+ 状态。
- `on_metrics(m)`：累加 DoseState；每 10 s/每 60 行 checkpoint 到 `sessions`/`minute_aggregates`。
- `stop()`：先 flush 该 session/channel 的 `EventAudioCapture`（把最后一个事件的 post 音频落盘），再从 DB/内存聚合 `LAeq_T`、`LEX_8h`、`TWA`、峰度、事件计数，写 session 状态；**不依赖优雅停止才保存**。
- 启动时 `recover()`：把 `state=running` 的 session 标为 `interrupted`，并可从 time_history 重建摘要。
- `session_registry` 删除；会话由 DB 管理；内存只保留当前活动 session（最多 1 个/通道）。
- 自动会话：job 开始时若无活动 session，创建 `auto` session，绑定校准/操作员；分块文件按 `wf_start_time` 继续同一 session。

**聚合**

新增 `app/dsp/aggregation.py`，对应 C++ `aggregate_metrics`：

```python
def aggregate_segments(segments: Sequence[Metrics], channel: str) -> Metrics:
    total = sum(s.duration_s for s in segments)
    if total <= 0:
        raise ValueError("empty segments")

    def energy(vals, weights):
        p = [(10 ** (v / 10), w) for v, w in zip(vals, weights) if v is not None]
        if not p:
            return None
        return 10 * np.log10(sum(x for x, _ in p) / sum(w for _, w in p))

    out = Metrics(timestamp_utc=segments[0].timestamp_utc,
                  duration_s=total, channel=channel)
    out.laeq = energy([s.laeq for s in segments], [s.duration_s for s in segments])
    out.lceq = energy([s.lceq for s in segments], [s.duration_s for s in segments])
    out.lzeq = energy([s.lzeq for s in segments], [s.duration_s for s in segments])
    weights = [s.duration_s for s in segments]
    out.lafmax = max((s.lafmax for s in segments if s.lafmax is not None), default=None)
    out.lasmax = max((s.lasmax for s in segments if s.lasmax is not None), default=None)
    out.lcsmax = max((s.lcsmax for s in segments if s.lcsmax is not None), default=None)
    out.lzpeak = max((s.lzpeak for s in segments if s.lzpeak is not None), default=None)
    out.lcpeak = max((s.lcpeak for s in segments if s.lcpeak is not None), default=None)
    out.lapeak = max((s.lapeak for s in segments if s.lapeak is not None), default=None)

    # 瞬时时间计权值取最后一个子块
    out.laf, out.las = segments[-1].laf, segments[-1].las
    out.lcf, out.lcs = segments[-1].lcf, segments[-1].lcs

    # 频段 SPL 能量平均；频段 S1–S4 求和
    out.freq_spl = tuple(
        energy([s.freq_spl[i] for s in segments], weights) for i in range(9)
    )
    out.freq_moments = tuple(
        FreqBandMoments(
            n=sum(s.freq_moments[i].n for s in segments),
            s1=sum(s.freq_moments[i].s1 for s in segments),
            s2=sum(s.freq_moments[i].s2 for s in segments),
            s3=sum(s.freq_moments[i].s3 for s in segments),
            s4=sum(s.freq_moments[i].s4 for s in segments),
        ) for i in range(9)
    )

    # 剂量/整体原始矩直接求和；事件/QC 计数由上层 minute 聚合处理
    out.dose_frac_niosh = sum(s.dose_frac_niosh for s in segments)
    out.dose_frac_osha_pel = sum(s.dose_frac_osha_pel for s in segments)
    out.dose_frac_osha_hca = sum(s.dose_frac_osha_hca for s in segments)
    out.dose_frac_eu_iso = sum(s.dose_frac_eu_iso for s in segments)
    out.n_samples = sum(s.n_samples for s in segments)
    out.s1 = sum(s.s1 for s in segments)
    out.s2 = sum(s.s2 for s in segments)
    out.s3 = sum(s.s3 for s in segments)
    out.s4 = sum(s.s4 for s in segments)
    out.beta_kurtosis = kurtosis_from_moments(out.n_samples, out.s1, out.s2, out.s3, out.s4)
    out.kurtosis_total = out.beta_kurtosis
    out.valid = all(s.valid for s in segments)
    out.artifact = any(s.artifact for s in segments)
    return out
```

- `aggregate_segments` 用于 10 × 1 s → 10 s（默认入库行）；
- `aggregate_seconds` 用于 6 × 10 s → 1 min；
- 使用 `duration_s` 加权，而不是简单 `count`（C++ 用 count，Python 可更准确处理最后一块）。
- `valid_seconds`/`overload_count`/`underrange_count`/事件计数一起累加。
- 分钟聚合持久化到 `minute_aggregates`，不再只写日志。

**验收**

- 90 dB × 10 s NIOSH 剂量与解析值误差 ≤1%。
- 85 dB × 8 h → 100% ±1%；TWA=85；LEX=85。
- 零剂量：TWA/LEX 返回 `None`，UI 显示“—”，不是 0 dB。
- 崩溃/强杀后重启：session 可恢复，time_history 可查，摘要可重建。
- 60 × 1 s 聚合的 LAeq 与整段能量平均差 ≤0.1 dB。

---

### WP-10 四维事件检测

**现状问题**

- 主流程创建 `EventProcessor` 但从不调用 `process_audio_chunk`；事件永远为空。
- `_on_event_end` 不 append，`_finish_event_recording` 依赖 `self.events[-1]`，正常事件丢失。
- 单峰值阈值、无 C 计权、逐样本 Python 循环、`beta=3.0` 占位。

**目标：移植 C++ v3.3.3 四维算法**

```python
@dataclass(frozen=True)
class EventConfig:
    laf_minor_db: float = 85.0
    laf_moderate_db: float = 95.0
    laf_severe_db: float = 110.0
    impulse_minor_db: float = 6.0
    impulse_severe_db: float = 12.0
    rise_minor_db: float = 10.0
    rise_moderate_db: float = 15.0
    background_delta_db: float = 15.0
    background_tau_s: float = 300.0
    peak_threshold_db: float = 140.0
    underrange_db: float = 30.0
    history_s: float = 16.0
    history_step_s: float = 0.1

@dataclass(slots=True)
class EventResult:
    event_type: int = 0
    severity: int = 0
    laf_db: float | None = None
    las_db: float | None = None
    impulse_db: float = 0.0
    rise_db: float = 0.0
    background_delta_db: float = 0.0
    is_overload: bool = False


class EventDetector:
    def __init__(self, cfg: EventConfig):
        self.cfg = cfg
        maxlen = int(cfg.history_s / cfg.history_step_s) + 2
        self._hist: deque[tuple[float, float]] = deque(maxlen=maxlen)
        self._t = 0.0
        self._bg_power: float | None = None

    def reset(self):
        self._hist.clear()
        self._t = 0.0
        self._bg_power = None

    def _lookback(self, seconds: float) -> float | None:
        target = self._t - seconds
        best = None
        best_dist = float("inf")
        for t, laf in self._hist:
            d = abs(t - target)
            if d < best_dist:
                best, best_dist = laf, d
        return best

    def check(self, m: Metrics) -> EventResult:
        r = EventResult(laf_db=m.laf, las_db=m.las)
        laf, las = m.laf, m.las
        dt = m.duration_s if m.duration_s > 0 else 1.0

        if laf is not None and las is not None:
            r.impulse_db = laf - las

        if laf is not None and self._t > 0.5:
            past = self._lookback(0.5)
            if past is not None:
                r.rise_db = laf - past

        if m.laeq is not None:
            p = 10 ** (m.laeq / 10.0)
            if self._bg_power is None:
                self._bg_power = p
            else:
                alpha = float(np.exp(-dt / self.cfg.background_tau_s))
                self._bg_power = alpha * self._bg_power + (1 - alpha) * p
            if laf is not None and self._bg_power > 0:
                r.background_delta_db = laf - 10 * np.log10(self._bg_power)

        laf_minor = laf is not None and laf >= self.cfg.laf_minor_db
        laf_mod = laf is not None and laf >= self.cfg.laf_moderate_db
        laf_sev = laf is not None and laf >= self.cfg.laf_severe_db
        imp_minor = r.impulse_db >= self.cfg.impulse_minor_db
        imp_sev = r.impulse_db >= self.cfg.impulse_severe_db
        rise_minor = r.rise_db >= self.cfg.rise_minor_db
        rise_mod = r.rise_db >= self.cfg.rise_moderate_db
        bg_trig = r.background_delta_db >= self.cfg.background_delta_db

        if laf_sev or imp_sev:
            r.event_type = 3
        elif laf_mod or rise_mod:
            r.event_type = 2
        elif laf_minor or rise_minor or imp_minor or bg_trig:
            r.event_type = 1

        r.is_overload = m.lzpeak is not None and m.lzpeak >= self.cfg.peak_threshold_db
        if r.is_overload and r.event_type < 3:
            r.event_type = 3

        if r.event_type == 3:
            r.severity = 80
        elif r.event_type == 2:
            r.severity = 50
        elif r.event_type == 1:
            r.severity = 20

        if laf is not None:
            self._hist.append((self._t, laf))
        self._t += dt
        m.event_type = r.event_type
        m.event_severity = r.severity
        return r
```

- `history` 用 `deque[(t, laf)]`，`t` 为累计秒；`lookback(0.5)` 找最近记录。
- `background` 用功率域指数平均：`alpha=exp(-dt/tau)`。
- 每个 1 s 分析步调用一次（默认）；`check` 返回 `event_type/severity` 并写回 `Metrics`。
- 事件开始/结束：维护 `active_event`；当 `event_type>0` 开始，连续 N 个 NONE 结束；判定结果交给 **WP-15 `EventAudioCapture`**，由它保存 pre/post 音频并写 `events` 行；事件音频用绝对 Pa，不归一化。
- 阈值必须在校准后的 dB SPL 上；未校准模式禁用事件判定或只记录相对值。
- 事件计数进入 `minute_aggregates`。

**验收**

- 合成 LAF 阶跃/脉冲：D1/D2/D3/D4 分别触发；分级正确。
- 安静背景：无误报；单个冲击：SEVERE/MODERATE 符合阈值。
- 连续调用 vs 只调用部分块：前者结果稳定；后者应被测试标记为错误用法（状态契约）。
- 事件表有开始/结束/严重度；`/events` 不再空。
- 1 s 分析步与 0.5 s 分析步的 D3 差异在允许范围；文档说明分辨率（默认 1 s，D3 的 500 ms 回看按最近 1 s 近似）。

---

### WP-11 API 重构

**现状问题**

- `/latest_metrics` 无结果返回 `None` → 500；`file_dir` 过滤与入库不一致。
- `/all_metrics` 用字符串比较 DateTime → 当天查不到；本地/UTC 混用。
- HTTP 200 + `code:500`；无分页；同步 DB 阻塞事件循环；无认证；无版本。

**目标**

- `app/api/` 路由，`/api/v1` 前缀；保留旧端点作为过渡适配器（从新表查询，返回旧结构）。
- 统一时区：请求/响应 `datetime` 带时区；DB 存 UTC。
- 正确状态码：无数据 404 或 200+空数组（明确契约），参数错误 422，内部错误 500。
- 分页：`limit<=1000`、`offset`；返回 `total`。
- `latest` 按 `channel` + `session` 查询，不再用 `Path(watch).name`。
- 依赖注入：`request.app.state.service`；DB/CPU 用 `run_in_threadpool`。
- 认证：`X-API-Key` 依赖；admin 路径白名单；CORS allowlist。

**API 端点（与 Streamlit 页面一一对应）**

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health/live` | 进程存活 |
| GET | `/health/ready` | DB/目录/队列/磁盘/校准就绪 |
| GET | `/api/v1/channels` | 可用通道（从 TDMS/配置读取） |
| GET | `/api/v1/metrics/latest?channel=CH1` | 最新 10 s 窗口指标 |
| GET | `/api/v1/metrics/history?channel&start&end&limit&offset` | 历史 10 s 行，分页 |
| GET | `/api/v1/sessions` | 会话列表 |
| POST | `/api/v1/sessions` | 创建/启动会话 |
| POST | `/api/v1/sessions/{id}/stop` | 停止会话 |
| GET | `/api/v1/sessions/{id}/aggregates?level=minute` | 分钟聚合 |
| GET | `/api/v1/sessions/{id}/events` | 事件列表 |
| GET | `/api/v1/events/{id}/audio` | 事件音频（鉴权） |
| GET | `/api/v1/system-events?resolved=&limit=` | 系统异常列表 |
| GET | `/api/v1/retention/status` | 留存模式/候选/最近审计（admin） |
| POST | `/api/v1/retention/preview` | dry-run 预览（admin） |
| POST | `/api/v1/retention/run` | 执行留存（admin；debug 下强制 dry-run） |
| GET | `/api/v1/calibrations/current` | 当前校准状态 |

**`MetricOut` 至少包含**：`timestamp_utc`、`duration_s`（10 s）、`channel`、`laeq/lceq/lzeq`、`laf/las/lcf/lcs`、`lafmax/lasmax/lcsmax`、`lzpeak/lcpeak/lapeak`、`dose_niosh/dose_osha_pel/dose_osha_hca/dose_eu_iso`、`freq_spl`（9 键 dict，缺失为 `null`）、`event_type/event_severity`、`calibrated`/`level_unit`。Streamlit 只依赖这个契约，不直接读 DB/文件。

```python
@router.get("/metrics/latest", response_model=MetricOut)
def latest(channel: str = "CH1", svc=Depends(get_service)):
    row = svc.repo.latest_metric(channel)
    if row is None:
        raise HTTPException(404, "no metrics for channel")
    return MetricOut.from_row(row)
```

```python
@router.get("/sessions/{sid}/time-history", response_model=PageOut)
def time_history(sid: str, start: datetime | None = None,
                 end: datetime | None = None,
                 limit: int = Query(1000, le=10000),
                 offset: int = 0, svc=Depends(get_service)):
    ...
```

**验收**

- 空库：`/latest` 404 而不是 500。
- 绝对监控目录：能查到最新记录。
- `start_time=今天 00:00`：返回今天记录。
- 静音文件：无 500。
- 分页边界；时区转换正确（Asia/Shanghai）。
- 未带 API Key：401；错误 Key：401/403；admin 路径非白名单：403。

---

### WP-12 Streamlit 可视化重构（必须交付）

**现状问题**

- import 时 `tk.Tk()`；远程用户无法选择服务器目录；无桌面/服务环境可能失败。
- 侧边栏每次 rerun 触发 `/change_watch_directory`；自动刷新 `sleep + rerun` 阻塞；所有 tab 每次全量请求。
- `st.metric` 对 None 格式化崩溃；Windows 路径 `split("/")`；`end_date` 未使用；算术平均 LAeq；`width`/`use_container_width` 混用。
- 当前 UI 只展示部分指标，没有 LAF/LAS、事件分级、校准状态、10 s 窗口说明。

**目标：四个页面 + 统一 API 客户端 + 局部刷新**

| 页面 | 内容 | 关键交互 |
|---|---|---|
| 实时监控 | 当前 10 s LAeq/LCeq/LZeq、LAF/LAS、LZpeak/LCpeak/LAPeak、四标准剂量、1/3 oct 频谱、最近 1 h 趋势、事件标记 | 通道选择、10 s 自动刷新、暂停/继续 |
| 历史数据 | 按日期/通道/会话查询；10 s 记录表；声级/剂量/峰度趋势；频谱热力图；CSV 导出 | 日期范围、分页、降采样、下载 |
| 会话与事件 | 当前会话、启动/停止、分钟聚合、声学/系统事件列表、严重度、事件音频播放 | 会话/类别/严重度筛选、音频播放 |
| 系统状态 | `/health/live`、`/health/ready`、队列深度、监控目录、磁盘、校准状态、系统异常、留存模式/审计 | 手动刷新、诊断、留存预览（admin） |

**统一 API 客户端**

```python
# app/web/api_client.py
import requests
from dataclasses import dataclass

@dataclass
class ApiClient:
    base_url: str
    api_key: str | None = None
    timeout: float = 5.0

    def __post_init__(self):
        self._s = requests.Session()
        if self.api_key:
            self._s.headers["X-API-Key"] = self.api_key

    def _get(self, path, **params):
        r = self._s.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def channels(self): return self._get("/api/v1/channels")
    def latest(self, channel): return self._get("/api/v1/metrics/latest", channel=channel)
    def history(self, channel, start, end, limit=500, offset=0):
        return self._get("/api/v1/metrics/history", channel=channel,
                         start=start.isoformat(), end=end.isoformat(),
                         limit=limit, offset=offset)
    def sessions(self): return self._get("/api/v1/sessions")
    def session(self, sid): return self._get(f"/api/v1/sessions/{sid}")
    def minutes(self, sid, channel, limit=200):
        return self._get(f"/api/v1/sessions/{sid}/aggregates",
                         channel=channel, level="minute", limit=limit)
    def events(self, sid, channel, limit=100):
        return self._get(f"/api/v1/sessions/{sid}/events",
                         channel=channel, limit=limit)
    def system_events(self, limit=100):
        return self._get("/api/v1/system-events", limit=limit)
    def retention(self): return self._get("/api/v1/retention/status")
    def health(self): return self._get("/health/ready")
```

**页面骨架**

```python
# app/web/streamlit_app.py
import streamlit as st
import plotly.express as px
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.web.api_client import ApiClient

st.set_page_config(page_title="噪声信息工具箱", layout="wide")
tz = ZoneInfo("Asia/Shanghai")

def fmt(v, unit="dB", digits=1):
    return "—" if v is None else f"{v:.{digits}f} {unit}"

import numpy as np

def energy_mean(vals):
    vals = [v for v in vals if v is not None]
    return None if not vals else float(10 * np.log10(np.mean(10 ** (np.array(vals) / 10))))

import os
client = ApiClient(os.getenv("NIT_BACKEND_URL", "http://127.0.0.1:8000"),
                   os.getenv("NIT_API_KEY"))

page = st.sidebar.radio("页面", ["实时监控", "历史数据", "会话与事件", "系统状态"])

# 健康/通道：放在所有页面之前，失败则整页提示
try:
    health = client.health()
    channels = client.channels().get("items", ["CH1"])
except Exception as exc:
    st.error(f"后端不可用: {exc}")
    st.stop()
channel = st.sidebar.selectbox("通道", channels, key="channel")
if not health.get("calibrated", False):
    st.warning("当前为未校准/相对 dBFS 模式，剂量与 LEX 结论不可用于合规判定。")
try:
    retention = client.retention()
    if retention.get("mode") == "debug":
        st.info("调试模式：保留全部原始音频与事件音频，不执行删除。")
except Exception:
    retention = {}

@st.fragment(run_every=10)
def live_panel():
    m = client.latest(channel)
    cols = st.columns(6)
    cols[0].metric("LAeq (10 s)", fmt(m["laeq"]))
    cols[1].metric("LCeq (10 s)", fmt(m["lceq"]))
    cols[2].metric("LAF", fmt(m["laf"]))
    cols[3].metric("LAS", fmt(m["las"]))
    cols[4].metric("LZpeak", fmt(m["lzpeak"]))
    cols[5].metric("NIOSH 剂量", fmt(m["dose_niosh"], "%", 2))

    bands = m["freq_spl"]  # {"63Hz": ..., ...}
    fig = px.bar(x=list(bands), y=list(bands.values()),
                 labels={"x": "频段", "y": "SPL (dB)"}, title="1/3 oct 频谱")
    st.plotly_chart(fig, width="stretch")

    hist = client.history(channel, datetime.now(tz) - timedelta(hours=1),
                          datetime.now(tz), limit=500)
    if hist:
        fig2 = px.line(hist, x="timestamp", y=["laeq", "laf", "las"],
                       title="最近 1 小时声级（10 s 窗口）")
        st.plotly_chart(fig2, width="stretch")

if page == "实时监控":
    st.subheader(f"{channel} 实时监控")
    live_panel()

elif page == "历史数据":
    st.subheader(f"{channel} 历史数据")
    c1, c2 = st.columns(2)
    start = c1.date_input("开始日期", datetime.now(tz).date() - timedelta(days=7))
    end = c2.date_input("结束日期", datetime.now(tz).date())
    rows = client.history(channel,
                          datetime.combine(start, datetime.min.time(), tz),
                          datetime.combine(end, datetime.max.time(), tz),
                          limit=1000)
    if rows:
        import pandas as pd
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(tz)
        st.dataframe(df, width="stretch")
        st.plotly_chart(px.line(df, x="timestamp", y=["laeq", "lceq"],
                                title="历史声级"), width="stretch")
        st.download_button("导出 CSV", df.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"{channel}_history.csv", mime="text/csv")
    else:
        st.info("该时间范围没有数据")

elif page == "会话与事件":
    st.subheader("会话与事件")
    sessions = client.sessions().get("items", [])
    if sessions:
        sid = st.selectbox("会话", [s["id"] for s in sessions],
                           format_func=lambda x: x[:8])
        minutes = client.minutes(sid, channel).get("items", [])
        if minutes:
            st.plotly_chart(px.line(minutes, x="start_time_utc", y="laeq",
                                    title="分钟聚合 LAeq"), width="stretch")
        events = client.events(sid, channel).get("items", [])
        if events:
            st.dataframe(events, width="stretch")
            for e in events:
                st.caption(f"{e.get('category', 'acoustic')} / severity={e.get('severity')}")
                if e.get("audio_path"):
                    st.audio(f"{client.base_url}/api/v1/events/{e['id']}/audio")
    else:
        st.info("暂无会话")

elif page == "系统状态":
    st.subheader("系统状态")
    st.json(health)
    st.caption("队列/磁盘/最近 job 由 /health/ready 返回")
    st.markdown("**系统异常**")
    try:
        st.dataframe(client.system_events().get("items", []), width="stretch")
    except Exception as exc:
        st.warning(f"系统异常接口不可用: {exc}")
    if retention:
        st.json(retention)
```

**图表与交互要求**

- **频谱**：Plotly bar；频段顺序固定为 63→16k；缺失频段显示 `—`/不画，不把 `None` 当 0。
- **时间趋势**：10 s 窗口的 LAeq/LAF/LAS；剂量累计曲线；事件用 `add_vline`/marker 标注。
- **历史热力图**：用 `freq_spl` 的 9 列 + 时间，`px.imshow`；空数据给提示。
- **事件**：表格列 `event_type/severity/laf/las/impulse/rise/background`；`st.audio` 播放事件 WAV；无音频时禁用按钮。事件音频接口必须鉴权；浏览器无法带自定义 header 时，用后端签发的短期签名 URL，不能把 `audio_events` 目录直接静态暴露。
- **导出**：`st.download_button` 导出 CSV（UTF-8-SIG，Excel 兼容）。
- **校准/单位**：每个指标旁标注 `dB SPL` 或 `dBFS`；未校准隐藏剂量/LEX 或加删除线。
- **通道**：从 `/api/v1/channels` 获取，不能只写死 CH1/CH2。
- **时间**：API 返回 UTC；前端 `datetime.fromisoformat(...).astimezone(tz)` 显示。
- **空值**：所有 `st.metric`/表格走 `fmt()`/`pd.isna`，禁止 `f"{None:.2f}"`。
- **刷新**：实时面板用 `st.fragment(run_every=10)`；页面用 `st.sidebar.radio` 而非 `st.tabs`，避免每次 rerun 把所有页面/API 都执行；历史页面用 `st.cache_data(ttl=10)`。
- **目录**：删除 `tkinter`/`filedialog`；监控目录由管理员配置或后端 API 设置，普通用户不可改。
- **错误**：API 超时/401/404 显示 `st.error` + 重试按钮，不让整页崩溃。

**Streamlit 部署配置**

```powershell
python -m streamlit run app/web/streamlit_app.py `
  --server.address 127.0.0.1 `
  --server.port 8501 `
  --server.headless true `
  --browser.gatherUsageStats false
```

- 认证由反向代理/API Key 负责；Streamlit 不直接暴露公网。
- `st.secrets` 存 `backend_url`/`api_key`，不写进代码。
- 与后端同机时只绑 127.0.0.1；LAN 访问经 IIS/Nginx + TLS + 登录。
- 10 s 刷新与后端 10 s 入库窗口对齐；用户可手动刷新，不阻塞。

**验收**

- 无桌面/服务模式启动不报 Tk；无 `filedialog`。
- 修改目录不会周期性重启监控；后端 `/watch` 只被调用一次。
- 自动刷新不阻塞交互；10 个用户同时打开不导致请求风暴；非当前页面不发起数据请求。
- 静音/无数据页面正常显示“—”，无异常。
- 时间显示为本地时区，与 TDMS 起始时间一致。
- 1/3 oct、LAF/LAS、剂量、事件、校准状态均有可见展示；事件音频可播放。
- 历史 CSV 可被 Excel 正确打开（UTF-8-SIG）。
- 调试模式顶部有“不删除”提示；事件/系统异常分类、严重度、事件音频、留存状态可见。
- 生产留存预览按钮只对 admin 可见；普通用户不能执行删除。
- `streamlit.testing.v1.AppTest` 冒烟：四个页面可渲染，无异常。

---

### WP-13 安全、服务化、备份与监控

**目标**

- 默认绑定 `127.0.0.1`；LAN 访问经 IIS/Nginx/Caddy 反向代理 + TLS + 认证；API Key 注入。
- 移除匿名 `/change_watch_directory`；管理员路径白名单（`allowed_watch_roots`），`Path.resolve()` 后校验；拒绝系统目录/UNC 根。
- Windows 服务：NSSM 或 Task Scheduler；工作目录 `C:\NoiseToolkit`；`--workers 1`；失败重启；日志重定向。
- 数据目录 ACL；专用低权限账户；SQLite/日志/temp 本地；音频/NAS 用 UNC。
- 备份：SQLite backup API + 音频索引；每日；恢复演练。
- 留存：每日低峰运行 `RetentionService`；`retention_mode=debug` 时只预览不删除；生产先 dry-run 7 天，再开删除；所有动作写 `retention_audit`。
- 监控：`/health/live`、`/health/ready`（DB 可写、watch dir 可读、队列深度、磁盘剩余、最近 job 时间）；Windows 服务恢复 + 外部轮询告警。
- 日志：loguru 轮转；请求 ID；不记录完整请求体；敏感路径脱敏。
- Defender/索引器排除数据目录；长路径/UTF-8/NTP/电源按现有审计报告执行。
- **文档同步**：README/AGENTS 的功能声明必须与实现一致；未实现的 WebSocket、NTP/GPS、声校准自动识别等要么实现，要么删除对应描述/测试；`.devcontainer` 的启动文件改为实际入口。
- **可观测性**：每个 job 记录文件、通道、耗时、错误、重试次数；日志带 `job_id`/`session_id`；`/health/ready` 暴露队列深度、最近成功时间、磁盘剩余。

**验收**

- 端口扫描：8000 不对外；8501 仅授权网段；未认证 401。
- `/health/ready` 在 DB 只读/磁盘满/监控目录不可读时返回 503。
- 服务重启/断电后自动恢复；备份可恢复。
- 1 周 soak：内存平稳、日志轮转、DB 无锁。

---

### WP-14 测试体系、Windows CI 与验收

- 采用第 6 节的单元/集成/性能/Windows 测试矩阵；`pytest` 覆盖 DSP、校准、TDMS、pipeline、DB、API、Streamlit。
- GitHub Actions `windows-latest` + Python 3.11：`pip check`、`pytest -q`、10 分钟合成 TDMS 流式测试、`AppTest` 冒烟。
- 现场验收按第 9 节清单逐项签字；真实 TDMS + 94/114 dB 校准器 + 断电/重启/备份恢复必须实测。
- 性能门禁：1 h 文件处理 ≤1 h，峰值 RSS ≤500 MB；8 h 文件不随长度增长。
- 调试期留存门禁：事件音频完整、原始文件不删除；生产留存 dry-run 报告通过后再开删除。

---

### WP-15 异常监测、事件音频捕获与留存清理

**现状问题**

- `EventProcessor`/`RingBuffer` 存在但主流程从未喂数据，`events` 永远为空；没有“异常前后音频”的落盘。
- 原始 TDMS/WAV 处理完从不删除，磁盘会无限增长；也没有调试期/生产期的留存策略。
- 系统异常（解析失败、DB 写失败、队列积压、磁盘不足、无数据）没有统一记录/告警。

**目标**

1. **声学异常**：过载、LAF 阈值、脉冲、上升率、背景对比，分级 MINOR/MODERATE/SEVERE；
2. **系统异常**：文件、DB、队列、磁盘、无数据、校准缺失，写 `system_events`，不生成音频；
3. **事件音频**：保留事件前 `event_pre_s`（默认 5 s）+ 事件后 `event_post_s`（默认 10 s），单事件最长 60 s；只保留这一小段，不保留整段录音；
4. **调试期**：`retention_mode=debug`，原始音频与事件音频全部保留，删除服务只记录候选、不执行删除；
5. **生产期**：先 dry-run，再按宽限期删除“已成功处理且事件音频已校验”的源音频；事件音频按保留期保留；所有删除写审计。

#### 15.1 异常分类

| 类别 | code / 触发 | 处理 |
|---|---|---|
| 声学 | `overload`：LZpeak ≥140 dB | 事件 + 音频，SEVERE |
| 声学 | `laf_threshold`：LAF ≥85/95/110 dB | 事件 + 音频，按档分级 |
| 声学 | `impulse`：LAF−LAS ≥6/12 dB | 事件 + 音频 |
| 声学 | `onset`：LAF 上升 ≥10/15 dB（500 ms） | 事件 + 音频 |
| 声学 | `background`：LAF−5 min 背景 ≥15 dB | 事件 + 音频 |
| 系统 | `file_parse_error` / `db_write_error` / `queue_overflow` | 只写 `system_events`，不生成音频 |
| 系统 | `disk_low` / `no_data_timeout` / `calibration_missing` | 只写 `system_events`，健康检查告警 |

#### 15.2 事件音频缓冲 `EventAudioCapture`

```python
# app/services/event_audio.py
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import hashlib, os, uuid
import numpy as np
import soundfile as sf

@dataclass
class ActiveEvent:
    event_id: str
    start_utc: datetime
    event_end_utc: datetime
    pre: np.ndarray
    chunks: list[np.ndarray] = field(default_factory=list)
    post_left: int = 0
    severity: int = 0
    event_type: int = 0
    triggers: set[str] = field(default_factory=set)

@dataclass
class EventClip:
    event_id: str
    path: Path
    event_start_utc: datetime
    event_end_utc: datetime
    audio_start_utc: datetime
    audio_end_utc: datetime
    pre_s: float
    post_s: float
    severity: int
    event_type: int
    triggers: list[str]
    sha256: str
    sample_rate: int

class EventAudioCapture:
    """每个 (session, channel) 一个；跨 10 s 窗口/文件保持，仅在会话结束 flush。"""
    def __init__(self, fs: int, out_dir: Path, pre_s=5.0, post_s=10.0,
                 max_s=60.0, min_gap_s=2.0, subtype="FLOAT"):
        self.fs, self.out_dir = fs, out_dir
        self.pre_n = max(1, int(fs * pre_s))
        self.post_n = max(0, int(fs * post_s))
        self.max_n = int(fs * max_s)
        self.min_gap = timedelta(seconds=min_gap_s)
        self.subtype = subtype
        self._ring = np.zeros(self.pre_n, dtype=np.float32)
        self._ring_len = 0
        self._active: ActiveEvent | None = None
        self._last_end: datetime | None = None

    def _ring_push(self, chunk: np.ndarray):
        if chunk.size >= self.pre_n:
            self._ring[:] = chunk[-self.pre_n:]
            self._ring_len = self.pre_n
            return
        self._ring = np.roll(self._ring, -chunk.size)
        self._ring[-chunk.size:] = chunk
        self._ring_len = min(self.pre_n, self._ring_len + chunk.size)

    def _pre_snapshot(self) -> np.ndarray:
        return self._ring[-self._ring_len:].copy() if self._ring_len else np.empty(0, np.float32)

    @staticmethod
    def _triggers(r) -> set[str]:
        out = set()
        for name, flag in (("laf", r.trigger_laf_threshold),
                           ("impulse", r.trigger_impulse),
                           ("onset", r.trigger_onset),
                           ("background", r.trigger_background)):
            if flag:
                out.add(name)
        if r.is_overload:
            out.add("overload")
        return out

    def push(self, chunk: np.ndarray, ts: datetime, result) -> EventClip | None:
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if chunk.size == 0:
            return None

        if self._active is not None:
            ev = self._active
            self._ring_push(chunk)          # 为“下一个事件”保留最近 pre
            ev.chunks.append(chunk.copy())
            total = ev.pre.size + sum(c.size for c in ev.chunks)
            if result.event_type > 0 or result.is_overload:
                ev.post_left = self.post_n
                ev.event_end_utc = ts + timedelta(seconds=chunk.size / self.fs)
                ev.severity = max(ev.severity, int(result.severity))
                ev.event_type = max(ev.event_type, int(result.event_type))
                ev.triggers |= self._triggers(result)
            else:
                ev.post_left -= chunk.size
            if ev.post_left <= 0 or total >= self.max_n:
                return self._finalize()
            return None

        # idle：先判定，再决定当前 chunk 进 ring 还是事件
        if result.event_type > 0 or result.is_overload:
            if self._last_end is not None and ts - self._last_end < self.min_gap:
                self._ring_push(chunk)
                return None
            self._active = ActiveEvent(
                event_id=str(uuid.uuid4()),
                start_utc=ts,
                event_end_utc=ts + timedelta(seconds=chunk.size / self.fs),
                pre=self._pre_snapshot(),
                chunks=[chunk.copy()],
                post_left=self.post_n,
                severity=int(result.severity),
                event_type=int(result.event_type),
                triggers=self._triggers(result),
            )
            self._ring_push(chunk)             # 下一事件的 pre 仍连续
            return None

        self._ring_push(chunk)
        return None

    def _finalize(self) -> EventClip:
        ev = self._active
        self._active = None
        assert ev is not None
        data = np.concatenate([ev.pre] + ev.chunks) if ev.chunks else ev.pre
        data = data[-self.max_n:].astype(np.float32, copy=False)
        pre_s = ev.pre.size / self.fs
        path = self.out_dir / f"{ev.start_utc:%Y%m%d_%H%M%S}_{ev.event_id[:8]}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.wav")
        sf.write(tmp, data, self.fs, subtype=self.subtype)
        os.replace(tmp, path)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        audio_start = ev.start_utc - timedelta(seconds=pre_s)
        audio_end = audio_start + timedelta(seconds=data.size / self.fs)
        event_samples = max(0, int(round(
            (ev.event_end_utc - ev.start_utc).total_seconds() * self.fs)))
        post_s = max(0.0, data.size / self.fs - pre_s - event_samples / self.fs)
        self._last_end = audio_end
        return EventClip(
            event_id=ev.event_id, path=path,
            event_start_utc=ev.start_utc, event_end_utc=ev.event_end_utc,
            audio_start_utc=audio_start, audio_end_utc=audio_end,
            pre_s=pre_s, post_s=post_s,
            severity=ev.severity, event_type=ev.event_type,
            triggers=sorted(ev.triggers), sha256=sha, sample_rate=self.fs,
        )

    def flush(self) -> EventClip | None:
        return self._finalize() if self._active is not None else None
```

**接入点**：在 WP-05 的 `process_file()` 里，每个 1 s 子块调用 `detector.check(seg)` 后：

```python
clip = capture.push(chunk_pa, ts, result)
if clip is not None:
    repo.insert_event(session_id, channel, clip, result)
```

- `capture` 由 `ProcessingService` 按 `(session_id, channel)` 持有，跨 10 s 窗口和分块文件保持；
- 若时间戳间隔 > 2 s（文件断档/乱序），调用 `capture.flush()` 并重建，避免把不连续音频拼在一起；
- 会话停止/服务停止时 `flush()`，最后一个事件的 post 窗口不会丢；
- 调试期仍写事件音频，但不删除任何源文件。

#### 15.3 事件音频格式与 DB 记录

- 文件：`audio_events/<session_id>/<channel>/<timestamp>_<event_id>.wav`；
- 格式：默认 `FLOAT`（保留校准后的 Pa 绝对幅度，不归一化）；可选 `PCM_16` 节省空间，但必须记录 `level_unit`/`calibrated`；
- DB `events` 增加/使用字段（完整 DDL 见 WP-08）：

```text
category TEXT NOT NULL DEFAULT 'acoustic',       -- acoustic | system
trigger_flags_json TEXT,                          -- ["laf","impulse",...]
audio_start_utc TEXT,
audio_end_utc TEXT,
audio_path TEXT,
audio_sha256 TEXT,
audio_bytes INTEGER,
retention_state TEXT DEFAULT 'retained',         -- retained | pending_delete | deleted
metadata_json TEXT
```

- `audio_start_utc = event_start - pre_s`（按实际 pre 样本数）；
- `audio_end_utc = audio_start + 实际样本数 / fs`；
- 事件必须同时有 `events` 行和 `audio_sha256`，才算“已校验”，后续才允许删除源文件。

#### 15.4 系统异常 `AnomalyService`

```python
# app/services/anomalies.py
from datetime import datetime, timedelta, timezone
import json

class AnomalyService:
    def __init__(self, db, dedupe_s: int = 300):
        self.db = db
        self.dedupe_s = dedupe_s
        self._last: dict[str, datetime] = {}

    def record(self, code: str, severity: int, message: str,
               context: dict | None = None) -> None:
        now = datetime.now(timezone.utc)
        if code in self._last and now - self._last[code] < timedelta(seconds=self.dedupe_s):
            return                         # 同 code 去重，避免刷屏
        self._last[code] = now
        with self.db.session_scope() as s:
            s.add(SystemEvent(
                code=code, severity=severity, message=message,
                context_json=json.dumps(context or {}, ensure_ascii=False),
                start_utc=now, created_at=now,
            ))
        logger.warning("system anomaly {}: {}", code, message)
```

- 在 pipeline 的 `except`、DB 写失败、队列满、磁盘检查、校准缺失、无数据超时调用；
- `system_events` 表字段：`id, code, severity, message, context_json, start_utc, end_utc, resolved, created_at`；
- 不生成音频；UI 系统状态页展示；`/health/ready` 可返回最近系统异常；
- 系统异常不能阻断声学事件落盘；两者独立。

#### 15.5 留存与清理 `RetentionService`

**调试模式（默认）**

- `retention_mode=debug`：**不做任何文件删除**；
- 只计算“若上线会删除哪些文件”，写 debug 日志/审计（`dry_run` 语义）；
- 原始 TDMS/WAV、事件音频、temp 全部保留；
- UI 顶部显示“调试模式：保留全部原始音频”。

**生产模式**

- 前置条件（全部满足才删除源文件）：
  1. `jobs.status='done'`，`file_results` 已提交；
  2. 若该 job 产生了事件：事件音频已落盘、`sha256` 校验通过；无事件则跳过此项；
  3. 文件年龄 ≥ `delete_source_after_days`（默认 7 天）；
  4. 当前没有 active event / 没有未 flush 的 capture；
  5. 文件未被修改（size/mtime 与 job 记录一致）；
  6. 不是失败/隔离/重试中的 job。
- 动作顺序：先 `move` 到 `trash/YYYYMMDD/`，写 `retention_audit`，宽限期后再物理删除；不要直接 `os.remove` 源文件。
- 事件音频保留 `event_retention_days`（默认 365 天）；SEVERE 可配置更长；到期删除也写审计。
- 若确实要“处理完立即删除源音频”，把 `delete_source_after_days` 设为 0；仍必须满足 6 个条件、先 dry-run、写审计，建议不要在调试期使用。
- `retention_dry_run=True` 时只生成报告，不移动/不删除；上线前先跑 7 天 dry-run。
- Windows 注意：先确保 TDMS 读取器已 `close()`；`os.replace` 失败（Defender/索引器占用）要重试并记录，不能强删。

```python
class RetentionService:
    def _eligible(self, job) -> tuple[bool, str]:
        if job.status != "done":
            return False, "job_not_done"
        if self.repo.event_count(job.id) > 0 and \
                not self.repo.has_verified_event_audio(job.id):
            return False, "event_audio_missing_or_bad_sha"
        if self.repo.has_active_event(job.session_id, job.channel):
            return False, "active_event"
        path = Path(job.file_path)
        try:
            st = path.stat()
        except FileNotFoundError:
            return False, "file_missing"
        if (st.st_size, st.st_mtime_ns) != (job.file_size, job.file_mtime_ns):
            return False, "file_changed"
        age_days = (datetime.now(timezone.utc) - job.finished_at).total_seconds() / 86400
        if age_days < self.settings.delete_source_after_days:
            return False, "grace_period"
        return True, "eligible"

    def run(self, dry_run: bool | None = None) -> dict:
        if self.settings.retention_mode == "debug":
            candidates = self._candidates()          # 只统计，不删除
            self._audit(candidates, action="preview", dry_run=True)
            return {"mode": "debug", "deleted": 0, "candidates": len(candidates)}
        dry = self.settings.retention_dry_run if dry_run is None else dry_run
        done = 0
        for job in self._candidates():
            ok, reason = self._eligible(job)
            if not ok:
                self._audit_one(job.file_path, "skip", reason, dry, 0)
                continue
            if dry:
                self._audit_one(job.file_path, "preview", "eligible", True, job.file_size)
                continue
            self._move_to_trash(job.file_path)       # 先移动，宽限期后再物理删除
            self.repo.mark_source_deleted(job.id)
            self._audit_one(job.file_path, "trash", "eligible", False, job.file_size)
            done += 1
        return {"mode": "production", "deleted": done, "dry_run": dry}
```

#### 15.6 配置与调度

| 变量 | 默认 | 说明 |
|---|---|---|
| `NIT_RETENTION_MODE` | `debug` | 调试期绝不删除；上线改 `production` |
| `NIT_EVENT_PRE_S` | `5.0` | 事件前音频 |
| `NIT_EVENT_POST_S` | `10.0` | 事件后音频 |
| `NIT_EVENT_MAX_S` | `60.0` | 单事件最长 |
| `NIT_EVENT_MIN_GAP_S` | `2.0` | 防重复 |
| `NIT_DELETE_SOURCE_AFTER_DAYS` | `7.0` | 生产宽限期 |
| `NIT_EVENT_RETENTION_DAYS` | `365.0` | 事件音频保留 |
| `NIT_RETENTION_DRY_RUN` | `true` | 上线前先预览 |

调度：每日低峰运行 `RetentionService.run()`；生产首次上线建议 `dry_run=true` 跑 7 天，核对候选/审计后再设 `false`。调试阶段**不要**启动删除调度。

#### 15.7 验收

- 合成 1 个冲击/阶跃：事件表有记录，WAV 含前 5 s + 后 10 s（边界文件可短）；音频不归一化（峰值/单位可追溯）。
- 事件连续触发：不会无限录制；超过 60 s 强制切分；相邻事件有 2 s 去抖。
- 文件开始/结束处事件：pre/post 自动截断，不越界、不崩溃。
- 跨 10 s 窗口/分块文件：事件音频连续；时间戳与 `wf_start_time` 对齐。
- 调试模式：处理/删库/重启后原始文件仍在；审计只有 preview。
- 生产 dry-run：只报告、不移动；生产实跑：只删满足 6 个条件的源文件；失败/隔离/事件未校验的文件不删；所有动作有审计。
- 系统异常：文件解析失败/DB 写失败/磁盘低/无数据能进 `system_events`，UI/健康检查可见。
- Windows 文件被 Defender 占用时删除失败：重试+记录，不损坏源文件。

---

## 5. 数据库迁移与兼容策略

### 5.1 迁移步骤

1. 停服务；用 SQLite backup API 备份 `noise_info.db`。
2. 创建新表（`schema_version=2`）；保留旧表。
3. 迁移 `sessions`/`time_history`：
   - 旧 `TimeHistory` 的核心字段直接映射；
   - `freq_63hz_spl...` → `freq_spl_json`；
   - `freq_*_n/s1..s4` → `freq_moments_json`；
   - 旧 `ProcessingResult/Metric/SpectrumData` 聚合为 `file_results.metrics_json`（或保留只读视图）。
4. 迁移 `SessionSummary` → `sessions` + `minute_aggregates`；缺失的 session 从 time_history 重建。
5. 校验：行数、时间范围、抽样 LAeq/剂量/频段。
6. 新建 `system_events`/`retention_audit`（空表即可）；`retention_mode=debug` 不触发删除。
7. 切换 API/前端；旧表只读保留一个版本周期。

### 5.2 兼容

- 旧端点 `/latest_metrics`、`/all_metrics` 保留为适配器，内部查新表，返回旧 JSON 结构；标记 deprecated。
- 旧 Streamlit 可先切到适配器，再升级到 v1。
- 数据版本：`sessions.calibration_id`、`file_results.metrics_version`、`filter_design_version`；不同版本不混入同一统计。
- 回滚：保留旧表/旧 DB 备份；`PROCESSOR_IMPL=legacy` 开关；新表不删除旧数据。

---

## 6. 测试与验收计划

### 6.1 单元测试（pytest）

| 测试 | 用例 | 通过标准 |
|---|---|---|
| `test_pure_tone` | 1 kHz 94 dB | LAeq/LCeq/LZeq 94 ±0.5 |
| `test_class1` | 33 个 IEC 频点 | A/C 最大误差 ≤0.7 dB（实用频段） |
| `test_bands` | 1 kHz 94 dB | 1 kHz 频段 94 ±1；其余 ≤ −15 dB；9 频段能量和 vs LZeq ≤1 dB |
| `test_sample_rates` | 44.1/48/32/16 kHz | 不崩溃；16k 高频段 `None`；LAeq 一致 |
| `test_block_state` | 20 Hz，10/50/100/1000 ms、1 s、10 s | 连续状态能量平均差 ≤0.5 dB；每块新建 processor 明显偏差（负向） |
| `test_reset` | reset 前后 | 状态清零；新测量不继承旧能量 |
| `test_time_weighting` | LAF/LAS 阶跃 | 时间常数/稳态符合 α 公式 |
| `test_silence_nan` | 全零/NaN/Inf | 返回 `None`/`artifact`，无 NaN/Inf/500 |
| `test_dose` | 85/90 dB 解析值 | 剂量误差 ≤1%；TWA/LEX 正确；零剂量 `None` |
| `test_kurtosis` | 正弦/噪声 | 与直接 S1–S4 公式一致；常量返回 `None` |
| `test_event` | D1–D4 合成信号 | 分级/严重度正确；无背景误报 |
| `test_aggregation` | 秒/分钟 | 能量平均、峰值、S1–S4、事件计数正确 |
| `test_tdms` | 合成双通道/仅 wf_increment | 采样率/起始时间/通道正确 |
| `test_calibration` | Pa/V/mV/未校准 | 换算正确；未校准标记 |
| `test_pipeline` | 慢写/重命名/重启 | 不重复、不丢失、停止 ≤30 s |
| `test_db` | 批量/并发/迁移 | 无锁；行数正确；JSON 可解析 |
| `test_api` | 空/绝对目录/今天/静音/分页/鉴权 | 状态码/时区/数据正确 |
| `test_streamlit_app` | `streamlit.testing.v1.AppTest` 四个页面 | 可渲染、无 Tk、无 sleep、无异常 |
| `test_ui_format` | None/NaN/Windows 路径/时区 | 显示“—”、路径正确、时间本地化 |
| `test_event_audio` | 冲击/阶跃/边界 | 前 5 s + 后 10 s、无归一化、sha256/DB 行完整 |
| `test_retention_debug` | 处理/重启/删库 | 原始与事件音频零删除；只有 preview 审计 |
| `test_retention_production` | dry-run/宽限期/失败 job | 只删满足条件源文件；事件音频保留；审计完整 |
| `test_system_anomaly` | 解析/DB/队列/磁盘 | `system_events` 有记录；UI/健康检查可见 |

**示例：纯音与状态持久性（可直接落地）**

```python
import numpy as np
from datetime import datetime, timezone

def tone(fs=48000, freq=1000.0, spl=94.0, dur=1.0, phase=0.0):
    n = int(fs * dur)
    t = np.arange(n) / fs
    rms = 20e-6 * 10 ** (spl / 20.0)
    return rms * np.sqrt(2.0) * np.sin(2 * np.pi * freq * t + phase)

def test_pure_tone_1k():
    p = StreamingNoiseProcessor(48000, load_weighting(48000),
                                load_bands(48000), Calibration.pa(),
                                QcThresholds())
    m = p.process_block(tone(), datetime.now(timezone.utc), 1.0)
    assert abs(m.laeq - 94.0) <= 0.5
    assert abs(m.lceq - 94.0) <= 0.5
    assert abs(m.freq_spl[4] - 94.0) <= 1.0

def test_state_persistence_20hz():
    fs, freq, total = 48000, 20.0, 12.0
    x = tone(fs, freq, 94.0, total)
    results = []
    for block_s in (0.01, 0.05, 0.1, 1.0, 10.0):
        p = StreamingNoiseProcessor(fs, load_weighting(fs), load_bands(fs),
                                    Calibration.pa(), QcThresholds())
        step = int(fs * block_s)
        vals = []
        for off in range(0, len(x) - step + 1, step):
            m = p.process_block(x[off:off + step],
                                datetime.now(timezone.utc), block_s)
            vals.append(m.laeq)
        # 跳过前 1 s 的滤波器建立时间，再能量平均
        skip = int(1.0 / block_s)
        vals = [v for v in vals[skip:] if v is not None]
        results.append(10 * np.log10(np.mean(10 ** (np.array(vals) / 10))))
    assert max(results) - min(results) <= 0.5
```


- 合成 1 h/8 h TDMS（分块写），流式处理，记录 RSS、耗时、DB 行数。
- 目标：1 h 峰值 RSS ≤500 MB；8 h ≤500 MB；处理速度 ≥1× 实时。
- 1 h 文件按 10 s 入库约 360 行 ±1；最后一块不丢。
- 断电模拟：SIGKILL/服务停止，重启后 job 恢复、无重复。
- Windows 10/11 + Windows Server 2019/2022 各跑一次。
- 真实 TDMS + 94/114 dB 校准器：LAeq 偏差/不确定度记录；A/C 频响抽查。
- 异常音频：人工敲击/阶跃/过载，验证事件前 5 s + 后 10 s、跨 10 s 窗口/分块文件连续、DB sha256 一致。
- 留存：调试模式跑 24 h 确认零删除；生产 dry-run 7 天报告；生产实删只影响合格源文件。

### 6.3 CI

- GitHub Actions `windows-latest` + Python 3.11：
  - 安装锁文件；
  - `pytest -q`；
  - 一个 10 分钟合成 TDMS 流式测试；
  - `pip check`；
  - 无 GUI/Tk。
- Linux CI 用于快速单元测试；Windows 用于最终门禁。
- 覆盖率门槛：DSP 核心 ≥85%，API ≥70%；关键公式分支必须覆盖。

---

## 7. 分阶段执行计划

### Phase 0：可运行基线（3–5 天，可选但推荐）

目标：在不改变算法的前提下，让现场先能稳定跑起来并暴露真实问题。

- WP-01 配置/目录/启动；
- WP-02 临时依赖仅用于 Phase 0 演示（`numpy 1.26 + scipy 1.13 + acoustics 0.2.6`）；**Phase 1 启动即替换为 SciPy 标准滤波，acoustics 不得进入最终交付**；也可以跳过 Phase 0 直接开始 WP-04/05；
- 修 P0-4 `round(ndarray)`；
- 修 P0-5/6 查询；
- 加 `None/NaN/Inf` 清洗；
- 移除 `tk.Tk()`；
- 文件处理移出 observer 线程（最小改动也可先做队列）；
- SQLite WAL + 批量写。

**门禁**：全新 Windows 能启动；48 kHz 文件能产出非空 SPL；静音不 500；停止服务 ≤30 s。

### Phase 1：SciPy DSP 核心（2–3 周）

- WP-03/04/05/06；
- 新 DSP 与旧 DSP 双跑（shadow）：同一文件分别算，记录差异；
- 测试 Class 1/频段/长文件/状态保持。

**门禁**：1 kHz 94 dB ±0.5；频段/能量和通过；1 h 内存 ≤500 MB；与 C++ 参考向量差异在容差内。

### Phase 2：数据与服务（2 周）

- WP-07/08/09/10/15；
- jobs/sessions/time_history/minute/events/system_events/retention_audit 新表；
- 迁移脚本/备份；
- 事件四维 + 事件音频 pre/post + 调试期不删除；
- 恢复/幂等/停止测试；
- 生产留存 dry-run 报告。

**门禁**：重启不重复；事件入库且音频完整；分钟聚合可查；旧库迁移通过；调试模式零删除。

### Phase 3：API/UI/安全（1–2 周）

- WP-11/12/13；
- v1 API + 旧适配器；
- 去 Tk；fragment；校准提示；分页；事件/系统异常/留存状态展示；
- 认证/TLS/服务化/健康检查/留存调度。

**门禁**：API 契约测试通过；无 500；LAN 认证；服务自动恢复。

### Phase 4：现场验收（1 周）

- Windows 全新 VM + 真实 TDMS + 校准器；
- 24 h/7 天 soak；
- 断电/重启/备份恢复；
- 异常音频：冲击/阶跃/边界/跨文件，前 5 s + 后 10 s 完整；
- 调试模式 7 天零删除；生产 dry-run 7 天报告；实删只影响合格文件；
- 输出验收报告和运维手册。

---

## 8. 风险与回滚

| 风险 | 缓解 |
|---|---|
| DSP 重写数值偏差 | 新旧双跑；C++/解析参考向量；先 shadow 后切换 |
| 去掉 acoustics/librosa 影响历史结果 | 保留旧算法开关；metrics_version/calibration_id；旧数据只读 |
| 校准数据缺失 | 未校准模式；明确 dBFS；禁用剂量结论；先补校准流程 |
| 长文件/连续写入 | 分块 TDMS 文件；稳定检测；可选 tail 模式；限制单文件大小 |
| 迁移破坏旧数据 | 备份；新表并存；只读视图；抽样校验；回滚脚本 |
| Windows 依赖/离线安装 | wheelhouse；固定 Python 3.11；`pip check`；无编译器依赖 |
| 误删源音频 | 默认 debug 零删除；生产先 dry-run；6 个条件、trash 宽限期、审计、失败/事件未校验不删 |
| 事件音频漏存/截断 | 会话级 capture 跨文件保持；会话停止 flush；边界/跨窗口集成测试；sha256 校验 |
| 服务停止超时 | observer 只入队；worker 单线程；stop timeout；持久化 job 状态 |
| 多用户并发 | 单 worker + SQLite 单写；如多用户/多设备，升级 PostgreSQL 并加任务队列 |

---

## 9. 验收清单（现场部署前逐项签字）

**数据正确性**
- [ ] 1 kHz/94 dB：LAeq/LCeq/LZeq 94 ±0.5 dB。
- [ ] A/C 计权 IEC 频点最大误差 ≤0.7 dB（或明确 Class 2 ≤1.5）。
- [ ] 1 kHz 频段 94 ±1 dB；其余 ≤ −15 dB；9 频段能量和 ≤1 dB。
- [ ] 20/25 Hz 在 10/50/100/1000 ms 分块下与连续状态一致（≤0.5 dB）。
- [ ] 静音/NaN/Inf 无 500、无 NaN 入库。
- [ ] 94/114 dB 校准器验证；未校准时 UI 标注。

**性能与可靠性**
- [ ] 1 h/8 h 文件内存 ≤500 MB；处理速度 ≥1× 实时。
- [ ] 停止服务 ≤30 s；重启不重复、不丢失。
- [ ] `.tmp→.tdms`、慢写、NAS/UNC、中文路径通过。
- [ ] SQLite WAL/批量写/迁移/备份恢复通过。

**功能**
- [ ] TDMS 多通道、`wf_increment`/`wf_start_time`、校准单位正确。
- [ ] LAF/LAS/LCF/LCS/LAPeak/事件分级入库并展示。
- [ ] 分钟聚合/会话摘要可查；崩溃后可恢复。
- [ ] API v1 分页/时区/错误码/鉴权通过。
- [ ] Streamlit 无 Tk、无 sleep、无重复重启监控；实时/历史/会话/事件/校准四个页面均有可见展示。
- [ ] 10 s 窗口的 LAeq/LAF/LAS、1/3 oct、剂量、事件标记、历史 CSV 导出、事件音频播放均可用。

**异常与留存**
- [ ] 声学异常（过载/LAF/脉冲/上升/背景）能触发事件并入库。
- [ ] 事件音频覆盖前 5 s + 后 10 s（可配）；跨 10 s 窗口/分块文件连续；sha256/DB 一致。
- [ ] 系统异常（文件/DB/队列/磁盘/无数据/校准）进入 `system_events`，UI/健康检查可见。
- [ ] `retention_mode=debug` 下原始音频/事件音频零删除，审计只有 preview。
- [ ] 生产 dry-run 7 天报告；实删只删除满足 6 个条件的源文件；事件音频保留期/审计正确。
- [ ] 文件被 Defender 占用时删除失败可重试/记录，不损坏源文件。

**Windows**
- [ ] 全新 Windows + 离线 wheelhouse 安装成功，`pip check`。
- [ ] 服务化（NSSM/Task Scheduler）自动启动/重启。
- [ ] 防火墙/反向代理/认证/TLS。
- [ ] 本地 DB/日志/temp；NAS 只放音频；Defender 排除；长路径/UTF-8/NTP/电源。
- [ ] 7 天 soak 无内存增长/无锁/无丢数。

---

## 10. 附录：文件级改造映射

| 当前文件 | 处理 | 目标 |
|---|---|---|
| `main.py` | 拆分 | `app/api/main.py` + routers；全局 `task_manager` 移除 |
| `config.py` | 重写 | `app/config.py`（pydantic-settings） |
| `app/core/audio_processor.py` | 删除/替换 | `app/dsp/processor.py` + `app/dsp/weighting.py` |
| `app/core/time_history_processor.py` | 删除/替换 | `app/dsp/processor.py`（流式） |
| `app/core/tdms_converter.py` | 删除 | `app/io/tdms.py`（直接读块，不转 WAV） |
| `utils/tdms_converter.py` | 删除/收编 | `tools/tdms_inspect.py`（只读诊断 CLI） |
| `app/core/file_monitor.py` | 重写 | `app/services/watcher.py`（只入队） |
| `app/core/background_tasks.py` | 重写 | `app/services/pipeline.py` |
| `app/core/session_manager.py` | 重写 | `app/services/session_service.py` + `app/domain/dose_state.py` |
| `app/core/summary_processor.py` | 重写 | `app/dsp/aggregation.py` |
| `app/core/event_processor.py` | 替换 | `app/dsp/event_detector.py` + `app/services/event_audio.py` |
| `app/core/event_detector.py` | 替换 | `app/dsp/event_detector.py`（四维） |
| `app/core/ring_buffer.py` | 替换 | `app/services/event_audio.py` 的 `EventAudioCapture`（pre/post 有界缓冲） |
| `app/core/connection_manager.py` | 删除或实现 | 若不做 WebSocket，删除 |
| `app/database/database.py` | 拆分 | `app/storage/db.py` + repositories + Alembic |
| `app/database/models.py` | 重写 | 新 schema（JSON 频段） |
| `app/models/*` | 重写 | Pydantic v2 API schemas |
| `streamlit_app.py` | 重构 | `app/web/streamlit_app.py`；去 Tk/fragment |
| `test/*` | 重写 | pytest + Windows CI + 合成 TDMS/纯音 |

**C++ 参考文件**

- `include/noise_processor.hpp`, `src/noise_processor.cpp`：流式状态、时间计权、聚合。
- `include/noise_metrics.hpp`：`FreqBandMoments`、指标/阈值。
- `include/dose_state.hpp`：DoseState 纯函数。
- `include/event_detector.hpp`, `src/event_detector.cpp`：四维事件。
- `tools/regen_weighting_coefficients.py`, `tools/regen_bandpass_coefficients.py`：IEC 参考表/设计校验**方法参考**；Python 运行时用 SciPy 现场设计，不复用其手写系数。
- `tests/test_state_persistence_matrix.cpp`, `tests/test_end_to_end.cpp`, `tests/test_class1_precision.cpp`：验收方法。
- `docs/THIRD_OCTAVE_BAND_CALCULATION.md`：频段归一化/峰值增益教训。
- `docs/DEVELOPMENT_PLAN_v3.3.2.md`：滤波器状态跨段保持教训。

---

**一句话执行建议**：先把“整段 `acoustics` 计算”替换成 **SciPy 标准滤波 + 10 s 读取窗口 + 1 s 分析步 + 状态保持**，这是同时解决内存、低频、SPL 全空、依赖冲突和事件/时间计权缺失的总开关；其余数据库、API、Streamlit 可视化、Windows 服务化都围绕这个新核心收尾。
