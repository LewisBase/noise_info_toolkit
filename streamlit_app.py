"""
Streamlit app for noise information toolkit
"""
import requests
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from datetime import datetime
from functional import seq

# Set up tkinter for folder selection
root = tk.Tk()
root.withdraw()
root.wm_attributes("-topmost", 1)


def initialize_session_state():
    """Initialize all session state variables"""
    session_vars = {
        "audio_directory": "./audio_files",
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


def change_watch_folder(new_folder):
    """Change the watch directory"""
    try:
        response = requests.post(
            f"{st.session_state.backend_url}/change_watch_directory",
            json={"watch_directory": new_folder},
            timeout=5
        )
        if response.status_code == 200:
            st.sidebar.success("成功更新监控目录")
        else:
            st.sidebar.error("更新监控目录失败")
    except requests.exceptions.RequestException as e:
        st.sidebar.error(f"更新监控目录时出错: {str(e)}")


def render_sidebar():
    """Render the sidebar configuration panel"""
    st.sidebar.header("配置选项")

    # File path selection with folder browser
    audio_directory = st.sidebar.text_input(
        "音频文件目录:", value=st.session_state.audio_directory, key="audio_dir_input")
    # 如果目录发生变化，则调用后端API更新监控目录
    if audio_directory != st.session_state.audio_directory:
        change_watch_folder(new_folder=audio_directory)
    # Button to select directory
    if st.sidebar.button("选择目录"):
        # Open folder selection dialog
        folder_selected = filedialog.askdirectory(master=root)
        if folder_selected:
            st.session_state.audio_directory = folder_selected
            # 调用后端API更新监控目录
            change_watch_folder(new_folder=folder_selected)
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
    backend_url = st.sidebar.text_input(
        "后端API地址:", value=st.session_state.backend_url)
    st.session_state.backend_url = backend_url

    # # Auto-refresh
    # auto_refresh = st.sidebar.checkbox("自动刷新", value=False)
    # refresh_interval = st.sidebar.slider("刷新间隔(秒)", 1, 60, 5)
    # # Auto-refresh functionality
    # if auto_refresh:
    #     time.sleep(refresh_interval)
    #     st.rerun()

    # Diagnose backend configuration
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

    # 监测麦克风通道
    st.sidebar.subheader("麦克风通道")
    microphone_channel = st.sidebar.multiselect(
        label="麦克风通道:", options=["CH1", "CH2"],default=["CH1"],
        help="选择要查看的麦克风通道。",
        key="microphone_channel")

    # 开始时间
    st.sidebar.subheader("监测开始时间")
    start_time = st.sidebar.text_input(
        "开始时间:", value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), key="start_time")
    
    print(backend_url)
    print(audio_directory)
    print(microphone_channel)
    print(start_time)
    return backend_url, audio_directory, microphone_channel, start_time


def fetch_latest_metrics(
    backend_url: str,
    microphone_channel: str = "CH1"
) -> dict:
    """Fetch latest metrics from backend API"""
    try:
        url = f"{backend_url}/latest_metrics"
        data = {"microphone_channel": microphone_channel}
        response = requests.post(url, json=data)
        if response.status_code == 200:
            result = response.json()
            return result.get("data", {})
    except requests.exceptions.RequestException as e:
        print(f"获取最新数据失败: {e}")
        return {}


def fetch_history_metrics(
    backend_url: str,
    start_time: str,
    microphone_channel: str = "CH1"
) -> list:
    """Fetch latest metrics from backend API"""
    try:
        url = f"{backend_url}/all_metrics"
        data = {"microphone_channel": microphone_channel,
                "start_time": start_time}
        response = requests.post(url, json=data)
        if response.status_code == 200:
            result = response.json()
            return result.get("data", [])
    except requests.exceptions.RequestException as e:
        print(f"获取最新数据失败: {e}")
        return []


