# 噪声剂量计项目升级设计方案

## 一、项目现状分析

### 1.1 当前功能概览

| 功能模块 | 当前状态 | 说明 |
|---------|---------|------|
| 基础指标计算 | ✅ | Leq, LAeq, LCeq, Peak SPL, 1/3倍频程 |
| 峭度计算 | ✅ | 全频段及分频段峭度 |
| TDMS文件支持 | ✅ | 自动转换并处理 |
| 实时文件监控 | ✅ | watchdog监控新文件 |
| 数据库存储 | ✅ | SQLite + SQLAlchemy |
| Web界面 | ✅ | Streamlit前端 |
| **噪声剂量计算** | ❌ | **需要新增** |
| **事件检测** | ❌ | **需要新增** |
| **环形缓冲** | ❌ | **需要新增** |
| **TWA计算** | ❌ | **需要新增** |
| **多标准支持** | ❌ | **需要新增** |

### 1.2 当前数据表结构

当前仅使用简单的 `processing_result` + `processing_metrics` 表结构，未完全遵循白皮书中的 **3+1 数据模型**。

---

## 二、噪声暴露累积量（Dose%）计算方案

### 2.1 标准参数定义

根据白皮书和权威资料，各标准的参数如下：

| 标准 | 准则级 (Lc) | 交换率 (ER) | 阈值 (LT) | 参考时长 (Tref) | 剂量限值 |
|------|------------|------------|----------|----------------|---------|
| **NIOSH** | 85 dBA | 3 dB | 0 dBA | 8 h | 100% |
| **OSHA_PEL** | 90 dBA | 5 dB | 0 dBA | 8 h | 100% |
| **OSHA_HCA** | 85 dBA | 5 dB | 0 dBA | 8 h | 100% |
| **EU_ISO** | 85 dBA | 3 dB | 0 dBA | 8 h | 100% |

### 2.2 核心计算公式

#### 2.2.1 允许暴露时间（T）
```
T = Tref / 2^((L - Lc) / ER)

其中：
- Tref = 8 小时（参考时长）
- L = 实测声级 (dBA)
- Lc = 准则级 (dBA)
- ER = 交换率 (dB)
```

**示例**：
- NIOSH标准下，95 dBA的允许时间：T = 8 / 2^((95-85)/3) = 8 / 2^3.33 = **~0.78 小时 (47分钟)**
- OSHA_PEL标准下，95 dBA的允许时间：T = 8 / 2^((95-90)/5) = 8 / 2^1 = **4 小时**

#### 2.2.2 剂量分数（Dose%）

**对于离散时间段**：
```
Dose% = 100 × Σ(Ci / Ti) = 100 × Σ[ (ti / Tref) × 2^((Li - Lc) / ER) ]

其中：
- ti = 第i个时间段的时长（小时）
- Li = 第i个时间段的等效声级 (dBA)
- Tref = 8小时
```

**对于连续测量**（每秒或每帧计算）：
```
Dose% = 100 × (1/Tref) × ∫ 2^((L(t) - Lc) / ER) dt

在离散实现中：
Dose%_increment = 100 × (Δt / Tref) × 2^((LAeq - Lc) / ER)
```

#### 2.2.3 时间加权平均声级（TWA）

```
# NIOSH / ISO
TWA = 10 × log10(Dose% / 100) + Lc

# OSHA (特殊系数)
TWA = 16.61 × log10(Dose% / 100) + Lc
```

#### 2.2.4 日噪声暴露级（LEX,8h / Lep'd）

ISO/EU标准中使用：
```
LEX,8h = 10 × log10( (1/Tref) × ∫ 10^(L(t)/10) dt )

或从Dose计算：
LEX,8h = Lc + 10 × log10(Dose% / 100)
```

### 2.3 模块设计方案

#### 2.3.1 新增文件：`app/core/dose_calculator.py`

