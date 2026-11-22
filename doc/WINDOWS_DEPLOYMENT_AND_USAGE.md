# Windows 部署与使用说明

> 适用版本：`v1.4.0-field-file-results` 及之后  
> 后端：FastAPI + Uvicorn  
> 前端：Streamlit  
> 存储：SQLite（WAL）  
> 输入：TDMS 文件  
> 默认留存：`debug`，绝不删除原始音频/事件音频

---

## 1. 当前支持范围

### 1.1 已支持

- 监控指定目录，发现新 TDMS 文件；
- 单 worker 逐个处理文件；
- 10 s 窗口 / 1 s 分析；
- LAeq、LCeq、LZeq、LAF、LAS、LCF、LCS、峰值、剂量、峰度；
- 1/3 倍频程；
- 异常事件检测、事件前后音频；
- 文件级结果 `file_results`；
- 10 s 明细 `time_history`；
- 事件人工确认/误报；
- 文件结果、历史、实时、会话、系统状态五个页面；
- 停止监测自动导出 CSV；
- SSE 实时数值流；
- 角色：operator / calibrator / admin；
- Windows 服务、备份、恢复、7 天 soak 脚本。

### 1.2 尚未支持

- **WAV 文件输入**：当前主流程只监控 `.tdms`；
- 实时麦克风声卡采集；
- 自动生成 Excel（当前导出 CSV，Excel 可直接打开）；
- 旧历史数据的 `file_results` 自动回填；
- 正式计量认证（当前 A/C 为算法/仿真验证，不是计量院证书）。

如果录音软件实际输出 WAV，需要先增加 WAV 源适配器，不能直接使用本版本。

---

## 2. 部署架构

```text
D:\NoiseData\*.tdms
        │
        ▼
C:\NoiseToolkit（后端，127.0.0.1:8000）
  ├── SQLite: Database\noise_info.db
  ├── 事件音频: audio_events\
  ├── 导出: exports\
  ├── 日志: log\
  ├── 临时: temp\
  └── 回收: trash\
        │
        ▼
C:\NoiseToolkit（Streamlit，127.0.0.1:8501）
        │
        ▼
浏览器 http://127.0.0.1:8501
```

- 后端和前端都只绑定 `127.0.0.1`；
- 如果要从其他机器访问，必须经 IIS/Nginx/Caddy + TLS + 认证，参见
  [`deploy/windows/reverse-proxy.md`](../deploy/windows/reverse-proxy.md)；
- 不要使用 `--workers > 1`，SQLite 和处理服务按单 writer/单 worker 设计；
- 不要使用 `--reload`。

---

## 3. 前置条件

- Windows 10/11 x64 或 Windows Server 2019+；
- Python **3.11 x64**（不要 3.13，不要 Microsoft Store 版）；
- 管理员权限；
- 安装路径使用短 ASCII 路径，推荐 `C:\NoiseToolkit`；
- 数据目录不要放在 OneDrive/网络盘；SQLite、日志、temp 放本地盘；
- 端口 `8000`、`8501` 未被占用；
- 如果要注册服务，准备 `nssm.exe`；
- 系统时间已用 NTP 同步；
- 禁用睡眠/休眠（现场连续监测）。

检查 Python：

```powershell
py -3.11 --version
```

应输出类似：

```text
Python 3.11.x
```

---

## 4. 准备安装目录

`install.ps1` 假定**仓库已经位于安装目录**，因为脚本会读取该目录下的：

- `requirements-field.txt`
- `.env.example`
- `app\...`
- `deploy\windows\...`

推荐：

```powershell
# 管理员 PowerShell
cd C:\
git clone <仓库地址> C:\NoiseToolkit
cd C:\NoiseToolkit
```

如果没有 Git，也可以把整个仓库压缩包解压到 `C:\NoiseToolkit`。

确认目录结构：

```text
C:\NoiseToolkit
├── app\
├── deploy\windows\
├── requirements-field.txt
├── .env.example
├── start_server.py
└── ...
```

---

## 5. 安装

