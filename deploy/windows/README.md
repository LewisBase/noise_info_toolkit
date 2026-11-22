# Windows 部署（现场）

## 一键安装

在管理员 PowerShell 中运行（脚本会下载 uv 和仓库，不需要手动安装 Python 或拷贝代码）：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
$b = "$env:TEMP\nit-bootstrap.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/LewisBase/noise_info_toolkit/feat/field-deployment-hardening/deploy/windows/bootstrap.ps1" `
  -OutFile $b
& $b -InstallDir C:\NoiseToolkit -RepoRef feat/field-deployment-hardening
```

也可以先手动下载仓库，再运行 `install.ps1`；`install.ps1` 现在使用 uv + `uv.lock`，不再使用 pip/venv 手装依赖。

---

## 前提

- Windows 10/11 x64 或 Server 2019+
- uv 会下载 Python 3.11；不必预先安装 Python
- 安装目录使用短 ASCII 路径，例如 `C:\NoiseToolkit`
- 数据目录不要用 OneDrive；SQLite/日志/temp 放本地盘，NAS 只放音频

## 1. 安装

```powershell
# 如果已经使用 bootstrap.ps1 或已把仓库放到 InstallDir：
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\windows\install.ps1 -InstallDir C:\NoiseToolkit
```

脚本会：

1. 创建 `C:\NoiseToolkit`、`audio_files`、`audio_events`、`Database`、`log`、`temp`、`trash`；
2. 用 uv 下载 Python 3.11 并创建 `.venv`；
3. `uv sync --frozen` 安装 `uv.lock` 中的依赖；
4. 从 `.env.example` 生成 `.env`（默认 `retention_mode=debug`，绝不删除）；
5. 执行 Python import 烟测。

## 2. 运行（前台验证）

```powershell
.\deploy\windows\run_backend.ps1 -InstallDir C:\NoiseToolkit
.\deploy\windows\run_frontend.ps1 -InstallDir C:\NoiseToolkit
```

- API：`http://127.0.0.1:8000/health/ready`
- UI：`http://127.0.0.1:8501`

## 3. 注册为服务（NSSM）

先下载 `nssm.exe` 到 `C:\NoiseToolkit\tools\nssm.exe`，然后：

```powershell
.\deploy\windows\install_services.ps1 -InstallDir C:\NoiseToolkit
```

- 后端：`uvicorn app.api.app:app --host 127.0.0.1 --port 8000 --workers 1`
- 前端：`streamlit run app/web/streamlit_app.py --global.developmentMode=false --server.address 127.0.0.1 --server.port 8501 --server.headless true`
- 两者均设置 `AppDirectory=C:\NoiseToolkit`，失败自动重启。
- **不要**使用 `--workers >1` 或 `--reload`。

## 4. 上线前

1. 保持 `NIT_RETENTION_MODE=debug` 运行至少 7 天，确认原始音频/事件音频完整且零删除；
2. 校准 94/114 dB，确认 `/health/ready` 的 `calibrated=true`；
3. 需要 LAN 访问时，经 IIS/Nginx/Caddy 反向代理 + TLS + 认证，不要直接暴露 8000/8501；
4. 设置 `NIT_RETENTION_MODE=production`、`NIT_RETENTION_DRY_RUN=true` 先预览 7 天；
5. 再设 `NIT_RETENTION_DRY_RUN=false`，并每日检查 `retention_audit`；
6. 配置 Windows 防火墙、Defender 排除数据目录、NTP、禁用睡眠。

## 5. 健康检查

```powershell
.\deploy\windows\healthcheck.ps1 -BaseUrl http://127.0.0.1:8000
```

退出码非 0 时由计划任务/监控告警。

## 6. 备份

```powershell
.\deploy\windows\backup.ps1 -InstallDir C:\NoiseToolkit -BackupDir D:\NoiseBackup
```

- 使用 SQLite backup API，不直接复制正在写的 `.db` + `-wal`；
- 复制 `audio_events`（事件音频）；
- 建议每日执行并定期做恢复演练；
- `audio_files` 是否备份取决于生产留存策略。

## 7. 目录白名单

生产环境必须在 `.env` 中配置允许浏览/监控的目录，例如：

```dotenv
NIT_ALLOWED_WATCH_ROOTS=["D:\\NoiseData","E:\\NoiseData"]
```

为空时 API 允许任意本地目录，仅适合本机调试；`/health/ready` 的
`directory_guard=unrestricted` 会提示该状态。

## 8. 恢复与 7 天 soak

- 恢复：先停止服务，再执行 `restore.ps1 -BackupDir D:\NoiseBackup\<stamp> -Force`；
- 恢复后运行 `smoke_test.ps1`，核对校准/留存/事件音频；
- 7 天 soak：`soak_test.ps1`，验收清单见 `SOAK_ACCEPTANCE.md`；
- 报告：`soak_report.ps1 -Csv ...`。

> 这些脚本需要在真实 Windows 环境执行，本仓库只提供脚本和验收流程。


完整 Windows 部署与使用说明见 [`doc/WINDOWS_DEPLOYMENT_AND_USAGE.md`](../../doc/WINDOWS_DEPLOYMENT_AND_USAGE.md)。
