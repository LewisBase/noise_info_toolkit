"""
Streamlit app for noise information toolkit
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import time
import requests
import json
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import filedialog

# Set up tkinter for folder selection
root = tk.Tk()
root.withdraw()
root.wm_attributes("-topmost", 1)

def initialize_session_state():
    """Initialize all session state variables"""
    session_vars = {
        "metrics_data": {},
        "metrics_history": [],
        "audio_directory": "./audio_files",
        "polling_connect": True,
        "new_data_available": False,
        "backend_url": "http://localhost:8000"
    }
    for key, default_value in session_vars.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

def setup_page_config():
    """Set up the Streamlit page configuration"""
    st.set_page_config(
        page_title="噪声信息工具箱",
        page_icon="🔊",
        layout="wide"
    )
    st.title("🔊 噪声信息工具箱")

def render_sidebar():
    """Render the sidebar configuration panel"""
    st.sidebar.header("配置选项")
    # File path selection with folder browser
    audio_directory = st.sidebar.text_input("音频文件目录:", value=st.session_state.audio_directory, key="audio_dir_input")
    st.session_state.audio_directory = audio_directory
    # Button to select directory
    if st.sidebar.button("选择目录"):
        # Open folder selection dialog
        folder_selected = filedialog.askdirectory(master=root)
        if folder_selected:
            st.session_state.audio_directory = folder_selected
            st.rerun()
    # Create directory if it doesn't exist
    Path(audio_directory).mkdir(parents=True, exist_ok=True)
    # Check if directory exists
    if not Path(audio_directory).exists():
        st.sidebar.error(f"目录不存在: {audio_directory}")
    else:
        st.sidebar.success(f"监控目录: {audio_directory}")
    # Backend connection
    st.sidebar.subheader("后端连接")
    backend_url = st.sidebar.text_input("后端API地址:", value=st.session_state.backend_url)
    st.session_state.backend_url = backend_url
    # Auto-refresh
    auto_refresh = st.sidebar.checkbox("自动刷新", value=True)
    refresh_interval = st.sidebar.slider("刷新间隔(秒)", 1, 60, 5)
    # Auto-refresh functionality
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()
    if st.sidebar.button("诊断后端配置"):
        try:
            # 检查API根端点
            response = requests.get(f"{backend_url}/", timeout=3)
            if response.status_code == 200:
                st.sidebar.success("✓ API根端点可访问")
            else:
                st.sidebar.error("✗ API根端点不可访问")
        except requests.exceptions.RequestException as e:
            st.sidebar.error(f"连接诊断失败: {str(e)}")
    return backend_url, audio_directory

def fetch_latest_metrics(backend_url):
    """Fetch latest metrics from backend API"""
    try:
        response = requests.get(f"{backend_url}/latest_metrics", timeout=2)
        if response.status_code == 200:
            return response.json()
    except requests.exceptions.RequestException as e:
        print(f"获取最新数据失败: {e}")
    return {}

def update_metrics_data(data):
    """Update metrics data in session state directly"""
    print(f"Updating metrics data: {list(data.keys()) if isinstance(data, dict) else type(data)}")
    
    # 更新 session state 中的数据
    st.session_state.metrics_data = data
    st.session_state.new_data_available = True  # 标记有新数据
    
    # 添加到历史记录
    if "leq" in data:
        if "metrics_history" not in st.session_state:
            st.session_state.metrics_history = []
            
        st.session_state.metrics_history.append({
            "timestamp": datetime.now(),
            "leq": data.get("leq", 0),
            "laeq": data.get("laeq", 0),
            "lceq": data.get("lceq", 0)
        })
        # 保持最后500条记录
        if len(st.session_state.metrics_history) > 500:
            st.session_state.metrics_history = st.session_state.metrics_history[-500:]

def render_real_time_monitoring_tab(metrics_data, metrics_history, polling_connect):
    """Render the real-time monitoring tab"""
    st.header("实时噪声监控")
    
    # Display current file being analyzed
    current_metrics = metrics_data
    print(f"Current metrics in render: {current_metrics}")
    if "file_path" in current_metrics:
        st.info(f"当前分析文件: {current_metrics['file_path']}")
    
    # Connection status
    col1, col2 = st.columns(2)
    with col1:
        if polling_connect:
            st.success("轮询模式已启用")
        else:
            st.warning("轮询模式未启用")
    with col2:
        if st.button("启用轮询模式"):
            st.session_state.polling_connect = True
            st.rerun()
        if st.button("禁用轮询模式"):
            st.session_state.polling_connect = False
            st.rerun()
    # Display current metrics
    metrics_container = st.container()
    
    with metrics_container:
        # Create columns for metrics display
        col1, col2, col3, col4 = st.columns(4)
        # Get current metrics from parameters
        current_metrics = metrics_data
        # st.info(current_metrics)
        with col1:
            leq = current_metrics.get("leq", "N/A")
            st.metric("等效声级 (Leq)", f"{leq:.2f} dB" if leq != "N/A" else "N/A dB", delta=None)
        with col2:
            laeq = current_metrics.get("laeq", "N/A")
            st.metric("A计权等效声级 (LAeq)", f"{laeq:.2f} dB" if laeq != "N/A" else "N/A dB", delta=None)
        with col3:
            lceq = current_metrics.get("lceq", "N/A")
            st.metric("C计权等效声级 (LCeq)", f"{lceq:.2f} dB" if lceq != "N/A" else "N/A dB", delta=None)
        with col4:
            peak_spl = current_metrics.get("peak_spl", "N/A")
            st.metric("峰值声压级", f"{peak_spl:.2f} dB" if peak_spl != "N/A" else "N/A dB", delta=None)
        # Frequency band chart
        st.subheader("1/3倍频程频谱")
        if "frequency_spl" in current_metrics:
            freq_dict = current_metrics["frequency_spl"]
            if freq_dict:
                freq_bands = list(freq_dict.keys())
                spl_values = list(freq_dict.values())
                fig = px.bar(x=freq_bands, y=spl_values, labels={"x": "频率", "y": "声压级 (dB)"})
                fig.update_layout(title="1/3倍频程频谱", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无频谱数据")
        
        # Time history chart
        st.subheader("时间历程")
        if metrics_history:
            # Use actual historical data
            hist_df = pd.DataFrame(metrics_history)
            if len(hist_df) > 1:
                fig2 = px.line(hist_df, x="timestamp", y="leq", labels={"timestamp": "时间", "leq": "Leq (dB)"})
                fig2.update_layout(title="声级时间历程", showlegend=False)
                st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("暂无历史数据用于时间历程图")

def render_historical_data_tab():
    """Render the historical data analysis tab"""
    st.header("历史数据分析")
    # File upload for offline analysis
    uploaded_files = st.file_uploader("上传音频文件进行分析", type=["wav", "tdms"], accept_multiple_files=True)
    if uploaded_files:
        st.success(f"已上传 {len(uploaded_files)} 个文件")
        for uploaded_file in uploaded_files:
            st.write(f"- {uploaded_file.name}")
    # Historical data display
    st.subheader("历史记录")
    # Sample historical data
    hist_data = pd.DataFrame({
        "时间": pd.date_range(start="2023-01-01", periods=10, freq="h"),
        "Leq (dB)": np.random.uniform(50, 70, 10),
        "LAeq (dB)": np.random.uniform(45, 65, 10),
        "LCeq (dB)": np.random.uniform(52, 72, 10),
        "峰值 (dB)": np.random.uniform(60, 85, 10)
    })
    st.dataframe(hist_data, use_container_width=True)
    # Historical chart
    st.subheader("历史趋势")
    fig3 = px.line(hist_data, x="时间", y=["Leq (dB)", "LAeq (dB)", "LCeq (dB)"], 
                   title="历史声级趋势")
    st.plotly_chart(fig3, use_container_width=True)

def render_system_status_tab(backend_url, audio_directory):
    """Render the system status tab"""
    st.header("系统状态")
    # System information
    st.subheader("系统信息")
    # Check if backend API is running
    try:
        response = requests.get(f"{backend_url}/health", timeout=1)
        if response.status_code == 200:
            health_data = response.json()
            st.success("后端服务运行正常")
            st.json(health_data)
        else:
            st.warning("后端服务响应异常")
    except requests.exceptions.RequestException as e:
        st.error(f"无法连接到后端服务: {str(e)}")
    # Directory information
    st.subheader("目录信息")
    if Path(audio_directory).exists():
        file_count = len(list(Path(audio_directory).glob("*")))
        st.info(f"监控目录文件数量: {file_count}")
        # List files in directory
        files = list(Path(audio_directory).glob("*"))
        if files:
            st.write("目录中的文件:")
            for file in files[:10]:  # Show first 10 files
                st.write(f"- {file.name}")
            if len(files) > 10:
                st.write(f"... 还有 {len(files) - 10} 个文件")
    else:
        st.error("监控目录不存在")

def main():
    """Main application function"""
    initialize_session_state()
    print(f"Starting Noise Info Toolkit...{st.session_state}")
    setup_page_config()
    backend_url, audio_directory = render_sidebar()
    print(f"Update...{st.session_state}")
    
    # 如果启用了轮询模式，定期获取数据
    if st.session_state.polling_connect:
        data = fetch_latest_metrics(backend_url)
        if data:
            update_metrics_data(data)
    
    # Create tabs
    tab1, tab2, tab3 = st.tabs(["实时监控", "历史数据", "系统状态"])
    print(st.session_state)
    with tab1:
        render_real_time_monitoring_tab(
            st.session_state.metrics_data,
            st.session_state.metrics_history,
            st.session_state.polling_connect
        )
    with tab2:
        render_historical_data_tab()
    with tab3:
        render_system_status_tab(backend_url, audio_directory)

if __name__ == "__main__":
    main()