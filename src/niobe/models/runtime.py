"""Frozen dataclass models for runtime observation data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class ServiceInfo:
    """A registered service under observation."""

    name: str
    pid: int | None = None
    port: int | None = None
    log_paths: tuple[str, ...] = ()
    registered_at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class ProcessMetrics:
    """Point-in-time process metrics from psutil."""

    pid: int
    status: str
    cpu_percent: float
    memory_mb: float
    num_threads: int
    num_connections: int
    captured_at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """Aggregated health observation for a service at a point in time."""

    snapshot_id: str
    service_name: str
    snapshot_at: datetime
    metrics: ProcessMetrics | None = None
    error_count: int = 0
    log_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class SnapshotDiff:
    """Delta between two snapshots of the same service."""

    service_name: str
    before: HealthSnapshot
    after: HealthSnapshot
    cpu_delta: float = 0.0
    memory_delta_mb: float = 0.0
    error_count_delta: int = 0
    log_rate_delta: float = 0.0
    status_changed: bool = False


@dataclass(frozen=True, slots=True)
class LogEntry:
    """A single parsed log line."""

    service_name: str
    level: str
    message: str
    source_file: str
    raw_line: str
    timestamp: datetime | None = None
    ingested_at: datetime = field(default_factory=_now)