def render_real_time_monitoring_tab(
    backend_url: str,
    microphone_channels: list, 
    start_time: str
    ):
    """Render the real-time monitoring tab"""
    st.header("实时噪声监控")

    # Display current metrics
    metrics_container = st.container()
    with metrics_container:
        # 为每个通道创建一个栏
        for channel_name in microphone_channels:
            st.subheader(f"{channel_name} 通道信息")
            channel_data = fetch_latest_metrics(
                backend_url=backend_url, microphone_channel=channel_name)
            if not channel_data:
                st.warning("没有可用数据")
                continue
            
            st.info(f"当前分析文件: {channel_data['file_path']}")
            metrics_data = channel_data["metrics"]
            # Create columns for metrics display
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                leq = metrics_data.get("leq", "N/A")
                st.metric(
                    "等效声级 (Leq)", f"{leq:.2f} dB" if leq != "N/A" else "N/A dB", delta=None)
            with col2:
                laeq = metrics_data.get("laeq", "N/A")
                st.metric(
                    "A计权等效声级 (LAeq)", f"{laeq:.2f} dB" if laeq != "N/A" else "N/A dB", delta=None)
            with col3:
                lceq = metrics_data.get("lceq", "N/A")
                st.metric(
                    "C计权等效声级 (LCeq)", f"{lceq:.2f} dB" if lceq != "N/A" else "N/A dB", delta=None)
            with col4:
                peak_spl = metrics_data.get("peak_spl", "N/A")
                st.metric(
                    "峰值声压级", f"{peak_spl:.2f} dB" if peak_spl != "N/A" else "N/A dB", delta=None)
            # Frequency band chart
            st.markdown("##### 1/3倍频程频谱")
            if "frequency_spl" in metrics_data:
                freq_dict = metrics_data["frequency_spl"]
                if freq_dict:
                    freq_bands = list(freq_dict.keys())
                    spl_values = list(freq_dict.values())
                    fig = px.bar(x=freq_bands, y=spl_values, labels={
                                 "x": "频率", "y": "声压级 (dB)"})
                    fig.update_layout(
                        title=f"{channel_name} 1/3倍频程频谱", showlegend=False)
                    st.plotly_chart(fig, width="stretch")
            else:
                st.info("暂无频谱数据")
            st.markdown("---")  # 分隔线
            # Time history chart - 显示所有通道的历史数据
            st.subheader("时间历程")
            metrics_history = fetch_history_metrics(
                backend_url=backend_url,
                start_time=start_time,
                microphone_channel=channel_name
            )
            if metrics_history:
                # Use actual historical data
                metrics_data_seq = seq(metrics_history).map(lambda x: {"timestamp": x["timestamp"],"leq": x["metrics"]["leq"]}).list()
                hist_df = pd.DataFrame(metrics_data_seq)
                print(hist_df)
                if len(hist_df) > 1:
                    fig2 = px.line(hist_df, x="timestamp", y="leq", labels={
                                   "timestamp": "时间", "leq": "Leq (dB)"})
                    fig2.update_layout(title="声级时间历程", showlegend=False)
                    st.plotly_chart(fig2, width="stretch")
            else:
                st.info("暂无历史数据用于时间历程图")


def render_historical_data_tab():
    """Render the historical data analysis tab"""
    st.header("历史数据分析")
    # File upload for offline analysis
    uploaded_files = st.file_uploader(
        "上传音频文件进行分析", type=["wav", "tdms"], accept_multiple_files=True)
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
    st.dataframe(hist_data, width="stretch")
    # Historical chart
    st.subheader("历史趋势")
    fig3 = px.line(hist_data, x="时间", y=["Leq (dB)", "LAeq (dB)", "LCeq (dB)"],
                   title="历史声级趋势")
    st.plotly_chart(fig3, width="stretch")


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
    setup_page_config()
    backend_url, watch_directory, microphone_channels, start_time = render_sidebar()

    # Create tabs
    tab1, tab2, tab3 = st.tabs(["实时监控", "历史数据", "系统状态"])
    with tab1:
        render_real_time_monitoring_tab(
            backend_url=backend_url,
            microphone_channels=microphone_channels,
            start_time=start_time)
    with tab2:
        render_historical_data_tab()
    with tab3:
        render_system_status_tab(backend_url, watch_directory)


if __name__ == "__main__":
    main()
