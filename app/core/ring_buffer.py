# -*- coding: utf-8 -*-
"""
@DATE: 2026-02-15 10:30:00
@Author: Liu Hengjiang
@File: app/core/ring_buffer.py
@Software: vscode
@Description:
        环形波形缓冲区
        用于保存事件触发前后的音频数据 (pre-trigger + post-trigger)
"""

import numpy as np
from datetime import datetime
from typing import Optional, Tuple
from pathlib import Path
import soundfile as sf

from app.utils import logger


class RingBuffer:
    """
    环形波形缓冲区
    
    根据白皮书要求：
    - 缓冲时长：≥ 12 秒
    - 触发前保留：2 秒 (pre-trigger)
    - 触发后录制：8 秒 (post-trigger)
    """
    
    def __init__(self,
                 sample_rate: int = 48000,
                 buffer_duration_s: float = 12.0,
                 pretrigger_s: float = 2.0,
                 posttrigger_s: float = 8.0,
                 channels: int = 1):
        """
        初始化环形缓冲区
        
        Args:
            sample_rate: 采样率 (Hz)
            buffer_duration_s: 缓冲区总时长 (秒)
            pretrigger_s: 触发前保留时长 (秒)
            posttrigger_s: 触发后录制时长 (秒)
            channels: 通道数
        """
        self.sample_rate = sample_rate
        self.buffer_duration_s = buffer_duration_s
        self.pretrigger_s = pretrigger_s
        self.posttrigger_s = posttrigger_s
        self.channels = channels
        
        # 计算样本数
        self.buffer_size = int(sample_rate * buffer_duration_s)
        self.pretrigger_samples = int(sample_rate * pretrigger_s)
        self.posttrigger_samples = int(sample_rate * posttrigger_s)
        
        # 初始化缓冲区
        if channels == 1:
            self.buffer = np.zeros(self.buffer_size, dtype=np.float32)
        else:
            self.buffer = np.zeros((self.buffer_size, channels), dtype=np.float32)
        
        self.write_index = 0
        self.is_full = False
        self.total_written = 0
        
        logger.info(f"RingBuffer initialized: {buffer_duration_s}s buffer, "
                   f"{pretrigger_s}s pre-trigger, {posttrigger_s}s post-trigger, "
                   f"{sample_rate}Hz, {channels}ch")
    
    def write(self, samples: np.ndarray) -> int:
        """
        写入新样本到环形缓冲区
        
        Args:
            samples: 音频样本 (samples,) 或 (samples, channels)
            
        Returns:
            int: 实际写入的样本数
        """
        samples_to_write = len(samples)
        
        if self.channels == 1:
            # 单通道
            if self.write_index + samples_to_write <= self.buffer_size:
                self.buffer[self.write_index:self.write_index + samples_to_write] = samples
            else:
                # 环绕写入
                first_part = self.buffer_size - self.write_index
                self.buffer[self.write_index:] = samples[:first_part]
                self.buffer[:samples_to_write - first_part] = samples[first_part:]
        else:
            # 多通道
            if self.write_index + samples_to_write <= self.buffer_size:
                self.buffer[self.write_index:self.write_index + samples_to_write, :] = samples
            else:
                # 环绕写入
                first_part = self.buffer_size - self.write_index
                self.buffer[self.write_index:, :] = samples[:first_part, :]
                self.buffer[:samples_to_write - first_part, :] = samples[first_part:, :]
        
        self.write_index = (self.write_index + samples_to_write) % self.buffer_size
        self.total_written += samples_to_write
        
        if not self.is_full and self.total_written >= self.buffer_size:
            self.is_full = True
        
        return samples_to_write
    
    def get_pretrigger_data(self) -> np.ndarray:
        """
        获取触发前数据
        
        Returns:
            np.ndarray: pre-trigger 音频数据
        """
        if self.write_index >= self.pretrigger_samples:
            # 连续数据，直接切片
            return self.buffer[self.write_index - self.pretrigger_samples:self.write_index]
        else:
            # 环绕数据，需要拼接
            first_part = self.pretrigger_samples - self.write_index
            if self.channels == 1:
                return np.concatenate([
                    self.buffer[self.buffer_size - first_part:],
                    self.buffer[:self.write_index]
                ])
            else:
                return np.concatenate([
                    self.buffer[self.buffer_size - first_part:, :],
                    self.buffer[:self.write_index, :]
                ])
    
    def get_continuous_buffer(self) -> np.ndarray:
        """
        获取连续的缓冲区数据（从最早到最新）
        
        Returns:
            np.ndarray: 按时间顺序排列的缓冲区数据
        """
        if not self.is_full:
            # 缓冲区未满，直接返回已写入部分
            return self.buffer[:self.write_index]
        
        # 缓冲区已满，需要重新排序
        if self.channels == 1:
            return np.concatenate([
                self.buffer[self.write_index:],
                self.buffer[:self.write_index]
            ])
        else:
            return np.concatenate([
                self.buffer[self.write_index:, :],
                self.buffer[:self.write_index, :]
            ])
    
    def save_event_audio(self,
                         event_id: str,
                         posttrigger_data: np.ndarray,
                         output_dir: str = "./audio_events") -> str:
        """
        保存事件音频（pre-trigger + post-trigger）
        
        Args:
            event_id: 事件ID
            posttrigger_data: 触发后录制的音频数据
            output_dir: 输出目录
            
        Returns:
            str: 保存的文件路径
        """
        # 创建输出目录
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # 获取触发前数据
        pretrigger_data = self.get_pretrigger_data()
        
        # 合并数据
        if self.channels == 1:
            full_event_audio = np.concatenate([pretrigger_data, posttrigger_data])
        else:
            full_event_audio = np.concatenate([pretrigger_data, posttrigger_data], axis=0)
        
        # 防止削波
        max_val = np.max(np.abs(full_event_audio))
        if max_val > 1.0:
            full_event_audio = full_event_audio / max_val * 0.95
            logger.warning(f"Event audio normalized due to clipping: {max_val:.2f}")
        
        # 保存为WAV
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{event_id}_{timestamp}.wav"
        filepath = output_path / filename
        
        sf.write(str(filepath), full_event_audio, self.sample_rate)
        
        logger.info(f"Event audio saved: {filepath} "
                   f"(pre={len(pretrigger_data)/self.sample_rate:.2f}s, "
                   f"post={len(posttrigger_data)/self.sample_rate:.2f}s)")
        
        return str(filepath)
    
    def get_buffer_info(self) -> dict:
        """获取缓冲区信息"""
        return {
            'sample_rate': self.sample_rate,
            'buffer_duration_s': self.buffer_duration_s,
            'buffer_size_samples': self.buffer_size,
            'pretrigger_s': self.pretrigger_s,
            'pretrigger_samples': self.pretrigger_samples,
            'posttrigger_s': self.posttrigger_s,
            'posttrigger_samples': self.posttrigger_samples,
            'channels': self.channels,
            'is_full': self.is_full,
            'write_index': self.write_index,
            'total_written': self.total_written,
        }
    
    def clear(self):
        """清空缓冲区"""
        if self.channels == 1:
            self.buffer = np.zeros(self.buffer_size, dtype=np.float32)
        else:
            self.buffer = np.zeros((self.buffer_size, self.channels), dtype=np.float32)
        
        self.write_index = 0
        self.is_full = False
        self.total_written = 0
        
        logger.info("RingBuffer cleared")


