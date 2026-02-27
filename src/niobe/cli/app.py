"""Typer CLI for Niobe runtime observation."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from niobe.config import NiobeConfig
from niobe.core.store import NiobeStore
from niobe.models.runtime import ServiceInfo

app = typer.Typer(
    name="niobe",
    help="Runtime intelligence for AI agents — observe, snapshot, compare.",
    no_args_is_help=True,
)
console = Console(stderr=True)


def _config() -> NiobeConfig:
    return NiobeConfig.load()


def _open_store(config: NiobeConfig) -> NiobeStore:
    store = NiobeStore(config.db_path)
    store.open()
    return store


@app.command()
def register(
    name: str,
    pid: Annotated[Optional[int], typer.Option("--pid", help="Process ID")] = None,
    port: Annotated[Optional[int], typer.Option("--port", help="Network port")] = None,
    log: Annotated[Optional[list[str]], typer.Option("--log", help="Log file paths")] = None,
) -> None:
    """Register a service for observation."""
    config = _config()
    log_paths = tuple(log) if log else ()
    service = ServiceInfo(name=name, pid=pid, port=port, log_paths=log_paths)

    with _open_store(config) as store:
        store.register_service(service)

    console.print(f"[green]Registered service:[/green] {name}")
    if pid:
        console.print(f"  PID: {pid}")
    if port:
        console.print(f"  Port: {port}")
    if log_paths:
        console.print(f"  Logs: {', '.join(log_paths)}")


@app.command()
def unregister(name: str) -> None:
    """Remove a service from observation."""
    config = _config()

    with _open_store(config) as store:
        removed = store.unregister_service(name)

    if removed:
        console.print(f"[green]Unregistered:[/green] {name}")
    else:
        console.print(f"[yellow]Service not found:[/yellow] {name}")
        raise typer.Exit(1)


@app.command()
def services() -> None:
    """List all registered services."""
    config = _config()

    with _open_store(config) as store:
        svcs = store.list_services()

    if not svcs:
        console.print("[dim]No services registered.[/dim]")
        return

    from rich.table import Table

    table = Table(title="Registered Services")
    table.add_column("Name", style="bold")
    table.add_column("PID")
    table.add_column("Port")
    table.add_column("Log Paths")

    for s in svcs:
        table.add_row(
            s.name,
            str(s.pid) if s.pid else "—",
            str(s.port) if s.port else "—",
            ", ".join(s.log_paths) if s.log_paths else "—",
        )
    console.print(table)


@app.command()
def snapshot(
    service: Annotated[Optional[str], typer.Argument(help="Service name (omit for all)")] = None,
) -> None:
    """Take a health snapshot."""
    from niobe.core.snapshot import create_all_snapshots, create_snapshot

    config = _config()

    with _open_store(config) as store:
        if service:
            svc = store.get_service(service)
            if svc is None:
                console.print(f"[red]Service not found:[/red] {service}")
                raise typer.Exit(1)
            snaps = [create_snapshot(store, svc, config)]
        else:
            snaps = create_all_snapshots(store, config)

    if not snaps:
        console.print("[dim]No services to snapshot.[/dim]")
        return

    for snap in snaps:
        console.print(f"\n[bold]{snap.service_name}[/bold] — {snap.snapshot_id[:12]}")
        if snap.metrics:
            m = snap.metrics
            console.print(f"  Status: {m.status}  CPU: {m.cpu_percent}%  Mem: {m.memory_mb}MB")
            console.print(f"  Threads: {m.num_threads}  Connections: {m.num_connections}")
        else:
            console.print("  [dim]No process metrics[/dim]")
        console.print(f"  Errors: {snap.error_count}  Log rate: {snap.log_rate}/s")


@app.command()
def compare(id_a: str, id_b: str) -> None:
    """Compare two snapshots (before → after)."""
    from niobe.core.snapshot import compare_snapshots

    config = _config()

    with _open_store(config) as store:
        diff = compare_snapshots(store, id_a, id_b)

    if diff is None:
        console.print("[red]Could not compare: snapshot(s) not found or service mismatch.[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Diff: {diff.service_name}[/bold]")
    console.print(f"  CPU: {diff.cpu_delta:+.1f}%")
    console.print(f"  Memory: {diff.memory_delta_mb:+.2f} MB")
    console.print(f"  Errors: {diff.error_count_delta:+d}")
    console.print(f"  Log rate: {diff.log_rate_delta:+.2f}/s")
    if diff.status_changed:
        console.print("  [yellow]Status changed![/yellow]")


@app.command()
def logs(
    service: Annotated[Optional[str], typer.Option("--service", "-s", help="Filter by service")] = None,
    query: Annotated[Optional[str], typer.Option("--query", "-q", help="FTS5 search query")] = None,
    level: Annotated[Optional[str], typer.Option("--level", "-l", help="Filter by level")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max entries")] = 50,
) -> None:
    """Search or list log entries."""
    config = _config()

    with _open_store(config) as store:
        if query:
            entries = store.search_logs(query, service_name=service, level=level, limit=limit)
        else:
            # Fall back to recent errors if no query
            entries = store.recent_errors(service_name=service, limit=limit)

    if not entries:
        console.print("[dim]No log entries found.[/dim]")
        return

    for e in entries:
        ts = e.timestamp.isoformat() if e.timestamp else "???"
        level_str = e.level.upper()
        style = "red" if level_str in ("ERROR", "CRITICAL") else "yellow" if level_str == "WARNING" else ""
        if style:
            console.print(f"[{style}][{level_str}][/{style}] {ts} [{e.service_name}] {e.message}")
        else:
            console.print(f"[{level_str}] {ts} [{e.service_name}] {e.message}")


@app.command()
def errors(
    service: Annotated[Optional[str], typer.Option("--service", "-s", help="Filter by service")] = None,
    since: Annotated[int, typer.Option("--since", help="Minutes to look back")] = 5,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max entries")] = 50,
) -> None:
    """Show recent errors from ingested logs."""
    config = _config()

    with _open_store(config) as store:
        entries = store.recent_errors(service_name=service, since_minutes=since, limit=limit)

    if not entries:
        console.print("[dim]No recent errors.[/dim]")
        return

    for e in entries:
        ts = e.timestamp.isoformat() if e.timestamp else "???"
        console.print(f"[red][{e.level.upper()}][/red] {ts} [{e.service_name}] {e.message}")


@app.command()
def ingest(
    service: str,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Watch for changes")] = False,
) -> None:
    """Ingest log files for a service."""
    from niobe.core.ingester import ingest_follow, ingest_once

    config = _config()

    with _open_store(config) as store:
        svc = store.get_service(service)
        if svc is None:
            console.print(f"[red]Service not found:[/red] {service}")
            raise typer.Exit(1)

        if not svc.log_paths:
            console.print(f"[yellow]No log paths configured for {service}[/yellow]")
            raise typer.Exit(1)

        if follow:
            console.print(f"[dim]Watching logs for {service}... (Ctrl+C to stop)[/dim]")
            try:
                for count in ingest_follow(store, service, svc.log_paths, config.ingestion):
                    if count:
                        console.print(f"  Ingested {count} entries")
            except KeyboardInterrupt:
                console.print("\n[dim]Stopped.[/dim]")
        else:
            count = ingest_once(store, service, svc.log_paths, config.ingestion)
            console.print(f"[green]Ingested {count} log entries for {service}[/green]")


@app.command()
def anomalies(
    service: Annotated[Optional[str], typer.Option("--service", "-s", help="Filter by service")] = None,
    since: Annotated[int, typer.Option("--since", help="Minutes to look back")] = 30,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max entries")] = 50,
) -> None:
    """Show detected anomalies (metrics exceeding baseline + 2σ)."""
    config = _config()

    with _open_store(config) as store:
        entries = store.recent_anomalies(service_name=service, since_minutes=since, limit=limit)

    if not entries:
        console.print("[dim]No anomalies detected.[/dim]")
        return

    from rich.table import Table

    table = Table(title="Anomalies")
    table.add_column("Service", style="bold")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_column("Mean", justify="right")
    table.add_column("σ", justify="right")
    table.add_column("Deviation", justify="right")

    for a in entries:
        sign = "+" if a.deviation > 0 else ""
        table.add_row(
            a.service_name,
            a.metric,
            f"{a.current_value:.2f}",
            f"{a.baseline_mean:.2f}",
            f"{a.baseline_stddev:.2f}",
            f"[red]{sign}{a.deviation:.1f}σ[/red]",
        )
    console.print(table)


@app.command()
def feedback(
    target_id: str,
    outcome: Annotated[str, typer.Argument(help="accepted, rejected, or modified")],
    target_type: Annotated[str, typer.Option("--type", "-t", help="snapshot or comparison")] = "snapshot",
    context: Annotated[Optional[str], typer.Option("--context", "-c", help="Explanation")] = None,
) -> None:
    """Submit feedback on a snapshot or comparison."""
    from niobe.models.runtime import Feedback

    if outcome not in ("accepted", "rejected", "modified"):
        console.print(f"[red]Invalid outcome:[/red] {outcome}")
        raise typer.Exit(1)

    fb = Feedback(
        target_id=target_id,
        target_type=target_type,
        outcome=outcome,
        context=context or "",
    )
    config = _config()

    with _open_store(config) as store:
        store.save_feedback(fb)

    console.print(f"[green]Feedback recorded:[/green] {outcome} on {target_type} {target_id[:12]}")


@app.command()
def audit(
    tool_name: Annotated[Optional[str], typer.Option("--tool", "-t", help="Filter by tool name")] = None,
    since: Annotated[Optional[int], typer.Option("--since", help="Minutes to look back")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max entries")] = 50,
) -> None:
    """Query the audit log of tool invocations."""
    config = _config()

    with _open_store(config) as store:
        entries = store.query_audit(tool_name=tool_name, since_minutes=since, limit=limit)

    if not entries:
        console.print("[dim]No audit entries found.[/dim]")
        return

    from rich.table import Table

    table = Table(title="Audit Log")
    table.add_column("Time")
    table.add_column("Tool", style="bold")
    table.add_column("Parameters")
    table.add_column("Result")

    for e in entries:
        params = e.parameters[:60] + "..." if len(e.parameters) > 60 else e.parameters
        result = e.result_summary[:60] + "..." if len(e.result_summary) > 60 else e.result_summary
        table.add_row(e.created_at.isoformat(), e.tool_name, params, result)
    console.print(table)


def main() -> None:
    """Entry point for the niobe CLI."""
    app()


if __name__ == "__main__":
    main()
