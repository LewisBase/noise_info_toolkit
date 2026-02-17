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

    # Session Management
    st.sidebar.subheader("测量会话管理")
    
    # Display current session status
    current_session = fetch_current_session(backend_url)
    if current_session:
        session_state = current_session.get("state", "unknown")
        session_id = current_session.get("session_id", "N/A")
        
        if session_state == "running":
            st.sidebar.success(f"🟢 会话运行中: {session_id[:8]}...")
            metrics = current_session.get("metrics", {})
            total_seconds = current_session.get("total_seconds_processed", 0)
            st.sidebar.caption(f"已处理: {total_seconds} 秒")
            
            # Show cumulative dose
            dose_niosh = metrics.get("cumulative_dose_niosh", 0)
            if dose_niosh:
                st.sidebar.caption(f"NIOSH剂量: {dose_niosh:.4f}%")
        else:
            st.sidebar.info(f"⚪ 会话状态: {session_state}")
    else:
        st.sidebar.warning("⚪ 无活动会话")
    
    # Session control buttons
    session_col1, session_col2 = st.sidebar.columns(2)
    with session_col1:
        if st.button("🟢 新建会话", key="create_session"):
            result = create_session(backend_url, profile="NIOSH")
            if result:
                st.sidebar.success(f"会话已创建: {result.get('session_id', 'N/A')[:8]}")
                st.rerun()
            else:
                st.sidebar.error("创建会话失败")
    with session_col2:
        if st.button("🔴 停止会话", key="stop_session"):
            result = stop_session(backend_url)
            if result:
                st.sidebar.success("会话已停止")
                st.rerun()
            else:
                st.sidebar.error("停止会话失败或没有活动会话")
    
    st.sidebar.markdown("---")

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


# ==================== Session Management APIs ====================

def fetch_current_session(backend_url: str) -> dict:
    """Fetch current session status"""
    try:
        url = f"{backend_url}/session/current"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            result = response.json()
            return result.get("data", {})
    except requests.exceptions.RequestException as e:
        print(f"获取当前会话失败: {e}")
        return {}


def fetch_session_list(backend_url: str, limit: int = 50) -> list:
    """Fetch list of sessions"""
    try:
        url = f"{backend_url}/session/list"
        response = requests.get(url, params={"limit": limit}, timeout=5)
        if response.status_code == 200:
            result = response.json()
            return result.get("data", {}).get("sessions", [])
    except requests.exceptions.RequestException as e:
        print(f"获取会话列表失败: {e}")
        return []


def fetch_session_time_history(backend_url: str, session_id: str, limit: int = 10000) -> list:
    """Fetch time history data for a session"""
    try:
        url = f"{backend_url}/session/{session_id}/time_history"
        response = requests.get(url, params={"limit": limit}, timeout=10)
        if response.status_code == 200:
            result = response.json()
            return result.get("data", {}).get("records", [])
    except requests.exceptions.RequestException as e:
        print(f"获取时间历程数据失败: {e}")
        return []


def fetch_session_time_history_summary(backend_url: str, session_id: str) -> dict:
    """Fetch time history summary for a session"""
    try:
        url = f"{backend_url}/session/{session_id}/time_history/summary"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            result = response.json()
            return result.get("data", {})
    except requests.exceptions.RequestException as e:
        print(f"获取时间历程汇总失败: {e}")
        return {}


def create_session(backend_url: str, profile: str = "NIOSH", operator: str = None) -> dict:
    """Create a new measurement session"""
    try:
        url = f"{backend_url}/session/create"
        data = {"profile": profile, "operator": operator}
        response = requests.post(url, json=data, timeout=5)
        if response.status_code == 200:
            result = response.json()
            return result.get("data", {})
    except requests.exceptions.RequestException as e:
        print(f"创建会话失败: {e}")
        return {}


