"""Layered configuration: .niobe/config.toml -> NIOBE_* env vars -> defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import logging
from typing import TypeVar

try:
    import tomllib  # 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

logger = logging.getLogger(__name__)
T = TypeVar("T", int, float)


def _safe_numeric(value: object, type_fn: type[T], env_name: str, default: T) -> T:
    """Convert a config value to int or float, falling back to default on error."""
    try:
        return type_fn(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        logger.warning(
            "Invalid value for %s: %r (expected %s, using default %s)",
            env_name, value, type_fn.__name__, default,
        )
        return default


@dataclass(frozen=True, slots=True)
class StoreConfig:
    """SQLite store settings."""

    db_name: str = "niobe.db"


@dataclass(frozen=True, slots=True)
class IngestionConfig:
    """Log ingestion settings."""

    tail_lines: int = 100
    max_line_length: int = 8192


@dataclass(frozen=True, slots=True)
class SnapshotConfig:
    """Snapshot capture settings."""

    error_window_minutes: int = 5
    cpu_sample_interval: float = 0.5


@dataclass(frozen=True, slots=True)
class McpConfig:
    """Defaults for MCP tool parameters."""

    default_error_since_minutes: int = 5
    default_anomaly_since_minutes: int = 30
    default_query_limit: int = 50


@dataclass(frozen=True, slots=True)
class NiobeConfig:
    """Top-level configuration container."""

    project_path: Path = field(default_factory=Path.cwd)
    store: StoreConfig = field(default_factory=StoreConfig)
    ingestion: IngestionConfig = field(default_factory=IngestionConfig)
    snapshot: SnapshotConfig = field(default_factory=SnapshotConfig)
    mcp: McpConfig = field(default_factory=McpConfig)

    @property
    def niobe_dir(self) -> Path:
        return self.project_path / ".niobe"

    @property
    def db_path(self) -> Path:
        return self.niobe_dir / self.store.db_name

    @classmethod
    def load(cls, project_path: Path | None = None) -> NiobeConfig:
        """Load config with layering: TOML file -> env vars -> defaults."""
        project = Path(project_path) if project_path else Path.cwd()
        toml_path = project / ".niobe" / "config.toml"

        toml_data: dict = {}
        if toml_path.is_file():
            with open(toml_path, "rb") as f:
                toml_data = tomllib.load(f)

        store_data = toml_data.get("store", {})
        ingestion_data = toml_data.get("ingestion", {})
        snapshot_data = toml_data.get("snapshot", {})

        mcp_data = toml_data.get("mcp", {})

        # Use literal defaults (slots=True prevents class-level attribute access)
        _store_defaults = StoreConfig()
        _ingest_defaults = IngestionConfig()
        _snap_defaults = SnapshotConfig()
        _mcp_defaults = McpConfig()

        store = StoreConfig(
            db_name=os.environ.get(
                "NIOBE_DB_NAME",
                store_data.get("db_name", _store_defaults.db_name),
            ),
        )

        ingestion = IngestionConfig(
            tail_lines=_safe_numeric(
                os.environ.get(
                    "NIOBE_TAIL_LINES",
                    ingestion_data.get("tail_lines", _ingest_defaults.tail_lines),
                ),
                int, "NIOBE_TAIL_LINES", _ingest_defaults.tail_lines,
            ),
            max_line_length=_safe_numeric(
                os.environ.get(
                    "NIOBE_MAX_LINE_LENGTH",
                    ingestion_data.get(
                        "max_line_length", _ingest_defaults.max_line_length
                    ),
                ),
                int, "NIOBE_MAX_LINE_LENGTH", _ingest_defaults.max_line_length,
            ),
        )

        snapshot = SnapshotConfig(
            error_window_minutes=_safe_numeric(
                os.environ.get(
                    "NIOBE_ERROR_WINDOW_MINUTES",
                    snapshot_data.get(
                        "error_window_minutes",
                        _snap_defaults.error_window_minutes,
                    ),
                ),
                int, "NIOBE_ERROR_WINDOW_MINUTES", _snap_defaults.error_window_minutes,
            ),
            cpu_sample_interval=_safe_numeric(
                os.environ.get(
                    "NIOBE_CPU_SAMPLE_INTERVAL",
                    snapshot_data.get(
                        "cpu_sample_interval",
                        _snap_defaults.cpu_sample_interval,
                    ),
                ),
                float, "NIOBE_CPU_SAMPLE_INTERVAL", _snap_defaults.cpu_sample_interval,
            ),
        )

        mcp = McpConfig(
            default_error_since_minutes=_safe_numeric(
                os.environ.get(
                    "NIOBE_DEFAULT_ERROR_SINCE_MINUTES",
                    mcp_data.get(
                        "default_error_since_minutes",
                        _mcp_defaults.default_error_since_minutes,
                    ),
                ),
                int, "NIOBE_DEFAULT_ERROR_SINCE_MINUTES", _mcp_defaults.default_error_since_minutes,
            ),
            default_anomaly_since_minutes=_safe_numeric(
                os.environ.get(
                    "NIOBE_DEFAULT_ANOMALY_SINCE_MINUTES",
                    mcp_data.get(
                        "default_anomaly_since_minutes",
                        _mcp_defaults.default_anomaly_since_minutes,
                    ),
                ),
                int, "NIOBE_DEFAULT_ANOMALY_SINCE_MINUTES", _mcp_defaults.default_anomaly_since_minutes,
            ),
            default_query_limit=_safe_numeric(
                os.environ.get(
                    "NIOBE_DEFAULT_QUERY_LIMIT",
                    mcp_data.get(
                        "default_query_limit",
                        _mcp_defaults.default_query_limit,
                    ),
                ),
                int, "NIOBE_DEFAULT_QUERY_LIMIT", _mcp_defaults.default_query_limit,
            ),
        )

        return cls(
            project_path=project,
            store=store,
            ingestion=ingestion,
            snapshot=snapshot,
            mcp=mcp,
        )
