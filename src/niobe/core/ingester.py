"""Log file tailing and ingestion."""

from __future__ import annotations

import logging
from collections.abc import Generator
from pathlib import Path

from niobe.config import IngestionConfig
from niobe.core.parser import detect_format, parse_line
from niobe.core.store import NiobeStore

logger = logging.getLogger("niobe.ingester")


def _tail_file(path: Path, num_lines: int, max_line_length: int) -> list[str]:
    """Read the last N lines from a file efficiently."""
    try:
        with open(path, "rb") as f:
            # Seek from end to find enough newlines
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return []

            # Read in chunks from the end
            chunk_size = min(max_line_length * num_lines, size)
            f.seek(max(0, size - chunk_size))
            data = f.read().decode("utf-8", errors="replace")

            lines = data.splitlines()
            # Take last num_lines, skip partial first line if we didn't start at 0
            if size > chunk_size and lines:
                lines = lines[1:]  # Drop potentially partial first line
            lines = lines[-num_lines:]

            # Enforce max line length
            return [line[:max_line_length] for line in lines]
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return []


def ingest_once(
    store: NiobeStore,
    service_name: str,
    log_paths: tuple[str, ...] | list[str],
    config: IngestionConfig | None = None,
) -> int:
    """Tail log files and ingest entries. Returns total count ingested."""
    if config is None:
        config = IngestionConfig()

    total = 0
    for path_str in log_paths:
        path = Path(path_str)
        if not path.is_file():
            logger.warning("Log file not found: %s", path)
            continue

        lines = _tail_file(path, config.tail_lines, config.max_line_length)
        if not lines:
            continue

        # Detect format on first non-empty line
        fmt = None
        for line in lines:
            if line.strip():
                fmt = detect_format(line)
                break

        entries = [
            parse_line(line, service_name, str(path), format_hint=fmt)
            for line in lines
            if line.strip()
        ]

        count = store.insert_log_entries(entries)
        total += count
        logger.debug("Ingested %d entries from %s", count, path)

    return total


def ingest_follow(
    store: NiobeStore,
    service_name: str,
    log_paths: tuple[str, ...] | list[str],
    config: IngestionConfig | None = None,
) -> Generator[int, None, None]:
    """Watch log files for changes and ingest continuously. Requires watchfiles."""
    try:
        from watchfiles import watch
    except ImportError:
        raise ImportError(
            "watchfiles is required for follow mode. Install with: pip install niobe[watch]"
        )

    if config is None:
        config = IngestionConfig()

    resolved = [Path(p) for p in log_paths if Path(p).is_file()]
    if not resolved:
        return

    # Track file positions
    positions: dict[Path, int] = {}
    for p in resolved:
        positions[p] = p.stat().st_size

    dirs = {p.parent for p in resolved}
    for changes in watch(*dirs):
        for _change_type, changed_path in changes:
            changed = Path(changed_path)
            if changed not in positions:
                continue

            try:
                current_size = changed.stat().st_size
            except OSError:
                continue

            last_pos = positions[changed]
            if current_size <= last_pos:
                continue

            with open(changed, "r", errors="replace") as f:
                f.seek(last_pos)
                new_lines = f.readlines()

            positions[changed] = current_size

            fmt = None
            for line in new_lines:
                if line.strip():
                    fmt = detect_format(line)
                    break

            entries = [
                parse_line(line, service_name, str(changed), format_hint=fmt)
                for line in new_lines
                if line.strip()
            ]

            count = store.insert_log_entries(entries)
            yield count
