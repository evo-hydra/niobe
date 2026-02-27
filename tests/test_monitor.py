"""Tests for process metrics capture (mocked psutil)."""

from unittest.mock import MagicMock, patch

import psutil
import pytest

from niobe.core.monitor import _find_pid_by_port, _map_status, capture_metrics
from niobe.models.enums import ServiceStatus
from niobe.models.runtime import ServiceInfo


class TestMapStatus:
    def test_known(self):
        assert _map_status(psutil.STATUS_RUNNING) == ServiceStatus.RUNNING.value
        assert _map_status(psutil.STATUS_SLEEPING) == ServiceStatus.SLEEPING.value

    def test_unknown(self):
        assert _map_status("something_weird") == ServiceStatus.UNKNOWN.value


class TestCaptureMetrics:
    @patch("niobe.core.monitor.psutil.Process")
    def test_success(self, mock_proc_cls):
        proc = MagicMock()
        proc.cpu_percent.return_value = 5.5
        proc.memory_info.return_value = MagicMock(rss=100 * 1024 * 1024)
        proc.status.return_value = psutil.STATUS_RUNNING
        proc.num_threads.return_value = 4
        proc.net_connections.return_value = [MagicMock(), MagicMock()]
        mock_proc_cls.return_value = proc

        svc = ServiceInfo(name="test", pid=123)
        m = capture_metrics(svc, cpu_interval=0.0)

        assert m is not None
        assert m.pid == 123
        assert m.cpu_percent == 5.5
        assert m.memory_mb == 100.0
        assert m.num_threads == 4
        assert m.num_connections == 2

    @patch("niobe.core.monitor.psutil.Process")
    def test_no_such_process(self, mock_proc_cls):
        mock_proc_cls.side_effect = psutil.NoSuchProcess(999)
        svc = ServiceInfo(name="test", pid=999)
        assert capture_metrics(svc) is None

    @patch("niobe.core.monitor.psutil.Process")
    def test_access_denied(self, mock_proc_cls):
        mock_proc_cls.side_effect = psutil.AccessDenied(1)
        svc = ServiceInfo(name="test", pid=1)
        assert capture_metrics(svc) is None

    def test_no_pid_no_port(self):
        svc = ServiceInfo(name="test")
        assert capture_metrics(svc) is None

    @patch("niobe.core.monitor._find_pid_by_port")
    @patch("niobe.core.monitor.psutil.Process")
    def test_resolve_by_port(self, mock_proc_cls, mock_find):
        mock_find.return_value = 456
        proc = MagicMock()
        proc.cpu_percent.return_value = 0.0
        proc.memory_info.return_value = MagicMock(rss=50 * 1024 * 1024)
        proc.status.return_value = psutil.STATUS_SLEEPING
        proc.num_threads.return_value = 1
        proc.net_connections.return_value = []
        mock_proc_cls.return_value = proc

        svc = ServiceInfo(name="test", port=8080)
        m = capture_metrics(svc, cpu_interval=0.0)
        assert m is not None
        assert m.pid == 456


class TestFindPidByPort:
    @patch("niobe.core.monitor.psutil.net_connections")
    def test_found(self, mock_conns):
        conn = MagicMock()
        conn.laddr = MagicMock(port=8080)
        conn.pid = 789
        mock_conns.return_value = [conn]
        assert _find_pid_by_port(8080) == 789

    @patch("niobe.core.monitor.psutil.net_connections")
    def test_not_found(self, mock_conns):
        mock_conns.return_value = []
        assert _find_pid_by_port(9999) is None
