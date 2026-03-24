"""Tests for snapshot orchestration."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from niobe.config import NiobeConfig
from niobe.core.snapshot import compare_snapshots, create_all_snapshots, create_snapshot
from niobe.core.store import NiobeStore
from niobe.models.runtime import HealthSnapshot, ProcessMetrics, ServiceInfo


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test.db"
    with NiobeStore(db_path) as s:
        yield s


@pytest.fixture
def service():
    return ServiceInfo(name="web", pid=1234)


class TestCreateSnapshot:
    @patch("niobe.core.snapshot.capture_metrics")
    def test_basic(self, mock_capture, store, service):
        store.register_service(service)
        mock_capture.return_value = ProcessMetrics(
            pid=1234, status="running", cpu_percent=2.0,
            memory_mb=50.0, num_threads=3, num_connections=1,
        )
        config = NiobeConfig(project_path=store._db_path.parent.parent)
        snap = create_snapshot(store, service, config)

        assert snap.service_name == "web"
        assert snap.metrics is not None
        assert snap.metrics.cpu_percent == 2.0
        assert len(snap.snapshot_id) == 32

    @patch("niobe.core.snapshot.capture_metrics")
    def test_no_metrics(self, mock_capture, store, service):
        store.register_service(service)
        mock_capture.return_value = None
        snap = create_snapshot(store, service)
        assert snap.metrics is None

    @patch("niobe.core.snapshot.capture_metrics")
    def test_snapshot_saved_to_store(self, mock_capture, store, service):
        store.register_service(service)
        mock_capture.return_value = None
        snap = create_snapshot(store, service)
        got = store.get_snapshot(snap.snapshot_id[:8])
        assert got is not None
        assert got.snapshot_id == snap.snapshot_id


class TestCompareSnapshots:
    def test_compare(self, store):
        svc = ServiceInfo(name="web", pid=1234)
        store.register_service(svc)
        now = datetime.now(timezone.utc)

        m1 = ProcessMetrics(pid=1234, status="running", cpu_percent=5.0, memory_mb=100.0, num_threads=4, num_connections=2)
        m2 = ProcessMetrics(pid=1234, status="running", cpu_percent=15.0, memory_mb=120.0, num_threads=6, num_connections=3)

        s1 = HealthSnapshot(snapshot_id="aaaa" * 8, service_name="web", snapshot_at=now, metrics=m1, error_count=1)
        s2 = HealthSnapshot(snapshot_id="bbbb" * 8, service_name="web", snapshot_at=now, metrics=m2, error_count=5)
        store.save_snapshot(s1)
        store.save_snapshot(s2)

        diff = compare_snapshots(store, "aaaa" * 8, "bbbb" * 8)
        assert diff is not None
        assert diff.cpu_delta == 10.0
        assert diff.memory_delta_mb == 20.0
        assert diff.error_count_delta == 4

    def test_compare_missing(self, store):
        diff = compare_snapshots(store, "nonexist", "also_nope")
        assert diff is None

    def test_compare_different_services(self, store):
        now = datetime.now(timezone.utc)
        store.register_service(ServiceInfo(name="a"))
        store.register_service(ServiceInfo(name="b"))
        s1 = HealthSnapshot(snapshot_id="x" * 32, service_name="a", snapshot_at=now)
        s2 = HealthSnapshot(snapshot_id="y" * 32, service_name="b", snapshot_at=now)
        store.save_snapshot(s1)
        store.save_snapshot(s2)
        diff = compare_snapshots(store, "x" * 32, "y" * 32)
        assert diff is None


class TestCreateAllSnapshots:
    @patch("niobe.core.snapshot.capture_metrics")
    def test_partial_failure_reports_both(self, mock_capture, store):
        """Partial failure returns successful snapshots AND failure details."""
        svc_good = ServiceInfo(name="good", pid=1000)
        svc_bad = ServiceInfo(name="bad", pid=2000)
        store.register_service(svc_good)
        store.register_service(svc_bad)

        def side_effect(svc, **kwargs):
            if svc.name == "bad":
                raise RuntimeError("process gone")
            return ProcessMetrics(
                pid=svc.pid, status="running", cpu_percent=1.0,
                memory_mb=10.0, num_threads=1, num_connections=0,
            )

        mock_capture.side_effect = side_effect

        result = create_all_snapshots(store)
        assert len(result.snapshots) == 1
        assert result.snapshots[0].service_name == "good"
        assert len(result.failures) == 1
        assert result.failures[0][0] == "bad"
        assert "process gone" in result.failures[0][1]
        assert result.total_services == 2

    @patch("niobe.core.snapshot.capture_metrics")
    def test_all_succeed(self, mock_capture, store):
        """All services succeed — no failures in result."""
        svc = ServiceInfo(name="web", pid=1234)
        store.register_service(svc)
        mock_capture.return_value = ProcessMetrics(
            pid=1234, status="running", cpu_percent=1.0,
            memory_mb=10.0, num_threads=1, num_connections=0,
        )

        result = create_all_snapshots(store)
        assert len(result.snapshots) == 1
        assert result.failures == []
        assert result.total_services == 1

    def test_no_services_returns_empty(self, store):
        """No services registered — empty result with total_services=0."""
        result = create_all_snapshots(store)
        assert result.snapshots == []
        assert result.failures == []
        assert result.total_services == 0
