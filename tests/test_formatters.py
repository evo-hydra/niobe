"""Tests for markdown formatters."""

from datetime import datetime, timezone

from niobe.mcp.formatters import (
    format_diff,
    format_log_entries,
    format_registration,
    format_services,
    format_snapshot,
    format_snapshots,
)
from niobe.models.runtime import (
    HealthSnapshot,
    LogEntry,
    ProcessMetrics,
    ServiceInfo,
    SnapshotDiff,
)


def _now():
    return datetime.now(timezone.utc)


class TestFormatSnapshot:
    def test_with_metrics(self):
        m = ProcessMetrics(pid=1, status="running", cpu_percent=5.0, memory_mb=100.0, num_threads=4, num_connections=2)
        snap = HealthSnapshot(snapshot_id="a" * 32, service_name="web", snapshot_at=_now(), metrics=m, error_count=3, log_rate=1.5)
        out = format_snapshot(snap)
        assert "web" in out
        assert "5.0%" in out
        assert "100.0 MB" in out

    def test_without_metrics(self):
        snap = HealthSnapshot(snapshot_id="b" * 32, service_name="api", snapshot_at=_now())
        out = format_snapshot(snap)
        assert "No process metrics" in out


class TestFormatSnapshots:
    def test_empty(self):
        assert "No snapshots" in format_snapshots([])

    def test_multiple(self):
        snaps = [
            HealthSnapshot(snapshot_id="a" * 32, service_name="a", snapshot_at=_now()),
            HealthSnapshot(snapshot_id="b" * 32, service_name="b", snapshot_at=_now()),
        ]
        out = format_snapshots(snaps)
        assert "---" in out


class TestFormatDiff:
    def test_basic(self):
        m1 = ProcessMetrics(pid=1, status="running", cpu_percent=5.0, memory_mb=100.0, num_threads=4, num_connections=2)
        m2 = ProcessMetrics(pid=1, status="running", cpu_percent=15.0, memory_mb=120.0, num_threads=6, num_connections=3)
        before = HealthSnapshot(snapshot_id="a" * 32, service_name="web", snapshot_at=_now(), metrics=m1, error_count=1)
        after = HealthSnapshot(snapshot_id="b" * 32, service_name="web", snapshot_at=_now(), metrics=m2, error_count=5)
        diff = SnapshotDiff(
            service_name="web", before=before, after=after,
            cpu_delta=10.0, memory_delta_mb=20.0,
            error_count_delta=4, log_rate_delta=0.5,
        )
        out = format_diff(diff)
        assert "+10.0%" in out
        assert "+20.0 MB" in out


class TestFormatLogEntries:
    def test_empty(self):
        assert "No entries" in format_log_entries([])

    def test_entries(self):
        entries = [
            LogEntry(service_name="web", level="error", message="fail", source_file="a.log", raw_line="err", timestamp=_now()),
        ]
        out = format_log_entries(entries, "Errors")
        assert "ERROR" in out
        assert "fail" in out


class TestFormatServices:
    def test_empty(self):
        assert "No services" in format_services([])

    def test_with_services(self):
        svcs = [ServiceInfo(name="web", pid=123, port=8080)]
        out = format_services(svcs)
        assert "web" in out
        assert "123" in out


class TestFormatRegistration:
    def test_basic(self):
        out = format_registration("web", pid=123, port=8080, log_paths=["/var/log/web.log"])
        assert "web" in out
        assert "123" in out
        assert "/var/log/web.log" in out
