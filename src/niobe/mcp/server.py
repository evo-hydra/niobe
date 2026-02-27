"""FastMCP server factory with 8 tools for runtime observation."""

from __future__ import annotations

import json
import sqlite3

from niobe.config import NiobeConfig
from niobe.mcp.formatters import (
    format_anomalies,
    format_audit,
    format_diff,
    format_feedback,
    format_log_entries,
    format_registration,
    format_services,
    format_snapshots,
)


def _audit(store, tool_name: str, params: dict, result: str) -> None:
    """Record a tool invocation in the audit log."""
    from niobe.models.runtime import AuditEntry

    # Truncate result summary for storage
    summary = result[:500] if len(result) > 500 else result
    entry = AuditEntry(
        tool_name=tool_name,
        parameters=json.dumps(params, default=str),
        result_summary=summary,
    )
    store.log_audit(entry)


def create_server(config: NiobeConfig | None = None):
    """Create and return a configured FastMCP server instance.

    Args:
        config: Optional pre-loaded config. If None, loads from cwd.
    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("niobe", instructions="Runtime intelligence for AI agents")
    _config = config or NiobeConfig.load()

    @mcp.tool()
    def niobe_register(
        name: str,
        pid: int | None = None,
        port: int | None = None,
        log_paths: list[str] | None = None,
    ) -> str:
        """Register a service for runtime observation.

        Args:
            name: Service name (unique identifier)
            pid: Process ID (optional — can be resolved from port)
            port: Network port the service listens on (optional)
            log_paths: Paths to log files to monitor (optional)
        """
        from niobe.core.store import NiobeStore
        from niobe.models.runtime import ServiceInfo

        paths = tuple(log_paths) if log_paths else ()
        service = ServiceInfo(name=name, pid=pid, port=port, log_paths=paths)

        try:
            with NiobeStore(_config.db_path) as store:
                store.register_service(service)
                all_services = store.list_services()
                result = format_registration(name, pid, port, log_paths)
                result += "\n\n" + format_services(all_services)
                _audit(store, "niobe_register", {"name": name, "pid": pid, "port": port}, result)
                return result
        except (sqlite3.Error, OSError) as exc:
            return f"Error registering service: {exc}"

    @mcp.tool()
    def niobe_snapshot(service: str | None = None) -> str:
        """Take a health snapshot of one or all registered services.

        Captures process metrics, ingests recent logs, and computes error rates.

        Args:
            service: Service name (omit for all services)
        """
        from niobe.core.snapshot import create_all_snapshots, create_snapshot
        from niobe.core.store import NiobeStore

        try:
            with NiobeStore(_config.db_path) as store:
                if service:
                    svc = store.get_service(service)
                    if svc is None:
                        return f"Service '{service}' not found. Use niobe_register first."
                    snap = create_snapshot(store, svc, _config)
                    result = format_snapshots([snap])
                else:
                    snaps = create_all_snapshots(store, _config)
                    if not snaps:
                        return "No services registered. Use niobe_register first."
                    result = format_snapshots(snaps)
                _audit(store, "niobe_snapshot", {"service": service}, result)
                return result
        except (sqlite3.Error, OSError) as exc:
            return f"Error taking snapshot: {exc}"

    @mcp.tool()
    def niobe_compare(snapshot_a: str, snapshot_b: str) -> str:
        """Compare two snapshots to see what changed (before/after diff).

        Args:
            snapshot_a: Snapshot ID (or 8+ char prefix) for the "before" state
            snapshot_b: Snapshot ID (or 8+ char prefix) for the "after" state
        """
        from niobe.core.snapshot import compare_snapshots
        from niobe.core.store import NiobeStore

        try:
            with NiobeStore(_config.db_path) as store:
                diff = compare_snapshots(store, snapshot_a, snapshot_b)
                if diff is None:
                    return "Could not compare: snapshot(s) not found or service mismatch."
                result = format_diff(diff)
                _audit(store, "niobe_compare", {"a": snapshot_a, "b": snapshot_b}, result)
                return result
        except (sqlite3.Error, OSError) as exc:
            return f"Error comparing snapshots: {exc}"

    @mcp.tool()
    def niobe_errors(
        service: str | None = None,
        since: int | None = None,
        limit: int | None = None,
    ) -> str:
        """Get recent errors from ingested logs.

        Args:
            service: Filter by service name (optional)
            since: Look back N minutes (default from config)
            limit: Max entries to return (default from config)
        """
        from niobe.core.store import NiobeStore

        since_val = since if since is not None else _config.mcp.default_error_since_minutes
        limit_val = limit if limit is not None else _config.mcp.default_query_limit

        try:
            with NiobeStore(_config.db_path) as store:
                entries = store.recent_errors(
                    service_name=service, since_minutes=since_val, limit=limit_val
                )
                result = format_log_entries(entries, title="Recent Errors")
                _audit(store, "niobe_errors", {"service": service, "since": since_val}, result)
                return result
        except (sqlite3.Error, OSError) as exc:
            return f"Error fetching errors: {exc}"

    @mcp.tool()
    def niobe_logs(
        query: str,
        service: str | None = None,
        level: str | None = None,
        limit: int | None = None,
    ) -> str:
        """Full-text search across ingested log entries.

        Args:
            query: FTS5 search query (supports AND, OR, NOT, phrase "quotes")
            service: Filter by service name (optional)
            level: Filter by log level: critical, error, warning, info, debug (optional)
            limit: Max entries to return (default from config)
        """
        from niobe.core.store import NiobeStore

        limit_val = limit if limit is not None else _config.mcp.default_query_limit

        try:
            with NiobeStore(_config.db_path) as store:
                entries = store.search_logs(
                    query=query, service_name=service, level=level, limit=limit_val
                )
                result = format_log_entries(entries, title=f'Search: "{query}"')
                _audit(store, "niobe_logs", {"query": query, "service": service}, result)
                return result
        except (sqlite3.Error, OSError) as exc:
            return f"Error searching logs: {exc}"

    @mcp.tool()
    def niobe_anomalies(
        service: str | None = None,
        since: int | None = None,
        limit: int | None = None,
    ) -> str:
        """Get active anomalies — metrics that exceed baseline mean + 2σ.

        Anomalies are detected automatically during snapshots once enough
        baseline samples exist (minimum 3 snapshots per service).

        Args:
            service: Filter by service name (optional)
            since: Look back N minutes (default 30)
            limit: Max entries to return (default from config)
        """
        from niobe.core.store import NiobeStore

        since_val = since if since is not None else 30
        limit_val = limit if limit is not None else _config.mcp.default_query_limit

        try:
            with NiobeStore(_config.db_path) as store:
                entries = store.recent_anomalies(
                    service_name=service, since_minutes=since_val, limit=limit_val
                )
                result = format_anomalies(entries)
                _audit(store, "niobe_anomalies", {"service": service, "since": since_val}, result)
                return result
        except (sqlite3.Error, OSError) as exc:
            return f"Error fetching anomalies: {exc}"

    @mcp.tool()
    def niobe_feedback(
        target_id: str,
        outcome: str,
        target_type: str = "snapshot",
        context: str = "",
    ) -> str:
        """Submit feedback on a snapshot or comparison result.

        Helps Niobe learn which observations are useful.

        Args:
            target_id: Snapshot ID or comparison key to give feedback on
            outcome: One of: accepted, rejected, modified
            target_type: Type of target: snapshot or comparison (default: snapshot)
            context: Optional explanation of why
        """
        from niobe.core.store import NiobeStore
        from niobe.models.runtime import Feedback

        if outcome not in ("accepted", "rejected", "modified"):
            return f"Invalid outcome '{outcome}'. Must be: accepted, rejected, modified."

        if target_type not in ("snapshot", "comparison"):
            return f"Invalid target_type '{target_type}'. Must be: snapshot, comparison."

        fb = Feedback(
            target_id=target_id,
            target_type=target_type,
            outcome=outcome,
            context=context,
        )

        try:
            with NiobeStore(_config.db_path) as store:
                store.save_feedback(fb)
                result = f"Feedback recorded: **{outcome}** on {target_type} `{target_id[:12]}`"
                if context:
                    result += f"\nContext: {context}"
                _audit(store, "niobe_feedback", {"target_id": target_id, "outcome": outcome}, result)
                return result
        except (sqlite3.Error, OSError) as exc:
            return f"Error saving feedback: {exc}"

    @mcp.tool()
    def niobe_audit(
        tool_name: str | None = None,
        since: int | None = None,
        limit: int | None = None,
    ) -> str:
        """Query the local audit log of all Niobe tool invocations.

        Args:
            tool_name: Filter by tool name (optional)
            since: Look back N minutes (optional)
            limit: Max entries to return (default from config)
        """
        from niobe.core.store import NiobeStore

        limit_val = limit if limit is not None else _config.mcp.default_query_limit

        try:
            with NiobeStore(_config.db_path) as store:
                entries = store.query_audit(
                    tool_name=tool_name, since_minutes=since, limit=limit_val
                )
                return format_audit(entries)
        except (sqlite3.Error, OSError) as exc:
            return f"Error querying audit log: {exc}"

    return mcp


def main() -> None:
    """Entry point for niobe-mcp (stdio transport)."""
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
