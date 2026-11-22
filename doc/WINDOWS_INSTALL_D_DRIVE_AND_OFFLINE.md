# Windows 安装到 D 盘与离线传输

> 适用版本：`v2.0.0-rc1-field` 及之后  
> 推荐安装目录：`D:\NoiseToolkit`  
> 推荐数据目录：`D:\NoiseData`

---

## 1. 目录规划

```text
D:\NoiseToolkit       程序、虚拟环境、数据库、事件音频、日志
D:\NoiseData          原始 TDMS 监控目录
```

建议：

- 路径使用短 ASCII 名称，不要中文/空格；
- 数据目录不要放 OneDrive、网络共享盘；
- D 盘必须是本地固定磁盘；
- 以管理员身份运行 PowerShell；
- 先确认 D 盘可写：

```powershell
Test-Path D:\
New-Item -ItemType Directory -Force D:\NoiseData
```

---

## 2. 在线一键安装到 D 盘

在目标 Windows 机器上执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass

$bootstrap = "$env:TEMP\nit-bootstrap.ps1"
Invoke-WebRequest `
  "https://raw.githubusercontent.com/LewisBase/noise_info_toolkit/v2.0.0-rc1-field/deploy/windows/bootstrap.ps1" `
  -OutFile $bootstrap

& $bootstrap -InstallDir "D:\NoiseToolkit" `
  -RepoRef "v2.0.0-rc1-field"
```

默认 `RepoRef` 现在是 `main`；使用 tag 时必须明确传入上面的 `-RepoRef`。

### 旧版 404 的原因

旧版 `bootstrap.ps1` 把 tag 拼成了：

```text
/archive/refs/heads/v2.0.0-rc1-field.zip
```

tag 不在 `refs/heads` 下，所以返回 404。  
新脚本改成：

```text
/archive/<ref>.zip
```

branch、tag、commit SHA 都可用。

---

## 3. 无法访问 GitHub：直接传递源码包

### 3.1 在开发机准备源码包

开发机执行：

```bash
cd /path/to/noise_info_toolkit
git archive --format=zip -o dist/noise_toolkit_source.zip HEAD
```

也可以直接使用发行版提供的：

```text
dist/noise_toolkit_v2.0.0-rc1-field_source.zip
```

该包只包含源码、文档、Windows 脚本和测试代码，不包含：

- `.git`；
- `.venv`；
- 数据库；
- 事件音频；
- 大型测试 TDMS。

### 3.2 传到目标机

通过 U 盘、内网共享、远程桌面复制均可：

```text
D:\noise_toolkit_source.zip
```

目标机解压：

```powershell
Expand-Archive `
  -Path D:\noise_toolkit_source.zip `
  -DestinationPath D:\NoiseToolkit `
  -Force
```

确认：

```powershell
Test-Path D:\NoiseToolkit\pyproject.toml
Test-Path D:\NoiseToolkit\deploy\windows\install.ps1
```

### 3.3 目标机已有 uv 时

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd D:\NoiseToolkit
.\deploy\windows\install.ps1 -InstallDir "D:\NoiseToolkit"
```

### 3.4 目标机没有 uv 时

如果目标机能访问 Astral/PyPI，但仍不能访问 GitHub：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd D:\NoiseToolkit
.\deploy\windows\bootstrap.ps1 `
  -InstallDir "D:\NoiseToolkit" `
  -SourceZip "D:\noise_toolkit_source.zip"
```

`bootstrap.ps1` 会：

1. 安装 uv；
2. 从本地 `SourceZip` 解压源码，不访问 GitHub；
3. 调用 `install.ps1`；
4. 用 uv 安装 Python 3.11 和依赖。

### 3.5 目标机完全离线

源码包本身只能解决“代码无法从 GitHub 下载”。  
如果目标机同时不能访问 PyPI/Astral，还需要额外的：

- Windows CPython 3.11 解释器或 uv 的离线 Python 包；
- `win_amd64` 全量 wheelhouse；
- 可选 `nssm.exe`。

这不是源码包能单独解决的。需要在一台可联网的 Windows 机器上预先生成 wheelhouse，或使用内部 PyPI 镜像。完全离线包应作为单独交付物，不建议用 Linux 上生成的 `.venv` 直接复制到 Windows。

---

## 4. 配置 `.env`

编辑：

```text
D:\NoiseToolkit\.env
```

推荐：

```dotenv
NIT_WATCH_DIR=D:/NoiseData
NIT_DB_PATH=D:/NoiseToolkit/Database/noise_info.db
NIT_EVENT_DIR=D:/NoiseToolkit/audio_events
NIT_EXPORT_DIR=D:/NoiseToolkit/exports

