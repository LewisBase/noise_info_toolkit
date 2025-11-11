# Audio Processing Task Manager 工作流程图

```mermaid
graph TD
    A[应用程序启动] --> B[创建AudioProcessingTaskManager]
    B --> C[初始化AudioFileMonitor<br/>监控.wav和.tdms文件]
    
    C --> D[启动文件监控]
    D --> E[AudioFileMonitor.start_monitoring<br/>传入_on_audio_file_detected回调]
    
    E --> F[创建AudioFileHandler<br/>注册FileSystemObserver]
    
    F --> G[文件系统事件监听]
    
    G -- 文件创建 --> H{文件类型?}
    G -- 文件修改 --> H
    
    H -->|WAV文件| I[_on_audio_file_detected<br/>触发处理]
    H -->|TDMS文件| I
    
    I --> J[创建异步任务<br/>_process_audio_file]
    
    J --> K{_process_audio_file执行}
    K --> L{是否为<br/>TDMS文件?}
    
    L -->|是| M[使用TDMSConverter<br/>转换为WAV]
    L -->|否| N[直接处理WAV文件]
    
    M --> O[AudioProcessor<br/>处理WAV文件]
    N --> O
    
    O --> P[计算噪声指标<br/>- Leq, LAeq, LCeq<br/>- 峰值声压级<br/>- 1/3倍频程分析<br/>- Kurtosis等]
    
    P --> Q[处理完成回调<br/>调用processing_callback]
    
    Q --> R[main.py中的<br/>on_audio_processed函数]
    
    R --> S[序列化处理结果<br/>serialize_processing_results]
    
    S --> T[通过WebSocket<br/>广播给所有客户端]
    
    T --> U[Streamlit前端<br/>接收并展示数据]
    
    subgraph "核心组件"
        B
        C
        F
        K
        O
    end
    
    subgraph "回调链"
        E
        I
        Q
        R
        S
        T
    end
    
    subgraph "前端展示"
        U
    end
    
    style A fill:#FFE4B5,stroke:#333
    style U fill:#E6E6FA,stroke:#333
    style B fill:#87CEEB,stroke:#333
    style C fill:#87CEEB,stroke:#333
    style F fill:#87CEEB,stroke:#333
    style K fill:#87CEEB,stroke:#333
    style O fill:#87CEEB,stroke:#333
    style R fill:#98FB98,stroke:#333
    style T fill:#FFB6C1,stroke:#333
```

## 组件交互说明

### 1. 启动阶段
1. FastAPI应用启动时创建[AudioProcessingTaskManager](file://d:/Study_and_Work/0.Main/0.Current/%E6%B5%99%E5%BB%BA/2.Code/Mine/noise_info_toolkit/app/core/background_tasks.py#L16-L77)
2. [AudioProcessingTaskManager](file://d:/Study_and_Work/0.Main/0.Current/%E6%B5%99%E5%BB%BA/2.Code/Mine/noise_info_toolkit/app/core/background_tasks.py#L16-L77)初始化[AudioFileMonitor](file://d:/Study_and_Work/0.Main/0.Current/%E6%B5%99%E5%BB%BA/2.Code/Mine/noise_info_toolkit/app/core/file_monitor.py#L36-L56)用于监控指定目录
3. 注册处理完成后的回调函数[on_audio_processed](file://d:/Study_and_Work/0.Main/0.Current/%E6%B5%99%E5%BB%BA/2.Code/Mine/noise_info_toolkit/app/main.py#L27-L35)

### 2. 监控阶段
1. [AudioFileMonitor]使用watchdog库监听文件系统事件
2. [AudioFileHandler]捕获文件创建/修改事件
3. 触发内部回调函数[_on_audio_file_detected]

### 3. 处理阶段
1. [_on_audio_file_detected]创建异步任务[_process_audio_file]
2. [_process_audio_file]根据文件类型决定是否需要转换
3. 使用[AudioProcessor]处理音频并计算噪声指标

### 4. 结果通知阶段
1. 处理完成后调用注册的回调函数
2. [on_audio_processed]序列化结果并广播给所有WebSocket客户端
3. Streamlit前端接收数据并展示