以管理员身份打开 PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd C:\NoiseToolkit
.\deploy\windows\install.ps1 -InstallDir C:\NoiseToolkit
```

脚本会：

1. 创建数据目录；
2. 创建 `.venv`；
3. 安装 `requirements-field.txt`；
4. 执行 `pip check`；
5. 如果不存在 `.env`，从 `.env.example` 复制；
6. 执行配置/依赖 import 烟测。

如果安装失败：

- 检查 Python 3.11 是否可用；
- 检查网络/代理；
- 不要使用含中文/空格的路径；
- 查看 PowerShell 报错，不要直接跳过 `pip check`。

---

## 6. 配置 `.env`

编辑：

```text
C:\NoiseToolkit\.env
```

最小配置示例：

```dotenv
NIT_WATCH_DIR=D:/NoiseData
NIT_DB_PATH=./Database/noise_info.db
NIT_EVENT_DIR=./audio_events
NIT_EXPORT_DIR=./exports

NIT_HOST=127.0.0.1
NIT_PORT=8000
NIT_BACKEND_URL=http://127.0.0.1:8000

# 生产必须改掉 change-me，并设置角色 key
NIT_ADMIN_API_KEY=请替换为长随机字符串
NIT_OPERATOR_API_KEY=请替换为另一个长随机字符串
NIT_CALIBRATOR_API_KEY=请替换为另一个长随机字符串

NIT_ALLOWED_WATCH_ROOTS=["D:/NoiseData"]

NIT_RETENTION_MODE=debug
NIT_RETENTION_DRY_RUN=true
NIT_AUTO_EXPORT_ON_STOP=true
```

### 6.1 关键配置说明

| 配置 | 说明 |
|---|---|
| `NIT_WATCH_DIR` | 默认监控目录；启动 API 时使用（推荐正斜杠，如 `D:/NoiseData`） |
| `NIT_DB_PATH` | SQLite 路径 |
| `NIT_EVENT_DIR` | 事件音频目录 |
| `NIT_EXPORT_DIR` | 自动导出目录 |
| `NIT_ALLOWED_WATCH_ROOTS` | 允许浏览/监控的目录白名单；空数组等于不限制，仅限调试 |
| `NIT_API_KEY` | 旧版单 key（admin）；新部署建议用三个角色 key |
| `NIT_OPERATOR_API_KEY` | 查看、监控、会话、事件审核 |
| `NIT_CALIBRATOR_API_KEY` | 校准、事件阈值 |
| `NIT_ADMIN_API_KEY` | 留存、管理操作 |
| `NIT_RETENTION_MODE` | `debug` 不删除；`production` 才可能移动源文件 |
| `NIT_RETENTION_DRY_RUN` | production 下先 true 预览 |
| `NIT_AUTO_EXPORT_ON_STOP` | 停止监测自动导出 CSV |
| `NIT_BACKEND_URL` | Streamlit 访问的后端地址 |
| `NIT_CORS_ORIGINS` | SSE 允许的浏览器来源，默认 `["http://127.0.0.1:8501","http://localhost:8501"]`；LAN 访问需加对应 origin |
| `NIT_TDMS_FALLBACK_FS` | TDMS 缺少 `wf_increment`/`SampleRate` 时的采样率，默认 48000；必须与录音软件一致 |

注意：

1. `NIT_ALLOWED_WATCH_ROOTS` 是 **JSON 数组**；推荐使用正斜杠，如 `["D:/NoiseData"]`；如果使用反斜杠，要写成 `\\\\`；
2. 修改 `.env` 后需要重启后端（NSSM 服务或前台进程）；
3. Streamlit **不会自动读取 `.env`**，API Key/后端地址在页面侧边栏输入，或启动前设置环境变量；
4. `NIT_WATCH_DIR` 是启动默认值；页面“开始监测”切换的目录只对当前运行生效，重启后回到 `.env`。

---

## 7. 前台启动验证

先不要注册服务，先用两个 PowerShell 窗口验证。

### 7.1 后端

```powershell
cd C:\NoiseToolkit
.\deploy\windows\run_backend.ps1 -InstallDir C:\NoiseToolkit
```

或：

```powershell
cd C:\NoiseToolkit
.\.venv\Scripts\python.exe -m uvicorn app.api.app:app `
  --host 127.0.0.1 --port 8000 --workers 1
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

### 7.2 前端

```powershell
cd C:\NoiseToolkit
.\deploy\windows\run_frontend.ps1 -InstallDir C:\NoiseToolkit
```

或：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app/web/streamlit_app.py `
  --global.developmentMode=false `
  --server.address 127.0.0.1 --server.port 8501 `
  --server.headless true
