"""
Background tasks for audio processing
"""
import asyncio
from typing import Callable, List
from pathlib import Path
import concurrent.futures
import os

from app.utils import logger
from app.core.audio_processor import AudioProcessor
from app.core.file_monitor import AudioFileMonitor
from app.core.tdms_converter import TDMSConverter
from app.database import DatabaseManager
from app.models import ProcessingResultSchema


class AudioProcessingTaskManager:
    """Manage audio processing background tasks"""

    def __init__(self, watch_directory: str = "./audio_files"):
        self.watch_directory = watch_directory
        self.audio_monitor = AudioFileMonitor(watch_directory, [".tdms"])
        self.audio_processor = AudioProcessor()
        self.tdms_converter = TDMSConverter()
        self.db_manager = DatabaseManager()
        self.is_monitoring = False
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def set_processing_callback(self, callback: Callable):
        """Set callback function for processing results"""
        self.processing_callback = callback

    async def start_monitoring(self):
        """Start monitoring audio files"""
        if not self.is_monitoring:
            self.is_monitoring = True
            logger.info(
                f"Starting audio file monitoring in {self.watch_directory}")

            # Start file monitoring
            self.audio_monitor.start_monitoring(self._on_audio_file_detected)

    async def stop_monitoring(self):
        """Stop monitoring audio files"""
        if self.is_monitoring:
            self.is_monitoring = False
            logger.info("Stopping audio file monitoring")
            self.audio_monitor.stop_monitoring()
            self.executor.shutdown(wait=True)

    def _on_audio_file_detected(self, file_path: str):
        """Handle detected audio file"""
        logger.info(f"New audio file detected: {file_path}")
        # Check if this is a temporary WAV file created during TDMS conversion
        # We only want to process original files, not temporary conversion files
        file_path_obj = Path(file_path)
        if file_path_obj.name.startswith("temp_") or "_converted" in file_path_obj.name:
            logger.info(f"Skipping temporary file: {file_path}")
            return
        # Process the audio file asynchronously using thread pool
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._process_audio_file(file_path))
        loop.close()

    async def _process_audio_file(self, file_path: str):
        """Process audio file asynchronously"""
        wav_file_path = None
        try:
            logger.info(f"Processing audio file: {file_path}")
            # Check file extension
            file_ext = Path(file_path).suffix.lower()
            # If it's a TDMS file, convert it to WAV first
            if file_ext == ".tdms":
                logger.info(f"Converting TDMS file to WAV: {file_path}")
                wav_file_path = self.tdms_converter.convert_tdms_to_wav(
                    file_path)
                processing_file_path = wav_file_path
            else:
                processing_file_path = file_path
            # Process the audio file (WAV format)
            results = self.audio_processor.process_wav_file(
                processing_file_path)
            # Convert DataFrames to dictionaries for JSON serialization
            frequency_spl_dict = {}
            frequency_kurtosis_dict = {}
            if results.get("frequency_spl") is not None and not results["frequency_spl"].empty:
                frequency_spl_dict = results["frequency_spl"].to_dict("records")[
                    0]
            if results.get("frequency_kurtosis") is not None and not results["frequency_kurtosis"].empty:
                frequency_kurtosis_dict = results["frequency_kurtosis"].to_dict("records")[
                    0]
            # Create schema-compliant result object
            processing_result = ProcessingResultSchema(
                file_path=file_path,
                sampling_rate=results.get("sampling_rate"),
                duration=results.get("duration"),
                channels=results.get("channels"),
                leq=float(results.get("leq")) if results.get(
                    "leq") is not None else None,
                laeq=float(results.get("laeq")) if results.get(
                    "laeq") is not None else None,
                lceq=float(results.get("lceq")) if results.get(
                    "lceq") is not None else None,
                peak_spl=float(results.get("peak_spl")) if results.get(
                    "peak_spl") is not None else None,
                peak_aspl=float(results.get("peak_aspl")) if results.get(
                    "peak_aspl") is not None else None,
                peak_cspl=float(results.get("peak_cspl")) if results.get(
                    "peak_cspl") is not None else None,
                total_kurtosis=float(results.get("total_kurtosis")) if results.get(
                    "total_kurtosis") is not None else None,
                a_weighted_kurtosis=float(results.get("a_weighted_kurtosis")) if results.get(
                    "a_weighted_kurtosis") is not None else None,
                c_weighted_kurtosis=float(results.get("c_weighted_kurtosis")) if results.get(
                    "c_weighted_kurtosis") is not None else None,
                frequency_spl={"frequency_bands": frequency_spl_dict},
                frequency_kurtosis={"frequency_bands": frequency_kurtosis_dict}
            )
            # Save to database using model_dump() method
            result_dict = processing_result.model_dump()
            # Extract metrics for database storage (excluding file_path fields)
            metrics_dict = {
                key: value for key, value in result_dict.items()
                if key not in ["file_path"]
            }

            self.db_manager.save_processing_result(file_path=file_path, metrics=metrics_dict)
            logger.info(f"Finished processing audio file: {file_path}")
        except Exception as e:
            logger.error(f"Error processing audio file {file_path}: {str(e)}")
        finally:
            # Clean up temporary WAV file if it was created
            if wav_file_path and os.path.exists(wav_file_path):
                try:
                    os.remove(wav_file_path)
                    logger.info(f"Deleted temporary WAV file: {wav_file_path}")
                except Exception as e:
                    logger.error(
                        f"Error deleting temporary WAV file {wav_file_path}: {e}")
