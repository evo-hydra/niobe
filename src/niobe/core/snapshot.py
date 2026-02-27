"""Snapshot creation and comparison orchestration."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from niobe.config import IngestionConfig, NiobeConfig, SnapshotConfig
from niobe.core.ingester import ingest_once
from niobe.core.monitor import capture_metrics
from niobe.core.store import NiobeStore
from niobe.models.runtime import HealthSnapshot, ServiceInfo, SnapshotDiff

logger = logging.getLogger("niobe.snapshot")


def create_snapshot(
    store: NiobeStore,
    service: ServiceInfo,
    config: NiobeConfig | None = None,
) -> HealthSnapshot:
    """Take a health snapshot: ingest logs, capture metrics, compute stats."""
    snap_config = config.snapshot if config else SnapshotConfig()
    ingest_config = config.ingestion if config else IngestionConfig()

    # 1. Ingest latest logs
    if service.log_paths:
        count = ingest_once(store, service.name, service.log_paths, ingest_config)
        logger.debug("Ingested %d log entries for %s", count, service.name)

    # 2. Capture process metrics
    metrics = capture_metrics(service, cpu_interval=snap_config.cpu_sample_interval)

    # 3. Count recent errors
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=snap_config.error_window_minutes)
    error_count = store.count_errors_since(service.name, window_start)

    # 4. Calculate log rate (lines per second in window)
    total_logs = store.count_logs_since(service.name, window_start)
    window_seconds = snap_config.error_window_minutes * 60
    log_rate = round(total_logs / window_seconds, 2) if window_seconds > 0 else 0.0

    # 5. Save and return
    snap = HealthSnapshot(
        snapshot_id=uuid.uuid4().hex,
        service_name=service.name,
        snapshot_at=now,
        metrics=metrics,
        error_count=error_count,
        log_rate=log_rate,
    )
    store.save_snapshot(snap)

    # 6. Update baselines and check for anomalies
    try:
        from niobe.core.anomaly import detect_anomalies, update_baselines

        update_baselines(store, snap)
        detect_anomalies(store, snap)
    except Exception:
        logger.debug("Anomaly detection skipped", exc_info=True)

    return snap


def create_all_snapshots(
    store: NiobeStore,
    config: NiobeConfig | None = None,
) -> list[HealthSnapshot]:
    """Take snapshots for all registered services."""
    services = store.list_services()
    results = []
    for svc in services:
        try:
            snap = create_snapshot(store, svc, config)
            results.append(snap)
        except Exception:
            logger.exception("Failed to snapshot service %s", svc.name)
    return results


def compare_snapshots(
    store: NiobeStore,
    id_a: str,
    id_b: str,
) -> SnapshotDiff | None:
    """Compare two snapshots and return the diff."""
    before = store.get_snapshot(id_a)
    after = store.get_snapshot(id_b)
    if before is None or after is None:
        return None

    if before.service_name != after.service_name:
        return None

    cpu_delta = 0.0
    memory_delta = 0.0
    status_changed = False

    if before.metrics and after.metrics:
        cpu_delta = round(after.metrics.cpu_percent - before.metrics.cpu_percent, 1)
        memory_delta = round(after.metrics.memory_mb - before.metrics.memory_mb, 2)
        status_changed = after.metrics.status != before.metrics.status

    return SnapshotDiff(
        service_name=before.service_name,
        before=before,
        after=after,
        cpu_delta=cpu_delta,
        memory_delta_mb=memory_delta,
        error_count_delta=after.error_count - before.error_count,
        log_rate_delta=round(after.log_rate - before.log_rate, 2),
        status_changed=status_changed,
    )
