# 7 天 Soak 验收

## 前置

- `retention_mode=debug`（绝不删除）；
- 已写入校准记录，`/health/ready` 的 `calibrated=true`；
- 已配置 `NIT_ALLOWED_WATCH_ROOTS`；
- 服务由 NSSM 托管，日志/DB/音频在本地盘。

## 执行

```powershell
# 每 5 分钟检查一次，运行 7 天
.\deploy\windows\soak_test.ps1 -ApiBase http://127.0.0.1:8000 -Days 7 -IntervalSeconds 300
```

期间持续向监控目录投放 TDMS（建议覆盖 8k/48k、单/多通道、静音、过载、长文件）。

## 每日检查

- `/health/ready` 200；
- `system_events` 无非预期错误；
- `jobs` failed=0，`quarantined` 已确认；
- `time_history` 时间连续，无 NaN/Inf；
- 事件音频文件存在且 sha256 校验通过；
- 磁盘剩余空间 > 20%；
- `retention_mode=debug`，源文件/事件音频无删除。

## 结束

```powershell
.\deploy\windows\soak_report.ps1 -Csv C:\NoiseToolkit\log\soak_YYYYmmdd_HHMMSS.csv
```

验收标准：

1. 7×24 小时 API/UI 可用；
2. 无源音频删除；
3. 无未处理/丢失文件；
4. 事件音频可播放且校验通过；
5. 失败 job 为 0，系统异常均有解释；
6. 通过后再进入 production dry-run 7 天。
