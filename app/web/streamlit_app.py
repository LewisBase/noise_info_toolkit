# -*- coding: utf-8 -*-
"""Streamlit visualization for the noise toolkit.

The field UI intentionally keeps the older four-tab workflow (live, history,
sessions, system status), now backed by the versioned API and the 10 s/1 s
streaming database.  Directory selection is server-side; no Tk dialog is used.
"""
from __future__ import annotations

import io
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from scipy import signal
from scipy.io import wavfile

from app.web.api_client import ApiClient, ApiError
from app.web.formatters import BAND_ORDER, band_series, energy_mean, fmt

TZ = ZoneInfo(os.getenv("NIT_TIMEZONE", "Asia/Shanghai"))


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _set_monitor_dir(path: str) -> None:
    st.session_state["monitor_dir_input"] = path


def _frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if "timestamp_utc" in frame:
        frame["timestamp"] = pd.to_datetime(
            frame["timestamp_utc"], utc=True, errors="coerce").dt.tz_convert(TZ)
    return frame


def _history(client: ApiClient, channel: str, hours: float = 1.0,
             limit: int = 1000) -> pd.DataFrame:
    now = datetime.now(TZ)
    return _frame(client.history(channel, now - timedelta(hours=hours), now,
                                 limit=limit))


def _compare_frame(client: ApiClient, channels: list[str],
                   hours: float = 1.0) -> pd.DataFrame:
    frames = []
    for name in channels:
        frame = _history(client, name, hours=hours, limit=500)
        if not frame.empty:
            frame = frame.copy()
            frame["channel"] = name
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _events_for_chart(client: ApiClient, channel: str,
                      limit: int = 50) -> list[dict]:
    try:
        session = client.current_session(channel)
        if session is None:
            sessions = client.sessions()
            if not sessions:
                return []
            session = sessions[0]
        return client.events(session["id"], channel, limit=limit)
    except Exception:
        return []


def _add_event_markers(fig, events: list[dict]) -> None:
    colors = {80: "red", 50: "orange", 20: "gold"}
    for event in events[:30]:
        try:
            stamp = pd.to_datetime(event["start_time_utc"], utc=True).tz_convert(TZ)
        except Exception:
            continue
        fig.add_vline(
            x=stamp, line_dash="dot",
            line_color=colors.get(event.get("severity"), "gray"),
            annotation_text=f"E{event.get('severity', '')}",
            annotation_position="top")


def _wav_arrays(data: bytes) -> tuple[int, np.ndarray]:
    sample_rate, samples = wavfile.read(io.BytesIO(data))
    samples = np.asarray(samples)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if np.issubdtype(samples.dtype, np.integer):
        peak = float(np.iinfo(samples.dtype).max)
        samples = samples.astype(np.float64) / peak
    else:
        samples = samples.astype(np.float64)
    return int(sample_rate), samples


