"""
Background tasks for audio processing
"""
import asyncio
from typing import Callable
from pathlib import Path

from app.utils import logger
from app.core.audio_processor import AudioProcessor
from app.core.file_monitor import AudioFileMonitor
from app.core.tdms_converter import TDMSConverter


class AudioProcessingTaskManager:
    """Manage audio processing background tasks"""
    
    def __init__(self, watch_directory: str = "./audio_files"):
        self.watch_directory = watch_directory
        # Monitor both WAV and TDMS files
        self.audio_monitor = AudioFileMonitor(watch_directory, [".wav", ".tdms"])
        self.audio_processor = AudioProcessor()
        self.tdms_converter = TDMSConverter()
        self.processing_callback = None
        self.is_monitoring = False
        
    def set_processing_callback(self, callback: Callable):
        """Set callback function for processing results"""
        self.processing_callback = callback
        
    async def start_monitoring(self):
        """Start monitoring audio files"""
        if not self.is_monitoring:
            self.is_monitoring = True
            logger.info(f"Starting audio file monitoring in {self.watch_directory}")
            
            # Start file monitoring
            self.audio_monitor.start_monitoring(self._on_audio_file_detected)
            
    async def stop_monitoring(self):
        """Stop monitoring audio files"""
        if self.is_monitoring:
            self.is_monitoring = False
            logger.info("Stopping audio file monitoring")
            self.audio_monitor.stop_monitoring()
            
    def _on_audio_file_detected(self, file_path: str):
        """Handle detected audio file"""
        logger.info(f"New audio file detected: {file_path}")
        
        # Process the audio file asynchronously
        asyncio.create_task(self._process_audio_file(file_path))
        
    async def _process_audio_file(self, file_path: str):
        """Process audio file asynchronously"""
        try:
            logger.info(f"Processing audio file: {file_path}")
            
            # Check file extension
            file_ext = Path(file_path).suffix.lower()
            
            # If it's a TDMS file, convert it to WAV first
            if file_ext == ".tdms":
                logger.info(f"Converting TDMS file to WAV: {file_path}")
                wav_file_path = self.tdms_converter.convert_tdms_to_wav(file_path)
                processing_file_path = wav_file_path
            else:
                processing_file_path = file_path
            
            # Process the audio file (WAV format)
            results = self.audio_processor.process_wav_file(processing_file_path)
            
            # Call callback with results if set
            if self.processing_callback:
                await self.processing_callback(file_path, results)
                
            logger.info(f"Finished processing audio file: {file_path}")
            
        except Exception as e:
            logger.error(f"Error processing audio file {file_path}: {str(e)}")