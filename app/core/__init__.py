# Core module for noise analysis
from .audio_processor import AudioProcessor
from .background_tasks import AudioProcessingTaskManager
from .connection_manager import ConnectionManager
from .file_monitor import AudioFileMonitor
from .tdms_converter import TDMSConverter
from .dose_calculator import DoseCalculator, DoseStandard, DoseProfile
from .time_history_processor import TimeHistoryProcessor, SecondMetrics, aggregate_session_metrics
from .summary_processor import (
    SummaryProcessor, 
    AggregatedMetrics, 
    AggregationLevel,
    MultiLevelAggregator,
    aggregate_from_moment_blocks,
    compare_kurtosis_methods
)
from .session_manager import (
    SessionManager, 
    SessionConfig, 
    SessionState, 
    SessionMetrics,
    SessionRegistry,
    session_registry
)

# Phase 3: Event Detection
from .event_detector import EventDetector, EventInfo, TriggerType, SlidingWindowCalculator
from .ring_buffer import RingBuffer, MultiChannelRingBuffer
from .event_processor import EventProcessor, BatchEventProcessor

__all__ = [
    'AudioProcessor',
    'AudioProcessingTaskManager',
    'ConnectionManager',
    'AudioFileMonitor',
    'TDMSConverter',
    'DoseCalculator',
    'DoseStandard',
    'DoseProfile',
    'TimeHistoryProcessor',
    'SecondMetrics',
    'aggregate_session_metrics',
    # Summary Processor
    'SummaryProcessor',
    'AggregatedMetrics',
    'AggregationLevel',
    'MultiLevelAggregator',
    'aggregate_from_moment_blocks',
    'compare_kurtosis_methods',
    'SessionManager',
    'SessionConfig',
    'SessionState',
    'SessionMetrics',
    'SessionRegistry',
    'session_registry',
    # Phase 3
    'EventDetector',
    'EventInfo',
    'TriggerType',
    'SlidingWindowCalculator',
    'RingBuffer',
    'MultiChannelRingBuffer',
    'EventProcessor',
    'BatchEventProcessor',
]
