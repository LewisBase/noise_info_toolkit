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
import websocket
from pathlib import Path
import os
from datetime import datetime
import threading

# Set page configuration
st.set_page_config(
    page_title="噪声信息工具箱",
    page_icon="🔊",
    layout="wide"
)

# Title
st.title("🔊 噪声信息工具箱")

# Initialize session state
if 'metrics_data' not in st.session_state:
    st.session_state.metrics_data = {}
if 'metrics_history' not in st.session_state:
    st.session_state.metrics_history = []
if 'websocket_connected' not in st.session_state:
    st.session_state.websocket_connected = False
if 'ws' not in st.session_state:
    st.session_state.ws = None

# Sidebar for configuration
st.sidebar.header("配置选项")

# File path selection with folder browser
default_audio_dir = "./audio_files"
audio_directory = st.sidebar.text_input("音频文件目录:", value=default_audio_dir)

# Button to select directory
if st.sidebar.button("选择目录"):
    st.sidebar.info("在实际应用中，这里会打开文件浏览器")

# Create directory if it doesn't exist
Path(audio_directory).mkdir(parents=True, exist_ok=True)

# Check if directory exists
if not Path(audio_directory).exists():
    st.sidebar.error(f"目录不存在: {audio_directory}")
else:
    st.sidebar.success(f"监控目录: {audio_directory}")

# Backend connection
st.sidebar.subheader("后端连接")
backend_url = st.sidebar.text_input("后端API地址:", value="http://localhost:8000")
websocket_url = st.sidebar.text_input("WebSocket地址:", value="ws://localhost:8000/ws")

# 添加WebSocket诊断信息
if st.sidebar.button("诊断WebSocket配置"):
    try:
        # 检查API根端点
        response = requests.get(f"{backend_url}/", timeout=3)
        if response.status_code == 200:
            st.sidebar.success("✓ API根端点可访问")
        else:
            st.sidebar.error("✗ API根端点不可访问")
            
        # 检查WebSocket信息端点
        response = requests.get(f"{backend_url}/websocket-info", timeout=3)
        if response.status_code == 200:
            ws_info = response.json()
            st.sidebar.success("✓ WebSocket信息端点可访问")
            st.sidebar.json(ws_info)
        else:
            st.sidebar.warning("⚠ WebSocket信息端点不可访问")
            
    except requests.exceptions.RequestException as e:
        st.sidebar.error(f"连接诊断失败: {str(e)}")

# WebSocket connection
def connect_websocket():
    try:
        if st.session_state.ws:
            st.session_state.ws.close()
        
        st.sidebar.info(f"正在连接到 WebSocket: {websocket_url}")
        ws = websocket.WebSocket()
        # 添加更多连接参数以提高兼容性
        ws.connect(websocket_url, timeout=10)
        st.session_state.ws = ws
        st.session_state.websocket_connected = True
        st.sidebar.success(f"WebSocket连接成功: {websocket_url}")
        return ws
    except websocket.WebSocketBadStatusException as e:
        st.session_state.websocket_connected = False
        st.sidebar.error(f"WebSocket握手失败: {str(e)}")
        st.sidebar.error(f"状态码: {e.status_code}")
        return None
    except websocket.WebSocketException as e:
        st.session_state.websocket_connected = False
        st.sidebar.error(f"WebSocket连接错误: {str(e)}")
        return None
    except Exception as e:
        st.session_state.websocket_connected = False
        st.sidebar.error(f"连接失败: {str(e)}")
        return None

def disconnect_websocket():
    try:
        if st.session_state.ws:
            st.session_state.ws.close()
        st.session_state.websocket_connected = False
        st.session_state.ws = None
    except Exception as e:
        pass

# WebSocket listener thread
def websocket_listener():
    while st.session_state.websocket_connected and st.session_state.ws:
        try:
            message = st.session_state.ws.recv()
            # Parse the JSON message
            data = json.loads(message)
            
            # Update session state with new data
            st.session_state.metrics_data = data
            
            # Add to history
            if 'leq' in data:
                st.session_state.metrics_history.append({
                    'timestamp': datetime.now(),
                    'leq': data.get('leq', 0),
                    'laeq': data.get('laeq', 0),
                    'lceq': data.get('lceq', 0)
                })
                
                # Keep only last 100 records
                if len(st.session_state.metrics_history) > 100:
                    st.session_state.metrics_history = st.session_state.metrics_history[-100:]
        except Exception as e:
            break

# Main content
tab1, tab2, tab3 = st.tabs(["实时监控", "历史数据", "系统状态"])

