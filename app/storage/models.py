# -*- coding: utf-8 -*-
"""SQLAlchemy schema for the field-deployment storage layer."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import TypeDecorator

Base = declarative_base()


class UtcDateTime(TypeDecorator):
    """Store timezone-aware UTC datetimes in a single SQLite text format."""
    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime is not allowed")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc)


class SessionRow(Base):
    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True)
    channel = Column(String(32), nullable=False, index=True)
    profile = Column(String(32), nullable=False, default="NIOSH")
    device_id = Column(String(100))
    operator = Column(String(100))
    organization = Column(String(200))
    calibration_id = Column(Integer)
    start_time_utc = Column(UtcDateTime, nullable=False, index=True)
    end_time_utc = Column(UtcDateTime)
    state = Column(String(16), nullable=False, default="running")
    total_duration_s = Column(Float, default=0.0)
    created_at = Column(UtcDateTime, nullable=False)

    events = relationship("EventRow", back_populates="session")


class JobRow(Base):
    __tablename__ = "jobs"

    id = Column(String(64), primary_key=True)
    file_path = Column(Text, nullable=False, index=True)
    channel = Column(String(32), nullable=False, index=True)
    file_size = Column(Integer, nullable=False)
    file_mtime_ns = Column(Integer, nullable=False)
    session_id = Column(String(64), ForeignKey("sessions.id"), index=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text)
    created_at = Column(UtcDateTime, nullable=False)
    started_at = Column(UtcDateTime)
    finished_at = Column(UtcDateTime)
    source_retained = Column(Boolean, nullable=False, default=True)
    source_deleted_at = Column(UtcDateTime)

    __table_args__ = (
        Index("ux_jobs_identity", "file_path", "channel", "file_size",
              "file_mtime_ns", unique=True),
    )


class TimeHistoryRow(Base):
    __tablename__ = "time_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), ForeignKey("sessions.id"), nullable=False)
    channel = Column(String(32), nullable=False)
    timestamp_utc = Column(UtcDateTime, nullable=False)
    duration_s = Column(Float, nullable=False)

    laeq = Column(Float)
    lceq = Column(Float)
    lzeq = Column(Float)
    laf = Column(Float)
    las = Column(Float)
    lcf = Column(Float)
    lcs = Column(Float)
    lafmax = Column(Float)
    lasmax = Column(Float)
    lcsmax = Column(Float)
    lzpeak = Column(Float)
    lcpeak = Column(Float)
    lapeak = Column(Float)

    # Percent (0-100) for storage/API compatibility.
    dose_niosh = Column(Float, default=0.0)
    dose_osha_pel = Column(Float, default=0.0)
    dose_osha_hca = Column(Float, default=0.0)
    dose_eu_iso = Column(Float, default=0.0)

    overload = Column(Boolean, default=False)
    underrange = Column(Boolean, default=False)
    wearing = Column(Boolean, default=True)
    valid = Column(Boolean, default=True)
    artifact = Column(Boolean, default=False)
    event_type = Column(Integer, default=0)
    event_severity = Column(Integer, default=0)

    kurtosis_total = Column(Float)
    kurtosis_a = Column(Float)
    kurtosis_c = Column(Float)
    beta_kurtosis = Column(Float)
    n_samples = Column(Integer, default=0)
    s1 = Column(Float, default=0.0)
    s2 = Column(Float, default=0.0)
    s3 = Column(Float, default=0.0)
    s4 = Column(Float, default=0.0)

    freq_spl_json = Column(Text)
    freq_moments_json = Column(Text)
    calibrated = Column(Boolean, default=False)
    level_unit = Column(String(16), default="dBFS")

    __table_args__ = (
        Index("ix_th_session_time", "session_id", "timestamp_utc"),
        Index("ix_th_channel_time", "channel", "timestamp_utc"),
    )


class EventRow(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(64), nullable=False, unique=True)
    session_id = Column(String(64), ForeignKey("sessions.id"), index=True)
    channel = Column(String(32), index=True)
    category = Column(String(16), nullable=False, default="acoustic", index=True)
    event_type = Column(Integer, nullable=False, default=0)
    severity = Column(Integer, nullable=False, default=0)
    start_time_utc = Column(UtcDateTime, nullable=False, index=True)
    end_time_utc = Column(UtcDateTime)
    duration_s = Column(Float)
    trigger_flags_json = Column(Text)
    laf_db = Column(Float)
    las_db = Column(Float)
    impulse_db = Column(Float)
    rise_db = Column(Float)
    background_delta_db = Column(Float)
    lzpeak_db = Column(Float)
    lcpeak_db = Column(Float)
    lapeak_db = Column(Float)
    audio_start_utc = Column(UtcDateTime)
    audio_end_utc = Column(UtcDateTime)
    audio_path = Column(Text)
    audio_sha256 = Column(String(64))
    audio_bytes = Column(Integer)
    retention_state = Column(String(16), default="retained")
    metadata_json = Column(Text)
    created_at = Column(UtcDateTime, nullable=False)

    session = relationship("SessionRow", back_populates="events")


class SystemEventRow(Base):
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), nullable=False, index=True)
    severity = Column(Integer, nullable=False, default=1)
    message = Column(Text, nullable=False)
    context_json = Column(Text)
    start_utc = Column(UtcDateTime, nullable=False)
    end_utc = Column(UtcDateTime)
    resolved = Column(Boolean, default=False)
    created_at = Column(UtcDateTime, nullable=False)


class RetentionAuditRow(Base):
    __tablename__ = "retention_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_path = Column(Text, nullable=False)
    action = Column(String(16), nullable=False)
    reason = Column(Text)
    mode = Column(String(16), nullable=False)
    dry_run = Column(Boolean, nullable=False)
    bytes = Column(Integer)
    created_at = Column(UtcDateTime, nullable=False)