```

打开：

```text
http://127.0.0.1:8501
```

### 7.3 首次进入页面

1. 侧边栏“后端 API 地址”填 `http://127.0.0.1:8000`；
2. “API Key”填 `.env` 中配置的 key；
3. 如果配置了角色 key，operator key 可用于查看和监测；
4. 侧边栏显示当前角色（operator/calibrator/admin）；
5. “音频文件目录”填 `D:\NoiseData`；
6. 可先点“浏览目录”选择子目录；
7. 点击“▶ 开始监测”。

如果页面提示“目录白名单未配置”，说明 `NIT_ALLOWED_WATCH_ROOTS` 仍为空，只适合本机调试。

---

## 8. 注册为 Windows 服务（NSSM）

### 8.1 准备 NSSM

下载 `nssm.exe`，放到：

```text
C:\NoiseToolkit\tools\nssm.exe
```

仓库不包含 NSSM 二进制文件。

### 8.2 安装服务

管理员 PowerShell：

```powershell
cd C:\NoiseToolkit
.\deploy\windows\install_services.ps1 -InstallDir C:\NoiseToolkit
```

会注册：

- `NoiseBackend`
- `NoiseFrontend`

并设置：

- `AppDirectory=C:\NoiseToolkit`
- stdout/stderr 日志到 `log\`
- 异常退出自动重启

### 8.3 常用服务命令

```powershell
# 查看
Get-Service NoiseBackend, NoiseFrontend

# 启动/停止/重启
Start-Service NoiseBackend
Stop-Service NoiseBackend
Restart-Service NoiseBackend

# 删除服务（仅卸载时）
C:\NoiseToolkit\tools\nssm.exe remove NoiseBackend confirm
C:\NoiseToolkit\tools\nssm.exe remove NoiseFrontend confirm
```

服务启动后：

```text
http://127.0.0.1:8501
http://127.0.0.1:8000/health/ready
```

### 8.4 停止服务与自动导出的区别

- 在 **Web 页面点击“停止监测”**：会停止 worker、flush 事件，并自动导出 CSV；
- 直接 `Stop-Service NoiseBackend`：属于进程级停止，不保证走 API 的停止/导出逻辑；
- 现场建议：先页面“停止监测”，确认导出完成，再停服务。

---

## 9. 页面使用说明

### 9.1 实时监控

- SSE 实时数值卡：LAeq/LCeq/LAF/LZpeak/剂量；
- 声级、峰值、峰度、剂量累计、频谱热力图；
- 质量标志：过载、欠量程、未佩戴、伪迹；
- 事件竖线标记；
- “详细图表自动刷新”默认关闭，可手动“刷新详细图表”。

`type=1 severity=20` 表示**轻微声学事件**，不是系统故障。默认 LAF ≥85 dB 触发；可在“系统状态 → 事件检测参数”调整。

### 9.2 历史数据

- 日期范围；
- 聚合粒度：10 s 原始 / 按分钟；
- 分页；
- 声级/峰值/剂量/频谱热力图；
- 当前页 CSV 导出；
- 全量导出请用“停止监测自动导出”或侧边栏“导出全部结果”。

### 9.3 文件结果

- 每个输入文件/通道一行；
- 文件名、通道、状态、LAeq、LZpeak、剂量、事件数；
- 选择文件查看文件内时序、频谱、事件音频；
- `file_results` 是最终按文件交付的首选表。

### 9.4 会话管理

- 当前会话；
- 时间历程、峰值、剂量；
- 异常事件；
- 事件波形/频谱；
- 人工审核：
  - 确认事件
  - 标记误报
  - 重置审核

审核状态：

```text
unreviewed / confirmed / false_positive
```

### 9.5 系统状态

- API/校准/留存/目录状态；
- 监测状态；
- 处理任务；
- 系统异常；
- 留存预览（admin）；
- 事件检测参数（calibrator/admin）；
- 写入校准记录（calibrator/admin）。

---

## 10. 校准

进入“系统状态 → 写入校准记录”，填写：

- 名称；
- 单位（Pa/V/mV/counts）；
- Pa/单位；
- 偏置；
- 证书/备注。

保存后：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

应看到：

```text
calibrated = True
```

注意：

- 建议用 94 dB 和 114 dB 两点校准；
- 当前 A/C 计权是按 IEC 参考曲线的算法验证，不是计量院正式认证；
- 未校准数据会显示“相对模式”，不能用于合规判定。

---

## 11. 事件检测参数

只有 `calibrator`/`admin` 可修改。

可调整：

- LAF 轻微/中等/严重阈值；
- 脉冲阈值；
- 上升沿阈值；
- 背景差值；
- 峰值过载阈值；
- 事件前/后时长；
- 事件最长；
- 最小事件间隔。

保存后**下一文件生效**，当前正在处理的文件不回溯。

---

## 12. 数据、导出和文件关系

### 12.1 数据目录

```text
C:\NoiseToolkit\
├── Database\noise_info.db
├── audio_events\<channel>\*.wav
├── exports\
├── log\
├── temp\
├── trash\
└── audio_files\        # 默认监控目录（可在 .env 改为 D:\NoiseData）
```

### 12.2 停止监测自动导出

页面“停止监测”后自动生成：

```text
exports\file_results_YYYYmmdd_HHMMSS.csv
exports\results_YYYYmmdd_HHMMSS.csv
exports\events_YYYYmmdd_HHMMSS.csv
```

含义：

- `file_results`：每个文件/通道一行，适合最终交付；
- `results`：每 10 s 一行，适合明细分析；
- `events`：每个事件一行，含审核字段。

CSV 为 UTF-8-BOM，Excel 可直接打开。字段解释见
[`EXPORT_SCHEMA.md`](EXPORT_SCHEMA.md)。

### 12.3 文件结果与明细的关系

```text
file_results.id
 ├── time_history.file_result_id
 └── events.file_result_id
