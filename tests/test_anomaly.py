"""Tests for anomaly detection engine."""

from datetime import datetime, timezone

import pytest

from niobe.core.anomaly import (
    MIN_SAMPLES,
    SIGMA_THRESHOLD,
    _extract_metrics,
    detect_anomalies,
    update_baselines,
)
from niobe.core.store import NiobeStore
from niobe.models.runtime import HealthSnapshot, MetricBaseline, ProcessMetrics, ServiceInfo


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test.db"
    with NiobeStore(db_path) as s:
        yield s


@pytest.fixture
def service(store):
    svc = ServiceInfo(name="web", pid=1234, port=8080)
    store.register_service(svc)
    return svc


def _snap(service_name="web", cpu=10.0, mem=256.0, errors=0, log_rate=0.0):
    return HealthSnapshot(
        snapshot_id="aabb" * 8,
        service_name=service_name,
        snapshot_at=datetime.now(timezone.utc),
        metrics=ProcessMetrics(
            pid=1234, status="running", cpu_percent=cpu,
            memory_mb=mem, num_threads=4, num_connections=2,
        ),
        error_count=errors,
        log_rate=log_rate,
    )


class TestExtractMetrics:
    def test_with_metrics(self):
        snap = _snap(cpu=25.0, mem=512.0, errors=3, log_rate=1.5)
        values = _extract_metrics(snap)
        assert values["cpu_percent"] == 25.0
        assert values["memory_mb"] == 512.0
        assert values["error_count"] == 3.0
        assert values["log_rate"] == 1.5

    def test_without_metrics(self):
        snap = HealthSnapshot(
            snapshot_id="ccdd" * 8,
            service_name="web",
            snapshot_at=datetime.now(timezone.utc),
            error_count=1,
            log_rate=0.5,
        )
        values = _extract_metrics(snap)
        assert values["cpu_percent"] is None
        assert values["memory_mb"] is None
        assert values["error_count"] == 1.0
        assert values["log_rate"] == 0.5


class TestUpdateBaselines:
    def test_first_sample(self, store, service):
        snap = _snap(cpu=10.0)
        baselines = update_baselines(store, snap)
        assert len(baselines) == 4  # cpu, mem, errors, log_rate

        bl = store.get_baseline("web", "cpu_percent")
        assert bl is not None
        assert bl.mean == 10.0
        assert bl.stddev == 0.0
        assert bl.sample_count == 1

    def test_multiple_samples_update_mean(self, store, service):
        update_baselines(store, _snap(cpu=10.0))
        update_baselines(store, _snap(cpu=20.0))

        bl = store.get_baseline("web", "cpu_percent")
        assert bl.sample_count == 2
        assert bl.mean == 15.0  # (10+20)/2

    def test_stddev_grows_with_variance(self, store, service):
        update_baselines(store, _snap(cpu=10.0))
        update_baselines(store, _snap(cpu=10.0))
        update_baselines(store, _snap(cpu=10.0))

        bl = store.get_baseline("web", "cpu_percent")
        assert bl.stddev == 0.0  # All same value

        # Now add a different value
        update_baselines(store, _snap(cpu=20.0))
        bl = store.get_baseline("web", "cpu_percent")
        assert bl.stddev > 0.0

    def test_list_baselines(self, store, service):
        update_baselines(store, _snap())
        baselines = store.list_baselines("web")
        metrics = {b.metric for b in baselines}
        assert "cpu_percent" in metrics
        assert "memory_mb" in metrics
        assert "error_count" in metrics
        assert "log_rate" in metrics


class TestDetectAnomalies:
    def _build_baseline(self, store, n=5, cpu=10.0):
        """Build a stable baseline with n samples."""
        for _ in range(n):
            update_baselines(store, _snap(cpu=cpu))

    def test_no_anomaly_within_threshold(self, store, service):
        self._build_baseline(store)
        # Value close to mean — no anomaly
        anomalies = detect_anomalies(store, _snap(cpu=10.0))
        assert len(anomalies) == 0

    def test_anomaly_detected_above_threshold(self, store, service):
        # Build baseline with some variance
        for cpu in [10.0, 11.0, 10.0, 11.0, 10.0]:
            update_baselines(store, _snap(cpu=cpu))

        bl = store.get_baseline("web", "cpu_percent")
        # Value way above mean + 2*stddev
        extreme_cpu = bl.mean + (SIGMA_THRESHOLD + 1) * bl.stddev + 1
        anomalies = detect_anomalies(store, _snap(cpu=extreme_cpu))

        cpu_anomalies = [a for a in anomalies if a.metric == "cpu_percent"]
        assert len(cpu_anomalies) == 1
        assert cpu_anomalies[0].deviation >= SIGMA_THRESHOLD

    def test_no_anomaly_with_insufficient_samples(self, store, service):
        # Less than MIN_SAMPLES — detection should not trigger
        for _ in range(MIN_SAMPLES - 1):
            update_baselines(store, _snap(cpu=10.0))

        anomalies = detect_anomalies(store, _snap(cpu=100.0))
        assert len(anomalies) == 0

    def test_anomaly_persisted_to_store(self, store, service):
        for cpu in [10.0, 11.0, 10.0, 11.0, 10.0]:
            update_baselines(store, _snap(cpu=cpu))

        bl = store.get_baseline("web", "cpu_percent")
        extreme_cpu = bl.mean + (SIGMA_THRESHOLD + 1) * bl.stddev + 1
        detect_anomalies(store, _snap(cpu=extreme_cpu))

        saved = store.recent_anomalies(service_name="web", since_minutes=5)
        assert len(saved) >= 1

    def test_zero_stddev_detects_deviation(self, store, service):
        # All identical — stddev=0, any different value is anomalous
        for _ in range(5):
            update_baselines(store, _snap(cpu=10.0))

        bl = store.get_baseline("web", "cpu_percent")
        assert bl.stddev == 0.0

        anomalies = detect_anomalies(store, _snap(cpu=11.0))
        cpu_anomalies = [a for a in anomalies if a.metric == "cpu_percent"]
        assert len(cpu_anomalies) == 1

    def test_negative_deviation_detected(self, store, service):
        # Build baseline with some variance
        for cpu in [50.0, 51.0, 50.0, 51.0, 50.0]:
            update_baselines(store, _snap(cpu=cpu))

        bl = store.get_baseline("web", "cpu_percent")
        extreme_low = bl.mean - (SIGMA_THRESHOLD + 1) * bl.stddev - 1
        anomalies = detect_anomalies(store, _snap(cpu=max(0, extreme_low)))

        cpu_anomalies = [a for a in anomalies if a.metric == "cpu_percent"]
        assert len(cpu_anomalies) == 1
        assert cpu_anomalies[0].deviation < 0


class TestSnapshotIntegration:
    def test_snapshot_updates_baselines(self, store, service):
        """Snapshot creation should auto-update baselines."""
        from unittest.mock import patch

        from niobe.core.snapshot import create_snapshot

        with patch("niobe.core.snapshot.capture_metrics") as mock_metrics:
            mock_metrics.return_value = ProcessMetrics(
                pid=1234, status="running", cpu_percent=15.0,
                memory_mb=128.0, num_threads=4, num_connections=1,
            )
            create_snapshot(store, service)

        bl = store.get_baseline("web", "cpu_percent")
        assert bl is not None
        assert bl.sample_count == 1
