# 导出 CSV 字段说明

停止监测后会在 `exports/` 生成三张表：

```text
results_YYYYmmdd_HHMMSS.csv
file_results_YYYYmmdd_HHMMSS.csv
events_YYYYmmdd_HHMMSS.csv
```

---

## 1. `results_*.csv`：10 s 明细

**一行 = 一个通道的一个 10 s 计算窗口。**

一个 60 s 的 TDMS 文件通常会产生 6 行（最后不足 10 s 也可能一行）。

关键字段：

| 字段 | 含义 |
|---|---|
| `id` | `time_history` 表主键，仅用于数据库排序/定位，不是文件 ID |
| `session_id` | 测量会话 ID；通常同一通道、同一次连续监测共用一个会话 |
| `file_result_id` | 该 10 s 数据所属的 `file_results.id`，用来关联源文件 |
| `channel` | TDMS 通道名，例如 `Microphone` |
| `timestamp_utc` | 文件内数据时间（来自 TDMS） |
| `recorded_at` | 本行写入数据库的时间（用于区分“本次监测”与历史数据） |
| `duration_s` | 本行覆盖时长，通常 10 s |
| `laeq/lceq/lzeq` | 等效声级 |
| `laf/las/lcf/lcs` | 时间计权瞬时值 |
| `lafmax/.../lzpeak/...` | 峰值/最大值 |
| `dose_*` | 当前窗口的剂量百分比 |
| `freq_spl` | 1/3 倍频程 JSON |
| `calibrated/level_unit` | 是否校准、单位（dB SPL 或 dBFS） |

示例关系：

```text
file_results.id = 7
  └── results.file_result_id = 7
        ├── timestamp 10:00:00
        ├── timestamp 10:00:10
        └── ...
```

---

## 2. `file_results_*.csv`：文件汇总

**一行 = 一个输入文件的一个通道。**

例如一个双通道 TDMS 文件会产生两行：CH1、CH2。

关键字段：

| 字段 | 含义 |
|---|---|
| `id` | `file_results` 主键，文件结果 ID |
| `session_id` | 该文件所属测量会话 |
| `job_id` | 处理任务 ID（`jobs.id`） |
| `file_path/file_name` | 源文件 |
| `file_size/file_mtime_ns` | 文件身份信息，用于幂等 |
| `channel` | 通道 |
| `start_time_utc/end_time_utc` | 文件内数据起止时间 |
| `duration_s/sample_rate` | 文件时长/采样率 |
| `laeq/.../lzpeak/...` | 整个文件的汇总指标 |
| `dose_*` | 整个文件的剂量 |
| `event_count` | 关联事件数 |
| `status/error` | 处理状态/错误 |
| `processor_version` | 处理器版本 |

同一个文件路径如果 size/mtime 变化，会生成新的 `file_results` 行。

---

## 3. `events_*.csv`：事件

**一行 = 一个异常事件。**

关键字段：

| 字段 | 含义 |
|---|---|
| `id` | `events` 主键 |
| `event_id` | 事件 UUID，用于 API/音频访问 |
| `file_result_id` | 事件所属文件结果 |
| `session_id` | 会话 |
| `start_time_utc/end_time_utc` | 事件时间 |
| `event_type/severity` | 1/2/3 与 20/50/80 |
| `trigger_flags` | 触发维度 JSON |
| `audio_path/audio_sha256` | 事件音频 |
| `review_state/reviewed_by/review_note` | 人工审核 |

---

## 4. 常用查询

按文件看所有 10 s 数据：

```sql
SELECT *
FROM time_history
WHERE file_result_id = 7
ORDER BY timestamp_utc;
```

按文件看汇总：

```sql
SELECT *
FROM file_results
WHERE id = 7;
```

从 10 s 数据回溯文件：

```sql
SELECT t.timestamp_utc, t.laeq, f.file_name
FROM time_history t
JOIN file_results f ON f.id = t.file_result_id
ORDER BY t.timestamp_utc;
```

---

## 5. 为什么 `id`、`session_id`、`file_result_id` 同时存在？

- `id`：这张表内部的行号，只在本表有意义；
- `session_id`：一次测量会话，用于把多个文件/通道的数据归到同一测量过程；
- `file_result_id`：真正指向“哪个输入文件/通道”的外键；
- `job_id`：处理任务，用于看重试/失败；
- `event_id`：事件 UUID，用于访问事件音频和审核。

不要用 `results.id` 当文件 ID；文件 ID 是 `file_result_id`，对应 `file_results.id`。