class MultiChannelRingBuffer:
    """多通道环形缓冲区管理器"""
    
    def __init__(self,
                 sample_rate: int = 48000,
                 buffer_duration_s: float = 12.0,
                 pretrigger_s: float = 2.0,
                 posttrigger_s: float = 8.0,
                 num_channels: int = 2):
        """
        初始化多通道环形缓冲区
        
        Args:
            sample_rate: 采样率
            buffer_duration_s: 缓冲区时长
            pretrigger_s: 触发前保留时长
            posttrigger_s: 触发后录制时长
            num_channels: 通道数
        """
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        
        # 为每个通道创建独立的缓冲区
        self.buffers = [
            RingBuffer(sample_rate, buffer_duration_s, pretrigger_s, posttrigger_s, channels=1)
            for _ in range(num_channels)
        ]
        
        logger.info(f"MultiChannelRingBuffer initialized: {num_channels} channels")
    
    def write(self, samples: np.ndarray) -> int:
        """
        写入多通道样本
        
        Args:
            samples: 形状为 (samples, channels) 或 (samples,) 的数组
            
        Returns:
            int: 实际写入的样本数
        """
        if samples.ndim == 1:
            # 单通道数据，写入第一个缓冲区
            return self.buffers[0].write(samples)
        
        # 多通道数据
        samples_written = 0
        for ch in range(min(self.num_channels, samples.shape[1])):
            ch_samples = samples[:, ch]
            samples_written = self.buffers[ch].write(ch_samples)
        
        return samples_written
    
    def get_pretrigger_data(self, channel: int = 0) -> np.ndarray:
        """获取指定通道的触发前数据"""
        if 0 <= channel < self.num_channels:
            return self.buffers[channel].get_pretrigger_data()
        return np.array([])
    
    def save_event_audio(self,
                         event_id: str,
                         posttrigger_data: np.ndarray,
                         channel: int = 0,
                         output_dir: str = "./audio_events") -> str:
        """
        保存指定通道的事件音频
        
        Args:
            event_id: 事件ID
            posttrigger_data: 触发后数据
            channel: 通道索引
            output_dir: 输出目录
            
        Returns:
            str: 保存的文件路径
        """
        if 0 <= channel < self.num_channels:
            return self.buffers[channel].save_event_audio(
                event_id, posttrigger_data, output_dir
            )
        return ""
    
    def clear(self):
        """清空所有通道的缓冲区"""
        for buf in self.buffers:
            buf.clear()