```python
class DoseProfile:
    """剂量计算标准配置"""
    def __init__(self, name: str, criterion_level: float, exchange_rate: float, 
                 threshold: float = 0, reference_duration: float = 8.0):
        self.name = name
        self.criterion_level = criterion_level  # Lc
        self.exchange_rate = exchange_rate      # ER
        self.threshold = threshold              # LT
        self.reference_duration = reference_duration  # Tref (hours)

class DoseCalculator:
    """噪声剂量计算器"""
    
    # 预定义标准
    PROFILES = {
        "NIOSH": DoseProfile("NIOSH", 85.0, 3.0, 0.0, 8.0),
        "OSHA_PEL": DoseProfile("OSHA_PEL", 90.0, 5.0, 0.0, 8.0),
        "OSHA_HCA": DoseProfile("OSHA_HCA", 85.0, 5.0, 0.0, 8.0),
        "EU_ISO": DoseProfile("EU_ISO", 85.0, 3.0, 0.0, 8.0),
    }
    
    def calculate_dose_increment(self, laeq: float, duration_s: float, 
                                  profile: DoseProfile) -> float:
        """计算单个时间段的剂量增量"""
        if laeq < profile.threshold:
            return 0.0
        
        duration_h = duration_s / 3600.0
        # Dose% = 100 × (dt/Tref) × 2^((L-Lc)/ER)
        dose_inc = 100.0 * (duration_h / profile.reference_duration) * \
                   (2 ** ((laeq - profile.criterion_level) / profile.exchange_rate))
        return dose_inc
    
    def calculate_twa(self, total_dose: float, profile: DoseProfile) -> float:
        """从总剂量计算TWA"""
        if profile.name.startswith("OSHA"):
            return 16.61 * np.log10(total_dose / 100.0) + profile.criterion_level
        else:
            return 10.0 * np.log10(total_dose / 100.0) + profile.criterion_level
    
    def calculate_lex(self, total_dose: float, profile: DoseProfile) -> float:
        """计算LEX,8h (ISO标准)"""
        return 10.0 * np.log10(total_dose / 100.0) + profile.criterion_level
```

#### 2.3.2 数据库表扩展

**新增 `dose_profiles` 表**：
```sql
CREATE TABLE dose_profiles (
    id INTEGER PRIMARY KEY,
    profile_name VARCHAR(50) UNIQUE,  -- NIOSH, OSHA_PEL, etc.
    criterion_level_dBA FLOAT,         -- 准则级
    exchange_rate_dB FLOAT,            -- 交换率
    threshold_dBA FLOAT,               -- 阈值
    reference_duration_h FLOAT,        -- 参考时长
    description TEXT
);
```

**新增 `time_history` 表**（每秒一行）：
```sql
CREATE TABLE time_history (
    id INTEGER PRIMARY KEY,
    session_id VARCHAR(100),
    device_id VARCHAR(100),
    profile_name VARCHAR(50),
    timestamp_utc DATETIME,
    duration_s FLOAT,
    LAeq_dB FLOAT,
    LCeq_dB FLOAT,
    LZeq_dB FLOAT,
    LAFmax_dB FLOAT,
    LZpeak_dB FLOAT,
    LCpeak_dB FLOAT,
    dose_frac_niosh FLOAT,      -- NIOSH剂量增量
    dose_frac_osha_pel FLOAT,   -- OSHA_PEL剂量增量
    dose_frac_osha_hca FLOAT,   -- OSHA_HCA剂量增量
    dose_frac_eu_iso FLOAT,     -- EU_ISO剂量增量
    wearing_state BOOLEAN,
    overload_flag BOOLEAN,
    underrange_flag BOOLEAN
);
```

**新增 `session_summary` 表**：
```sql
CREATE TABLE session_summary (
    id INTEGER PRIMARY KEY,
    session_id VARCHAR(100),
    profile_name VARCHAR(50),
    start_time_utc DATETIME,
    end_time_utc DATETIME,
    total_duration_h FLOAT,
    LAeq_T FLOAT,               -- 全程等效声级
    LEX_8h FLOAT,               -- 日暴露级
    total_dose_pct FLOAT,       -- 总剂量%
    TWA FLOAT,                  -- 时间加权平均
    peak_max_dB FLOAT,          -- 最大峰值
    events_count INTEGER        -- 事件数量
);
```