NIT_HOST=127.0.0.1
NIT_PORT=8000
NIT_BACKEND_URL=http://127.0.0.1:8000

NIT_ALLOWED_WATCH_ROOTS=["D:/NoiseData"]

NIT_RETENTION_MODE=debug
NIT_RETENTION_DRY_RUN=true
NIT_AUTO_EXPORT_ON_STOP=true

NIT_OPERATOR_API_KEY=请替换为长随机字符串
NIT_CALIBRATOR_API_KEY=请替换为另一个长随机字符串
NIT_ADMIN_API_KEY=请替换为另一个长随机字符串
```

注意：

- 路径统一用正斜杠；
- `NIT_ALLOWED_WATCH_ROOTS` 是 JSON 数组；
- `D:/NoiseData` 必须存在；
- 生产环境不要使用空白名单；
- `.env` 修改后必须重启后端。

---

## 5. 启动验证

### 后端

```powershell
cd D:\NoiseToolkit
.\deploy\windows\run_backend.ps1 -InstallDir "D:\NoiseToolkit"
```

### 前端

另开 PowerShell：

```powershell
cd D:\NoiseToolkit
.\deploy\windows\run_frontend.ps1 -InstallDir "D:\NoiseToolkit"
```

或直接：

```powershell
uv run uvicorn app.api.app:app --host 127.0.0.1 --port 8000 --workers 1
uv run streamlit run app/web/streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

验证：

```text
http://127.0.0.1:8501
http://127.0.0.1:8000/health/ready
```

侧边栏后端地址：

```text
http://127.0.0.1:8000
```

---

## 6. 注册服务

需要开机自启时：

```powershell
cd D:\NoiseToolkit
.\deploy\windows\install_services.ps1 -InstallDir "D:\NoiseToolkit"
```

检查：

```powershell
Get-Service NoiseBackend, NoiseFrontend
Restart-Service NoiseBackend
Restart-Service NoiseFrontend
```

日志：

```text
D:\NoiseToolkit\log\backend.log
D:\NoiseToolkit\log\backend-stdout.log
D:\NoiseToolkit\log\backend-stderr.log
```

---

## 7. 测试文件

如需在本机生成连续 TDMS 测试文件：

```powershell
uv run python -m tools.generate_continuous_test_files `
  --source D:\NoiseData `
  --out D:\NoiseData\continuous
```

或使用已有 TDMS 目录。

---

## 8. 常见问题

### 404 Not Found

旧版 bootstrap 的 tag URL 错误，使用本文档第 2 节的新脚本，或直接使用本地源码包。

### PowerShell 禁止运行脚本

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

### D 盘路径无权限

以管理员身份运行；不要把安装目录放在受保护目录。

### `Get-Command : 参数为 Null 或空`

如果 `install.ps1` 报：

```text
Get-Command : 无法对参数“Name”执行参数验证。参数为 Null 或空。
```

说明 `-UvPath` 被传成了空值。RC3 已修复：

- `-UvPath` 为空时自动回退到 `uv`；
- 自动查找：

```text
%USERPROFILE%\.local\bin\uv.exe
D:\NoiseToolkit\tools\uv.exe
```

也可以显式指定：

```powershell
.\deploy\windows\install.ps1 `
  -InstallDir "D:\NoiseToolkit" `
  -UvPath "C:\Users\lenovo\.local\bin\uv.exe"
```

### `uv sync` 仍访问 GitHub

源码包已经绕过 GitHub；如果依赖拉取失败，检查 PyPI/内部镜像，而不是 bootstrap URL。

### 端口被占用

默认 `8000`/`8501`；修改启动命令和 `NIT_CORS_ORIGINS`。

### 不要把 Linux `.venv` 复制到 Windows

虚拟环境含平台相关解释器和二进制扩展，必须在目标 Windows 上用 `uv sync` 重建。
