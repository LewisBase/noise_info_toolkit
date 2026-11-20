# 现场部署重构：实现状态与运行说明

## 基线

- Tag：`v1.1.0-field-baseline`
- 开发分支：`feat/field-deployment-hardening`
- 方案：`doc/field_deployment_optimization_plan.md`
- 审计：`doc/code_quality_and_windows_deployment_audit.md`

## 已完成（垂直切片）

### 1. SciPy DSP

- `app/dsp/filters.py`
  - A/C：8/16/32/44.1/48 kHz 加载 SciPy `least_squares` + 优化 peaking 的 SOS 缓存（A 约 0.13–0.67 dB，C 约 0.04–0.29 dB，均达 IEC Class 1 ±0.7 dB）；其他采样率回退 NumPy matched-z + SciPy `zpk2sos` / `sosfreqz`；
  - 1/3 oct：SciPy `butter(..., output="sos")`；
  - 不对整段音频滤波。
- `app/dsp/processor.py`
  - `StreamingNoiseProcessor`：SciPy `sosfilt` 状态保持；
  - LAF/LAS/LCF/LCS、LAFmax/LASmax/LCSmax、LAPeak；
  - 10 s 窗口 / 1 s 子块；
  - 静音/NaN 返回 `None`，不产生 `-inf/NaN`。
- `app/dsp/aggregation.py`
  - 时长加权的能量平均、S1–S4 累加、事件/QC 合并。

### 2. 校准与 TDMS

- `app/domain/calibration.py`：Pa/V/mV/counts 统一转 Pa，未校准显式标记。
- `app/io/tdms_source.py`：`TdmsFile.open` + `read_data` 分块，读取 `wf_increment`/`wf_start_time`，不生成临时 WAV。

### 3. 异常与事件音频

- `app/dsp/event_detector.py`：D1–D4 四维判定 + 过载直通。
- `app/services/event_audio.py`：
  - 默认前 5 s + 后 10 s，单事件最长 60 s；
  - 会话/通道级有界环形缓冲，跨 10 s 窗口；`ProcessingService` 跨分块文件持有 capture；
  - FLOAT WAV（无 soundfile 时用 scipy fallback）、sha256、事件元数据。
- `app/services/anomalies.py`：系统异常去重记录。

### 4. 留存

- `app/services/retention.py`：
  - `debug` 默认，绝不删除；只输出 preview 审计；
  - `production` 先 dry-run；6 个条件；先移动 `trash/`；审计。
- `app/storage/repository.py` 提供 jobs/events/audit 查询与 `task_jobs_for_retention`。
- `tools/migrate_legacy_db.py`：旧 `time_history`/`session_summary`/`event_log` → 新 schema，保留 `legacy_*` 表，支持 dry-run/备份。

### 5. 存储

- `app/storage/models.py`：sessions/jobs/time_history/events/system_events/retention_audit/calibrations。
- SQLite WAL、busy_timeout、UTC TypeDecorator。
- `time_history` 存 10 s 行；freq_spl/freq_moments 为 JSON。

### 6. API v1 与 Streamlit

- `app/api/app.py`：
  - `/health/live`、`/health/ready`；
  - `/api/v1/channels`、`metrics/latest`、`metrics/history`；
  - `monitor/config|start|stop`、`fs/dirs` 服务端目录浏览；
  - sessions/current/stop/metrics/events、event audio、system events、calibration、retention preview。
- `app/services/processing_service.py`：watcher 只入队、单 worker、幂等 job、稳定文件检测、多通道 job、会话级事件音频 capture。
- `app/web/streamlit_app.py`：
  - 恢复四标签页：实时监控、历史数据、会话管理、系统状态；
  - 侧边栏监控目录输入、服务端目录浏览、开始/停止监测、通道/刷新/会话控制；
  - 实时/历史/会话均含声级、峰值、峰度、剂量累计、1/3 倍频程及频谱热力图；
  - 事件音频播放、调试模式提示、系统异常、留存/校准状态；
  - 无 Tk、无 sleep；纯格式化函数在 `app/web/formatters.py`，AppTest 覆盖无后端与有后端渲染。

## 运行

