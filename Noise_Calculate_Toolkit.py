# -*- coding: utf-8 -*-
"""
@DATE: 2024-12-13 20:52:55
@Author: Liu Hengjiang
@File: Noise_Calculate_Toolkit.py
@Software: vscode
@Description:
        噪声等效声压级计算工具展示
"""
import streamlit as st
import pandas as pd
import numpy as np
from functional import seq
from scipy.stats import kurtosis
from acoustics import Signal
from acoustics.standards.iso_tr_25417_2007 import sound_pressure_level, peak_sound_pressure_level

REFER_SOUND_PRESSURE = 20e-6
 
def calculate_Leq(time_s, spl):
    dt = time_s[-1] / len(time_s)
    total_t = time_s[-1]
    Leq = 10 * np.log10(np.nansum(10**(0.1 * np.array(spl))) * dt / total_t)
    return Leq
    
if __name__ == "__main__":
    root_path = "."
    
    st.write("# 噪声等效声压级计算工具")
    st.write("功能：根据文件中的噪声的声压信息完成对噪声相关指标的计算。")
    st.write("输入：请上传一个Excle文件。文件中需包含两列内容，分别为等间隔分布的时间（单位：ms）与声压（单位：kpa）")
    uploaded_file = st.file_uploader("点击上传或拖拽文件至下方", type=["xlsx", "xls"])
    if uploaded_file is not None:
        # 显示文件名
        st.write(f"您选择了文件: {uploaded_file.name}")
        try:
            # 使用pandas读取Excel文件
            df = pd.read_excel(uploaded_file, engine="openpyxl")
            # 显示数据框
            st.subheader("原始数据")
            st.dataframe(df.T)
            # 进行一些简单处理（例如，统计描述）
            st.subheader("计算结果")
            time_s = df.iloc[:,0].values / 1000
            pressure_pa = df.iloc[:,1].values * 1000
            fs = int(1 / np.mean(np.diff(time_s)))
            s = Signal(pressure_pa, fs)
            
            SPL = sound_pressure_level(s.values)
            Peak_SPL = peak_sound_pressure_level(s.values)
            Leq = s.leq()
            LAeq = s.weigh("A").leq()
            LCeq = s.weigh("C").leq()
            kurtosis_total = kurtosis(s.values, fisher=False)
            A_kurtosis_total = kurtosis(s.weigh("A").values, fisher=False)
            C_kurtosis_total = kurtosis(s.weigh("C").values, fisher=False)
            st.write(f"Peak SPL = {round(Peak_SPL, 2)} dB")
            st.write(f"Leq = {round(Leq, 2)} dB")
            st.write(f"LAeq = {round(LAeq, 2)} dB")
            st.write(f"LCeq = {round(LCeq, 2)} dB")
            st.write(f"Total kurtosis= {round(kurtosis_total, 2)}")
            st.write(f"Total A Weighting kurtosis= {round(A_kurtosis_total, 2)}")
            st.write(f"Total C Weighting kurtosis= {round(C_kurtosis_total, 2)}")
            
        except Exception as e:
            st.error(f"读取文件时出错: {e}")

    

  