---

## 三、事件检测与环形缓冲方案

### 3.1 事件检测算法

根据白皮书，事件触发条件（可组合）：

#### 3.1.1 触发条件

| 条件类型 | 阈值 | 说明 |
|---------|------|------|
| **声级触发** | LZeq_125 ≥ 90-95 dB | 125ms窗口Z计权等效声级 |
| **峰值触发** | LCpeak ≥ 130 dB | C计权峰值声压级 |
| **斜率触发** | ΔLZeq ≥ 10 dB/50ms | 声级变化率 |

#### 3.1.2 去抖动机制

```python
class EventDetector:
    """冲击噪声事件检测器"""
    
    def __init__(self, 
                 leq_threshold: float = 90.0,      # LZeq_125阈值
                 peak_threshold: float = 130.0,     # LCpeak阈值
                 slope_threshold: float = 10.0,     # dB/50ms
                 debounce_s: float = 0.5):          # 去抖动时间
        self.leq_threshold = leq_threshold
        self.peak_threshold = peak_threshold
        self.slope_threshold = slope_threshold
        self.debounce_s = debounce_s
        
        self.last_event_time = None
        self.event_counter = 0
    
    def detect_event(self, lzeq_125: float, lcpeak: float, 
                     current_time: datetime) -> bool:
        """检测是否触发事件"""
        # 检查去抖动
        if self.last_event_time is not None:
            if (current_time - self.last_event_time).total_seconds() < self.debounce_s:
                return False
        
        # 检查触发条件
        triggered = False
        
        if lzleq_125 >= self.leq_threshold:
            triggered = True
        elif lcpeak >= self.peak_threshold:
            triggered = True
        # 斜率检测需要历史数据，此处简化
        
        if triggered:
            self.last_event_time = current_time
            self.event_counter += 1
            return True
        
        return False
```

### 3.2 环形缓冲区设计

#### 3.2.1 功能需求

- **缓冲时长**：≥ 12 秒（白皮书要求）
- **触发前保留**：2 秒（pre-trigger）
- **触发后录制**：8 秒（post-trigger）
- **存储格式**：WAV/FLAC

#### 3.2.2 实现方案

```python
class RingBuffer:
    """环形波形缓冲区"""
    
    def __init__(self, sample_rate: int = 48000, 
                 buffer_duration_s: float = 12.0,
                 pretrigger_s: float = 2.0,
                 posttrigger_s: float = 8.0):
        self.sample_rate = sample_rate
        self.buffer_size = int(sample_rate * buffer_duration_s)
        self.pretrigger_samples = int(sample_rate * pretrigger_s)
        self.posttrigger_samples = int(sample_rate * posttrigger_s)
        
        self.buffer = np.zeros(self.buffer_size, dtype=np.float32)
        self.write_index = 0
        self.is_full = False
    
    def write(self, samples: np.ndarray):
        """写入新样本到环形缓冲"""
        samples_to_write = len(samples)
        
        if self.write_index + samples_to_write <= self.buffer_size:
            self.buffer[self.write_index:self.write_index + samples_to_write] = samples
        else:
            # 环绕写入
            first_part = self.buffer_size - self.write_index
            self.buffer[self.write_index:] = samples[:first_part]
            self.buffer[:samples_to_write - first_part] = samples[first_part:]
        
        self.write_index = (self.write_index + samples_to_write) % self.buffer_size
        if not self.is_full and self.write_index < samples_to_write:
            self.is_full = True
    
    def get_pretrigger_data(self) -> np.ndarray:
        """获取触发前数据（用于事件录音）"""
        if self.write_index >= self.pretrigger_samples:
            return self.buffer[self.write_index - self.pretrigger_samples:self.write_index]
        else:
            # 环绕读取
            first_part = self.pretrigger_samples - self.write_index
            return np.concatenate([
                self.buffer[self.buffer_size - first_part:],
                self.buffer[:self.write_index]
            ])
    
    def save_event_audio(self, event_id: str, posttrigger_data: np.ndarray,
                         output_dir: str = "./audio_events") -> str:
        """保存事件音频（pre + post trigger）"""
        pretrigger_data = self.get_pretrigger_data()
        full_event_audio = np.concatenate([pretrigger_data, posttrigger_data])
        
        # 保存为WAV
        output_path = f"{output_dir}/{event_id}.wav"
        sf.write(output_path, full_event_audio, self.sample_rate)
        return output_path
```

