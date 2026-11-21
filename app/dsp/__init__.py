# -*- coding: utf-8 -*-
"""SciPy/NumPy based DSP core for streaming noise metrics."""
from .filters import (
    BandDesign,
    WeightingDesign,
    design_bands,
    design_weighting,
    max_weighting_error,
)
from .processor import (
    QCThresholds,
    StreamingNoiseProcessor,
    kurtosis_from_moments,
    peak_to_db,
    power_to_db,
)
from .event_detector import EventConfig, EventDetector, EventResult
from .aggregation import aggregate_minutes, aggregate_segments, energy_average

__all__ = [
    "BandDesign",
    "WeightingDesign",
    "design_bands",
    "design_weighting",
    "max_weighting_error",
    "QCThresholds",
    "StreamingNoiseProcessor",
    "kurtosis_from_moments",
    "peak_to_db",
    "power_to_db",
    "EventConfig",
    "EventDetector",
    "EventResult",
    "aggregate_minutes",
    "aggregate_segments",
    "energy_average",
]
