"""Anomaly detection via rolling baselines and mean + 2*stddev thresholds."""

from __future__ import annotations

import logging
import math

from niobe.core.store import NiobeStore
from niobe.models.runtime import Anomaly, HealthSnapshot, MetricBaseline

logger = logging.getLogger("niobe.anomaly")

# Metrics extracted from HealthSnapshot for baseline tracking
TRACKED_METRICS = ("cpu_percent", "memory_mb", "error_count", "log_rate")

# Default threshold: flag if value > mean + SIGMA_THRESHOLD * stddev
SIGMA_THRESHOLD = 2.0

# Minimum samples before anomaly detection activates
MIN_SAMPLES = 3


def update_baselines(store: NiobeStore, snap: HealthSnapshot) -> list[MetricBaseline]:
    """Update rolling baselines from a new snapshot using Welford's online algorithm.

    Returns the updated baselines.
    """
    values = _extract_metrics(snap)
    updated = []

    for metric, value in values.items():
        if value is None:
            continue

        existing = store.get_baseline(snap.service_name, metric)

        if existing is None:
            # First sample — initialize
            baseline = MetricBaseline(
                service_name=snap.service_name,
                metric=metric,
                mean=value,
                stddev=0.0,
                sample_count=1,
            )
        else:
            # Welford's online update for mean and variance
            n = existing.sample_count + 1
            delta = value - existing.mean
            new_mean = existing.mean + delta / n
            # For stddev, track running variance via M2
            # M2_old = existing.stddev^2 * (n-1 - 1) = existing.stddev^2 * existing.sample_count
            # But we stored stddev, not M2. Reconstruct:
            old_var = existing.stddev ** 2
            old_m2 = old_var * existing.sample_count  # sum of squared deviations
            delta2 = value - new_mean
            new_m2 = old_m2 + delta * delta2
            new_var = new_m2 / n if n > 0 else 0.0
            new_stddev = math.sqrt(max(0.0, new_var))

            baseline = MetricBaseline(
                service_name=snap.service_name,
                metric=metric,
                mean=round(new_mean, 4),
                stddev=round(new_stddev, 4),
                sample_count=n,
            )

        store.upsert_baseline(baseline)
        updated.append(baseline)

    return updated


def detect_anomalies(
    store: NiobeStore,
    snap: HealthSnapshot,
    sigma_threshold: float = SIGMA_THRESHOLD,
) -> list[Anomaly]:
    """Check current snapshot values against baselines, flag anomalies.

    Returns list of detected anomalies (empty if none).
    """
    values = _extract_metrics(snap)
    anomalies = []

    for metric, value in values.items():
        if value is None:
            continue

        baseline = store.get_baseline(snap.service_name, metric)
        if baseline is None or baseline.sample_count < MIN_SAMPLES:
            continue

        if baseline.stddev == 0.0:
            # All samples identical — any deviation is anomalous if nonzero
            if value != baseline.mean:
                deviation = float("inf")
            else:
                continue
        else:
            deviation = (value - baseline.mean) / baseline.stddev

        if abs(deviation) >= sigma_threshold:
            anomaly = Anomaly(
                service_name=snap.service_name,
                metric=metric,
                current_value=round(value, 4),
                baseline_mean=baseline.mean,
                baseline_stddev=baseline.stddev,
                deviation=round(deviation, 2),
            )
            store.save_anomaly(anomaly)
            anomalies.append(anomaly)
            logger.info(
                "Anomaly: %s.%s = %.2f (mean=%.2f, stddev=%.2f, %.1fσ)",
                snap.service_name, metric, value,
                baseline.mean, baseline.stddev, deviation,
            )

    return anomalies


def _extract_metrics(snap: HealthSnapshot) -> dict[str, float | None]:
    """Extract trackable metric values from a snapshot."""
    values: dict[str, float | None] = {
        "error_count": float(snap.error_count),
        "log_rate": snap.log_rate,
    }
    if snap.metrics:
        values["cpu_percent"] = snap.metrics.cpu_percent
        values["memory_mb"] = snap.metrics.memory_mb
    else:
        values["cpu_percent"] = None
        values["memory_mb"] = None
    return values
