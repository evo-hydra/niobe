"""Tests for Niobe data models."""

from datetime import datetime, timezone

from niobe.models import (
    HealthSnapshot,
    LogEntry,
    LogFormat,
    LogLevel,
    ProcessMetrics,
    ServiceInfo,
    ServiceStatus,
    SnapshotDiff,
)


class TestEnums:
    def test_service_status_values(self):
        assert ServiceStatus.RUNNING == "running"
        assert ServiceStatus.ZOMBIE == "zombie"

    def test_log_level_values(self):
        assert LogLevel.ERROR == "error"
        assert LogLevel.CRITICAL == "critical"

    def test_log_format_values(self):
        assert LogFormat.JSON == "json"
        assert LogFormat.CLF == "clf"


class TestServiceInfo:
    def test_defaults(self):
        svc = ServiceInfo(name="test")
        assert svc.name == "test"
        assert svc.pid is None
        assert svc.port is None
        assert svc.log_paths == ()
        assert isinstance(svc.registered_at, datetime)

    def test_frozen(self):
        svc = ServiceInfo(name="test")
        try:
            svc.name = "other"  # type: ignore
            assert False, "Should be frozen"
        except AttributeError:
            pass


class TestProcessMetrics:
    def test_creation(self):
        m = ProcessMetrics(
            pid=123, status="running", cpu_percent=5.0,
            memory_mb=100.0, num_threads=4, num_connections=2,
        )
        assert m.pid == 123
        assert m.memory_mb == 100.0


class TestHealthSnapshot:
    def test_creation(self):
        snap = HealthSnapshot(
            snapshot_id="abc123", service_name="test",
            snapshot_at=datetime.now(timezone.utc),
        )
        assert snap.error_count == 0
        assert snap.log_rate == 0.0
        assert snap.metrics is None


class TestSnapshotDiff:
    def test_creation(self):
        now = datetime.now(timezone.utc)
        before = HealthSnapshot(snapshot_id="a", service_name="s", snapshot_at=now)
        after = HealthSnapshot(snapshot_id="b", service_name="s", snapshot_at=now)
        diff = SnapshotDiff(service_name="s", before=before, after=after)
        assert diff.cpu_delta == 0.0
        assert diff.status_changed is False


class TestLogEntry:
    def test_defaults(self):
        e = LogEntry(
            service_name="svc", level="info",
            message="hello", source_file="/tmp/test.log",
            raw_line="hello",
        )
        assert e.timestamp is None
        assert isinstance(e.ingested_at, datetime)