def _render_event_audio(data: bytes) -> None:
    try:
        sample_rate, samples = _wav_arrays(data)
    except Exception as exc:
        st.caption(f"无法解析事件波形：{exc}")
        return
    if samples.size == 0:
        st.caption("事件音频为空")
        return
    step = max(1, samples.size // 20000)
    times = np.arange(0, samples.size, step) / sample_rate
    fig = px.line(x=times, y=samples[::step],
                  labels={"x": "时间 (s)", "y": "幅值"},
                  title="事件波形")
    st.plotly_chart(fig, width="stretch")

    nperseg = min(1024, max(64, samples.size // 8 or 64))
    try:
        frequencies, times_spec, power = signal.spectrogram(
            samples, fs=sample_rate, nperseg=nperseg)
        fig = go.Figure(go.Heatmap(
            x=times_spec, y=frequencies,
            z=10 * np.log10(power + 1e-30),
            colorscale="Viridis",
            colorbar={"title": "dB"},
        ))
        fig.update_layout(title="事件频谱", xaxis_title="时间 (s)",
                          yaxis_title="频率 (Hz)")
        st.plotly_chart(fig, width="stretch")
    except Exception as exc:
        st.caption(f"无法生成事件频谱：{exc}")


def _spectrum_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "freq_spl" not in frame:
        return pd.DataFrame()
    records = []
    for _, row in frame.iterrows():
        values = row.get("freq_spl") or {}
        if not isinstance(values, dict):
            continue
        record = {"timestamp": row["timestamp"]}
        record.update({name: values.get(name) for name in BAND_ORDER})
        records.append(record)
    return pd.DataFrame(records).set_index("timestamp") if records else pd.DataFrame()


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------
def render_sidebar(client: ApiClient, channels: list[str]
                   ) -> tuple[str, list[str], bool, int]:
    st.sidebar.header("配置选项")

    try:
        monitor = client.monitor_config()
    except Exception as exc:
        st.sidebar.warning(f"监控配置不可用：{exc}")
        monitor = {}
    current_dir = monitor.get("watch_directory", "")
    st.session_state.setdefault("monitor_dir_input", current_dir)

    directory = st.sidebar.text_input(
        "音频文件目录（服务器路径）",
        key="monitor_dir_input",
        help="输入 TDMS 所在目录；可先用下方“浏览目录”选择子目录。",
    )

    if st.sidebar.button("📁 浏览目录", width="stretch"):
        try:
            st.session_state["dir_listing"] = client.list_dirs(directory or None)
        except Exception as exc:
            st.sidebar.error(f"目录浏览失败：{exc}")
            st.session_state.pop("dir_listing", None)

    listing = st.session_state.get("dir_listing")
    if listing:
        st.sidebar.caption(f"当前目录：{listing.get('path')}")
        options = [item["path"] for item in listing.get("dirs", [])]
        if options:
            selected = st.sidebar.selectbox("子目录", options, key="dir_selected")
            st.sidebar.button(
                "使用选中的子目录", width="stretch",
                on_click=_set_monitor_dir, args=(selected,))
        else:
            st.sidebar.caption("该目录下没有子目录")

    start_col, stop_col = st.sidebar.columns(2)
    with start_col:
        start = st.button("▶ 开始监测", type="primary", width="stretch")
    with stop_col:
        stop = st.button("■ 停止监测", width="stretch")
    if start:
        try:
            client.start_monitor(directory, st.session_state.get("channel", channels[0]))
            st.sidebar.success("监测已启动")
            st.session_state.pop("dir_listing", None)
            st.rerun()
        except Exception as exc:
            st.sidebar.error(f"启动失败：{exc}")
    if stop:
        try:
            client.stop_monitor()
            st.sidebar.success("监测已停止")
            st.rerun()
        except Exception as exc:
            st.sidebar.error(f"停止失败：{exc}")

    processing = monitor.get("processing", {})
    if processing.get("running"):
        st.sidebar.success("🟢 监测运行中")
        st.sidebar.caption(
            f"目录：{processing.get('watch_dir', current_dir)}\n"
            f"实时监听：{'是' if processing.get('watching') else '否（仅扫描）'}")
    else:
        st.sidebar.info("⚪ 监测未启动")

    st.sidebar.markdown("---")
    st.sidebar.subheader("测量会话")
    try:
        current = client.current_session(st.session_state.get("channel"))
    except Exception:
        current = None
    if current:
        st.sidebar.success(f"🟢 会话运行中：{current['id'][:8]}…")
        st.sidebar.caption(f"通道：{current.get('channel')} / {current.get('profile')}")
        if st.sidebar.button("🔴 停止当前会话", width="stretch"):
            try:
                client.stop_session(current["id"])
                st.rerun()
            except Exception as exc:
                st.sidebar.error(f"停止会话失败：{exc}")
    else:
        st.sidebar.warning("⚪ 无活动会话")
        if st.sidebar.button("🟢 新建会话", width="stretch"):
            try:
                client.create_session(st.session_state.get("channel", channels[0]))
                st.rerun()
            except Exception as exc:
                st.sidebar.error(f"创建会话失败：{exc}")

    st.sidebar.markdown("---")
    st.sidebar.subheader("刷新与通道")
    auto_refresh = st.sidebar.checkbox(
        "详细图表自动刷新（可选；SSE 数值已实时）", value=False)
    refresh_s = st.sidebar.slider("刷新间隔（秒）", 5, 60, 10)
    channel = st.sidebar.selectbox(
        "麦克风通道", channels, key="channel")
    compare_options = [item for item in channels if item != channel]
    compare_channels = st.sidebar.multiselect(
        "对比通道", compare_options, default=[],
        help="在实时/历史趋势中叠加其他通道的 LAeq。")
    st.sidebar.caption("10 s 入库；趋势图最多读取 5000 条。")
    return channel, compare_channels, auto_refresh, refresh_s


# ---------------------------------------------------------------------------
# live tab
# ---------------------------------------------------------------------------
def _render_sse_ticker(client: ApiClient) -> None:
    url = client.stream_url()
    components.html(f"""
    <div style="font-family:system-ui;color:#e8eef8;background:#111827;
                border-radius:10px;padding:12px 16px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <b>SSE 实时流</b>
        <span id="sse-state" style="font-size:12px;color:#fbbf24">连接中…</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;
                  margin-top:10px">
        <div><small>LAeq</small><div id="m-laeq" style="font-size:20px">—</div></div>
        <div><small>LCeq</small><div id="m-lceq" style="font-size:20px">—</div></div>
        <div><small>LAF</small><div id="m-laf" style="font-size:20px">—</div></div>
        <div><small>LZpeak</small><div id="m-lzpeak" style="font-size:20px">—</div></div>
        <div><small>NIOSH 剂量</small><div id="m-dose" style="font-size:20px">—</div></div>
      </div>
      <div id="sse-event" style="margin-top:8px;color:#f87171;font-size:13px"></div>
      <canvas id="spark" width="900" height="70" style="width:100%;margin-top:8px"></canvas>
    </div>
    <script>
    const es = new EventSource({url!r});
    const state = document.getElementById('sse-state');
    const fmt = (v, unit) => v === null || v === undefined ? '—' : Number(v).toFixed(1) + ' ' + unit;
    let history = [];
    es.onopen = () => {{ state.textContent = '已连接'; state.style.color = '#34d399'; }};
    es.onerror = () => {{ state.textContent = '重连中'; state.style.color = '#fbbf24'; }};
    es.addEventListener('metric', (ev) => {{
      const m = JSON.parse(ev.data).item;
      document.getElementById('m-laeq').textContent = fmt(m.laeq, 'dBA');
      document.getElementById('m-lceq').textContent = fmt(m.lceq, 'dBC');
      document.getElementById('m-laf').textContent = fmt(m.laf, 'dBA');
      document.getElementById('m-lzpeak').textContent = fmt(m.lzpeak, 'dB');
      document.getElementById('m-dose').textContent = fmt(m.dose_niosh, '%');
      if (m.laeq !== null && m.laeq !== undefined) {{
        history.push(Number(m.laeq)); if (history.length > 180) history.shift();
      }}
      draw();
    }});
    es.addEventListener('event', (ev) => {{
      const e = JSON.parse(ev.data).item;
      document.getElementById('sse-event').textContent =
        '新事件 ' + (e.event_type || '') + ' / severity=' + (e.severity || '');
    }});
    function draw() {{
      const c = document.getElementById('spark'), ctx = c.getContext('2d');
      ctx.clearRect(0, 0, c.width, c.height);
      if (history.length < 2) return;
      const min = Math.min(...history), max = Math.max(...history);
      const span = Math.max(1, max - min);
      ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 2; ctx.beginPath();
      history.forEach((v, i) => {{
        const x = i * c.width / (history.length - 1);
        const y = c.height - (v - min) / span * (c.height - 10) - 5;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }});
      ctx.stroke();
    }}
    </script>
    """, height=250, scrolling=False)


def _render_live_body(client: ApiClient, channel: str) -> None:
    _render_sse_ticker(client)
    try:
        m = client.latest(channel)
    except ApiError as exc:
        st.warning(f"暂无最新数据：{exc}")
        st.info("请确认监测目录中有 TDMS 文件，并点击侧边栏“开始监测”。")
        return

    st.caption(
        f"会话 {str(m.get('session_id', ''))[:8]}… / "
        f"时间 {m.get('timestamp_utc')} / "
        f"{m.get('level_unit', 'dB')} / "
        f"校准：{'是' if m.get('calibrated') else '否'}")
    if m.get("event_type"):
        st.warning(f"当前窗口异常：type={m.get('event_type')} severity={m.get('event_severity')}")
    flags = []
    if m.get("overload"):
        flags.append("过载")
    if m.get("underrange"):
        flags.append("欠量程")
    if m.get("wearing") is False:
        flags.append("未佩戴")
    if m.get("artifact"):
        flags.append("伪迹")
    if flags:
        st.error("质量标志：" + " / ".join(flags))

    st.markdown("**声级指标（10 s 窗口）**")
    c = st.columns(4)
    c[0].metric("LAeq", fmt(m.get("laeq")))
    c[1].metric("LCeq", fmt(m.get("lceq")))
    c[2].metric("LZeq", fmt(m.get("lzeq")))
    c[3].metric("LAF", fmt(m.get("laf")))
    c = st.columns(4)
    c[0].metric("LAS", fmt(m.get("las")))
    c[1].metric("LZpeak", fmt(m.get("lzpeak")))
    c[2].metric("LCpeak", fmt(m.get("lcpeak")))
    c[3].metric("LAPeak", fmt(m.get("lapeak")))

    st.markdown("**噪声剂量（当前 10 s 窗口）**")
    c = st.columns(4)
    c[0].metric("NIOSH", fmt(m.get("dose_niosh"), "%", 3))
    c[1].metric("OSHA PEL", fmt(m.get("dose_osha_pel"), "%", 3))
    c[2].metric("OSHA HCA", fmt(m.get("dose_osha_hca"), "%", 3))
    c[3].metric("EU/ISO", fmt(m.get("dose_eu_iso"), "%", 3))

    names, values = band_series(m.get("freq_spl"))
    if any(v is not None for v in values):
        fig = px.bar(x=names, y=values, labels={"x": "频段", "y": "SPL (dB)"},
                     title="1/3 倍频程频谱")
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("当前窗口暂无 1/3 倍频程数据")

    frame = _history(client, channel, hours=1.0, limit=500)
    if frame.empty:
        return

    st.markdown("**最近 1 小时时间历程**")
    fig = px.line(frame, x="timestamp", y=["laeq", "lceq", "laf", "las"],
                  labels={"value": "dB", "variable": "指标"},
                  title="声级与时间计权")
    st.plotly_chart(fig, width="stretch")

    c = st.columns(2)
    with c[0]:
        fig = px.line(frame, x="timestamp", y=["lzpeak", "lcpeak", "lapeak"],
                      labels={"value": "dB", "variable": "峰值"},
                      title="峰值声级")
        st.plotly_chart(fig, width="stretch")
    with c[1]:
        kurt_cols = [col for col in ("kurtosis_total", "kurtosis_a",
                                     "kurtosis_c", "beta_kurtosis")
                     if col in frame and frame[col].notna().any()]
        if kurt_cols:
            fig = px.line(frame, x="timestamp", y=kurt_cols,
                          labels={"value": "峰度", "variable": "类型"},
                          title="峰度")
            if "beta_kurtosis" in kurt_cols:
                fig.add_hline(y=3.0, line_dash="dash", line_color="gray",
                              annotation_text="β=3")
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("暂无峰度数据")

    dose_cols = [col for col in ("dose_niosh", "dose_osha_pel",
                                 "dose_osha_hca", "dose_eu_iso")
                 if col in frame and frame[col].notna().any()]
    if dose_cols:
        cumulative = frame[["timestamp"] + dose_cols].copy()
        for col in dose_cols:
            cumulative[col] = cumulative[col].fillna(0.0).cumsum()
        fig = px.line(cumulative, x="timestamp", y=dose_cols,
                      labels={"value": "累计剂量 (%)", "variable": "标准"},
                      title="窗口剂量累计")
        st.plotly_chart(fig, width="stretch")

    spectrum = _spectrum_frame(frame)
    if not spectrum.empty:
        fig = px.imshow(spectrum.T, aspect="auto", origin="lower",
                        labels={"x": "时间", "y": "频段", "color": "SPL (dB)"},
                        title="频谱时间热力图")
        st.plotly_chart(fig, width="stretch")

    with st.expander("查看最近 20 条 10 s 数据"):
        st.dataframe(frame.tail(20), width="stretch")


def render_realtime(client: ApiClient, channel: str,
                    compare_channels: list[str], auto_refresh: bool,
                    refresh_s: int) -> None:
    st.subheader(f"{channel} 实时监控")
    if auto_refresh:
        @st.fragment(run_every=refresh_s)
        def panel() -> None:
            _render_live_body(client, channel)
            _render_channel_compare(client, channel, compare_channels)
    else:
        def panel() -> None:
            _render_live_body(client, channel)
            _render_channel_compare(client, channel, compare_channels)
    panel()
    if not auto_refresh and st.button("刷新详细图表"):
        st.rerun()


# ---------------------------------------------------------------------------
# history tab
# ---------------------------------------------------------------------------
def _render_channel_compare(client: ApiClient, channel: str,
                            compare_channels: list[str]) -> None:
    if not compare_channels:
        return
    frame = _compare_frame(client, [channel] + compare_channels, hours=1.0)
    if frame.empty:
        return
    fig = px.line(frame, x="timestamp", y="laeq", color="channel",
                  labels={"laeq": "LAeq (dBA)", "timestamp": "时间"},
                  title="多通道 LAeq 对比（最近 1 小时）")
    st.plotly_chart(fig, width="stretch")


def render_history(client: ApiClient, channel: str,
                   compare_channels: list[str] | None = None) -> None:
    st.subheader(f"{channel} 历史数据")
    c = st.columns(3)
    start_date = c[0].date_input(
        "开始日期", datetime.now(TZ).date() - timedelta(days=7), key="hist_start")
    end_date = c[1].date_input(
        "结束日期", datetime.now(TZ).date(), key="hist_end")
    limit = c[2].number_input("每页记录数", 50, 10000, 500, step=50)
    c = st.columns(2)
    aggregate = c[0].selectbox("聚合粒度", ["minute", "raw"],
                               format_func=lambda x: "按分钟" if x == "minute" else "10 s 原始")
    page = c[1].number_input("页码", min_value=1, value=1, step=1)
    start = datetime.combine(start_date, time.min, TZ)
    end = datetime.combine(end_date, time.max, TZ)
    if start > end:
        st.error("开始日期不能晚于结束日期")
        return
    try:
        payload = client.history_page(
            channel, start, end, limit=int(limit),
            offset=(int(page) - 1) * int(limit), aggregate=aggregate)
        frame = _frame(payload.get("items", []))
    except Exception as exc:
        st.error(f"历史数据加载失败：{exc}")
        return
    if frame.empty:
        st.info("该时间范围没有数据（或页码超出范围）")
        return

    total = int(payload.get("total", len(frame)))
    pages = max(1, (total + int(limit) - 1) // int(limit))
    st.caption(
        f"共 {total} 条；第 {page}/{pages} 页；时间按 {TZ} 显示；"
        f"聚合={'分钟' if aggregate == 'minute' else '10 s'}")
    c = st.columns(4)
    c[0].metric("平均 LAeq", fmt(energy_mean(frame["laeq"])))
    c[1].metric("最大 LZpeak", fmt(frame["lzpeak"].max() if "lzpeak" in frame else None))
    c[2].metric("最大 LCpeak", fmt(frame["lcpeak"].max() if "lcpeak" in frame else None))
    c[3].metric("NIOSH 累计", fmt(frame["dose_niosh"].fillna(0).sum(), "%", 3))

    fig = px.line(frame, x="timestamp", y=["laeq", "lceq", "laf", "las"],
                  labels={"value": "dB", "variable": "指标"},
                  title="声级时间历程")
    st.plotly_chart(fig, width="stretch")

    c = st.columns(2)
    with c[0]:
        fig = px.line(frame, x="timestamp", y=["lzpeak", "lcpeak", "lapeak"],
                      labels={"value": "dB", "variable": "峰值"},
                      title="峰值时间历程")
        st.plotly_chart(fig, width="stretch")
    with c[1]:
        dose_cols = [col for col in ("dose_niosh", "dose_osha_pel",
                                     "dose_osha_hca", "dose_eu_iso")
                     if col in frame and frame[col].notna().any()]
        if dose_cols:
            cumulative = frame[["timestamp"] + dose_cols].copy()
            for col in dose_cols:
                cumulative[col] = cumulative[col].fillna(0).cumsum()
            fig = px.line(cumulative, x="timestamp", y=dose_cols,
                          labels={"value": "累计剂量 (%)", "variable": "标准"},
                          title="累计剂量")
            st.plotly_chart(fig, width="stretch")

    spectrum = _spectrum_frame(frame)
    if not spectrum.empty:
        fig = px.imshow(spectrum.T, aspect="auto", origin="lower",
                        labels={"x": "时间", "y": "频段", "color": "SPL (dB)"},
                        title="1/3 倍频程时间热力图")
        st.plotly_chart(fig, width="stretch")

    with st.expander("数据表 / 导出"):
        st.dataframe(frame, width="stretch")
        st.download_button(
            "导出 CSV", frame.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{channel}_history.csv", mime="text/csv")


# ---------------------------------------------------------------------------
# sessions tab
# ---------------------------------------------------------------------------
def render_sessions(client: ApiClient, channel: str) -> None:
    st.subheader("会话与事件")
    try:
        current = client.current_session(channel)
    except Exception:
        current = None
    if current:
        st.success(f"当前会话：{current['id']} / {current.get('channel')} / {current.get('profile')}")
    try:
        sessions = client.sessions()
    except Exception as exc:
        st.error(f"会话列表加载失败：{exc}")
        return
    if not sessions:
        st.info("暂无会话；可在侧边栏新建会话或开始监测。")
        return

    labels = {
        s["id"]: f"{s['id'][:8]}… | {s.get('channel')} | {s.get('state')} | {s.get('start_time')}"
        for s in sessions
    }
    selected = st.selectbox("选择会话", list(labels), format_func=labels.get,
                            key="session_selected")
    selected_info = next((s for s in sessions if s["id"] == selected), {})
    st.json(selected_info)

    try:
        metrics = client.session_metrics(selected, channel)
    except Exception as exc:
        st.warning(f"会话时序数据不可用：{exc}")
        metrics = []
    frame = _frame(metrics)
    if not frame.empty:
        c = st.columns(4)
        c[0].metric("平均 LAeq", fmt(energy_mean(frame["laeq"])))
        c[1].metric("最大 LZpeak", fmt(frame["lzpeak"].max() if "lzpeak" in frame else None))
        c[2].metric("NIOSH 累计", fmt(frame["dose_niosh"].fillna(0).sum(), "%", 3))
        c[3].metric("记录数", f"{len(frame)}")
        st.markdown("**会话时间历程**")
        fig = px.line(frame, x="timestamp", y=["laeq", "lceq", "laf", "las"],
                      labels={"value": "dB", "variable": "指标"},
                      title="会话声级")
        st.plotly_chart(fig, width="stretch")
        c = st.columns(2)
        with c[0]:
            fig = px.line(frame, x="timestamp", y=["lzpeak", "lcpeak"],
                          labels={"value": "dB", "variable": "峰值"},
                          title="会话峰值")
            st.plotly_chart(fig, width="stretch")
        with c[1]:
            dose_cols = [col for col in ("dose_niosh", "dose_osha_pel",
                                         "dose_osha_hca", "dose_eu_iso")
                         if col in frame and frame[col].notna().any()]
            if dose_cols:
                cumulative = frame[["timestamp"] + dose_cols].copy()
                for col in dose_cols:
                    cumulative[col] = cumulative[col].fillna(0).cumsum()
                fig = px.line(cumulative, x="timestamp", y=dose_cols,
                              labels={"value": "累计剂量 (%)", "variable": "标准"},
                              title="会话累计剂量")
                st.plotly_chart(fig, width="stretch")
    else:
        st.info("该会话暂无时序数据")

    try:
        events = client.events(selected, channel)
    except Exception as exc:
        st.warning(f"事件加载失败：{exc}")
        events = []
    if events:
        st.markdown("**异常事件**")
        st.dataframe(pd.DataFrame(events), width="stretch")
        for event in events:
            st.caption(
                f"{event.get('start_time_utc')} / type={event.get('event_type')} "
                f"/ severity={event.get('severity')} / {event.get('trigger_flags')} "
                f"/ review={event.get('review_state', 'unreviewed')}")
            note = st.text_input(
                "审核备注", key=f"review_note_{event['event_id']}")
            review_cols = st.columns(3)
            if review_cols[0].button("确认事件", key=f"confirm_{event['event_id']}"):
                client.review_event(event["event_id"], "confirmed",
                                    note=note, reviewer="operator")
                st.rerun()
            if review_cols[1].button("标记误报", key=f"false_{event['event_id']}"):
                client.review_event(event["event_id"], "false_positive",
                                    note=note, reviewer="operator")
                st.rerun()
            if review_cols[2].button("重置审核", key=f"reset_{event['event_id']}"):
                client.review_event(event["event_id"], "unreviewed",
                                    note=note, reviewer="operator")
                st.rerun()
            if event.get("reviewed_by"):
                st.caption(f"审核人：{event.get('reviewed_by')} / {event.get('reviewed_at')}")
            if event.get("audio_path"):
                try:
                    audio = client.event_audio(event["event_id"])
                    st.audio(io.BytesIO(audio), format="audio/wav")
                except Exception as exc:
                    st.caption(f"事件音频不可用：{exc}")
                else:
                    with st.expander("事件波形与频谱"):
                        _render_event_audio(audio)
    else:
        st.info("该会话没有异常事件")


# ---------------------------------------------------------------------------
# system tab
# ---------------------------------------------------------------------------
def render_system(client: ApiClient, health: dict, retention: dict,
                  directory: str, role: str = "operator") -> None:
    st.subheader("系统状态")
    c = st.columns(4)
    c[0].metric("API", health.get("status", "?"))
    c[1].metric("校准", "是" if health.get("calibrated") else "否")
    c[2].metric("留存模式", health.get("retention_mode", "?"))
    c[3].metric("监控目录", "有效" if health.get("watch_dir_exists") else "无效")
    st.caption(f"监控目录：{health.get('watch_dir', directory)}")

    try:
        monitor = client.monitor_config()
    except Exception:
        monitor = {}
    st.markdown("**监测状态**")
    st.json(monitor)

    st.markdown("**目录浏览 / 文件输入**")
    c = st.columns([3, 1])
    browse_path = c[0].text_input("目录路径", value=directory, key="system_dir")
    if c[1].button("列出子目录", width="stretch"):
        try:
            st.session_state["system_listing"] = client.list_dirs(browse_path)
        except Exception as exc:
            st.error(f"目录读取失败：{exc}")
    listing = st.session_state.get("system_listing")
    if listing:
        st.caption(f"路径：{listing.get('path')}")
        st.dataframe(pd.DataFrame(listing.get("dirs", [])), width="stretch")

    st.markdown("**处理任务**")
    try:
        jobs = client.jobs()
    except Exception as exc:
        st.warning(f"任务列表不可用：{exc}")
        jobs = []
    if jobs:
        st.dataframe(pd.DataFrame(jobs), width="stretch")
    else:
        st.caption("暂无任务记录")

    st.markdown("**系统异常**")
    try:
        events = client.system_events()
    except Exception as exc:
        st.warning(f"系统异常接口不可用：{exc}")
        events = []
    if events:
        st.dataframe(pd.DataFrame(events), width="stretch")
    else:
        st.caption("无")

    st.markdown("**留存策略 / 校准**")
    st.json(retention)
    try:
        calibration = client.calibration()
        st.json(calibration)
    except Exception:
        st.caption("尚未写入校准记录")
    if role == "admin":
        if st.button("预览留存（不删除）"):
            try:
                st.json(client.retention_preview())
            except Exception as exc:
                st.error(f"留存预览失败：{exc}")

    can_calibrate = role in ("calibrator", "admin")
    if can_calibrate:
        st.markdown("**事件检测参数**")
        try:
            event_cfg = client.event_config()
        except Exception as exc:
            event_cfg = {}
            st.warning(f"事件参数读取失败：{exc}")
        with st.expander("阈值 / 前触发 / 后触发 / 最小间隔", expanded=False):
            with st.form("event_config_form"):
                c = st.columns(3)
                laf_minor = c[0].number_input("LAF 轻微阈值 (dB)", value=float(event_cfg.get("laf_minor_db", 85.0)), step=1.0)
                laf_moderate = c[1].number_input("LAF 中等阈值 (dB)", value=float(event_cfg.get("laf_moderate_db", 95.0)), step=1.0)
                laf_severe = c[2].number_input("LAF 严重阈值 (dB)", value=float(event_cfg.get("laf_severe_db", 110.0)), step=1.0)
                c = st.columns(3)
                impulse_minor = c[0].number_input("脉冲轻微阈值 (dB)", value=float(event_cfg.get("impulse_minor_db", 6.0)), step=0.5)
                impulse_severe = c[1].number_input("脉冲严重阈值 (dB)", value=float(event_cfg.get("impulse_severe_db", 12.0)), step=0.5)
                rise_minor = c[2].number_input("上升沿轻微阈值 (dB)", value=float(event_cfg.get("rise_minor_db", 10.0)), step=0.5)
                c = st.columns(3)
                rise_moderate = c[0].number_input("上升沿中等阈值 (dB)", value=float(event_cfg.get("rise_moderate_db", 15.0)), step=0.5)
                background_delta = c[1].number_input("背景差值阈值 (dB)", value=float(event_cfg.get("background_delta_db", 15.0)), step=0.5)
                peak_threshold = c[2].number_input("峰值过载阈值 (dB)", value=float(event_cfg.get("peak_threshold_db", 140.0)), step=1.0)
                c = st.columns(4)
                pre_s = c[0].number_input("事件前 (s)", value=float(event_cfg.get("pre_s", 5.0)), min_value=0.0, step=1.0)
                post_s = c[1].number_input("事件后 (s)", value=float(event_cfg.get("post_s", 10.0)), min_value=0.0, step=1.0)
                max_s = c[2].number_input("事件最长 (s)", value=float(event_cfg.get("max_s", 60.0)), min_value=1.0, step=1.0)
                min_gap_s = c[3].number_input("最小间隔 (s)", value=float(event_cfg.get("min_gap_s", 2.0)), min_value=0.0, step=0.5)
                if st.form_submit_button("保存事件参数"):
                    try:
                        client.update_event_config({
                            "laf_minor_db": laf_minor,
                            "laf_moderate_db": laf_moderate,
                            "laf_severe_db": laf_severe,
                            "impulse_minor_db": impulse_minor,
                            "impulse_severe_db": impulse_severe,
                            "rise_minor_db": rise_minor,
                            "rise_moderate_db": rise_moderate,
                            "background_delta_db": background_delta,
                            "peak_threshold_db": peak_threshold,
                            "pre_s": pre_s, "post_s": post_s,
                            "max_s": max_s, "min_gap_s": min_gap_s,
                        })
                        st.success("事件参数已保存，下一文件生效")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"保存事件参数失败：{exc}")

        st.markdown("**写入校准记录**")
        with st.form("calibration_form"):
            c = st.columns(3)
            name = c[0].text_input("校准名称", value="cal-94dB")
            unit = c[1].selectbox("输入单位", ["Pa", "V", "mV", "counts"])
            pa_per_unit = c[2].number_input(
                "Pa/单位", min_value=1e-9, value=1.0, format="%.6f")
            c = st.columns(3)
            offset_pa = c[0].number_input("偏置 (Pa)", value=0.0, format="%.6f")
            offset_db = c[1].number_input("偏置 (dB)", value=0.0, format="%.3f")
            certificate = c[2].text_input("证书/备注", value="")
            submitted = st.form_submit_button("保存校准记录")
            if submitted:
                try:
                    client.add_calibration({
                        "name": name, "unit": unit,
                        "pa_per_unit": pa_per_unit,
                        "offset_pa": offset_pa,
                        "offset_db": offset_db,
                        "calibrated": True,
                        "certificate": certificate,
                    })
                    st.success("校准记录已保存")
                    st.rerun()
                except Exception as exc:
                    st.error(f"保存校准失败：{exc}")
    else:
        st.info("事件阈值和校准写操作需要校准员/管理员角色。")

    with st.expander("原始健康检查 JSON"):
        st.json(health)


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------
def safe_page() -> None:
    st.set_page_config(page_title="噪声信息工具箱", page_icon="🔊", layout="wide")
    st.title("🔊 噪声信息工具箱")

    # Connection controls must be rendered before any API client is built, so
    # changing the URL/API key takes effect on the next Streamlit rerun.
    st.sidebar.header("后端连接")
    backend = st.sidebar.text_input(
        "后端 API 地址",
        value=os.getenv("NIT_BACKEND_URL", "http://127.0.0.1:8000"),
        key="backend_url_input")
    api_key = st.sidebar.text_input(
        "API Key（可选）", value=os.getenv("NIT_API_KEY", ""),
        type="password", key="api_key_input")
    client = ApiClient(backend, api_key or None)
    if st.sidebar.button("🩺 诊断后端", width="stretch"):
        try:
            ready = client.health()
            st.sidebar.success(
                f"API 正常；通道：{', '.join(ready.get('channels', [])) or '无'}")
        except Exception as exc:
            st.sidebar.error(f"连接失败：{exc}")

    try:
        health = client.health()
        channels = client.channels()
        role = client.whoami().get("role", "unknown")
    except Exception as exc:
        st.error(f"后端不可用：{exc}")
        st.info("请先启动 API，并确认上方后端地址和 API Key。")
        st.stop()
    st.sidebar.caption(f"当前角色：{role}")

    if health.get("directory_guard") == "unrestricted":
        st.warning(
            "目录白名单未配置（NIT_ALLOWED_WATCH_ROOTS）；仅建议用于本机调试，"
            "现场部署请限制可浏览/监控目录。")

    channel, compare_channels, auto_refresh, refresh_s = render_sidebar(
        client, channels)

    try:
        retention = client.retention()
    except Exception:
        retention = {}

    if retention.get("mode") == "debug":
        st.info("调试模式：保留全部原始音频与事件音频，不执行删除。")
    if not health.get("calibrated", False):
        st.warning("当前未校准/相对模式；剂量与 LEX 结论不可用于合规判定。")

    pages = ["实时监控", "历史数据", "会话管理", "系统状态"]
    if hasattr(st, "segmented_control"):
        page = st.segmented_control("页面", pages, default="实时监控", key="page")
    else:  # pragma: no cover - older Streamlit fallback
        page = st.radio("页面", pages, horizontal=True, key="page")
    page = page or "实时监控"

    # Only the selected page is executed.  This avoids four eager API queries
    # on every rerun and keeps the live fragment responsive.
    if page == "实时监控":
        render_realtime(client, channel, compare_channels,
                        auto_refresh, refresh_s)
    elif page == "历史数据":
        render_history(client, channel, compare_channels)
    elif page == "会话管理":
        render_sessions(client, channel)
    else:
        render_system(client, health, retention,
                      st.session_state.get("monitor_dir_input",
                                           health.get("watch_dir", "")), role)


def main() -> None:
    safe_page()


if __name__ == "__main__":
    main()
