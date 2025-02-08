# -*- coding: utf-8 -*-
"""
@DATE: 2025-02-07 14:22:59
@Author: Liu Hengjiang
@File: wav_file_toolkit.py
@Software: vscode
@Description:
        噪声等效声压级计算工具展示(读入wav文件)
"""

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import librosa
from functional import seq
from scipy.stats import kurtosis
from scipy.signal import welch
from acoustics import Signal
from acoustics.standards.iso_tr_25417_2007 import sound_pressure_level, equivalent_sound_pressure_level, peak_sound_pressure_level
from acoustics.standards.iec_61672_1_2013 import time_averaged_sound_level

from matplotlib.font_manager import FontProperties
from matplotlib import rcParams

config = {
    "font.family": "serif",
    "font.size": 12,
    "mathtext.fontset": "stix",  # matplotlib渲染数学字体时使用的字体，和Times New Roman差别不大
    "font.serif": ["STZhongsong"],  # 华文中宋
    "axes.unicode_minus": False  # 处理负号，即-号
}
rcParams.update(config)


@st.cache_data
def signal_process(wav_file, REFER_SOUND_PRESSURE):
    """加载wav对象并进行计算

    Args:
        wav_file (_type_): wav文件
        REFER_SOUND_PRESSURE (float): 参考声压值

    Returns:
        s: Signal对象
        freq_kurtosises_df: 1/3倍频程滤波后的峰度信息
        freq_SPLs_df: 1/3倍频程滤波后的声压级信息
        kurtosis_total: 时域峰度
        A_kurtosis_total: A计权时域峰度
        C_kurtosis_total: C计权时域峰度
        Leq: 等效声压级
        LAeq: A计权等效声压级
        LCeq: C计权等效声压级
        Peak_SPL: 峰值声压级
        Peak_ASPL: A计权峰值声压级
        Peak_CSPL: C计权峰值声压级
        
    """
    y, sr = librosa.load(wav_file, sr=None)
    s = Signal(y, sr)
    center_freq, octaves = s.third_octaves()
    freq_kurtosises = []
    freq_SPLs = []
    for freq_index in np.arange(8, 35, 3):
        s_octave = octaves[freq_index]
        freq_kurtosis = kurtosis(s_octave.values, fisher=False)
        freq_SPL = sound_pressure_level(
            s_octave.values, reference_pressure=REFER_SOUND_PRESSURE)
        freq_kurtosises.append(round(freq_kurtosis, 2))
        freq_SPLs.append(freq_SPL)

    kurtosis_total = kurtosis(s.values, fisher=False)
    A_kurtosis_total = kurtosis(s.weigh("A").values, fisher=False)
    C_kurtosis_total = kurtosis(s.weigh("C").values, fisher=False)

    Leq = equivalent_sound_pressure_level(
        s.values, reference_pressure=REFER_SOUND_PRESSURE)
    LAeq = equivalent_sound_pressure_level(
        s.weigh("A").values, reference_pressure=REFER_SOUND_PRESSURE)
    LCeq = equivalent_sound_pressure_level(
        s.weigh("C").values, reference_pressure=REFER_SOUND_PRESSURE)

    Peak_SPL = peak_sound_pressure_level(
        s.values, reference_pressure=REFER_SOUND_PRESSURE)
    Peak_ASPL = peak_sound_pressure_level(
        s.weigh("A").values, reference_pressure=REFER_SOUND_PRESSURE)
    Peak_CSPL = peak_sound_pressure_level(
        s.weigh("C").values, reference_pressure=REFER_SOUND_PRESSURE)

    freq_kurtosises_df = pd.DataFrame(
        dict(
            zip([
                "63 Hz", "125 Hz", "250 Hz", "500 Hz", "1000 Hz", "2000 Hz",
                "4000 Hz", "8000 Hz", "16000 Hz"
            ],
                seq(freq_kurtosises).map(lambda x: [x]))))
    freq_SPLs_df = pd.DataFrame(
        dict(
            zip([
                "63 Hz", "125 Hz", "250 Hz", "500 Hz", "1000 Hz", "2000 Hz",
                "4000 Hz", "8000 Hz", "16000 Hz"
            ], freq_SPLs)))

    return s, freq_kurtosises_df, freq_SPLs_df,\
           kurtosis_total, A_kurtosis_total, C_kurtosis_total,\
           Leq, LAeq, LCeq,\
           Peak_SPL, Peak_ASPL, Peak_CSPL


@st.cache_data
def plot_time_average_SPL(s: Signal, REFER_SOUND_PRESSURE: float):
    """绘制时间平均的声压级变化图

    Args:
        s (Signal): Signal对象
        REFER_SOUND_PRESSURE (float): 参考声压值

    Returns:
        fig: 绘图对象
    """
    fig, ax = plt.subplots(1, 1, figsize=(6, 5))
    times, levels = time_averaged_sound_level(
        pressure=s.values,
        sample_frequency=s.fs,
        averaging_time=0.125,
        reference_pressure=REFER_SOUND_PRESSURE)
    ax.plot(times, levels)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("SPL (dB)")
    ax.set_title("Time Average SPL")
    ax.annotate("Time bin = 0.125 s", xy=(0.1, 0.1), xycoords='axes fraction')
    return fig


