from nptdms import TdmsFile
from loguru import logger
import pandas as pd

def read_tdms(file_path):
    """读取 TDMS 文件并解析数据"""
    try:
        # 读取文件
        tdms_file = TdmsFile.read(file_path)
        
        # 遍历所有组和通道
        for group in tdms_file.groups():
            logger.info(f"\n组名: {group.name}")
            
            # 遍历通道
            for channel in group.channels():
                data = channel[:]
                
                logger.info(f"\n通道: {channel.name}")
                logger.info(f"单位: {channel.properties.get('unit_string', '无')}")
                logger.info(f"数据量: {len(data)}")
                logger.info(f"前5个数据点: {data[:5]}")
                
                # # 提取时间戳（如果存在）
                # if channel.has_time:
                #     time = channel.time_track()
                #     df = pd.DataFrame({'Time': time, 'Value': data})
                #     logger.info("\nDataFrame 示例:")
                #     logger.info(df.head())
                # else:
                #     logger.info("无时间戳信息")
    
    except Exception as e:
        logger.info(f"读取失败: {str(e)}")
    return tdms_file

# 使用示例
read_tdms("example_files/CH1_20250415_124437.tdms")