def stop_session(backend_url: str) -> dict:
    """Stop current session"""
    try:
        url = f"{backend_url}/session/stop"
        response = requests.post(url, timeout=5)
        if response.status_code == 200:
            result = response.json()
            return result.get("data", {})
    except requests.exceptions.RequestException as e:
        print(f"停止会话失败: {e}")
        return {}


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
            
            # Basic metrics row
            st.markdown("**基础声级指标**")
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
            
            # Dose metrics row
            st.markdown("**噪声剂量指标**")
            dose_col1, dose_col2, dose_col3, dose_col4 = st.columns(4)
            with dose_col1:
                dose_niosh = metrics_data.get("dose_niosh", "N/A")
                twa_niosh = metrics_data.get("twa_niosh", "N/A")
                lex_niosh = metrics_data.get("lex_niosh", "N/A")
                if dose_niosh != "N/A":
                    st.metric("NIOSH 剂量", f"{dose_niosh:.2f}%")
                    st.caption(f"TWA: {twa_niosh:.1f} dBA | LEX,8h: {lex_niosh:.1f} dBA")
                else:
                    st.metric("NIOSH 剂量", "N/A")
            with dose_col2:
                dose_osha = metrics_data.get("dose_osha_pel", "N/A")
                twa_osha = metrics_data.get("twa_osha_pel", "N/A")
                lex_osha = metrics_data.get("lex_osha_pel", "N/A")
                if dose_osha != "N/A":
                    st.metric("OSHA PEL 剂量", f"{dose_osha:.2f}%")
                    st.caption(f"TWA: {twa_osha:.1f} dBA | LEX,8h: {lex_osha:.1f} dBA")
                else:
                    st.metric("OSHA PEL 剂量", "N/A")
            with dose_col3:
                dose_osha_hca = metrics_data.get("dose_osha_hca", "N/A")
                twa_osha_hca = metrics_data.get("twa_osha_hca", "N/A")
                lex_osha_hca = metrics_data.get("lex_osha_hca", "N/A")
                if dose_osha_hca != "N/A":
                    st.metric("OSHA HCA 剂量", f"{dose_osha_hca:.2f}%")
                    st.caption(f"TWA: {twa_osha_hca:.1f} dBA | LEX,8h: {lex_osha_hca:.1f} dBA")
                else:
                    st.metric("OSHA HCA 剂量", "N/A")
            with dose_col4:
                dose_eu = metrics_data.get("dose_eu_iso", "N/A")
                twa_eu = metrics_data.get("twa_eu_iso", "N/A")
                lex_eu = metrics_data.get("lex_eu_iso", "N/A")
                if dose_eu != "N/A":
                    st.metric("EU/ISO 剂量", f"{dose_eu:.2f}%")
                    st.caption(f"TWA: {twa_eu:.1f} dBA | LEX,8h: {lex_eu:.1f} dBA")
                else:
                    st.metric("EU/ISO 剂量", "N/A")
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
            
            # ===== TimeHistory 每秒数据显示 =====
            st.subheader("⏱️ TimeHistory 每秒数据 (Session)")
            
            # Try to get current active session first, then fall back to latest session
            session_info = fetch_current_session(backend_url)
            session_id = None
            
            if session_info and session_info.get("session_id"):
                session_id = session_info.get("session_id")
                st.caption(f"📊 显示当前活动会话: {session_id[:8]}... (状态: {session_info.get('state', 'unknown')})")
            else:
                # No active session, try to get the latest session from the list
                sessions = fetch_session_list(backend_url, limit=1)
                if sessions and len(sessions) > 0:
                    session_id = sessions[0].get("session_id")
                    st.caption(f"📊 显示最新会话: {session_id[:8]}... (已停止)")
            
            if session_id:
                # Fetch time history data for this session
                with st.spinner("加载TimeHistory数据..."):
                    time_history = fetch_session_time_history(backend_url, session_id, limit=1000)
                    th_summary = fetch_session_time_history_summary(backend_url, session_id)
                
                if time_history and len(time_history) > 0:
                    # Convert to DataFrame
                    th_df = pd.DataFrame(time_history)
                    th_df['timestamp'] = pd.to_datetime(th_df['timestamp'])
                    
                    # Show summary metrics
                    summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
                    with summary_col1:
                        st.metric("总记录数", len(th_df))
                    with summary_col2:
                        avg_laeq = th_df['LAeq_dB'].mean()
                        st.metric("平均 LAeq", f"{avg_laeq:.1f} dB")
                    with summary_col3:
                        max_lzpeak = th_df['LZpeak_dB'].max()
                        st.metric("最大 LZpeak", f"{max_lzpeak:.1f} dB")
                    with summary_col4:
                        total_dose = th_summary.get("total_dose", {}).get("NIOSH", 0)
                        st.metric("NIOSH总剂量", f"{total_dose:.4f}%")
                    
                    # TimeHistory charts - 每秒数据
                    th_col1, th_col2 = st.columns(2)
                    
                    with th_col1:
                        # LAeq time history
                        fig_laeq = px.line(
                            th_df, 
                            x="timestamp", 
                            y="LAeq_dB",
                            title="LAeq 每秒变化",
                            labels={"timestamp": "时间", "LAeq_dB": "LAeq (dBA)"}
                        )
                        fig_laeq.update_traces(line_color='blue')
                        st.plotly_chart(fig_laeq, use_container_width=True)
                    
                    with th_col2:
                        # LZpeak time history
                        fig_lzpeak = px.line(
                            th_df, 
                            x="timestamp", 
                            y="LZpeak_dB",
                            title="LZpeak 每秒变化",
                            labels={"timestamp": "时间", "LZpeak_dB": "LZpeak (dB)"}
                        )
                        fig_lzpeak.update_traces(line_color='red')
                        st.plotly_chart(fig_lzpeak, use_container_width=True)
                    
                    # Dose accumulation chart
                    st.markdown("**剂量累计曲线**")
                    th_df['cumulative_dose_niosh'] = th_df['dose_frac_niosh'].cumsum()
                    th_df['cumulative_dose_osha_pel'] = th_df['dose_frac_osha_pel'].cumsum()
                    
                    fig_dose_cum = px.line(
                        th_df,
                        x="timestamp",
                        y=["cumulative_dose_niosh", "cumulative_dose_osha_pel"],
                        title="累计剂量变化 (NIOSH vs OSHA PEL)",
                        labels={"timestamp": "时间", "value": "累计剂量 (%)", "variable": "标准"}
                    )
                    st.plotly_chart(fig_dose_cum, use_container_width=True)
                    
                    # Show data table with recent records
                    with st.expander("查看每秒数据详情 (最近20条)"):
                        display_df = th_df[["timestamp", "LAeq_dB", "LCeq_dB", "LZpeak_dB", 
                                           "dose_frac_niosh", "overload_flag", "wearing_state"]].tail(20)
                        st.dataframe(display_df, use_container_width=True)
                else:
                    st.info("暂无TimeHistory数据。请开始一个会话并处理音频文件。")
            else:
                st.info("暂无会话记录。请在侧边栏点击'🟢 新建会话'开始测量，或将音频文件放入监控目录。")
            
            st.markdown("---")  # 分隔线
            
            # Time history chart - 显示所有通道的历史数据 (文件级)
            st.subheader("📁 文件历史时间历程")
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
                    fig2.update_layout(title="声级时间历程 (文件级)", showlegend=False)
                    st.plotly_chart(fig2, width="stretch")
            else:
                st.info("暂无历史数据用于时间历程图")


