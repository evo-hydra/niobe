"""Tests for the Typer CLI."""

import os
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from niobe.cli.app import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def use_tmp_dir(tmp_path, monkeypatch):
    """Run CLI commands in a temp directory so .niobe/niobe.db is isolated."""
    monkeypatch.chdir(tmp_path)


class TestRegister:
    def test_register_basic(self):
        result = runner.invoke(app, ["register", "myapp"])
        assert result.exit_code == 0
        assert "myapp" in result.output

    def test_register_with_options(self):
        result = runner.invoke(app, ["register", "web", "--pid", "1234", "--port", "8080"])
        assert result.exit_code == 0
        assert "web" in result.output


class TestUnregister:
    def test_unregister_existing(self):
        runner.invoke(app, ["register", "myapp"])
        result = runner.invoke(app, ["unregister", "myapp"])
        assert result.exit_code == 0
        assert "Unregistered" in result.output

    def test_unregister_missing(self):
        result = runner.invoke(app, ["unregister", "nope"])
        assert result.exit_code == 1


class TestServices:
    def test_empty(self):
        result = runner.invoke(app, ["services"])
        assert result.exit_code == 0
        assert "No services" in result.output

    def test_with_services(self):
        runner.invoke(app, ["register", "web"])
        result = runner.invoke(app, ["services"])
        assert result.exit_code == 0
        assert "web" in result.output


class TestSnapshot:
    @patch("niobe.core.snapshot.capture_metrics")
    def test_snapshot_service(self, mock_capture):
        mock_capture.return_value = None
        runner.invoke(app, ["register", "myapp"])
        result = runner.invoke(app, ["snapshot", "myapp"])
        assert result.exit_code == 0
        assert "myapp" in result.output

    def test_snapshot_missing_service(self):
        result = runner.invoke(app, ["snapshot", "nope"])
        assert result.exit_code == 1

    @patch("niobe.core.snapshot.capture_metrics")
    def test_snapshot_all_empty(self, mock_capture):
        result = runner.invoke(app, ["snapshot"])
        assert result.exit_code == 0
        assert "No services" in result.output

    @patch("niobe.core.snapshot.capture_metrics")
    def test_snapshot_all_with_services(self, mock_capture):
        mock_capture.return_value = None
        runner.invoke(app, ["register", "svc1"])
        runner.invoke(app, ["register", "svc2"])
        result = runner.invoke(app, ["snapshot"])
        assert result.exit_code == 0
        assert "svc1" in result.output


class TestCompare:
    @patch("niobe.core.snapshot.capture_metrics")
    def test_compare_success(self, mock_capture):
        mock_capture.return_value = None
        runner.invoke(app, ["register", "myapp"])
        r1 = runner.invoke(app, ["snapshot", "myapp"])
        r2 = runner.invoke(app, ["snapshot", "myapp"])
        # Extract snapshot IDs from output
        import re
        ids = re.findall(r'[a-f0-9]{12}', r1.output + r2.output)
        if len(ids) >= 2:
            result = runner.invoke(app, ["compare", ids[0], ids[1]])
            assert result.exit_code == 0

    def test_compare_missing(self):
        result = runner.invoke(app, ["compare", "nonexist1", "nonexist2"])
        assert result.exit_code == 1


class TestLogs:
    def test_no_logs(self):
        result = runner.invoke(app, ["logs"])
        assert result.exit_code == 0

    def test_logs_with_query(self, tmp_path):
        # Register, ingest, then search
        log = tmp_path / "test.log"
        log.write_text('{"level":"error","message":"database timeout"}\n')
        runner.invoke(app, ["register", "svc", "--log", str(log)])
        runner.invoke(app, ["ingest", "svc"])
        result = runner.invoke(app, ["logs", "--query", "database"])
        assert result.exit_code == 0


class TestErrors:
    def test_no_errors(self):
        result = runner.invoke(app, ["errors"])
        assert result.exit_code == 0
        assert "No recent errors" in result.output

    def test_errors_with_data(self, tmp_path):
        log = tmp_path / "test.log"
        log.write_text('{"level":"error","message":"crash"}\n')
        runner.invoke(app, ["register", "svc", "--log", str(log)])
        runner.invoke(app, ["ingest", "svc"])
        result = runner.invoke(app, ["errors", "--service", "svc", "--since", "60"])
        assert result.exit_code == 0
        assert "crash" in result.output


class TestIngest:
    def test_ingest_basic(self, tmp_path):
        log = tmp_path / "test.log"
        log.write_text("line1\nline2\n")
        runner.invoke(app, ["register", "svc", "--log", str(log)])
        result = runner.invoke(app, ["ingest", "svc"])
        assert result.exit_code == 0
        assert "Ingested" in result.output

    def test_ingest_missing_service(self):
        result = runner.invoke(app, ["ingest", "nope"])
        assert result.exit_code == 1

    def test_ingest_no_log_paths(self):
        runner.invoke(app, ["register", "svc"])
        result = runner.invoke(app, ["ingest", "svc"])
        assert result.exit_code == 1