### 3.3 EventLog 表结构

```sql
CREATE TABLE event_log (
    id INTEGER PRIMARY KEY,
    session_id VARCHAR(100),
    event_id VARCHAR(100),
    start_time_utc DATETIME,
    end_time_utc DATETIME,
    duration_s FLOAT,
    trigger_type VARCHAR(50),       -- 'leq', 'peak', 'slope'
    LZpeak_dB FLOAT,
    LCpeak_dB FLOAT,
    LAeq_event_dB FLOAT,
    SEL_LAE_dB FLOAT,               -- 声暴露级
    beta_excess_event_Z FLOAT,      -- 超额峰度
    audio_file_path VARCHAR(500),
    pretrigger_s FLOAT,
    posttrigger_s FLOAT,
    notes TEXT
);
```

---

## 四、缺失功能及实现难度评估

### 4.1 功能缺口清单

| 功能 | 优先级 | 改动范围 | 实现难度 | 依赖 |
|------|-------|---------|---------|------|
| **噪声剂量计算** | P0 | 中 | 低 | 无 |
| **TWA计算** | P0 | 小 | 低 | 剂量计算 |
| **多标准支持** | P0 | 中 | 低 | 剂量计算 |
| **TimeHistory表** | P0 | 大 | 中 | 数据库迁移 |
| **事件检测** | P1 | 中 | 中 | 滑动窗口 |
| **环形缓冲** | P1 | 中 | 中 | 内存管理 |
| **EventLog表** | P1 | 中 | 低 | 事件检测 |
| **Metadata表** | P2 | 中 | 低 | 数据录入 |
| **Session管理** | P2 | 大 | 中 | 架构调整 |
| **统计指标(Ln)** | P2 | 小 | 低 | 后处理 |
| **LAFmax/LASmax** | P2 | 小 | 低 | 时间加权 |
| **SEL/LAE计算** | P2 | 小 | 低 | 事件分析 |
| **质控标记** | P2 | 中 | 低 | 阈值判断 |
| **过载/欠载检测** | P2 | 小 | 低 | 阈值判断 |
| **真峰值检测** | P3 | 小 | 中 | 模拟电路模型 |
| **1/3倍频程优化** | P3 | 中 | 中 | IEC 61260 |
| **温度/湿度记录** | P3 | 小 | 低 | 传感器接口 |
| **频响补偿** | P4 | 大 | 高 | 校准数据 |
| **温度补偿** | P4 | 大 | 高 | 硬件接口 |

### 4.2 详细评估

#### P0 优先级（必需）

**1. 噪声剂量计算（Dose%）**
- **改动范围**：中
- **实现难度**：⭐⭐（低）
- **工作项**：
  - 新增 `dose_calculator.py` 模块
  - 实现4种标准的剂量计算
  - 修改 `AudioProcessor` 集成剂量计算
  - 新增数据库表 `dose_profiles`、`time_history`
- **测试要求**：单元测试覆盖所有标准、边界值测试

**2. TimeHistory 数据表**
- **改动范围**：大
- **实现难度**：⭐⭐⭐（中）
- **工作项**：
  - 数据库模型迁移
  - 修改数据存储逻辑（从单文件结果 → 时间历程）
  - 修改 API 接口
- **风险评估**：需要数据迁移，影响现有查询接口

#### P1 优先级（重要）

**3. 事件检测**
- **改动范围**：中
- **实现难度**：⭐⭐⭐（中）
- **工作项**：
  - 实现滑动窗口计算 LZeq_125
  - 实现触发条件判断
  - 去抖动机制