def render_historical_data_tab(backend_url: str):
    """Render the historical data analysis tab with real data from API"""
    st.header("历史数据分析")
    
    # Channel selection
    microphone_channels = ["CH1", "CH2"]
    selected_channel = st.selectbox("选择通道:", microphone_channels)
    
    # Time range selection
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("开始日期:", value=pd.to_datetime("today") - pd.Timedelta(days=7))
    with col2:
        end_date = st.date_input("结束日期:", value=pd.to_datetime("today"))
    
    start_time = f"{start_date}T00:00:00"
    
    # Fetch real historical data from API
    with st.spinner("加载历史数据..."):
        history_data = fetch_history_metrics(
            backend_url=backend_url,
            start_time=start_time,
            microphone_channel=selected_channel
        )
    
    if history_data and len(history_data) > 0:
        st.success(f"已加载 {len(history_data)} 条历史记录")
        
        # Convert to DataFrame
        hist_list = []
        for record in history_data:
            metrics = record.get("metrics", {})
            hist_list.append({
                "时间": record.get("timestamp", ""),
                "文件": record.get("file_path", "").split("/")[-1],
                "Leq (dB)": metrics.get("leq", None),
                "LAeq (dB)": metrics.get("laeq", None),
                "LCeq (dB)": metrics.get("lceq", None),
                "峰值 (dB)": metrics.get("peak_spl", None),
                "NIOSH剂量 (%)": metrics.get("dose_niosh", None),
                "OSHA PEL剂量 (%)": metrics.get("dose_osha_pel", None),
                "OSHA HCA剂量 (%)": metrics.get("dose_osha_hca", None),
                "EU/ISO剂量 (%)": metrics.get("dose_eu_iso", None),
                "NIOSH TWA (dBA)": metrics.get("twa_niosh", None),
                "OSHA PEL TWA (dBA)": metrics.get("twa_osha_pel", None),
                "OSHA HCA TWA (dBA)": metrics.get("twa_osha_hca", None),
                "EU/ISO TWA (dBA)": metrics.get("twa_eu_iso", None),
                "NIOSH LEX (dBA)": metrics.get("lex_niosh", None),
                "OSHA PEL LEX (dBA)": metrics.get("lex_osha_pel", None),
                "OSHA HCA LEX (dBA)": metrics.get("lex_osha_hca", None),
                "EU/ISO LEX (dBA)": metrics.get("lex_eu_iso", None),
            })
        
        hist_df = pd.DataFrame(hist_list)
        
        # Display data table
        st.subheader("历史记录详情")
        st.dataframe(hist_df, width="stretch", use_container_width=True)
        
        # Historical trend charts
        st.subheader("历史趋势")
        
        # Sound level trend
        fig_sound = px.line(
            hist_df, 
            x="时间", 
            y=["Leq (dB)", "LAeq (dB)", "LCeq (dB)"],
            title="声级历史趋势",
            labels={"value": "声压级 (dB)", "variable": "指标"}
        )
        st.plotly_chart(fig_sound, use_container_width=True)
        
        # Dose trend
        dose_columns = ["NIOSH剂量 (%)", "OSHA PEL剂量 (%)", "OSHA HCA剂量 (%)", "EU/ISO剂量 (%)"]
        available_dose_columns = [col for col in dose_columns if col in hist_df.columns and hist_df[col].notna().any()]
        
        if available_dose_columns:
            fig_dose = px.bar(
                hist_df,
                x="时间",
                y=available_dose_columns,
                title="噪声剂量历史趋势",
                labels={"value": "剂量 (%)", "variable": "标准"},
                barmode='group'  # 并列显示柱子
            )
            st.plotly_chart(fig_dose, use_container_width=True)
        
        # Statistics summary
        st.subheader("统计汇总")
        stats_col1, stats_col2, stats_col3, stats_col4 = st.columns(4)
        with stats_col1:
            laeq_mean = hist_df['LAeq (dB)'].mean()
            st.metric("平均 LAeq", f"{laeq_mean:.1f} dB" if pd.notna(laeq_mean) else "N/A")
        with stats_col2:
            peak_max = hist_df['峰值 (dB)'].max()
            st.metric("最大峰值", f"{peak_max:.1f} dB" if pd.notna(peak_max) else "N/A")
        with stats_col3:
            total_dose = hist_df['NIOSH剂量 (%)'].sum()
            st.metric("总NIOSH剂量", f"{total_dose:.1f}%" if pd.notna(total_dose) else "N/A")
        with stats_col4:
            st.metric("记录数", len(hist_df))
    else:
        st.warning("暂无历史数据")
        st.info("提示：在\"实时监控\"Tab中处理音频文件后，数据将显示在这里")
    
    # File upload for offline analysis
    st.markdown("---")
    st.subheader("离线文件分析")
    uploaded_files = st.file_uploader(
        "上传音频文件进行分析", type=["wav", "tdms"], accept_multiple_files=True)
    if uploaded_files:
        st.success(f"已上传 {len(uploaded_files)} 个文件")
        for uploaded_file in uploaded_files:
            st.write(f"- {uploaded_file.name}")
        st.info("离线分析功能开发中...")


