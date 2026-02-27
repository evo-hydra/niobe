"""Tests for log file ingestion."""

import pytest

from niobe.config import IngestionConfig
from niobe.core.ingester import _tail_file, ingest_once
from niobe.core.store import NiobeStore
from niobe.models.runtime import ServiceInfo


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test.db"
    with NiobeStore(db_path) as s:
        yield s


class TestTailFile:
    def test_basic(self, tmp_path):
        log = tmp_path / "test.log"
        log.write_text("line1\nline2\nline3\nline4\nline5\n")
        lines = _tail_file(log, 3, 8192)
        assert len(lines) == 3
        assert lines[-1] == "line5"

    def test_fewer_lines(self, tmp_path):
        log = tmp_path / "test.log"
        log.write_text("only\n")
        lines = _tail_file(log, 10, 8192)
        assert len(lines) == 1

    def test_empty_file(self, tmp_path):
        log = tmp_path / "empty.log"
        log.write_text("")
        lines = _tail_file(log, 10, 8192)
        assert lines == []

    def test_missing_file(self, tmp_path):
        lines = _tail_file(tmp_path / "nope.log", 10, 8192)
        assert lines == []

    def test_max_line_length(self, tmp_path):
        log = tmp_path / "long.log"
        log.write_text("a" * 100 + "\n")
        lines = _tail_file(log, 10, 50)
        assert len(lines[0]) == 50


class TestIngestOnce:
    def test_ingest_json_logs(self, store, tmp_path):
        svc = ServiceInfo(name="app", log_paths=(str(tmp_path / "app.log"),))
        store.register_service(svc)

        log = tmp_path / "app.log"
        log.write_text(
            '{"level": "error", "message": "disk full"}\n'
            '{"level": "info", "message": "all good"}\n'
        )

        count = ingest_once(store, "app", svc.log_paths)
        assert count == 2

        errors = store.recent_errors("app", since_minutes=60)
        assert len(errors) == 1

    def test_ingest_no_files(self, store):
        count = ingest_once(store, "nope", ("/nonexistent/log.txt",))
        assert count == 0

    def test_ingest_with_config(self, store, tmp_path):
        svc = ServiceInfo(name="app", log_paths=(str(tmp_path / "app.log"),))
        store.register_service(svc)

        log = tmp_path / "app.log"
        lines = [f'{{"level": "info", "message": "line {i}"}}\n' for i in range(20)]
        log.write_text("".join(lines))

        config = IngestionConfig(tail_lines=5)
        count = ingest_once(store, "app", svc.log_paths, config)
        assert count == 5
