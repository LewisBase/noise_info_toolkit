# -*- coding: utf-8 -*-
"""
@DATE: 2026-04-04
@Author: Liu Hengjiang
@File: utils/tdms_converter.py
@Description:
    独立的TDMS转WAV格式转换工具
    支持单文件转换和批量转换功能
"""

import numpy as np
import soundfile as sf
from nptdms import TdmsFile
from pathlib import Path
from typing import Union, Optional, List
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TDMSConverter:
    """TDMS文件转WAV格式转换器
    
    用于将TDMS格式的噪声信号文件转换为WAV音频格式。
    支持自动采样率检测和多通道数据处理。
    """
    
    def __init__(self):
        pass
    
    def convert_tdms_to_wav(
        self, 
        tdms_file_path: str, 
        wav_file_path: Optional[str] = None, 
        sampling_rate: int = 44100,
        channel_index: int = 0
    ) -> str:
        """将单个TDMS文件转换为WAV格式
        
        Args:
            tdms_file_path: TDMS文件的完整路径
            wav_file_path: 输出WAV文件的路径，默认为None（在同一目录生成）
            sampling_rate: 默认采样率（Hz），当无法从TDMS文件中提取时使用
            channel_index: 要提取的通道索引，默认为0（第一个通道）
            
        Returns:
            转换后的WAV文件路径
            
        Raises:
            FileNotFoundError: TDMS文件不存在
            ValueError: TDMS文件格式错误或没有有效的数据组/通道
        """
        tdms_path = Path(tdms_file_path)
        
        # 检查文件是否存在
        if not tdms_path.exists():
            raise FileNotFoundError(f"TDMS文件不存在: {tdms_file_path}")
        
        # 如果没有指定输出路径，在同一目录生成WAV文件
        if wav_file_path is None:
            wav_file_path = tdms_path.parent / f"{tdms_path.stem}.wav"
        else:
            wav_file_path = Path(wav_file_path)
        
        try:
            logger.info(f"正在读取TDMS文件: {tdms_file_path}")
            tdms_file = TdmsFile.read(tdms_file_path)
            
            # 获取所有组
            groups = tdms_file.groups()
            if not groups:
                raise ValueError("TDMS文件中没有找到任何数据组")
            
            # 获取第一个组
            first_group = groups[0]
            channels = first_group.channels()
            
            if not channels:
                raise ValueError("TDMS文件的第一个数据组中没有找到任何通道")
            
            # 检查通道索引是否有效
            if channel_index >= len(channels):
                raise ValueError(
                    f"指定的通道索引 {channel_index} 超出范围，"
                    f"该文件共有 {len(channels)} 个通道"
                )
            
            # 获取指定通道的数据
            target_channel = channels[channel_index]
            data = target_channel[:]
            
            # 尝试从TDMS文件中提取采样率
            actual_sampling_rate = sampling_rate
            try:
                if hasattr(target_channel, "properties"):
                    props = target_channel.properties
                    if "SampleRate" in props:
                        actual_sampling_rate = int(props["SampleRate"])
                    elif "sample_rate" in props:
                        actual_sampling_rate = int(props["sample_rate"])
                    elif "wf_samples" in props and "wf_increment" in props:
                        # 从NI标准属性计算采样率
                        actual_sampling_rate = int(1.0 / props["wf_increment"])
                logger.info(f"检测到采样率: {actual_sampling_rate} Hz")
            except Exception as e:
                logger.warning(f"无法从TDMS文件提取采样率，使用默认值 {sampling_rate} Hz: {e}")
                actual_sampling_rate = sampling_rate
            
            # 数据格式转换和归一化
            if data.dtype != np.float32:
                if data.dtype in [np.int16, np.int32]:
                    # 整数类型归一化到 [-1, 1]
                    data = data.astype(np.float32) / np.iinfo(data.dtype).max
                else:
                    # 其他类型按最大值归一化
                    data_max = np.max(np.abs(data))
                    if data_max > 0:
                        data = data.astype(np.float32) / data_max
                    else:
                        data = data.astype(np.float32)
            
            # 写入WAV文件
            logger.info(f"正在写入WAV文件: {wav_file_path}")
            sf.write(wav_file_path, data, actual_sampling_rate, subtype='FLOAT')
            logger.info(f"转换成功: {tdms_file_path} -> {wav_file_path}")
            
            return str(wav_file_path)
            
        except Exception as e:
            logger.error(f"转换失败: {e}")
            raise
    
    def batch_convert(
        self, 
        input_directory: str, 
        output_directory: Optional[str] = None,
        pattern: str = "*.tdms",
        sampling_rate: int = 44100
    ) -> List[str]:
        """批量转换目录中的TDMS文件
        
        Args:
            input_directory: 包含TDMS文件的输入目录
            output_directory: WAV文件的输出目录，默认为None（使用输入目录）
            pattern: 文件匹配模式，默认为"*.tdms"
            sampling_rate: 默认采样率（Hz）
            
        Returns:
            成功转换的文件路径列表
        """
        input_dir = Path(input_directory)
        
        if not input_dir.exists():
            raise FileNotFoundError(f"输入目录不存在: {input_directory}")
        
        # 设置输出目录
        if output_directory is None:
            output_dir = input_dir
        else:
            output_dir = Path(output_directory)
            output_dir.mkdir(parents=True, exist_ok=True)
        
        # 查找所有匹配的TDMS文件
        tdms_files = list(input_dir.glob(pattern))
        
        if not tdms_files:
            logger.warning(f"在 {input_directory} 中没有找到匹配的TDMS文件")
            return []
        
        logger.info(f"找到 {len(tdms_files)} 个TDMS文件待转换")
        
        converted_files = []
        failed_files = []
        
        for tdms_file in tdms_files:
            try:
                wav_file_path = output_dir / f"{tdms_file.stem}.wav"
                converted_path = self.convert_tdms_to_wav(
                    str(tdms_file), 
                    str(wav_file_path),
                    sampling_rate
                )
                converted_files.append(converted_path)
            except Exception as e:
                logger.error(f"转换失败 [{tdms_file.name}]: {e}")
                failed_files.append(str(tdms_file))
                continue
        
        logger.info(f"批量转换完成: 成功 {len(converted_files)} 个, 失败 {len(failed_files)} 个")
        
        return converted_files
    
    def get_tdms_info(self, tdms_file_path: str) -> dict:
        """获取TDMS文件的基本信息
        
        Args:
            tdms_file_path: TDMS文件路径
            
        Returns:
            包含文件信息的字典
        """
        tdms_path = Path(tdms_file_path)
        
        if not tdms_path.exists():
            raise FileNotFoundError(f"TDMS文件不存在: {tdms_file_path}")
        
        try:
            tdms_file = TdmsFile.read(tdms_file_path)
            
            info = {
                "file_path": str(tdms_path),
                "file_name": tdms_path.name,
                "file_size_bytes": tdms_path.stat().st_size,
                "groups": []
            }
            
            for group in tdms_file.groups():
                group_info = {
                    "name": group.name,
                    "channels": []
                }
                
                for channel in group.channels():
                    channel_info = {
                        "name": channel.name,
                        "data_type": str(channel.data_type),
                        "data_length": len(channel),
                        "properties": {}
                    }
                    
                    # 提取通道属性
                    if hasattr(channel, "properties"):
                        for key, value in channel.properties.items():
                            channel_info["properties"][key] = str(value)
                    
                    group_info["channels"].append(channel_info)
                
                info["groups"].append(group_info)
            
            return info
            
        except Exception as e:
            logger.error(f"读取TDMS文件信息失败: {e}")
            raise


