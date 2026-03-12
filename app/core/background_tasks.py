"""
Background tasks for audio processing with TimeHistory support
"""
import asyncio
from typing import Callable, List, Optional
from pathlib import Path
from datetime import datetime
import concurrent.futures
import os

from app.utils import logger
from app.core.audio_processor import AudioProcessor
from app.core.file_monitor import AudioFileMonitor
from app.core.tdms_converter import TDMSConverter
from app.core.time_history_processor import TimeHistoryProcessor, aggregate_session_metrics
from app.core.session_manager import SessionManager, SessionConfig, SessionState, session_registry
from app.core.dose_calculator import DoseStandard
from app.core.event_processor import EventProcessor
from app.core.event_detector import EventInfo
from app.database import DatabaseManager
from app.models import ProcessingResultSchema


class AudioProcessingTaskManager:
    """Manage audio processing background tasks with TimeHistory support"""

    def __init__(self, watch_directory: str = "./audio_files"):
        self.watch_directory = watch_directory
        self.audio_monitor = AudioFileMonitor(watch_directory, [".tdms"])
        self.audio_processor = AudioProcessor()
        self.tdms_converter = TDMSConverter()
        self.time_history_processor = TimeHistoryProcessor()
        self.event_processor: Optional[EventProcessor] = None
        self.db_manager = DatabaseManager()
        self.is_monitoring = False
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        
        # Current session
        self.current_session: Optional[SessionManager] = None
        self.auto_create_session = True  # 自动为每个文件创建会话
        self.enable_event_detection = True  # 启用事件检测

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
            
            # Stop current session if exists
            if self.current_session and self.current_session.state == SessionState.RUNNING:
                self.current_session.stop()
                self._save_session_summary()
            
            self.executor.shutdown(wait=True)
    
    def create_session(self, profile: DoseStandard = DoseStandard.NIOSH,
                       device_id: Optional[str] = None,
                       operator: Optional[str] = None) -> SessionManager:
        """
        手动创建新会话
        
        Args:
            profile: 剂量计算标准
            device_id: 设备ID
            operator: 操作员
            
        Returns:
            SessionManager: 会话管理器实例
        """
        # Stop existing session if running
        if self.current_session and self.current_session.state == SessionState.RUNNING:
            self.current_session.stop()
            self._save_session_summary()
        
        # Create new session
        config = SessionConfig(
            profile=profile,
            device_id=device_id,
            operator=operator
        )
        self.current_session = session_registry.create_session(config=config)
        self.current_session.start()
        
        logger.info(f"Created new session: {self.current_session.session_id}")
        return self.current_session
    
    def stop_current_session(self) -> Optional[dict]:
        """停止当前会话并返回摘要"""
        if not self.current_session:
            return None
        
        self.current_session.stop()
        summary = self._save_session_summary()
        
        return summary
    
    def get_current_session_summary(self) -> Optional[dict]:
        """获取当前会话摘要"""
        if not self.current_session:
            return None
        return self.current_session.get_summary()

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
        """Process audio file asynchronously with TimeHistory support"""
        wav_file_path = None
        try:
            logger.info(f"Processing audio file: {file_path}")
            
            # Create or get session
            session = self._get_or_create_session(file_path)
            
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
            
            # Process the audio file with TimeHistory (per-second processing)
            await self._process_with_timehistory(processing_file_path, session)
            
            # Also process the audio file for overall metrics (legacy)
            results = self.audio_processor.process_wav_file(processing_file_path)
            
            # Save overall processing result
            await self._save_processing_result(file_path, results, session.session_id)
            
            logger.info(f"Finished processing audio file: {file_path}")
            
        except Exception as e:
            logger.error(f"Error processing audio file {file_path}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Clean up temporary WAV file if it was created
            if wav_file_path and os.path.exists(wav_file_path):
                try:
                    os.remove(wav_file_path)
                    logger.info(f"Deleted temporary WAV file: {wav_file_path}")
                except Exception as e:
                    logger.error(
                        f"Error deleting temporary WAV file {wav_file_path}: {e}")
    
    def _get_or_create_session(self, file_path: str) -> SessionManager:
        """获取或创建会话"""
        if self.current_session and self.current_session.state == SessionState.RUNNING:
            return self.current_session
        
        if self.auto_create_session:
            # Create new session for this file
            config = SessionConfig(
                profile=DoseStandard.NIOSH,
                device_id="auto",
                notes=f"Auto-created session for file: {Path(file_path).name}"
            )
            self.current_session = session_registry.create_session(config=config)
            self.current_session.start()
            logger.info(f"Auto-created session: {self.current_session.session_id}")
            return self.current_session
        else:
            raise RuntimeError("No active session and auto_create_session is disabled")
    
    async def _process_with_timehistory(self, file_path: str, session: SessionManager):
        """使用时间历程处理器按秒处理音频，同时检测事件"""
        import librosa
        import warnings
        from acoustics import Signal
        
        logger.info(f"Processing with TimeHistory: {file_path}")
        
        # Load audio file
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            y, sr = librosa.load(file_path, sr=None)
        
        signal = Signal(y, sr)
        
        # Initialize event processor if enabled
        if self.enable_event_detection:
            self.event_processor = EventProcessor(
                sample_rate=sr,
                output_dir="./audio_events",
                enable_audio_save=True
            )
            self.event_processor.start(session.session_id)
            self.event_processor.add_event_callback(self._on_event_detected)
            logger.info(f"Event detection started for session {session.session_id}")
        
        # Process per second
        def on_second_processed(metrics):
            """Callback for each second processed"""
            # Update session
            session.process_second(metrics)
            
            # Save to database (async)
            try:
                self._save_time_history_record(session.session_id, metrics)
            except Exception as e:
                logger.error(f"Error saving time history: {e}")
        
        # Set callback and process
        self.time_history_processor.callback = on_second_processed
        time_history = self.time_history_processor.process_signal_per_second(
            signal, start_time=datetime.utcnow())
        
        logger.info(f"Processed {len(time_history)} seconds for session {session.session_id}")
        
        # Stop event processor and get detected events
        if self.event_processor:
            events = self.event_processor.stop()
            logger.info(f"Event detection complete: {len(events)} events detected")
            
            # Update session summary with event count
            if self.current_session:
                self.current_session.metrics.event_count = len(events)
            
            self.event_processor = None
    
    def _on_event_detected(self, event_info: EventInfo):
        """事件检测回调"""
        logger.info(f"Event detected: {event_info.event_id}, saving to database")
        
        try:
            self.db_manager.save_event(
                session_id=event_info.session_id,
                event_id=event_info.event_id,
                start_time=event_info.start_time,
                end_time=event_info.end_time,
                duration_s=event_info.duration_s,
                trigger_type=event_info.trigger_type.value,
                lzpeak_db=event_info.lzpeak_db,
                lcpeak_db=event_info.lcpeak_db,
                laeq_event_db=event_info.laeq_event_db,
                sel_lae_db=event_info.sel_lae_db,
                beta_excess_z=event_info.beta_excess_z,
                audio_file_path=event_info.audio_file_path,
                pretrigger_s=event_info.pretrigger_s,
                posttrigger_s=event_info.posttrigger_s,
                notes=event_info.notes
            )
            logger.info(f"Event saved: {event_info.event_id}")
        except Exception as e:
            logger.error(f"Error saving event: {e}")
    
    def _save_time_history_record(self, session_id: str, metrics):
        """保存单条时间历程记录到数据库"""
        try:
            self.db_manager.save_time_history(
                session_id=session_id,
                timestamp_utc=metrics.timestamp,
                laeq=metrics.LAeq,
                lceq=metrics.LCeq,
                lzpeak=metrics.LZpeak or 0.0,
                lcpeak=metrics.LCpeak or 0.0,
                dose_fracs={
                    "NIOSH": metrics.dose_frac_niosh,
                    "OSHA_PEL": metrics.dose_frac_osha_pel,
                    "OSHA_HCA": metrics.dose_frac_osha_hca,
                    "EU_ISO": metrics.dose_frac_eu_iso,
                },
                duration_s=metrics.duration_s,
                device_id=None,
                wearing_state=metrics.wearing_state,
                overload_flag=metrics.overload_flag,
                underrange_flag=metrics.underrange_flag,
            )
        except Exception as e:
            logger.error(f"Error in _save_time_history_record: {e}")
    
    async def _save_processing_result(self, file_path: str, results: dict, session_id: str):
        """保存处理结果到数据库"""
        # Convert DataFrames to dictionaries for JSON serialization
        frequency_spl_dict = {}
        frequency_kurtosis_dict = {}
        if results.get("frequency_spl") is not None and not results["frequency_spl"].empty:
            frequency_spl_dict = results["frequency_spl"].to_dict("records")[0]
        if results.get("frequency_kurtosis") is not None and not results["frequency_kurtosis"].empty:
            frequency_kurtosis_dict = results["frequency_kurtosis"].to_dict("records")[0]
        
        # Create schema-compliant result object
        processing_result = ProcessingResultSchema(
            file_path=file_path,
            sampling_rate=results.get("sampling_rate"),
            duration=results.get("duration"),
            channels=results.get("channels"),
            leq=float(results.get("leq")) if results.get("leq") is not None else None,
            laeq=float(results.get("laeq")) if results.get("laeq") is not None else None,
            lceq=float(results.get("lceq")) if results.get("lceq") is not None else None,
            peak_spl=float(results.get("peak_spl")) if results.get("peak_spl") is not None else None,
            peak_aspl=float(results.get("peak_aspl")) if results.get("peak_aspl") is not None else None,
            peak_cspl=float(results.get("peak_cspl")) if results.get("peak_cspl") is not None else None,
            total_kurtosis=float(results.get("total_kurtosis")) if results.get("total_kurtosis") is not None else None,
            a_weighted_kurtosis=float(results.get("a_weighted_kurtosis")) if results.get("a_weighted_kurtosis") is not None else None,
            c_weighted_kurtosis=float(results.get("c_weighted_kurtosis")) if results.get("c_weighted_kurtosis") is not None else None,
            frequency_spl={"frequency_bands": frequency_spl_dict},
            frequency_kurtosis={"frequency_bands": frequency_kurtosis_dict},
            # Dose metrics
            dose_niosh=float(results.get("dose_niosh")) if results.get("dose_niosh") is not None else None,
            dose_osha_pel=float(results.get("dose_osha_pel")) if results.get("dose_osha_pel") is not None else None,
            dose_osha_hca=float(results.get("dose_osha_hca")) if results.get("dose_osha_hca") is not None else None,
            dose_eu_iso=float(results.get("dose_eu_iso")) if results.get("dose_eu_iso") is not None else None,
            # TWA metrics
            twa_niosh=float(results.get("twa_niosh")) if results.get("twa_niosh") is not None else None,
            twa_osha_pel=float(results.get("twa_osha_pel")) if results.get("twa_osha_pel") is not None else None,
            twa_osha_hca=float(results.get("twa_osha_hca")) if results.get("twa_osha_hca") is not None else None,
            twa_eu_iso=float(results.get("twa_eu_iso")) if results.get("twa_eu_iso") is not None else None,
            # LEX metrics
            lex_niosh=float(results.get("lex_niosh")) if results.get("lex_niosh") is not None else None,
            lex_osha_pel=float(results.get("lex_osha_pel")) if results.get("lex_osha_pel") is not None else None,
            lex_osha_hca=float(results.get("lex_osha_hca")) if results.get("lex_osha_hca") is not None else None,
            lex_eu_iso=float(results.get("lex_eu_iso")) if results.get("lex_eu_iso") is not None else None,
        )
        
        # Save to database using model_dump() method
        result_dict = processing_result.model_dump()
        # Extract metrics for database storage (excluding file_path fields)
        metrics_dict = {
            key: value for key, value in result_dict.items()
            if key not in ["file_path"]
        }

        self.db_manager.save_processing_result(
            file_path=file_path, 
            metrics=metrics_dict,
            session_id=session_id
        )
    
    def _save_session_summary(self) -> Optional[dict]:
        """保存会话摘要到数据库"""
        if not self.current_session:
            return None
        
        try:
            summary = self.current_session.get_summary()
            metrics = summary.get('metrics', {})
            profile_summary = summary.get('profile_summary', {})
            
            self.db_manager.save_session_summary(
                session_id=self.current_session.session_id,
                profile_name=self.current_session.config.profile.value,
                start_time=datetime.fromisoformat(metrics.get('start_time')) if metrics.get('start_time') else datetime.utcnow(),
                end_time=datetime.fromisoformat(metrics.get('end_time')) if metrics.get('end_time') else None,
                total_duration_h=profile_summary.get('total_duration_h', 0),
                laeq_t=profile_summary.get('LAeq_T', 0),
                lex_8h=profile_summary.get('LEX_8h', 0),
                total_dose_pct=profile_summary.get('total_dose_pct', 0),
                twa=profile_summary.get('TWA', 0),
                peak_max_db=profile_summary.get('peak_max_dB', 0),
                events_count=metrics.get('event_count', 0),
                overload_count=metrics.get('overload_count', 0),
                underrange_count=metrics.get('underrange_count', 0),
            )
            
            logger.info(f"Saved session summary for {self.current_session.session_id}")
            return summary
            
        except Exception as e:
            logger.error(f"Error saving session summary: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
