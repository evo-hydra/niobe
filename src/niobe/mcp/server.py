"""FastMCP server factory with 5 tools for runtime observation."""

from __future__ import annotations

from niobe.config import NiobeConfig
from niobe.mcp.formatters import (
    format_diff,
    format_log_entries,
    format_registration,
    format_services,
    format_snapshots,
)


def create_server():
    """Create and return a configured FastMCP server instance."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("niobe", description="Runtime intelligence for AI agents")

    def _get_config() -> NiobeConfig:
        return NiobeConfig.load()

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

        config = _get_config()
        paths = tuple(log_paths) if log_paths else ()
        service = ServiceInfo(name=name, pid=pid, port=port, log_paths=paths)

        try:
            with NiobeStore(config.db_path) as store:
                store.register_service(service)
                all_services = store.list_services()
        except Exception as exc:
            return f"Error registering service: {exc}"

        registration = format_registration(name, pid, port, log_paths)
        services_table = format_services(all_services)
        return f"{registration}\n\n{services_table}"

    @mcp.tool()
    def niobe_snapshot(service: str | None = None) -> str:
        """Take a health snapshot of one or all registered services.

        Captures process metrics, ingests recent logs, and computes error rates.

        Args:
            service: Service name (omit for all services)
        """
        from niobe.core.snapshot import create_all_snapshots, create_snapshot
        from niobe.core.store import NiobeStore

        config = _get_config()

        try:
            with NiobeStore(config.db_path) as store:
                if service:
                    svc = store.get_service(service)
                    if svc is None:
                        return f"Service '{service}' not found. Use niobe_register first."
                    snap = create_snapshot(store, svc, config)
                    return format_snapshots([snap])
                else:
                    snaps = create_all_snapshots(store, config)
                    if not snaps:
                        return "No services registered. Use niobe_register first."
                    return format_snapshots(snaps)
        except Exception as exc:
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

        config = _get_config()

        try:
            with NiobeStore(config.db_path) as store:
                diff = compare_snapshots(store, snapshot_a, snapshot_b)
        except Exception as exc:
            return f"Error comparing snapshots: {exc}"

        if diff is None:
            return "Could not compare: snapshot(s) not found or service mismatch."
        return format_diff(diff)

    @mcp.tool()
    def niobe_errors(
        service: str | None = None,
        since: int = 5,
        limit: int = 50,
    ) -> str:
        """Get recent errors from ingested logs.

        Args:
            service: Filter by service name (optional)
            since: Look back N minutes (default: 5)
            limit: Max entries to return (default: 50)
        """
        from niobe.core.store import NiobeStore

        config = _get_config()

        try:
            with NiobeStore(config.db_path) as store:
                entries = store.recent_errors(
                    service_name=service, since_minutes=since, limit=limit
                )
        except Exception as exc:
            return f"Error fetching errors: {exc}"

        return format_log_entries(entries, title="Recent Errors")

    @mcp.tool()
    def niobe_logs(
        query: str,
        service: str | None = None,
        level: str | None = None,
        limit: int = 50,
    ) -> str:
        """Full-text search across ingested log entries.

        Args:
            query: FTS5 search query (supports AND, OR, NOT, phrase "quotes")
            service: Filter by service name (optional)
            level: Filter by log level: critical, error, warning, info, debug (optional)
            limit: Max entries to return (default: 50)
        """
        from niobe.core.store import NiobeStore

        config = _get_config()

        try:
            with NiobeStore(config.db_path) as store:
                entries = store.search_logs(
                    query=query, service_name=service, level=level, limit=limit
                )
        except Exception as exc:
            return f"Error searching logs: {exc}"

        return format_log_entries(entries, title=f'Search: "{query}"')

    return mcp


def main() -> None:
    """Entry point for niobe-mcp (stdio transport)."""
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