```

同一个文件/通道的所有 10 s 数据和事件都可以回溯到文件结果。

### 12.4 旧数据

升级前已经处理的数据：

- 不会自动生成 `file_result_id`；
- 需要重新处理源文件，才会生成文件级结果；
- 旧 `legacy_*` 表保留，不自动删除。

---

## 13. 备份

```powershell
cd C:\NoiseToolkit
.\deploy\windows\backup.ps1 `
  -InstallDir C:\NoiseToolkit `
  -BackupDir D:\NoiseBackup
```

备份内容：

- SQLite（使用 SQLite backup API，不直接复制活跃 WAL）；
- `audio_events`；
- 不默认复制 `audio_files`，因为调试期源文件本来就要保留，生产期按留存策略。

建议：

- 每日计划任务；
- 备份到独立磁盘；
- 每月做一次恢复演练。

---

## 14. 恢复

```powershell
.\deploy\windows\restore.ps1 `
  -BackupDir D:\NoiseBackup\20261121_120000 `
  -InstallDir C:\NoiseToolkit
```

脚本会停止 NSSM 服务、恢复 DB/事件音频、重新启动服务。

恢复后必须：

1. 运行 `smoke_test.ps1`；
2. 检查 `/health/ready`；
3. 检查校准记录；
4. 检查最近文件结果和事件音频；
5. 检查留存模式仍为 `debug`。

---

## 15. 备份恢复/健康检查脚本

```powershell
# 健康检查（API）
.\deploy\windows\healthcheck.ps1 -BaseUrl http://127.0.0.1:8000

# 完整烟测（依赖、API、UI）
.\deploy\windows\smoke_test.ps1 -InstallDir C:\NoiseToolkit

# 7 天 soak
.\deploy\windows\soak_test.ps1 -ApiBase http://127.0.0.1:8000 -Days 7

# soak 报告
.\deploy\windows\soak_report.ps1 -Csv C:\NoiseToolkit\log\soak_....csv
```

7 天验收标准见：

```text
deploy\windows\SOAK_ACCEPTANCE.md
```

---

## 16. 留存切换（非常重要）

### 阶段 1：debug（默认）

```dotenv
NIT_RETENTION_MODE=debug
```

- 不删除任何源音频/事件音频；
- 适合安装、调试、7 天验收。

### 阶段 2：production dry-run

```dotenv
NIT_RETENTION_MODE=production
NIT_RETENTION_DRY_RUN=true
```

- 只预览，不移动文件；
- 检查 `retention_audit` 和候选文件。

### 阶段 3：production 实删

```dotenv
NIT_RETENTION_MODE=production
NIT_RETENTION_DRY_RUN=false
```

前置条件：

- debug 至少 7 天零删除；
- 文件结果/事件音频校验通过；
- 备份和恢复演练通过；
- 获得现场负责人书面确认。

---

## 17. 角色与安全

| 角色 | 权限 |
|---|---|
| operator | 查看数据、开始/停止监测、会话、事件审核 |
| calibrator | 校准、事件检测参数 |
| admin | 留存、管理操作 |

生产要求：

- 配置三个随机 API Key；
- 配置 `NIT_ALLOWED_WATCH_ROOTS`；
- 不直接暴露 8000/8501；
- 使用 IIS/Nginx/Caddy + TLS；
- SSE 的 `?api_key=` 通过反向代理/短期 token 处理；
- 定期轮换 key；
- 备份中不含明文 key。

参考：

```text
deploy\windows\reverse-proxy.md
```

---

## 18. 常见问题

### 18.1 页面显示“后端不可用”

- 后端是否启动；
- `http://127.0.0.1:8000/health/ready` 是否 200；
- 侧边栏后端地址是否正确；
- 防火墙是否阻止；
- API Key 是否正确。

