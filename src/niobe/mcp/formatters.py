"""Markdown formatters for LLM-friendly output."""

from __future__ import annotations

from niobe.models.runtime import (
    Anomaly,
    AuditEntry,
    Feedback,
    HealthSnapshot,
    LogEntry,
    ServiceInfo,
    SnapshotDiff,
)


def format_snapshot(snap: HealthSnapshot) -> str:
    """Format a single snapshot as markdown."""
    lines = [
        f"## Snapshot: {snap.service_name}",
        f"**ID:** `{snap.snapshot_id[:12]}`  ",
        f"**Time:** {snap.snapshot_at.isoformat()}  ",
        "",
    ]

    if snap.metrics:
        m = snap.metrics
        lines.extend([
            "| Metric | Value |",
            "|--------|-------|",
            f"| PID | {m.pid} |",
            f"| Status | {m.status} |",
            f"| CPU | {m.cpu_percent}% |",
            f"| Memory | {m.memory_mb} MB |",
            f"| Threads | {m.num_threads} |",
            f"| Connections | {m.num_connections} |",
            "",
        ])
    else:
        lines.append("*No process metrics available*\n")

    lines.extend([
        f"**Errors (window):** {snap.error_count}  ",
        f"**Log rate:** {snap.log_rate} lines/sec",
    ])

    return "\n".join(lines)


def format_snapshots(snapshots: list[HealthSnapshot]) -> str:
    """Format multiple snapshots separated by dividers."""
    if not snapshots:
        return "No snapshots found."
    return "\n\n---\n\n".join(format_snapshot(s) for s in snapshots)


def format_diff(diff: SnapshotDiff) -> str:
    """Format a snapshot diff with deltas."""

    def _delta(val: float | int, suffix: str = "") -> str:
        sign = "+" if val > 0 else ""
        return f"{sign}{val}{suffix}"

    lines = [
        f"## Diff: {diff.service_name}",
        "",
        "| Metric | Before | After | Delta |",
        "|--------|--------|-------|-------|",
    ]

    if diff.before.metrics and diff.after.metrics:
        bm, am = diff.before.metrics, diff.after.metrics
        lines.extend([
            f"| Status | {bm.status} | {am.status} | {'CHANGED' if diff.status_changed else 'same'} |",
            f"| CPU | {bm.cpu_percent}% | {am.cpu_percent}% | {_delta(diff.cpu_delta, '%')} |",
            f"| Memory | {bm.memory_mb} MB | {am.memory_mb} MB | {_delta(diff.memory_delta_mb, ' MB')} |",
            f"| Threads | {bm.num_threads} | {am.num_threads} | {_delta(am.num_threads - bm.num_threads)} |",
            f"| Connections | {bm.num_connections} | {am.num_connections} | {_delta(am.num_connections - bm.num_connections)} |",
        ])

    lines.extend([
        f"| Errors | {diff.before.error_count} | {diff.after.error_count} | {_delta(diff.error_count_delta)} |",
        f"| Log rate | {diff.before.log_rate}/s | {diff.after.log_rate}/s | {_delta(diff.log_rate_delta, '/s')} |",
    ])

    return "\n".join(lines)


def format_log_entries(entries: list[LogEntry], title: str = "Log Entries") -> str:
    """Format log entries as a bulleted list."""
    if not entries:
        return f"## {title}\n\nNo entries found."

    lines = [f"## {title}", ""]
    for e in entries:
        ts = e.timestamp.isoformat() if e.timestamp else "???"
        lines.append(f"- **[{e.level.upper()}]** `{ts}` *{e.service_name}* — {e.message}")

    return "\n".join(lines)


def format_services(services: list[ServiceInfo]) -> str:
    """Format registered services as a table."""
    if not services:
        return "No services registered."

    lines = [
        "## Registered Services",
        "",
        "| Name | PID | Port | Log Paths |",
        "|------|-----|------|-----------|",
    ]
    for s in services:
        pid = str(s.pid) if s.pid else "—"
        port = str(s.port) if s.port else "—"
        paths = ", ".join(s.log_paths) if s.log_paths else "—"
        lines.append(f"| {s.name} | {pid} | {port} | {paths} |")

    return "\n".join(lines)


def format_registration(
    name: str,
    pid: int | None = None,
    port: int | None = None,
    log_paths: list[str] | None = None,
) -> str:
    """Format a service registration confirmation."""
    lines = [f"Registered service **{name}**:"]
    if pid is not None:
        lines.append(f"- PID: {pid}")
    if port is not None:
        lines.append(f"- Port: {port}")
    if log_paths:
        lines.append(f"- Log paths: {', '.join(log_paths)}")
    return "\n".join(lines)


def format_anomalies(anomalies: list[Anomaly], title: str = "Anomalies") -> str:
    """Format detected anomalies as a table."""
    if not anomalies:
        return f"## {title}\n\nNo anomalies detected."

    lines = [
        f"## {title}",
        "",
        "| Service | Metric | Value | Mean | StdDev | Deviation | Time |",
        "|---------|--------|-------|------|--------|-----------|------|",
    ]
    for a in anomalies:
        sign = "+" if a.deviation > 0 else ""
        lines.append(
            f"| {a.service_name} | {a.metric} | {a.current_value} "
            f"| {a.baseline_mean} | {a.baseline_stddev} "
            f"| {sign}{a.deviation}σ | {a.detected_at.isoformat()} |"
        )
    return "\n".join(lines)


def format_feedback(entries: list[Feedback], title: str = "Feedback") -> str:
    """Format feedback entries as a bulleted list."""
    if not entries:
        return f"## {title}\n\nNo feedback recorded."

    lines = [f"## {title}", ""]
    for f in entries:
        lines.append(
            f"- **[{f.outcome}]** `{f.target_type}:{f.target_id[:12]}` "
            f"— {f.context or '(no comment)'} ({f.created_at.isoformat()})"
        )
    return "\n".join(lines)


def format_audit(entries: list[AuditEntry], title: str = "Audit Log") -> str:
    """Format audit log entries as a table."""
    if not entries:
        return f"## {title}\n\nNo audit entries found."

    lines = [
        f"## {title}",
        "",
        "| Time | Tool | Parameters | Result |",
        "|------|------|------------|--------|",
    ]
    for e in entries:
        # Truncate long params/results for readability
        params = e.parameters[:80] + "..." if len(e.parameters) > 80 else e.parameters
        result = e.result_summary[:80] + "..." if len(e.result_summary) > 80 else e.result_summary
        lines.append(
            f"| {e.created_at.isoformat()} | {e.tool_name} | {params} | {result} |"
        )
    return "\n".join(lines)
