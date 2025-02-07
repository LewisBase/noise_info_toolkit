# -*- coding: utf-8 -*-
"""
@DATE: 2025-02-07 21:10:07
@Author: Liu Hengjiang
@File: noise_info_toolkit.py
@Software: vscode
@Description:
        mainPage
"""

import streamlit as st


if __name__ == "__main__":
    st.write("# 噪声等效声压级计算工具")
    st.write("根据噪声信息完成对噪声相关指标的计算。")
    page = st.sidebar.selectbox("选择要处理的文件类型", ["wav", "xls"])
    if page == "wav":
        st.write("## 读入wav文件")
        st.write("功能：读入wav文件并完成对噪声相关指标的计算。")
        wav_page = __import__("wav_file_toolkit")
        wav_page.run()
    elif page == "xls":
        st.write("## 读入xls文件")
        st.write("功能：读入xls文件并完成对噪声相关指标的计算。")
        xls_page = __import__("xls_file_toolkit")
        xls_page.run()
    
