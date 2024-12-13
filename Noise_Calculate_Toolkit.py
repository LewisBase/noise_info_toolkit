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

REFER_SOUND_PRESSURE = 2e-5
 
def calculate_Leq(df):
    dt = df.iloc[0, 0]
    total_t = df.iloc[-1, 0]
    Leq = 10 * np.log10(np.nansum(10**(0.1 * df["SPL"])) * dt / total_t)
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
            df["SPL"] = df.iloc[:,1].apply(lambda x: 10 * np.log10((x * 10**3)**2 / REFER_SOUND_PRESSURE**2))
            st.write(df.describe().T)
            peak_sound_pressure_level = np.nanmax(df["SPL"].values)
            Leq = calculate_Leq(df=df)
            st.write(f"Peak Sound Pressure Level = {round(peak_sound_pressure_level, 2)} dB")
            st.write(f"Leq = {round(Leq, 2)} dB")
        except Exception as e:
            st.error(f"读取文件时出错: {e}")

    

  