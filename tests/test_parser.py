"""Tests for log format detection and parsing."""

from niobe.core.parser import detect_format, parse_line
from niobe.models.enums import LogFormat


class TestDetectFormat:
    def test_json(self):
        assert detect_format('{"level": "info", "message": "hello"}') == LogFormat.JSON

    def test_clf(self):
        line = '127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /index.html HTTP/1.1" 200 2326'
        assert detect_format(line) == LogFormat.CLF

    def test_python(self):
        line = "2024-01-15 10:30:45,123 - myapp - INFO - Server started"
        assert detect_format(line) == LogFormat.PYTHON

    def test_raw(self):
        assert detect_format("just some random text") == LogFormat.RAW

    def test_empty(self):
        assert detect_format("") == LogFormat.RAW

    def test_invalid_json(self):
        assert detect_format("{not valid json") == LogFormat.RAW


class TestParseJsonLine:
    def test_basic(self):
        entry = parse_line(
            '{"level": "error", "message": "disk full", "timestamp": "2024-01-15T10:30:00"}',
            "svc", "app.log",
        )
        assert entry.level == "error"
        assert entry.message == "disk full"
        assert entry.timestamp is not None

    def test_alternate_keys(self):
        entry = parse_line(
            '{"severity": "WARN", "msg": "slow query"}',
            "svc", "app.log",
        )
        assert entry.level == "warning"
        assert entry.message == "slow query"

    def test_invalid_json_fallback(self):
        entry = parse_line("{broken", "svc", "app.log", format_hint=LogFormat.JSON)
        assert entry.level == "unknown"


class TestParseClfLine:
    def test_200(self):
        line = '127.0.0.1 - - [10/Oct/2000:13:55:36 -0700] "GET / HTTP/1.1" 200 2326'
        entry = parse_line(line, "web", "access.log")
        assert entry.level == "info"
        assert "200" in entry.message

    def test_404(self):
        line = '10.0.0.1 - - [10/Oct/2000:13:55:36 -0700] "GET /missing HTTP/1.1" 404 0'
        entry = parse_line(line, "web", "access.log")
        assert entry.level == "warning"

    def test_500(self):
        line = '10.0.0.1 - - [10/Oct/2000:13:55:36 -0700] "POST /api HTTP/1.1" 503 0'
        entry = parse_line(line, "web", "access.log")
        assert entry.level == "error"


class TestParsePythonLine:
    def test_basic(self):
        line = "2024-01-15 10:30:45,123 - myapp - ERROR - Something broke"
        entry = parse_line(line, "svc", "app.log")
        assert entry.level == "error"
        assert entry.message == "Something broke"
        assert entry.timestamp is not None


class TestParseRawLine:
    def test_raw(self):
        entry = parse_line("just text", "svc", "out.log")
        assert entry.level == "unknown"
        assert entry.message == "just text"
