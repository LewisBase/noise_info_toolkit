# 现场部署重构：实现状态与运行说明

## 基线

- Tag：`v1.1.0-field-baseline`
- 开发分支：`feat/field-deployment-hardening`
- 方案：`doc/field_deployment_optimization_plan.md`
- 审计：`doc/code_quality_and_windows_deployment_audit.md`

## 已完成（垂直切片）

### 1. SciPy DSP

- `app/dsp/filters.py`
  - A/C：48/44.1/32 kHz 加载 SciPy `least_squares` 拟合的 SOS 缓存；其他采样率回退 NumPy matched-z + SciPy `zpk2sos` / `sosfreqz`；
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
- `app/services/processing_service.py`：watcher 只入队、单 worker、幂等 job、稳定文件检测。
- `app/web/streamlit_app.py`：
  - 实时/历史/会话与事件/系统状态四页；
  - `st.fragment(run_every=10)` 局部刷新；
  - 事件音频播放、调试模式提示、系统异常、留存状态；
  - 无 Tk、无 sleep。

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
python -m streamlit run app/web/streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

## 测试

```bash
python -m pytest -q tests
```

当前覆盖：SciPy 处理器、1 kHz/100 Hz、静音、块状态、10 s 聚合、事件音频、debug/生产留存、TDMS 源、pipeline、真实 TDMS 端到端、ProcessingService→SQLite、API v1、API Key、校准、旧库迁移、Streamlit 格式化（33 passed + 3 skipped；安装 nptdms 后 35 passed，Streamlit 未安装时跳过 import smoke）。

## 已知限制 / 下一步

1. A/C 高频仍按 matched-z 的残余误差；需用 IEC 参考表做完整 Class 1/2 判定，必要时用 SciPy 频响拟合改进。
2. `ProcessingService` 目前按单通道 CH1 建 job；多通道需每 channel 独立 job/session。
3. `EventAudioCapture` 目前每文件重建；跨分块文件的 post 需要会话级 capture（计划中）。
4. `retention/run` 已把成功移动的 job 标记 `source_deleted`；仍需真实生产 dry-run 验收。
5. Streamlit 依赖未在本机安装；`AppTest` 尚未跑。
6. 旧 `main.py`/`streamlit_app.py` 仍是 legacy；新入口是 `start_field_server.py` + `app/web/streamlit_app.py`。
7. 旧库迁移脚本、Windows NSSM 安装/备份脚本已提供；认证/TLS 仍按方案后续执行，需在真实 Windows 上验证。