### 18.2 页面显示 401

- 未填 API Key；
- key 与 `.env` 不一致；
- 当前角色 key 填错；
- 修改 `.env` 后后端没重启。

### 18.3 目录浏览 403

- 目录不在 `NIT_ALLOWED_WATCH_ROOTS`；
- 路径不是绝对路径；
- 目录没有权限。

### 18.4 开始监测失败

- 目录不存在或不可写；
- 路径不在白名单；
- 端口/服务异常；
- 查看 `log\backend-stderr.log`。

### 18.5 没有数据

- 监控文件是 `.tdms` 吗？
- 文件是否仍在写入？等待稳定 2 s；
- 是否被其他程序占用；
- `jobs` 是否 failed；
- `系统状态 → 处理任务`。

### 18.6 `type=1 severity=20`

- 轻微声学事件，不是系统错误；
- 默认 LAF ≥85 dB 触发；
- 可在事件检测参数中调整，或查看 `trigger_flags`。

### 18.7 Streamlit 报 developmentMode/port 错误

使用：

```powershell
--global.developmentMode=false
```

`run_frontend.ps1` 已包含。

### 18.8 SQLite locked

- 确认只有一个 worker；
- 不要同时运行两个后端实例；
- 不要用 Excel/DB 工具长时间独占 DB；
- 看 `backend-stderr.log`。

### 18.9 服务启动后立即停止

- 查看 `log\backend-stderr.log`；
- 检查 `.env` 路径/权限；
- 检查 NSSM `AppDirectory`；
- 检查 Python 依赖是否完整。

---

## 19. 封版验收清单

- [ ] 干净 Windows 机器安装成功；
- [ ] NSSM 服务重启/自动恢复；
- [ ] 真实 TDMS 8k/48k 回放；
- [ ] 多通道结果分开；
- [ ] 94/114 dB 校准，`calibrated=true`；
- [ ] 事件阈值现场调优；
- [ ] debug 7 天零删除；
- [ ] `file_results` 与 `time_history/events` 关联正确；
- [ ] 停止监测自动导出三个 CSV；
- [ ] 备份/恢复演练；
- [ ] 目录白名单/角色/TLS；
- [ ] production dry-run 7 天；
- [ ] 7 天 soak，`soak_report` failures=0；
- [ ] 验收记录归档，打最终生产 tag。

---

## 20. 常用命令速查

```powershell
cd C:\NoiseToolkit
Set-ExecutionPolicy -Scope Process Bypass

# 安装
.\deploy\windows\install.ps1 -InstallDir C:\NoiseToolkit

# 前台
.\deploy\windows\run_backend.ps1 -InstallDir C:\NoiseToolkit
.\deploy\windows\run_frontend.ps1 -InstallDir C:\NoiseToolkit

# 服务
.\deploy\windows\install_services.ps1 -InstallDir C:\NoiseToolkit
Get-Service NoiseBackend, NoiseFrontend

# 检查
.\deploy\windows\healthcheck.ps1 -BaseUrl http://127.0.0.1:8000
.\deploy\windows\smoke_test.ps1 -InstallDir C:\NoiseToolkit

# 备份/恢复
.\deploy\windows\backup.ps1 -InstallDir C:\NoiseToolkit -BackupDir D:\NoiseBackup
.\deploy\windows\restore.ps1 -BackupDir D:\NoiseBackup\20261121_120000 -InstallDir C:\NoiseToolkit

# 7 天 soak
.\deploy\windows\soak_test.ps1 -ApiBase http://127.0.0.1:8000 -Days 7
.\deploy\windows\soak_report.ps1 -Csv C:\NoiseToolkit\log\soak_....csv

# API 健康
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```
