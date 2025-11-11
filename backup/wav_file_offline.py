# -*- coding: utf-8 -*-
"""
@DATE: 2025-02-11 15:27:19
@Author: Liu Hengjiang
@File: wav_file_offline.py
@Software: vscode
@Description:
        离线处理音频文件
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import librosa
from functional import seq
from scipy.stats import kurtosis
from scipy.signal import welch, get_window, savgol_filter, butter, filtfilt
from acoustics import Signal
from acoustics.standards.iso_tr_25417_2007 import sound_pressure_level, equivalent_sound_pressure_level, peak_sound_pressure_level
from acoustics.standards.iec_61672_1_2013 import time_averaged_sound_level, average

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


def lowpass_filter(data, cutoff, fs, order=5):
    nyq = 0.5 * fs
    normal_cutoff = cutoff / nyq
    b, a = butter(order, normal_cutoff, btype="low")
    filtered = filtfilt(b, a, data)
    return filtered


def plot_time_average_SPL(ss: list[Signal], names: list, average_time: float,
                          REFER_SOUND_PRESSURE: float):
    """绘制时间平均的声压级变化图

    Args:
        s (Signal): Signal对象
        REFER_SOUND_PRESSURE (float): 参考声压值

    Returns:
        fig: 绘图对象
    """
    colors = [
        "blue", "red", "orange", '1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
        '#9467bd', '#8c564b'
    ]
    res = []
    for s in ss:
        times, levels = time_averaged_sound_level(
            pressure=s.values,
            sample_frequency=s.fs,
            averaging_time=average_time,
            reference_pressure=REFER_SOUND_PRESSURE)
        res.append((times, levels))
    fig, ax = plt.subplots(1, 1, figsize=(6, 5))
    for (times, levels), name, color in zip(res, names, colors[:len(res)]):
        ax.plot(times, levels, color=color, label=name)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("SPL (dB)")
    ax.set_title("Time Average SPL")
    ax.annotate(f"Time bin = {average_time} s",
                xy=(0.1, 0.1),
                xycoords='axes fraction')
    plt.legend()
    return fig


def plot_power_spectrum_SPL(ss: list[Signal],
                            names: list,
                            REFER_SOUND_PRESSURE: float,
                            window_name: str = "hann",
                            nperseg: int = 1024):
    colors = [
        "blue", "red", "orange", '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728',
        '#9467bd', '#8c564b'
    ]
    window_recover_dict = {"boxcar": 1, "hann": 2, "hamming": 1.852, "blackman": 2.381}
    res = []
    move_up = 0
    for s in ss:
        # window = get_window(window_name, len(s.values))
        # recorver = np.sqrt(len(s.values)/np.sum(window**2))
        # windowed_s = Signal(s.values * window, s.fs)
        freqs, psd = s.power_spectrum(N=nperseg)
        freq_SPLs = sound_pressure_level(
            np.sqrt(psd), reference_pressure=REFER_SOUND_PRESSURE)
        # filter and move_up
        freq_SPLs = savgol_filter(freq_SPLs, window_length=11, polyorder=2)
        freq_SPLs[85:171] = freq_SPLs[85:171] - 0.5 * (freq_SPLs[85:171] - freq_SPLs[85:171].mean())
        freq_SPLs[85:171] += move_up
        # move_up += 2.5
        # freqs, psd = welch(s.values, fs=s.fs, nperseg=nperseg, window=window_name)
        # pref = REFER_SOUND_PRESSURE * 1e-12 / 2e-5
        # freq_SPLs = 10 * np.log10(psd / pref)
        res.append((freqs, freq_SPLs))
    fig, ax = plt.subplots(1, 1, figsize=(6, 5))
    for (freqs, freq_SPLs), name, color in zip(res, names, colors[:len(res)]):
        ax.plot(freqs[10:-10], freq_SPLs[10:-10], color=color, label=name)
    # ax.set_xscale("log")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("SPL (dB)")
    ax.set_title("Power Spectrum SPL")
    ax.set_xlim(0, 25000)
    plt.legend()
    return fig


if __name__ == "__main__":
    # 读取音频文件
    audio_path = [
        "example_files/Gaussian.wav", "example_files/K35.wav",
        "example_files/K75.wav"
    ]
    ss = []
    for path in audio_path:
        y, sr = librosa.load(path, sr=None)
        Leq = equivalent_sound_pressure_level(y, reference_pressure=2.33e-7)
        y = y/0.89 if Leq < 99 else y
        s = Signal(y, sr)
        Leq_new = equivalent_sound_pressure_level(s.values, reference_pressure=2.33e-7)
        ss.append(s)

    # 绘制时间平均的声压级变化图
    fig1 = plot_time_average_SPL(ss=ss,
                                 names=["Gaussian", "K25", "K50"],
                                 average_time=0.05,
                                 REFER_SOUND_PRESSURE=2.33e-7)
    fig1.savefig("pictures/time_average_SPL.svg", format="svg", bbox_inches="tight")

    # 绘制功率谱声压级变化图
    fig2 = plot_power_spectrum_SPL(ss=ss,
                                   names=["Gaussian", "K25", "K50"],
                                   REFER_SOUND_PRESSURE=2.33e-7,
                                   window_name="hamming",
                                   nperseg=512)
    fig2.savefig("pictures/power_spectrum_SPL.svg", format="svg", bbox_inches="tight")

    print(1)
