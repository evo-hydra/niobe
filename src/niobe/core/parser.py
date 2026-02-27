"""Log format detection and parsing for JSON, CLF, Python, and RAW formats."""

from __future__ import annotations

import json
import re
from datetime import datetime

from niobe.models.enums import LogFormat, LogLevel
from niobe.models.runtime import LogEntry

# CLF: 127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.1" 200 2326
_CLF_RE = re.compile(
    r'^(?P<host>\S+)\s+\S+\s+\S+\s+'
    r'\[(?P<time>[^\]]+)\]\s+'
    r'"(?P<request>[^"]*)"\s+'
    r'(?P<status>\d{3})\s+'
    r'(?P<size>\S+)'
)

# Python logging: 2024-01-15 10:30:45,123 - name - LEVEL - message
_PYTHON_RE = re.compile(
    r'^(?P<time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,.\d]*)\s+'
    r'(?:-\s+\S+\s+)?-?\s*'
    r'(?P<level>[A-Z]+)\s+'
    r'(?:-\s+)?(?P<message>.*)'
)

_LEVEL_MAP: dict[str, str] = {
    "critical": LogLevel.CRITICAL.value,
    "fatal": LogLevel.CRITICAL.value,
    "error": LogLevel.ERROR.value,
    "err": LogLevel.ERROR.value,
    "warning": LogLevel.WARNING.value,
    "warn": LogLevel.WARNING.value,
    "info": LogLevel.INFO.value,
    "debug": LogLevel.DEBUG.value,
    "trace": LogLevel.DEBUG.value,
}


def _normalize_level(raw: str) -> str:
    """Normalize a level string to a LogLevel value."""
    return _LEVEL_MAP.get(raw.lower().strip(), LogLevel.UNKNOWN.value)


def detect_format(line: str) -> LogFormat:
    """Detect the log format of a single line."""
    stripped = line.strip()
    if not stripped:
        return LogFormat.RAW

    if stripped.startswith("{"):
        try:
            json.loads(stripped)
            return LogFormat.JSON
        except (json.JSONDecodeError, ValueError):
            pass

    if _CLF_RE.match(stripped):
        return LogFormat.CLF

    if _PYTHON_RE.match(stripped):
        return LogFormat.PYTHON

    return LogFormat.RAW


def parse_line(
    line: str,
    service_name: str,
    source_file: str,
    format_hint: LogFormat | None = None,
) -> LogEntry:
    """Parse a log line into a LogEntry, auto-detecting format if no hint given."""
    fmt = format_hint or detect_format(line)

    if fmt == LogFormat.JSON:
        return _parse_json_line(line, service_name, source_file)
    if fmt == LogFormat.CLF:
        return _parse_clf_line(line, service_name, source_file)
    if fmt == LogFormat.PYTHON:
        return _parse_python_line(line, service_name, source_file)
    return _parse_raw_line(line, service_name, source_file)


def _parse_json_line(line: str, service_name: str, source_file: str) -> LogEntry:
    try:
        data = json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return _parse_raw_line(line, service_name, source_file)

    level_raw = data.get("level") or data.get("severity") or "unknown"
    message = data.get("message") or data.get("msg") or ""

    timestamp = None
    for key in ("timestamp", "time", "ts", "@timestamp"):
        if key in data:
            try:
                timestamp = datetime.fromisoformat(str(data[key]))
            except (ValueError, TypeError):
                pass
            break

    return LogEntry(
        service_name=service_name,
        level=_normalize_level(str(level_raw)),
        message=str(message),
        source_file=source_file,
        raw_line=line.rstrip("\n"),
        timestamp=timestamp,
    )


def _parse_clf_line(line: str, service_name: str, source_file: str) -> LogEntry:
    m = _CLF_RE.match(line.strip())
    if not m:
        return _parse_raw_line(line, service_name, source_file)

    status = int(m.group("status"))
    if status >= 500:
        level = LogLevel.ERROR.value
    elif status >= 400:
        level = LogLevel.WARNING.value
    else:
        level = LogLevel.INFO.value

    timestamp = None
    try:
        # CLF time: 10/Oct/2000:13:55:36 -0700
        timestamp = datetime.strptime(m.group("time"), "%d/%b/%Y:%H:%M:%S %z")
    except (ValueError, TypeError):
        pass

    request = m.group("request")
    message = f"{request} -> {status}"

    return LogEntry(
        service_name=service_name,
        level=level,
        message=message,
        source_file=source_file,
        raw_line=line.rstrip("\n"),
        timestamp=timestamp,
    )


def _parse_python_line(line: str, service_name: str, source_file: str) -> LogEntry:
    m = _PYTHON_RE.match(line.strip())
    if not m:
        return _parse_raw_line(line, service_name, source_file)

    timestamp = None
    try:
        time_str = m.group("time").replace(",", ".")
        timestamp = datetime.fromisoformat(time_str)
    except (ValueError, TypeError):
        pass

    return LogEntry(
        service_name=service_name,
        level=_normalize_level(m.group("level")),
        message=m.group("message").strip(),
        source_file=source_file,
        raw_line=line.rstrip("\n"),
        timestamp=timestamp,
    )


def _parse_raw_line(line: str, service_name: str, source_file: str) -> LogEntry:
    return LogEntry(
        service_name=service_name,
        level=LogLevel.UNKNOWN.value,
        message=line.strip(),
        source_file=source_file,
        raw_line=line.rstrip("\n"),
    )
