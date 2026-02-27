"""Enumerations for Niobe runtime models."""

from enum import Enum


class ServiceStatus(str, Enum):
    """Process status as observed by psutil."""

    RUNNING = "running"
    SLEEPING = "sleeping"
    STOPPED = "stopped"
    ZOMBIE = "zombie"
    DEAD = "dead"
    UNKNOWN = "unknown"


class LogLevel(str, Enum):
    """Normalised log severity levels."""

    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"
    UNKNOWN = "unknown"


class LogFormat(str, Enum):
    """Detected log line format."""

    JSON = "json"
    CLF = "clf"
    PYTHON = "python"
    RAW = "raw"