with tab1:
    st.header("实时噪声监控")
    
    # Connection status
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.session_state.websocket_connected:
            st.success("WebSocket已连接")
        else:
            st.warning("WebSocket未连接")
    with col2:
        if st.button("连接WebSocket"):
            st.sidebar.info(f"正在连接到: {websocket_url}")
            ws = connect_websocket()
            if ws:
                st.success("WebSocket连接成功")
                # Start listener thread
                listener_thread = threading.Thread(target=websocket_listener, daemon=True)
                listener_thread.start()
            else:
                st.error("WebSocket连接失败")
    with col3:
        if st.button("断开WebSocket"):
            disconnect_websocket()
            st.info("WebSocket已断开")
    
    # Display current metrics
    metrics_container = st.container()
    
    with metrics_container:
        # Create columns for metrics display
        col1, col2, col3, col4 = st.columns(4)
        
        # Get current metrics from session state
        current_metrics = st.session_state.metrics_data
        
        with col1:
            leq = current_metrics.get('leq', 'N/A')
            st.metric("等效声级 (Leq)", f"{leq:.2f} dB" if leq != 'N/A' else "N/A dB", delta=None)
            
        with col2:
            laeq = current_metrics.get('laeq', 'N/A')
            st.metric("A计权等效声级 (LAeq)", f"{laeq:.2f} dB" if laeq != 'N/A' else "N/A dB", delta=None)
            
        with col3:
            lceq = current_metrics.get('lceq', 'N/A')
            st.metric("C计权等效声级 (LCeq)", f"{lceq:.2f} dB" if lceq != 'N/A' else "N/A dB", delta=None)
            
        with col4:
            peak_spl = current_metrics.get('peak_spl', 'N/A')
            st.metric("峰值声压级", f"{peak_spl:.2f} dB" if peak_spl != 'N/A' else "N/A dB", delta=None)
        
        # Frequency band chart
        st.subheader("1/3倍频程频谱")
        if 'frequency_spl' in current_metrics:
            freq_df = pd.DataFrame(current_metrics['frequency_spl'])
            if not freq_df.empty:
                freq_bands = freq_df.columns.tolist()
                spl_values = freq_df.iloc[0].tolist()
                
                fig = px.bar(x=freq_bands, y=spl_values, labels={'x': '频率', 'y': '声压级 (dB)'})
                fig.update_layout(title="1/3倍频程频谱", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
        else:
            # Placeholder data
            freq_bands = ["63 Hz", "125 Hz", "250 Hz", "500 Hz", "1000 Hz", "2000 Hz", "4000 Hz", "8000 Hz", "16000 Hz"]
            spl_values = [np.random.uniform(40, 80) for _ in freq_bands]
            
            fig = px.bar(x=freq_bands, y=spl_values, labels={'x': '频率', 'y': '声压级 (dB)'})
            fig.update_layout(title="1/3倍频程频谱", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        
        # Time history chart
        st.subheader("时间历程")
        if st.session_state.metrics_history:
            # Use actual historical data
            hist_df = pd.DataFrame(st.session_state.metrics_history)
            if len(hist_df) > 1:
                fig2 = px.line(hist_df, x='timestamp', y='leq', labels={'timestamp': '时间', 'leq': 'Leq (dB)'})
                fig2.update_layout(title="声级时间历程", showlegend=False)
                st.plotly_chart(fig2, use_container_width=True)
        else:
            # Placeholder data
            time_points = list(range(60))  # Last 60 seconds
            leq_history = [np.random.uniform(50, 70) for _ in time_points]
            
            fig2 = px.line(x=time_points, y=leq_history, labels={'x': '时间 (s)', 'y': 'Leq (dB)'})
            fig2.update_layout(title="声级时间历程", showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

with tab2:
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
        '时间': pd.date_range(start='2023-01-01', periods=10, freq='H'),
        'Leq (dB)': np.random.uniform(50, 70, 10),
        'LAeq (dB)': np.random.uniform(45, 65, 10),
        'LCeq (dB)': np.random.uniform(52, 72, 10),
        '峰值 (dB)': np.random.uniform(60, 85, 10)
    })
    
    st.dataframe(hist_data, use_container_width=True)
    
    # Historical chart
    st.subheader("历史趋势")
    fig3 = px.line(hist_data, x='时间', y=['Leq (dB)', 'LAeq (dB)', 'LCeq (dB)'], 
                   title="历史声级趋势")
    st.plotly_chart(fig3, use_container_width=True)

with tab3:
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
        st.error("请确保后端服务正在运行")
    
    # WebSocket connection test
    st.subheader("WebSocket连接测试")
    if st.button("测试WebSocket连接"):
        try:
            test_ws = websocket.WebSocket()
            test_ws.connect(websocket_url, timeout=3)
            test_ws.close()
            st.success("WebSocket连接测试成功")
        except Exception as e:
            st.error(f"WebSocket连接测试失败: {str(e)}")
    
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

# Auto-refresh
auto_refresh = st.sidebar.checkbox("自动刷新", value=False)
refresh_interval = st.sidebar.slider("刷新间隔(秒)", 1, 60, 5)

# Auto-refresh functionality
if auto_refresh:
    time.sleep(refresh_interval)
    st.rerun()