- **依赖**：需要实时处理流式数据

**4. 环形缓冲**
- **改动范围**：中
- **实现难度**：⭐⭐⭐（中）
- **工作项**：
  - 实现环形缓冲区
  - 预触发/后触发音频保存
  - 内存管理优化
- **风险**：内存占用（48kHz × 12s × 4字节 ≈ 2.3MB/通道）

#### P2 优先级（增强）

**5. Metadata 管理**
- 仪器信息、校准记录、采样参数
- 难度：⭐⭐（低）

**6. 统计指标（Ln）**
- L10, L50, L90 等分位声级
- 难度：⭐（很简单）

**7. 质控标记**
- 过载/欠载/佩戴状态检测
- 难度：⭐（很简单）

#### P3/P4 优先级（未来）

- 真峰值检测（需要模拟电路知识）
- 频响/温度补偿（需要硬件支持）

---

## 五、实施路线图

### 阶段一：核心剂量计算（Week 1-2）

**目标**：实现完整的剂量计算和多标准支持

**任务清单**：
1. [ ] 创建 `app/core/dose_calculator.py` 模块
2. [ ] 实现 DoseProfile 配置类
3. [ ] 实现 DoseCalculator 计算类
4. [ ] 扩展 `AudioProcessor` 集成剂量计算
5. [ ] 新增 `dose_profiles` 数据库表
6. [ ] 编写单元测试（覆盖率 > 80%）
7. [ ] 更新 API 接口返回剂量数据
8. [ ] 更新 Streamlit 界面显示剂量

**验收标准**：
- ✅ 能正确计算 NIOSH/OSHA/EU_ISO 四种标准的剂量
- ✅ 单元测试通过
- ✅ 前端界面显示 Dose% 和 TWA

### 阶段二：时间历程数据（Week 3）

**目标**：建立 TimeHistory 表，存储每秒数据

**任务清单**：
1. [ ] 设计 `time_history` 表结构
2. [ ] 数据库迁移脚本
3. [ ] 修改数据处理流程（每秒保存一条记录）
4. [ ] 新增 Session 概念（会话管理）
5. [ ] 实现 Session 级剂量累计
6. [ ] 新增 `session_summary` 表
7. [ ] 更新查询接口支持时间范围筛选

**验收标准**：
- ✅ 每秒数据保存到 time_history
- ✅ 能按 Session 查询累计剂量
- ✅ 现有功能不中断

### 阶段三：事件检测（Week 4）

**目标**：实现冲击噪声事件检测和记录

**任务清单**：
1. [ ] 实现滑动窗口计算 LZeq_125
2. [ ] 实现 EventDetector 类
3. [ ] 实现 RingBuffer 类
4. [ ] 新增 `event_log` 表
5. [ ] 事件触发时保存音频片段
6. [ ] 事件音频文件管理
7. [ ] 前端事件列表展示

**验收标准**：
- ✅ 能正确检测到峰值事件
- ✅ 事件音频正确保存（pre 2s + post 8s）
- ✅ 单元测试通过

### 阶段四：功能增强（Week 5-6）

**目标**：补充其他重要功能

**任务清单**：
1. [ ] Metadata 表和录入界面
2. [ ] Ln 统计指标计算（L10, L50, L90）
3. [ ] 质控标记（过载/欠载检测）
4. [ ] SEL/LAE 计算
5. [ ] 性能优化
6. [ ] 集成测试
7. [ ] 文档更新

**验收标准**：
- ✅ 所有单元测试通过
- ✅ 集成测试通过
- ✅ 文档完整

---

## 六、接口设计

### 6.1 新增 API 接口

```python
# GET /dose_profiles
# 获取所有剂量计算标准配置

# GET /session/{session_id}/dose?profile=NIOSH
# 获取指定 Session 的累计剂量

# GET /session/{session_id}/time_history
# 获取时间历程数据

# GET /session/{session_id}/events
# 获取事件列表

# POST /session
# 创建新 Session（开始测量）

# PUT /session/{session_id}
# 结束 Session
```