def main():
    """命令行入口函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="TDMS转WAV格式转换工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  1. 转换单个文件:
     python -m utils.tdms_converter -i input.tdms -o output.wav
  
  2. 批量转换目录:
     python -m utils.tdms_converter -d ./tdms_files -o ./wav_files
  
  3. 查看TDMS文件信息:
     python -m utils.tdms_converter -i input.tdms --info
        """
    )
    
    parser.add_argument("-i", "--input", type=str, help="输入的TDMS文件路径")
    parser.add_argument("-o", "--output", type=str, help="输出的WAV文件路径或目录")
    parser.add_argument("-d", "--directory", type=str, help="包含TDMS文件的输入目录（批量转换）")
    parser.add_argument("-r", "--rate", type=int, default=44100, help="采样率（Hz），默认44100")
    parser.add_argument("-c", "--channel", type=int, default=0, help="通道索引，默认0")
    parser.add_argument("--info", action="store_true", help="仅显示TDMS文件信息，不进行转换")
    
    args = parser.parse_args()
    
    converter = TDMSConverter()
    
    # 查看文件信息模式
    if args.info and args.input:
        try:
            info = converter.get_tdms_info(args.input)
            print(f"\nTDMS文件信息: {info['file_name']}")
            print(f"文件大小: {info['file_size_bytes'] / 1024:.2f} KB")
            print(f"数据组数量: {len(info['groups'])}")
            
            for i, group in enumerate(info['groups']):
                print(f"\n  组 [{i}]: {group['name']}")
                print(f"  通道数量: {len(group['channels'])}")
                
                for j, ch in enumerate(group['channels']):
                    print(f"\n    通道 [{j}]: {ch['name']}")
                    print(f"    数据类型: {ch['data_type']}")
                    print(f"    数据长度: {ch['data_length']}")
                    if ch['properties']:
                        print(f"    属性:")
                        for k, v in ch['properties'].items():
                            print(f"      {k}: {v}")
        except Exception as e:
            print(f"错误: {e}")
            return 1
        return 0
    
    # 批量转换模式
    if args.directory:
        try:
            converted = converter.batch_convert(
                args.directory,
                args.output,
                sampling_rate=args.rate
            )
            print(f"\n批量转换完成，共转换 {len(converted)} 个文件")
            for f in converted:
                print(f"  - {f}")
        except Exception as e:
            print(f"错误: {e}")
            return 1
        return 0
    
    # 单文件转换模式
    if args.input:
        try:
            output_path = converter.convert_tdms_to_wav(
                args.input,
                args.output,
                args.rate,
                args.channel
            )
            print(f"\n转换成功: {output_path}")
        except Exception as e:
            print(f"错误: {e}")
            return 1
        return 0
    
    # 如果没有参数，显示帮助
    parser.print_help()
    return 0


if __name__ == "__main__":
    exit(main())
