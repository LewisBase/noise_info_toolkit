# -*- coding: utf-8 -*-
"""
@DATE: 2026-04-06 10:00:00
@Author: Liu Hengjiang
@File: test/test_kurtosis_aggregation.py
@Software: vscode
@Description:
        峰度聚合算法测试脚本
        验证规范 4.X.11.1 的一致性要求：
        - 路径 A：直接从完整波形计算峰度
        - 路径 B：按秒计算 S1-S4，再合成峰度
        两者结果应在预设数值误差范围内一致
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from scipy.stats import kurtosis
import warnings

from app.core.time_history_processor import TimeHistoryProcessor, SecondMetrics
from app.core.summary_processor import (
    SummaryProcessor, 
    aggregate_from_moment_blocks,
    compare_kurtosis_methods
)
from app.utils import logger


def test_kurtosis_from_moments():
    """测试从原始矩计算峰度的基本功能"""
    print("=" * 60)
    print("测试 1: 从原始矩计算峰度")
    print("=" * 60)
    
    # 生成测试数据：正态分布（峰度应为 3）
    np.random.seed(42)
    data = np.random.normal(0, 1, 48000)  # 1秒 @ 48kHz
    
    # 方法 1：直接计算
    kurtosis_direct = kurtosis(data, fisher=False)
    
    # 方法 2：通过原始矩计算
    n = len(data)
    s1 = np.sum(data)
    s2 = np.sum(data ** 2)
    s3 = np.sum(data ** 3)
    s4 = np.sum(data ** 4)
    
    kurtosis_from_moments = TimeHistoryProcessor.calculate_kurtosis_from_moments(
        n, s1, s2, s3, s4
    )
    
    print(f"样本数: {n}")
    print(f"直接计算峰度: {kurtosis_direct:.6f}")
    print(f"原始矩计算峰度: {kurtosis_from_moments:.6f}")
    print(f"差异: {abs(kurtosis_direct - kurtosis_from_moments):.10f}")
    
    # 验证：两者应非常接近
    assert abs(kurtosis_direct - kurtosis_from_moments) < 1e-10, "峰度计算不一致"
    print("[PASS] 测试通过: 两种方法结果一致")
    print()


def test_moment_aggregation():
    """测试矩统计量的汇聚功能"""
    print("=" * 60)
    print("测试 2: 矩统计量汇聚")
    print("=" * 60)
    
    # 生成 60 秒的测试数据
    np.random.seed(42)
    sample_rate = 48000
    total_seconds = 60
    total_samples = sample_rate * total_seconds
    
    # 生成具有特定峰度的数据（使用拉普拉斯分布，超额峰度为 3，即峰度为 6）
    data = np.random.laplace(0, 1, total_samples)
    
    # 路径 A：直接计算 60 秒数据的峰度
    kurtosis_direct = kurtosis(data, fisher=False)
    
    # 路径 B：按秒计算 S1-S4，然后汇聚
    blocks = []
    for i in range(total_seconds):
        start = i * sample_rate
        end = (i + 1) * sample_rate
        second_data = data[start:end]
        
        n = len(second_data)
        s1 = np.sum(second_data)
        s2 = np.sum(second_data ** 2)
        s3 = np.sum(second_data ** 3)
        s4 = np.sum(second_data ** 4)
        blocks.append((n, s1, s2, s3, s4))
    
    # 汇聚计算峰度
    kurtosis_aggregated = aggregate_from_moment_blocks(blocks)
    
    print(f"总样本数: {len(data)}")
    print(f"直接计算峰度 (60s): {kurtosis_direct:.6f}")
    print(f"汇聚计算峰度 (60x1s): {kurtosis_aggregated:.6f}")
    print(f"绝对差异: {abs(kurtosis_direct - kurtosis_aggregated):.10f}")
    print(f"相对误差: {abs(kurtosis_direct - kurtosis_aggregated) / kurtosis_direct * 100:.6f}%")
    
    # 验证：相对误差应小于 1%
    relative_error = abs(kurtosis_direct - kurtosis_aggregated) / kurtosis_direct
    assert relative_error < 0.01, f"相对误差过大: {relative_error}"
    print("[PASS] 测试通过: 汇聚结果与直接计算一致（误差 < 1%）")
    print()


def test_with_real_audio_file(file_path: str):
    """使用真实音频文件测试"""
    print("=" * 60)
    print(f"测试 3: 真实音频文件测试 - {os.path.basename(file_path)}")
    print("=" * 60)
    
    try:
        import librosa
        from acoustics import Signal
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            y, sr = librosa.load(file_path, sr=None)
        
        signal = Signal(y, sr)
        data = signal.values
        duration = len(data) / sr
        
        print(f"文件: {file_path}")
        print(f"采样率: {sr} Hz")
        print(f"时长: {duration:.2f} s")
        print(f"样本数: {len(data)}")
        
        # 使用 compare_kurtosis_methods 进行对比
        result = compare_kurtosis_methods(data, sample_rate=sr)
        
        print(f"\n直接计算峰度: {result['kurtosis_direct']:.6f}")
        print(f"汇聚计算峰度: {result['kurtosis_aggregated']:.6f}")
        print(f"差异: {result['difference']:.10f}")
        print(f"相对误差: {result['relative_error'] * 100:.6f}%")
        print(f"一致性检查: {'通过' if result['consistent'] else '失败'}")
        
        if result['consistent']:
            print("[PASS] 测试通过: 真实音频文件的峰度计算一致")
        else:
            print("[WARN] 警告: 真实音频文件的峰度计算存在较大差异")
        
        return result
        
    except Exception as e:
        print(f"[FAIL] 测试失败: {e}")
        import traceback
        print(traceback.format_exc())
        return None


def test_summary_processor():
    """测试 SummaryProcessor 的完整流程"""
    print("=" * 60)
    print("测试 4: SummaryProcessor 完整流程测试")
    print("=" * 60)
    
    from datetime import datetime
    
    # 创建 SummaryProcessor
    processor = SummaryProcessor(aggregation_seconds=60)
    
    # 生成 120 秒的模拟秒级数据
    np.random.seed(42)
    aggregated_results = []
    
    def on_aggregated(metrics):
        aggregated_results.append(metrics)
        print(f"  汇聚完成: LAeq={metrics.LAeq:.2f}, beta={metrics.beta_kurtosis:.4f}, "
              f"samples={metrics.sample_count}")
    
    processor.set_callback(on_aggregated)
    
    # 模拟每秒数据
    base_time = datetime.utcnow()
    for i in range(120):
        # 生成每秒的数据（使用拉普拉斯分布）
        second_data = np.random.laplace(0, 1, 48000)
        
        n = len(second_data)
        s1 = np.sum(second_data)
        s2 = np.sum(second_data ** 2)
        s3 = np.sum(second_data ** 3)
        s4 = np.sum(second_data ** 4)
        
        # 计算该秒的 LAeq（简化）
        laeq = 10 * np.log10(np.mean(second_data ** 2) + 1e-10) + 94  # 简化的声压级计算
        
        metrics = SecondMetrics(
            timestamp=base_time + __import__('datetime').timedelta(seconds=i),
            duration_s=1.0,
            LAeq=laeq,
            LCeq=laeq + 1,
            LZeq=laeq + 2,
            n_samples=n,
            sum_x=s1,
            sum_x2=s2,
            sum_x3=s3,
            sum_x4=s4,
            beta_kurtosis=TimeHistoryProcessor.calculate_kurtosis_from_moments(n, s1, s2, s3, s4)
        )
        
        result = processor.add_second_metrics(metrics)
    
    # 刷新剩余数据
    remaining = processor.flush_remaining()
    
    print(f"\n生成了 {len(aggregated_results)} 个完整时段")
    print(f"处理器统计: {processor.get_stats()}")
    
    # 验证：应该有 2 个完整的 60 秒时段
    assert len(aggregated_results) == 2, f"预期 2 个时段，实际 {len(aggregated_results)} 个"
    print("[PASS] 测试通过: SummaryProcessor 正确汇聚数据")
    print()


def test_edge_cases():
    """测试边界条件"""
    print("=" * 60)
    print("测试 5: 边界条件测试")
    print("=" * 60)
    
    # 测试 1：零样本
    result = TimeHistoryProcessor.calculate_kurtosis_from_moments(0, 0, 0, 0, 0)
    assert result is None, "零样本应返回 None"
    print("[PASS] 零样本处理正确")
    
    # 测试 2：负方差（m2 <= 0）
    result = TimeHistoryProcessor.calculate_kurtosis_from_moments(10, 100, 0, 0, 0)
    assert result is None, "负方差应返回 None"
    print("[PASS] 负方差处理正确")
    
    # 测试 3：所有相同样本（方差为 0）
    result = TimeHistoryProcessor.calculate_kurtosis_from_moments(10, 50, 50, 50, 50)
    assert result is None, "零方差应返回 None"
    print("[PASS] 零方差处理正确")
    
    # 测试 4：正常数据
    data = np.random.normal(0, 1, 1000)
    n = len(data)
    s1 = np.sum(data)
    s2 = np.sum(data ** 2)
    s3 = np.sum(data ** 3)
    s4 = np.sum(data ** 4)
    result = TimeHistoryProcessor.calculate_kurtosis_from_moments(n, s1, s2, s3, s4)
    assert result is not None, "正常数据应返回有效结果"
    assert 2 < result < 4, f"正态分布峰度应在 3 附近，实际 {result}"
    print(f"[PASS] 正常数据处理正确 (峰度={result:.4f})")
    
    print("\n[PASS] 所有边界条件测试通过")
    print()


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("峰度聚合算法一致性测试")
    print("根据规范 4.X.11 的验证要求")
    print("=" * 60 + "\n")
    
    # 运行基本测试
    test_kurtosis_from_moments()
    test_moment_aggregation()
    test_summary_processor()
    test_edge_cases()
    
    # 测试真实音频文件
    audio_dir = "./audio_files"
    if os.path.exists(audio_dir):
        audio_files = [f for f in os.listdir(audio_dir) if f.endswith('.wav')]
        if audio_files:
            for audio_file in audio_files[:2]:  # 只测试前 2 个文件
                file_path = os.path.join(audio_dir, audio_file)
                test_with_real_audio_file(file_path)
                print()
        else:
            print("[WARN] 未找到 WAV 音频文件，跳过真实文件测试")
    else:
        print(f"[WARN] 音频目录不存在: {audio_dir}")
    
    print("=" * 60)
    print("所有测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