def render_sessions_tab(backend_url: str):
    """Render the sessions management tab"""
    st.header("📊 会话管理 (Sessions)")
    
    # Current session status
    st.subheader("当前活动会话")
    current_session = fetch_current_session(backend_url)
    
    if current_session:
        session_id = current_session.get("session_id", "N/A")
        state = current_session.get("state", "unknown")
        config = current_session.get("config", {})
        metrics = current_session.get("metrics", {})
        
        # Session info in columns
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"**会话ID**: `{session_id}`")
            st.markdown(f"**状态**: {state}")
            st.markdown(f"**标准**: {config.get('profile', 'N/A')}")
        with col2:
            st.markdown(f"**操作员**: {config.get('operator', 'N/A')}")
            st.markdown(f"**设备ID**: {config.get('device_id', 'N/A')}")
            st.markdown(f"**总秒数**: {current_session.get('total_seconds_processed', 0)}")
        with col3:
            cumulative_dose = metrics.get("cumulative_dose_niosh", 0)
            st.markdown(f"**NIOSH累计剂量**: {cumulative_dose:.4f}%")
            st.markdown(f"**当前TWA**: {metrics.get('current_TWA', 0):.1f} dBA")
            st.markdown(f"**最大峰值**: {metrics.get('max_peak_dB', 0):.1f} dB")
        
        # Get and display time history for current session
        if st.button("刷新TimeHistory数据"):
            st.rerun()
        
        time_history = fetch_session_time_history(backend_url, session_id, limit=10000)
        if time_history:
            th_df = pd.DataFrame(time_history)
            th_df['timestamp'] = pd.to_datetime(th_df['timestamp'])
            
            st.markdown(f"**TimeHistory记录数**: {len(th_df)}")
            
            # Charts
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                fig = px.line(th_df, x="timestamp", y="LAeq_dB", 
                             title="LAeq 每秒变化",
                             labels={"timestamp": "时间", "LAeq_dB": "LAeq (dBA)"})
                st.plotly_chart(fig, use_container_width=True)
            with chart_col2:
                fig2 = px.line(th_df, x="timestamp", y="LZpeak_dB",
                              title="LZpeak 每秒变化",
                              labels={"timestamp": "时间", "LZpeak_dB": "LZpeak (dB)"})
                st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("没有活动的会话。请在侧边栏点击'新建会话'开始测量。")
    
    st.markdown("---")
    
    # Session list
    st.subheader("历史会话列表")
    sessions = fetch_session_list(backend_url)
    
    if sessions:
        session_df = pd.DataFrame([
            {
                "会话ID": s.get("session_id", "")[:16] + "...",
                "完整ID": s.get("session_id", ""),
                "标准": s.get("profile_name", ""),
                "开始时间": s.get("start_time", ""),
                "结束时间": s.get("end_time", ""),
                "总时长(小时)": f"{s.get('total_duration_h', 0):.2f}",
                "LAeq_T": f"{s.get('LAeq_T', 0):.1f} dB",
                "TWA": f"{s.get('TWA', 0):.1f} dBA",
                "总剂量(%)": f"{s.get('total_dose_pct', 0):.4f}",
                "事件数": s.get("events_count", 0),
            }
            for s in sessions
        ])
        st.dataframe(session_df, use_container_width=True)
        
        # Select session to view details
        st.subheader("查看会话详情")
        selected_full_id = st.selectbox(
            "选择会话查看详细TimeHistory:",
            options=[s.get("session_id", "") for s in sessions],
            format_func=lambda x: x[:16] + "..." if len(x) > 16 else x
        )
        
        if selected_full_id:
            th_data = fetch_session_time_history(backend_url, selected_full_id, limit=10000)
            if th_data:
                th_detail_df = pd.DataFrame(th_data)
                th_detail_df['timestamp'] = pd.to_datetime(th_detail_df['timestamp'])
                
                st.success(f"加载了 {len(th_detail_df)} 条TimeHistory记录")
                
                # Summary stats
                summary = fetch_session_time_history_summary(backend_url, selected_full_id)
                if summary:
                    stat_col1, stat_col2, stat_col3, stat_col4 = st.columns(4)
                    with stat_col1:
                        st.metric("总记录数", summary.get("record_count", 0))
                    with stat_col2:
                        st.metric("平均LAeq", f"{summary.get('avg_laeq', 0):.1f} dB")
                    with stat_col3:
                        st.metric("最大LZpeak", f"{summary.get('max_lzpeak', 0):.1f} dB")
                    with stat_col4:
                        total_dose = summary.get("total_dose", {})
                        st.metric("NIOSH总剂量", f"{total_dose.get('NIOSH', 0):.4f}%")
                
                # Time history chart
                fig_th = px.line(
                    th_detail_df,
                    x="timestamp",
                    y=["LAeq_dB", "LCeq_dB"],
                    title="声级时间历程 (每秒)",
                    labels={"timestamp": "时间", "value": "声级 (dB)", "variable": "指标"}
                )
                st.plotly_chart(fig_th, use_container_width=True)
                
                # Dose accumulation
                th_detail_df['cumulative_dose_niosh'] = th_detail_df['dose_frac_niosh'].cumsum()
                fig_dose = px.line(
                    th_detail_df,
                    x="timestamp",
                    y="cumulative_dose_niosh",
                    title="NIOSH剂量累计",
                    labels={"timestamp": "时间", "cumulative_dose_niosh": "累计剂量 (%)"}
                )
                st.plotly_chart(fig_dose, use_container_width=True)
                
                # Data table
                with st.expander("查看完整数据"):
                    st.dataframe(th_detail_df, use_container_width=True)
    else:
        st.info("暂无会话记录")


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
    tab1, tab2, tab3, tab4 = st.tabs(["实时监控", "历史数据", "会话管理", "系统状态"])
    with tab1:
        render_real_time_monitoring_tab(
            backend_url=backend_url,
            microphone_channels=microphone_channels,
            start_time=start_time)
    with tab2:
        render_historical_data_tab(backend_url)
    with tab3:
        render_sessions_tab(backend_url)
    with tab4:
        render_system_status_tab(backend_url, watch_directory)


if __name__ == "__main__":
    main()
