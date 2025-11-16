"""
TDMS to WAV converter module
"""
import numpy as np
import soundfile as sf
from nptdms import TdmsFile
from pathlib import Path
from typing import Union, Optional

from app.utils import logger


class TDMSConverter:
    """Convert TDMS files to WAV format"""
    
    def __init__(self):
        pass
    
    def convert_tdms_to_wav(self, tdms_file_path: str, wav_file_path: str = None, sampling_rate: int = 44100) -> str:
        """Convert a TDMS file to WAV format
        
        Args:
            tdms_file_path (str): Path to the TDMS file
            wav_file_path (str, optional): Path for the output WAV file. 
                                         If None, will create a WAV file in the same directory.
                                         
        Returns:
            str: Path to the converted WAV file
        """
        try:
            # If no output path specified, create one based on the input file with a temporary name
            if wav_file_path is None:
                tdms_path = Path(tdms_file_path)
                wav_file_path = tdms_path.parent / f"temp_{tdms_path.stem}.wav"
            # Read TDMS file
            logger.info(f"Reading TDMS file: {tdms_file_path}")
            tdms_file = TdmsFile.read(tdms_file_path)
            # Extract data from the first channel (assuming single channel audio)
            # You might need to adjust this based on your specific TDMS file structure
            groups = tdms_file.groups()
            if not groups:
                raise ValueError("No groups found in TDMS file")
            # Get the first group and channel
            first_group = groups[0]
            channels = first_group.channels()
            if not channels:
                raise ValueError("No channels found in the first group")
            # Get data from the first channel
            first_channel = channels[0]
            data = first_channel[:]
            # Get sampling rate if available
            try:
                # Try to get sampling rate from properties
                if hasattr(first_channel, "properties"):
                    if "SampleRate" in first_channel.properties:
                        sampling_rate = first_channel.properties["SampleRate"]
                    elif "sample_rate" in first_channel.properties:
                        sampling_rate = first_channel.properties["sample_rate"]
            except Exception as e:
                logger.warning(f"Could not extract sampling rate from TDMS file: {e}")
            # Convert to float32 if needed (soundfile works best with float32)
            if data.dtype != np.float32:
                # Normalize data to [-1, 1] range for audio
                if data.dtype in [np.int16, np.int32]:
                    data = data.astype(np.float32) / np.iinfo(data.dtype).max
                else:
                    # For other data types, normalize to [-1, 1]
                    data_max = np.max(np.abs(data))
                    if data_max > 0:
                        data = data.astype(np.float32) / data_max
                    else:
                        data = data.astype(np.float32)
            
            # Ensure the data is in the proper format for librosa
            # Write to WAV file with format that librosa can easily read
            logger.info(f"Writing WAV file: {wav_file_path}")
            sf.write(wav_file_path, data, sampling_rate, subtype='FLOAT')
            logger.info(f"Successfully converted {tdms_file_path} to {wav_file_path}")
            return str(wav_file_path)
        except Exception as e:
            logger.error(f"Error converting TDMS to WAV: {e}")
            raise
    
    def batch_convert_tdms_files(self, tdms_directory: str, wav_directory: str = None) -> list:
        """Convert all TDMS files in a directory to WAV format
        Args:
            tdms_directory (str): Directory containing TDMS files
            wav_directory (str, optional): Directory for output WAV files.
                                         If None, will create WAV files in the same directory.
        Returns:
            list: List of paths to converted WAV files
        """
        tdms_dir = Path(tdms_directory)
        if not tdms_dir.exists():
            raise FileNotFoundError(f"Directory {tdms_directory} does not exist")
        # If no output directory specified, use the same directory
        if wav_directory is None:
            wav_directory = tdms_directory
        else:
            wav_dir = Path(wav_directory)
            wav_dir.mkdir(parents=True, exist_ok=True)
        # Find all TDMS files
        tdms_files = list(tdms_dir.glob("*.tdms"))
        converted_files = []
        for tdms_file in tdms_files:
            try:
                wav_file_path = Path(wav_directory) / f"temp_{tdms_file.stem}.wav"
                converted_path = self.convert_tdms_to_wav(str(tdms_file), str(wav_file_path))
                converted_files.append(converted_path)
            except Exception as e:
                logger.error(f"Failed to convert {tdms_file}: {e}")
                continue
        
        return converted_files