### 6.2 修改现有接口

```python
# POST /latest_metrics
# 新增返回字段：
# - dose_niosh: float
# - dose_osha_pel: float  
# - dose_osha_hca: float
# - dose_eu_iso: float
# - twa_niosh: float
# - twa_osha: float
# - lex_8h: float
```

---

## 七、数据库迁移方案

### 7.1 迁移脚本

```python
# migration_001_add_dose_tables.py

def upgrade():
    # 1. 创建 dose_profiles 表并插入标准数据
    # 2. 创建 time_history 表
    # 3. 创建 event_log 表
    # 4. 创建 session_summary 表
    # 5. 修改 processing_result 表，添加 session_id 字段
    pass

def downgrade():
    # 回滚操作
    pass
```

### 7.2 数据兼容性

- 保留现有 `processing_result` 表用于单文件结果
- 新增表用于时间历程和事件数据
- 通过 `session_id` 关联新旧数据

---

## 八、测试策略

### 8.1 单元测试

```python
# test_dose_calculator.py

class TestDoseCalculator:
    def test_niosh_dose_calculation(self):
        """测试 NIOSH 标准剂量计算"""
        calc = DoseCalculator()
        profile = DoseCalculator.PROFILES["NIOSH"]
        
        # 85 dBA 持续 8 小时 = 100% 剂量
        dose = calc.calculate_dose_increment(85.0, 8*3600, profile)
        assert abs(dose - 100.0) < 0.1
        
        # 88 dBA 持续 8 小时 = 200% 剂量 (3dB翻倍)
        dose = calc.calculate_dose_increment(88.0, 8*3600, profile)
        assert abs(dose - 200.0) < 0.1
    
    def test_osha_dose_calculation(self):
        """测试 OSHA 标准剂量计算"""
        calc = DoseCalculator()
        profile = DoseCalculator.PROFILES["OSHA_PEL"]
        
        # 90 dBA 持续 8 小时 = 100% 剂量
        dose = calc.calculate_dose_increment(90.0, 8*3600, profile)
        assert abs(dose - 100.0) < 0.1
        
        # 95 dBA 持续 8 小时 = 200% 剂量 (5dB翻倍)
        dose = calc.calculate_dose_increment(95.0, 8*3600, profile)
        assert abs(dose - 200.0) < 0.1
```

### 8.2 集成测试

- 完整文件处理流程测试
- 数据库读写测试
- API 接口测试

---

## 九、风险评估与应对

| 风险 | 概率 | 影响 | 应对措施 |
|------|-----|------|---------|
| 数据库迁移失败 | 低 | 高 | 备份现有数据库，提供回滚脚本 |
| 性能下降 | 中 | 中 | 批量插入优化，异步处理 |
| 内存溢出（环形缓冲） | 低 | 中 | 限制缓冲区大小，监控内存使用 |
| 标准计算错误 | 低 | 高 | 参考权威资料，交叉验证计算结果 |
| 单元测试失败 | 中 | 中 | 先修复测试再提交代码 |

---

## 十、总结

本设计方案涵盖：

1. **噪声暴露累积量计算**：支持 NIOSH、OSHA_PEL、OSHA_HCA、EU_ISO 四种标准，实现 Dose%、TWA、LEX,8h 计算

2. **事件检测与环形缓冲**：实现 LZeq_125 滑动窗口、多条件触发、12秒环形缓冲、pre/post触发音频保存

3. **数据库扩展**：新增 TimeHistory、EventLog、Session 等表，支持白皮书 3+1 数据模型

4. **实施路线图**：分4个阶段实施，每个阶段有明确的验收标准

5. **风险管控**：识别主要风险并制定应对措施

---

**审核人意见**：

| 审核人 | 意见 | 签名 | 日期 |
|-------|-----|-----|-----|
| | | | |

**修改记录**：

| 版本 | 日期 | 修改内容 | 修改人 |
|-----|-----|---------|-------|
| v1.0 | 2026-02-13 | 初稿 | Liu Hengjiang |
