"""Tests for MCP server tool functions."""

from unittest.mock import MagicMock, patch

import pytest


class TestMcpToolsDirect:
    """Test the core logic that MCP tools use, without requiring mcp package."""

    def test_register_flow(self, tmp_path):
        from niobe.core.store import NiobeStore
        from niobe.mcp.formatters import format_registration, format_services
        from niobe.models.runtime import ServiceInfo

        with NiobeStore(tmp_path / "test.db") as store:
            svc = ServiceInfo(name="test", pid=123, port=8080)
            store.register_service(svc)
            all_svcs = store.list_services()

        reg = format_registration("test", 123, 8080)
        tbl = format_services(all_svcs)
        assert "test" in reg
        assert "test" in tbl

    def test_snapshot_flow(self, tmp_path):
        from niobe.core.store import NiobeStore
        from niobe.mcp.formatters import format_snapshots
        from niobe.models.runtime import HealthSnapshot, ServiceInfo
        from datetime import datetime, timezone

        with NiobeStore(tmp_path / "test.db") as store:
            store.register_service(ServiceInfo(name="svc"))
            snap = HealthSnapshot(
                snapshot_id="a" * 32, service_name="svc",
                snapshot_at=datetime.now(timezone.utc),
            )
            store.save_snapshot(snap)
            snaps = store.list_snapshots("svc")

        out = format_snapshots(snaps)
        assert "svc" in out

    def test_errors_flow(self, tmp_path):
        from niobe.core.store import NiobeStore
        from niobe.mcp.formatters import format_log_entries
        from niobe.models.runtime import LogEntry, ServiceInfo

        with NiobeStore(tmp_path / "test.db") as store:
            store.register_service(ServiceInfo(name="svc"))
            store.insert_log_entries([
                LogEntry(
                    service_name="svc", level="error",
                    message="boom", source_file="a.log", raw_line="err",
                ),
            ])
            errors = store.recent_errors("svc", since_minutes=60)

        out = format_log_entries(errors, "Recent Errors")
        assert "boom" in out

    def test_search_flow(self, tmp_path):
        from niobe.core.store import NiobeStore
        from niobe.mcp.formatters import format_log_entries
        from niobe.models.runtime import LogEntry, ServiceInfo

        with NiobeStore(tmp_path / "test.db") as store:
            store.register_service(ServiceInfo(name="svc"))
            store.insert_log_entries([
                LogEntry(
                    service_name="svc", level="info",
                    message="database migration complete",
                    source_file="a.log", raw_line="info",
                ),
            ])
            results = store.search_logs("migration")

        out = format_log_entries(results, "Search")
        assert "migration" in out

    def test_compare_flow(self, tmp_path):
        from datetime import datetime, timezone
        from niobe.core.snapshot import compare_snapshots
        from niobe.core.store import NiobeStore
        from niobe.mcp.formatters import format_diff
        from niobe.models.runtime import HealthSnapshot, ServiceInfo

        with NiobeStore(tmp_path / "test.db") as store:
            store.register_service(ServiceInfo(name="svc"))
            now = datetime.now(timezone.utc)
            s1 = HealthSnapshot(snapshot_id="a" * 32, service_name="svc", snapshot_at=now, error_count=1)
            s2 = HealthSnapshot(snapshot_id="b" * 32, service_name="svc", snapshot_at=now, error_count=5)
            store.save_snapshot(s1)
            store.save_snapshot(s2)
            diff = compare_snapshots(store, "a" * 32, "b" * 32)

        assert diff is not None
        out = format_diff(diff)
        assert "svc" in out
