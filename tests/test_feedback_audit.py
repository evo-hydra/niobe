"""Tests for feedback and audit log features."""

from datetime import datetime, timezone

import pytest

from niobe.core.store import NiobeStore
from niobe.models.runtime import AuditEntry, Feedback, ServiceInfo


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


class TestFeedback:
    def test_save_and_list(self, store, service):
        fb = Feedback(
            target_id="aabb" * 8,
            target_type="snapshot",
            outcome="accepted",
            context="Looks correct",
        )
        store.save_feedback(fb)

        entries = store.list_feedback()
        assert len(entries) == 1
        assert entries[0].outcome == "accepted"
        assert entries[0].context == "Looks correct"

    def test_filter_by_target(self, store, service):
        store.save_feedback(Feedback(
            target_id="aaaa1111", target_type="snapshot", outcome="accepted",
        ))
        store.save_feedback(Feedback(
            target_id="bbbb2222", target_type="comparison", outcome="rejected",
        ))

        entries = store.list_feedback(target_id="aaaa")
        assert len(entries) == 1
        assert entries[0].target_id == "aaaa1111"

    def test_list_empty(self, store):
        entries = store.list_feedback()
        assert entries == []

    def test_multiple_feedback_same_target(self, store, service):
        for outcome in ("accepted", "modified", "rejected"):
            store.save_feedback(Feedback(
                target_id="cccc3333", target_type="snapshot", outcome=outcome,
            ))

        entries = store.list_feedback(target_id="cccc")
        assert len(entries) == 3

    def test_limit(self, store, service):
        for i in range(10):
            store.save_feedback(Feedback(
                target_id=f"id{i:08d}", target_type="snapshot", outcome="accepted",
            ))

        entries = store.list_feedback(limit=3)
        assert len(entries) == 3


class TestAuditLog:
    def test_log_and_query(self, store):
        entry = AuditEntry(
            tool_name="niobe_snapshot",
            parameters='{"service": "web"}',
            result_summary="Snapshot taken",
        )
        store.log_audit(entry)

        entries = store.query_audit()
        assert len(entries) == 1
        assert entries[0].tool_name == "niobe_snapshot"
        assert entries[0].parameters == '{"service": "web"}'

    def test_filter_by_tool(self, store):
        store.log_audit(AuditEntry(
            tool_name="niobe_snapshot", parameters="{}", result_summary="ok",
        ))
        store.log_audit(AuditEntry(
            tool_name="niobe_errors", parameters="{}", result_summary="ok",
        ))

        entries = store.query_audit(tool_name="niobe_snapshot")
        assert len(entries) == 1
        assert entries[0].tool_name == "niobe_snapshot"

    def test_filter_by_time(self, store):
        store.log_audit(AuditEntry(
            tool_name="niobe_logs", parameters="{}", result_summary="ok",
        ))

        # Recent entries should appear
        entries = store.query_audit(since_minutes=5)
        assert len(entries) == 1

    def test_empty_audit(self, store):
        entries = store.query_audit()
        assert entries == []

    def test_limit(self, store):
        for i in range(10):
            store.log_audit(AuditEntry(
                tool_name=f"tool_{i}", parameters="{}", result_summary="ok",
            ))

        entries = store.query_audit(limit=3)
        assert len(entries) == 3

    def test_ordering_newest_first(self, store):
        store.log_audit(AuditEntry(
            tool_name="first", parameters="{}", result_summary="ok",
        ))
        store.log_audit(AuditEntry(
            tool_name="second", parameters="{}", result_summary="ok",
        ))

        entries = store.query_audit()
        assert entries[0].tool_name == "second"
        assert entries[1].tool_name == "first"


class TestFormatters:
    def test_format_anomalies_empty(self):
        from niobe.mcp.formatters import format_anomalies
        result = format_anomalies([])
        assert "No anomalies detected" in result

    def test_format_anomalies_with_data(self):
        from niobe.mcp.formatters import format_anomalies
        from niobe.models.runtime import Anomaly

        anomalies = [
            Anomaly(
                service_name="web", metric="cpu_percent",
                current_value=95.0, baseline_mean=10.0,
                baseline_stddev=2.0, deviation=42.5,
            ),
        ]
        result = format_anomalies(anomalies)
        assert "web" in result
        assert "cpu_percent" in result
        assert "42.5σ" in result

    def test_format_feedback_empty(self):
        from niobe.mcp.formatters import format_feedback
        result = format_feedback([])
        assert "No feedback recorded" in result

    def test_format_feedback_with_data(self):
        from niobe.mcp.formatters import format_feedback

        entries = [
            Feedback(
                target_id="aabb" * 8, target_type="snapshot",
                outcome="accepted", context="Good",
            ),
        ]
        result = format_feedback(entries)
        assert "accepted" in result
        assert "Good" in result

    def test_format_audit_empty(self):
        from niobe.mcp.formatters import format_audit
        result = format_audit([])
        assert "No audit entries found" in result

    def test_format_audit_with_data(self):
        from niobe.mcp.formatters import format_audit

        entries = [
            AuditEntry(
                tool_name="niobe_snapshot",
                parameters='{"service": "web"}',
                result_summary="Snapshot taken",
            ),
        ]
        result = format_audit(entries)
        assert "niobe_snapshot" in result
        assert "Snapshot taken" in result


class TestSchemaV2Migration:
    def test_fresh_db_has_v2_tables(self, tmp_path):
        """A fresh DB should have all v2 tables."""
        db_path = tmp_path / "fresh.db"
        with NiobeStore(db_path) as store:
            assert store.get_meta("schema_version") == "2"

            # Verify tables exist by querying them
            store.conn.execute("SELECT COUNT(*) FROM metric_baselines")
            store.conn.execute("SELECT COUNT(*) FROM anomalies")
            store.conn.execute("SELECT COUNT(*) FROM feedback")
            store.conn.execute("SELECT COUNT(*) FROM audit_log")

    def test_v1_db_migrates_to_v2(self, tmp_path):
        """An existing v1 DB should migrate to v2."""
        import sqlite3

        db_path = tmp_path / "old.db"
        # Create a minimal v1 database
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE niobe_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO niobe_meta VALUES ('schema_version', '1')")
        conn.execute("""CREATE TABLE services (
            name TEXT PRIMARY KEY, pid INTEGER, port INTEGER,
            log_paths TEXT NOT NULL DEFAULT '[]', registered_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE snapshots (
            snapshot_id TEXT PRIMARY KEY, service_name TEXT NOT NULL,
            snapshot_at TEXT NOT NULL, metrics TEXT,
            error_count INTEGER NOT NULL DEFAULT 0, log_rate REAL NOT NULL DEFAULT 0.0
        )""")
        conn.execute("""CREATE TABLE log_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_name TEXT NOT NULL, timestamp TEXT,
            level TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
            source_file TEXT NOT NULL DEFAULT '', raw_line TEXT NOT NULL DEFAULT '',
            ingested_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE VIRTUAL TABLE log_fts USING fts5(
            message, content='log_entries', content_rowid='id',
            tokenize='porter unicode61'
        )""")
        conn.commit()
        conn.close()

        # Open with NiobeStore — should migrate
        with NiobeStore(db_path) as store:
            assert store.get_meta("schema_version") == "2"
            store.conn.execute("SELECT COUNT(*) FROM metric_baselines")
            store.conn.execute("SELECT COUNT(*) FROM anomalies")
            store.conn.execute("SELECT COUNT(*) FROM feedback")
            store.conn.execute("SELECT COUNT(*) FROM audit_log")
