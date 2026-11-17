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
  - sessions/current/stop/events、event audio、system events、calibration、retention preview。
- `app/services/processing_service.py`：watcher 只入队、单 worker、幂等 job、稳定文件检测、多通道 job、会话级事件音频 capture。
- `app/web/streamlit_app.py`：
  - 实时/历史/会话与事件/系统状态四页；
  - `st.fragment(run_every=10)` 局部刷新；
  - 事件音频播放、调试模式提示、系统异常、留存状态；
  - 无 Tk、无 sleep；纯格式化函数在 `app/web/formatters.py`，有 AppTest smoke。

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

当前覆盖：SciPy 处理器、1 kHz/100 Hz、静音、块状态、10 s 聚合、事件音频、debug/生产留存、TDMS 源、pipeline、真实 TDMS 端到端、ProcessingService→SQLite、API v1、API Key、校准、旧库迁移、跨 TDMS 分块事件音频、Streamlit 格式化 + AppTest（安装 nptdms+Streamlit 后 38 passed）。

## 已知限制 / 下一步

1. 8–48 kHz A/C 已达到 Class 1；非标准采样率仍回退 matched-z。
2. `ProcessingService` 时间戳断档时不会强制 reset capture；跨文件连续事件已支持，边界策略仍可加强。
3. `retention/run` 已把成功移动的 job 标记 `source_deleted`；仍需真实生产 dry-run/7 天验收。
4. Streamlit AppTest 已在本地临时环境（Streamlit 1.67）跑通；Windows CI 会再次执行。
5. 旧 `main.py` 仍为 legacy；新入口是 `start_field_server.py` + `app/web/streamlit_app.py`。
6. Windows NSSM/备份/反向代理/烟测脚本已提供，需在真实 Windows 上验证。
7. TLS/认证加固、生产 dry-run、7 天 soak 仍需现场执行。