@st.cache_data
def plot_power_spectrum_SPL(s: Signal,
                            REFER_SOUND_PRESSURE: float,
                            window: str = "hann",
                            nperseg: int = 1024):
    freqs, psd = welch(s.values, fs=s.fs, nperseg=nperseg, window=window)
    freq_SPLs = sound_pressure_level(np.sqrt(psd),
                                     reference_pressure=REFER_SOUND_PRESSURE)
    fig, ax = plt.subplots(1, 1, figsize=(6, 5))
    ax.plot(freqs, freq_SPLs)
    ax.set_xscale("log")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("SPL (dB)")
    ax.set_title("Power Spectrum SPL")
    return fig


@st.cache_data
def convert_df(df):
    return df.to_csv(index=False).encode("utf-8")


def run():
    st.write("输入：请上传一个噪声音频的wav文件。")
    uploaded_file = st.file_uploader("点击上传或拖拽文件至下方", type=["wav"])
    if uploaded_file is not None:
        # 显示文件名
        st.write(f"您选择了文件: {uploaded_file.name}")
        REFER_SOUND_PRESSURE = st.number_input("请输入参考声压值 (μPa)", value=2.33e-1)
        REFER_SOUND_PRESSURE *= 1e-6
        FFT_SIZE = st.number_input("请输入FFT窗口大小", value=1024)
        WINDOWS_FUNC = st.selectbox("请选择窗口函数", [
            "boxcar", "triang", "hann", "hamming", "blackman", "bartlett",
            "blackmanharris"
        ],
                                    index=3)
        try:
            # 使用acoustics读取wav文件
            s, freq_kurtosises_df, freq_SPLs_df,\
            kurtosis_total, A_kurtosis_total, C_kurtosis_total,\
            Leq, LAeq, LCeq,\
            Peak_SPL, Peak_ASPL, Peak_CSPL = signal_process(
                uploaded_file, REFER_SOUND_PRESSURE)
            # 基本信息
            with st.container():
                st.write("## 噪声音频基本信息")
                col1, col2, col3 = st.columns(3)
                col1.metric("采样率 (Hz)", s.fs)
                col2.metric("声道数", s.channels)
                col3.metric("时长 (s)", round(s.duration, 2))
                # 显示波形图
                col1, col2 = st.columns(2)
                fig1 = plot_time_average_SPL(s, REFER_SOUND_PRESSURE)
                fig2 = plot_power_spectrum_SPL(s,
                                               REFER_SOUND_PRESSURE,
                                               nperseg=FFT_SIZE,
                                               window=WINDOWS_FUNC)
                col1.pyplot(fig1)
                col2.pyplot(fig2)

            with st.container():
                st.write("## 噪声音频计算结果")
                st.write("### 峰度信息")
                col1, col2, col3 = st.columns(3)
                col1.metric("时域峰度 (kurtosis)", round(kurtosis_total, 2))
                col2.metric("A计权时域峰度 (A-kurtosis)", round(A_kurtosis_total, 2))
                col3.metric("C计权时域峰度 (C-kurtosis)", round(C_kurtosis_total, 2))

                st.write("1/3 倍频程滤波后的峰度信息")
                st.dataframe(freq_kurtosises_df,
                             hide_index=True,
                             use_container_width=True)

            with st.container():
                st.write("### 声压级信息")
                col1, col2, col3 = st.columns(3)
                col1.metric("等效声压级 (Leq dB)", round(Leq, 2))
                col2.metric("A计权等效声压级 (LAeq dBA)", round(LAeq, 2))
                col3.metric("C计权等效声压级 (LCeq dBC)", round(LCeq, 2))

                col1, col2, col3 = st.columns(3)
                col1.metric("峰值声压级 (Peak SPL dB)", round(Peak_SPL, 2))
                col2.metric("A计权峰值声压级 (Peak ASPL dBA)", round(Peak_ASPL, 2))
                col3.metric("C计权峰值声压级 (Peak CSPL dBC)", round(Peak_CSPL, 2))

                st.write("1/3 倍频程滤波后的声压级信息")
                st.dataframe(freq_SPLs_df.head(10),
                             hide_index=True,
                             use_container_width=True)
                csv = convert_df(freq_SPLs_df)
                st.download_button("点击下载完整的倍频程SPL信息表格",
                                   csv,
                                   "file.csv",
                                   "text/csv",
                                   key='download-csv')

        except Exception as e:
            st.error(f"读取文件时出错: {e}")


if __name__ == "__main__":
    run()
