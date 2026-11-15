# -*- coding: utf-8 -*-
"""Streamlit visualization for the noise toolkit.

Pages:
  * realtime: latest 10 s metrics, spectrum, recent trends, anomaly markers
  * history: date/channel range, table, trend, CSV export
  * sessions/events: sessions, minute aggregates, acoustic events + audio
  * status: readiness, system anomalies, retention mode
"""
from __future__ import annotations

import io
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from app.web.api_client import ApiClient, ApiError
from app.web.formatters import BAND_ORDER, band_series, energy_mean, fmt

TZ = ZoneInfo(os.getenv("NIT_TIMEZONE", "Asia/Shanghai"))


def safe_page() -> None:
    st.set_page_config(page_title="噪声信息工具箱", page_icon="🔊", layout="wide")
    st.title("🔊 噪声信息工具箱")
    backend = os.getenv("NIT_BACKEND_URL", "http://127.0.0.1:8000")
    api_key = os.getenv("NIT_API_KEY")
    client = ApiClient(backend, api_key)

    try:
        health = client.health()
        channels = client.channels()
    except Exception as exc:
        st.error(f"后端不可用：{exc}")
        st.stop()

    page = st.sidebar.radio(
        "页面", ["实时监控", "历史数据", "会话与事件", "系统状态"])
    channel = st.sidebar.selectbox("通道", channels, key="channel")

    try:
        retention = client.retention()
    except Exception:
        retention = {}

    if retention.get("mode") == "debug":
        st.info("调试模式：保留全部原始音频与事件音频，不执行删除。")
    if not health.get("calibrated", False):
        st.warning("当前未校准/相对模式；剂量与 LEX 结论不可用于合规判定。")

    if page == "实时监控":
        render_realtime(client, channel)
    elif page == "历史数据":
        render_history(client, channel)
    elif page == "会话与事件":
        render_sessions(client, channel)
    else:
        render_status(client, health, retention)


def render_realtime(client: ApiClient, channel: str) -> None:
    st.subheader(f"{channel} 实时监控（10 s 窗口）")

    @st.fragment(run_every=10)
    def panel() -> None:
        try:
            m = client.latest(channel)
        except ApiError as exc:
            st.warning(f"暂无最新数据：{exc}")
            return
        cols = st.columns(6)
        cols[0].metric("LAeq (10 s)", fmt(m.get("laeq")))
        cols[1].metric("LCeq (10 s)", fmt(m.get("lceq")))
        cols[2].metric("LAF", fmt(m.get("laf")))
        cols[3].metric("LAS", fmt(m.get("las")))
        cols[4].metric("LZpeak", fmt(m.get("lzpeak")))
        cols[5].metric("NIOSH 剂量", fmt(m.get("dose_niosh"), "%", 2))

        names, values = band_series(m.get("freq_spl"))
        if any(v is not None for v in values):
            fig = px.bar(x=names, y=values,
                         labels={"x": "频段", "y": "SPL (dB)"},
                         title="1/3 倍频程频谱")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无频谱数据")

        try:
            now = datetime.now(TZ)
            rows = client.history(channel, now - timedelta(hours=1), now,
                                  limit=500)
        except Exception as exc:
            st.warning(f"趋势数据不可用：{exc}")
            rows = []
        if rows:
            frame = pd.DataFrame(rows)
            frame["timestamp"] = pd.to_datetime(
                frame["timestamp_utc"], utc=True).dt.tz_convert(TZ)
            fig = px.line(frame, x="timestamp", y=["laeq", "laf", "las"],
                          labels={"value": "dB", "variable": "指标"},
                          title="最近 1 小时（10 s 入库）")
            st.plotly_chart(fig, width="stretch")

    panel()


def render_history(client: ApiClient, channel: str) -> None:
    st.subheader(f"{channel} 历史数据")
    c1, c2 = st.columns(2)
    start_date = c1.date_input("开始日期", datetime.now(TZ).date() - timedelta(days=7))
    end_date = c2.date_input("结束日期", datetime.now(TZ).date())
    start = datetime.combine(start_date, time.min, TZ)
    end = datetime.combine(end_date, time.max, TZ)
    try:
        rows = client.history(channel, start, end, limit=2000)
    except Exception as exc:
        st.error(f"历史数据加载失败：{exc}")
        return
    if not rows:
        st.info("该时间范围没有数据")
        return
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(
        frame["timestamp_utc"], utc=True).dt.tz_convert(TZ)
    st.dataframe(frame, width="stretch")
    fig = px.line(frame, x="timestamp", y=["laeq", "lceq"],
                  title="历史声级", labels={"value": "dB", "variable": "指标"})
    st.plotly_chart(fig, width="stretch")
    st.download_button(
        "导出 CSV", frame.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{channel}_history.csv", mime="text/csv")


def render_sessions(client: ApiClient, channel: str) -> None:
    st.subheader("会话与事件")
    current = client.current_session(channel)
    if current:
        st.success(f"运行中：{current['id'][:8]} / {current.get('profile')}")
        if st.button("停止当前会话"):
            client.stop_session(current["id"])
            st.rerun()
    else:
        if st.button("新建会话"):
            client.create_session(channel)
            st.rerun()

    sessions = client.sessions()
    if not sessions:
        st.info("暂无会话")
        return
    ids = [s["id"] for s in sessions]
    selected = st.selectbox("选择会话", ids, format_func=lambda x: x[:8])
    try:
        events = client.events(selected, channel)
    except Exception as exc:
        st.warning(f"事件加载失败：{exc}")
        events = []
    if events:
        st.dataframe(pd.DataFrame(events), width="stretch")
        for event in events:
            st.caption(
                f"{event.get('category', 'acoustic')} / "
                f"{event.get('start_time_utc')} / severity={event.get('severity')}")
            if event.get("audio_path"):
                try:
                    audio = client.event_audio(event["event_id"])
                    st.audio(io.BytesIO(audio), format="audio/wav")
                except Exception as exc:
                    st.caption(f"事件音频不可用：{exc}")
    else:
        st.info("该会话没有事件")


def render_status(client: ApiClient, health: dict, retention: dict) -> None:
    st.subheader("系统状态")
    st.json(health)
    st.markdown("**留存策略**")
    st.json(retention)
    st.markdown("**系统异常**")
    try:
        st.dataframe(pd.DataFrame(client.system_events()), width="stretch")
    except Exception as exc:
        st.warning(f"系统异常接口不可用：{exc}")


def main() -> None:
    safe_page()


if __name__ == "__main__":
    main()
