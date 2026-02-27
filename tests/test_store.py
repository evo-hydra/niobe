"""Tests for NiobeStore — CRUD + FTS5."""

from datetime import datetime, timezone

import pytest

from niobe.core.store import NiobeStore
from niobe.models.runtime import HealthSnapshot, LogEntry, ProcessMetrics, ServiceInfo


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test.db"
    with NiobeStore(db_path) as s:
        yield s


@pytest.fixture
def sample_service():
    return ServiceInfo(
        name="web", pid=1234, port=8080,
        log_paths=("/var/log/web.log",),
    )


class TestServices:
    def test_register_and_get(self, store, sample_service):
        store.register_service(sample_service)
        svc = store.get_service("web")
        assert svc is not None
        assert svc.name == "web"
        assert svc.pid == 1234
        assert svc.log_paths == ("/var/log/web.log",)

    def test_list_services(self, store, sample_service):
        store.register_service(sample_service)
        svcs = store.list_services()
        assert len(svcs) == 1

    def test_unregister(self, store, sample_service):
        store.register_service(sample_service)
        assert store.unregister_service("web") is True
        assert store.get_service("web") is None

    def test_unregister_nonexistent(self, store):
        assert store.unregister_service("nope") is False

    def test_register_replaces(self, store, sample_service):
        store.register_service(sample_service)
        updated = ServiceInfo(name="web", pid=5678, port=9090)
        store.register_service(updated)
        svc = store.get_service("web")
        assert svc.pid == 5678


class TestSnapshots:
    def test_save_and_get(self, store, sample_service):
        store.register_service(sample_service)
        now = datetime.now(timezone.utc)
        snap = HealthSnapshot(
            snapshot_id="aabbccdd11223344",
            service_name="web",
            snapshot_at=now,
            error_count=3,
            log_rate=1.5,
        )
        store.save_snapshot(snap)
        got = store.get_snapshot("aabbccdd")
        assert got is not None
        assert got.snapshot_id == "aabbccdd11223344"
        assert got.error_count == 3

    def test_save_with_metrics(self, store, sample_service):
        store.register_service(sample_service)
        now = datetime.now(timezone.utc)
        metrics = ProcessMetrics(
            pid=1234, status="running", cpu_percent=10.5,
            memory_mb=256.0, num_threads=8, num_connections=3,
        )
        snap = HealthSnapshot(
            snapshot_id="deadbeef12345678",
            service_name="web",
            snapshot_at=now,
            metrics=metrics,
        )
        store.save_snapshot(snap)
        got = store.get_snapshot("deadbeef")
        assert got.metrics is not None
        assert got.metrics.cpu_percent == 10.5

    def test_list_snapshots(self, store, sample_service):
        store.register_service(sample_service)
        now = datetime.now(timezone.utc)
        for i in range(3):
            snap = HealthSnapshot(
                snapshot_id=f"snap{i:028d}",
                service_name="web", snapshot_at=now,
            )
            store.save_snapshot(snap)
        assert len(store.list_snapshots("web")) == 3
        assert len(store.list_snapshots()) == 3


class TestLogs:
    def test_insert_and_search(self, store, sample_service):
        store.register_service(sample_service)
        entries = [
            LogEntry(
                service_name="web", level="error",
                message="connection refused to database",
                source_file="/var/log/web.log",
                raw_line="ERROR connection refused to database",
            ),
            LogEntry(
                service_name="web", level="info",
                message="server started on port 8080",
                source_file="/var/log/web.log",
                raw_line="INFO server started on port 8080",
            ),
        ]
        count = store.insert_log_entries(entries)
        assert count == 2

        results = store.search_logs("connection")
        assert len(results) == 1
        assert "connection" in results[0].message

    def test_recent_errors(self, store, sample_service):
        store.register_service(sample_service)
        entries = [
            LogEntry(
                service_name="web", level="error",
                message="disk full", source_file="a.log", raw_line="err",
            ),
            LogEntry(
                service_name="web", level="info",
                message="all good", source_file="a.log", raw_line="ok",
            ),
        ]
        store.insert_log_entries(entries)
        errs = store.recent_errors(since_minutes=60)
        assert len(errs) == 1
        assert errs[0].level == "error"

    def test_count_logs_since(self, store, sample_service):
        store.register_service(sample_service)
        entries = [
            LogEntry(
                service_name="web", level="info",
                message="line1", source_file="a.log", raw_line="l1",
            ),
            LogEntry(
                service_name="web", level="info",
                message="line2", source_file="a.log", raw_line="l2",
            ),
        ]
        store.insert_log_entries(entries)
        from datetime import timedelta
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        assert store.count_logs_since("web", past) == 2

    def test_insert_empty(self, store):
        assert store.insert_log_entries([]) == 0


class TestMeta:
    def test_get_set(self, store):
        store.set_meta("foo", "bar")
        assert store.get_meta("foo") == "bar"

    def test_get_missing(self, store):
        assert store.get_meta("nope") is None

    def test_schema_version(self, store):
        assert store.get_meta("schema_version") == "1"


class TestContextManager:
    def test_open_close(self, tmp_path):
        db_path = tmp_path / "ctx.db"
        store = NiobeStore(db_path)
        with store:
            store.set_meta("test", "val")
        # After close, conn should be None
        assert store._conn is None