```bash
# 1. 安装新栈（Python 3.11；Windows 建议生成 lock/wheelhouse）
pip install -r requirements-field.txt

# 2. 处理一个 TDMS（写入 SQLite + 事件音频）
python -m app.cli process D:\NoiseData\CH1_001.tdms --channel CH1

# 3. 启动 API v1（单 worker）
python start_field_server.py
# 或 uvicorn app.api.app:app --host 127.0.0.1 --port 8000 --workers 1

# 4. 启动 Streamlit
python -m streamlit run app/web/streamlit_app.py --global.developmentMode=false --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

## 测试

```bash
python -m pytest -q tests
```

当前覆盖：SciPy 处理器、1 kHz/100 Hz、静音、块状态、10 s 聚合、事件音频、debug/生产留存、TDMS 源、pipeline、真实 TDMS 端到端、ProcessingService→SQLite、API v1、API Key、校准、旧库迁移、跨 TDMS 分块事件音频、monitor/fs API、Streamlit 四页图表 + AppTest（安装 nptdms+Streamlit 后 39 passed）。

## 已知限制 / 下一步

1. 8–48 kHz A/C 已达到 Class 1；非标准采样率仍回退 matched-z。
2. `ProcessingService` 时间戳断档时不会强制 reset capture；跨文件连续事件已支持，边界策略仍可加强。
3. `retention/run` 已把成功移动的 job 标记 `source_deleted`；仍需真实生产 dry-run/7 天验收。
4. Streamlit AppTest 已在本地临时环境（Streamlit 1.67）跑通；有后端时渲染 20 个指标卡/8 个图表。
5. 旧 `main.py` 仍为 legacy；新入口是 `start_field_server.py` + `app/web/streamlit_app.py`。
6. Windows NSSM/备份/反向代理/烟测脚本已提供，需在真实 Windows 上验证。
7. TLS/认证加固、生产 dry-run、7 天 soak 仍需现场执行。

## 2026-11-17 UI 深度优化

- Tag：`v1.2.0-field-ui`（四页 UI + monitor API + Class 1 计权基线）
- 侧边栏后端地址/API Key 提前渲染并重建 `ApiClient`，修改后当前 rerun 生效；
- 目录浏览/监控增加 `NIT_ALLOWED_WATCH_ROOTS` 白名单；为空时 `/health/ready` 标记 `directory_guard=unrestricted` 并在 UI 警示；
- 页面改为分段控件按需加载，避免四个页面每次 rerun 都请求；
- 实时页增加质量标志、事件竖线标记、异常事件表；
- 会话/历史页增加事件波形与频谱；
- 系统页增加处理任务列表、校准记录写入表单、目录白名单状态；
- 新增 `/api/v1/jobs`，展示 queued/running/done/failed/quarantined job；
- 新增 `tests/test_api_client.py`、`tests/test_api_directory_guard.py`、`tests/test_api_monitor.py`。
- 当前测试：默认 `36 passed, 5 skipped`；安装 nptdms+Streamlit 后 `41 passed`。

### UI 优化续

- 多通道对比：实时/历史页叠加其他通道 LAeq；
- 处理任务列表 `/api/v1/jobs` 和系统页任务表；
- 事件波形/频谱、质量标志、事件竖线；
- 校准记录前端表单；
- 目录浏览/监控白名单；
- 页面按需加载（不再四个页面同时拉数据）；
- 侧边栏后端地址/API Key 即时生效。
- 当前优化 tag：`v1.2.1-field-ui-optimized`。

## 2026-11-21 实时/治理升级

- **SSE/WebSocket**：`GET /api/v1/stream`、`WS /api/v1/ws`，事件总线由 worker 线程推送到 asyncio；Streamlit 实时卡片使用 EventSource，详细图表轮询改为可选。
- **历史分页/分钟聚合**：`/api/v1/metrics/history?aggregate=minute&limit=&offset=`，返回 `total`；UI 增加页码/每页/分钟聚合。
- **事件参数 UI**：`/api/v1/event-config` 持久化到 `app_config`，支持阈值、前/后触发、最长、最小间隔；下一文件生效。
- **人工审核**：事件 `review_state=unreviewed|confirmed|false_positive`，审核写入 `event_review_audit` 和事件字段；会话页可确认/误报/重置。
- **角色**：`operator/calibrator/admin`，通过 `NIT_*_API_KEY` 或 legacy `NIT_API_KEY`；校准/事件参数需 calibrator，留存需 admin，监控/数据需 operator。
- **Windows**：`restore.ps1`、`soak_test.ps1`、`soak_report.ps1`、`SOAK_ACCEPTANCE.md`；7 天验收需在真实 Windows 执行。
- 测试：默认 `41 passed, 5 skipped`；安装 nptdms+Streamlit 后 `46 passed`。

## 2026-11-21 实时流/反馈/角色/Soak 收尾

- Tag：`v1.3.0-field-realtime`
- SSE：`/api/v1/stream` 已实际收到 `metric` 事件；WebSocket `/api/v1/ws` 有测试；
- Streamlit 实时卡片使用 EventSource，详细图表自动刷新默认关闭，手动“刷新详细图表”；
- 历史分页/分钟聚合、事件参数表单、事件人工审核、角色权限；
- Windows `restore.ps1`、`soak_test.ps1`、`soak_report.ps1`、`SOAK_ACCEPTANCE.md`；
- 默认测试 `41 passed, 5 skipped`；安装 nptdms+Streamlit 后 `46 passed`。
- 未执行：真实 Windows 的 NSSM/恢复/7 天 soak（需现场环境）。
