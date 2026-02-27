"""SQLite store with WAL mode and FTS5 for log search."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from niobe.models import (
    HealthSnapshot,
    LogEntry,
    ProcessMetrics,
    ServiceInfo,
)

logger = logging.getLogger("niobe.store")

SCHEMA_VERSION = "1"

# Ordered list of migration functions keyed by target version.
# Each function receives a sqlite3.Connection and migrates from (version - 1).
_MIGRATIONS: dict[str, callable] = {}

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS niobe_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS services (
    name          TEXT PRIMARY KEY,
    pid           INTEGER,
    port          INTEGER,
    log_paths     TEXT NOT NULL DEFAULT '[]',
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id   TEXT PRIMARY KEY,
    service_name  TEXT NOT NULL REFERENCES services(name),
    snapshot_at   TEXT NOT NULL,
    metrics       TEXT,
    error_count   INTEGER NOT NULL DEFAULT 0,
    log_rate      REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_snapshots_service_time
    ON snapshots(service_name, snapshot_at);

CREATE TABLE IF NOT EXISTS log_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name  TEXT NOT NULL REFERENCES services(name),
    timestamp     TEXT,
    level         TEXT NOT NULL,
    message       TEXT NOT NULL DEFAULT '',
    source_file   TEXT NOT NULL DEFAULT '',
    raw_line      TEXT NOT NULL DEFAULT '',
    ingested_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_logs_service_time
    ON log_entries(service_name, timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_level
    ON log_entries(level);

CREATE VIRTUAL TABLE IF NOT EXISTS log_fts USING fts5(
    message,
    content='log_entries',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Auto-sync triggers for FTS5
CREATE TRIGGER IF NOT EXISTS log_fts_ai AFTER INSERT ON log_entries BEGIN
    INSERT INTO log_fts(rowid, message) VALUES (new.id, new.message);
END;
CREATE TRIGGER IF NOT EXISTS log_fts_ad AFTER DELETE ON log_entries BEGIN
    INSERT INTO log_fts(log_fts, rowid, message) VALUES ('delete', old.id, old.message);
END;
CREATE TRIGGER IF NOT EXISTS log_fts_au AFTER UPDATE ON log_entries BEGIN
    INSERT INTO log_fts(log_fts, rowid, message) VALUES ('delete', old.id, old.message);
    INSERT INTO log_fts(rowid, message) VALUES (new.id, new.message);
END;
"""


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_dt(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def _metrics_to_json(m: ProcessMetrics | None) -> str | None:
    if m is None:
        return None
    return json.dumps(
        {
            "pid": m.pid,
            "status": m.status,
            "cpu_percent": m.cpu_percent,
            "memory_mb": m.memory_mb,
            "num_threads": m.num_threads,
            "num_connections": m.num_connections,
            "captured_at": _iso(m.captured_at),
        }
    )


def _metrics_from_json(s: str | None) -> ProcessMetrics | None:
    if s is None:
        return None
    d = json.loads(s)
    return ProcessMetrics(
        pid=d["pid"],
        status=d["status"],
        cpu_percent=d["cpu_percent"],
        memory_mb=d["memory_mb"],
        num_threads=d["num_threads"],
        num_connections=d["num_connections"],
        captured_at=datetime.fromisoformat(d["captured_at"]),
    )


class NiobeStore:
    """SQLite-backed store for Niobe runtime data."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> NiobeStore:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def open(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA_SQL)
        self._ensure_schema_version()
        self._run_migrations()

    def _ensure_schema_version(self) -> None:
        """Set schema version on first run."""
        cur = self.conn.execute(
            "SELECT value FROM niobe_meta WHERE key='schema_version'"
        )
        if cur.fetchone() is None:
            self.conn.execute(
                "INSERT INTO niobe_meta(key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
            self.conn.commit()

    def _run_migrations(self) -> None:
        """Apply any pending migrations sequentially."""
        current = self.get_meta("schema_version") or "0"
        if current == SCHEMA_VERSION:
            return

        current_int = int(current)
        target_int = int(SCHEMA_VERSION)

        for version_num in range(current_int + 1, target_int + 1):
            version_key = str(version_num)
            migrate_fn = _MIGRATIONS.get(version_key)
            if migrate_fn is None:
                raise RuntimeError(
                    f"Missing migration for schema version {version_key}"
                )
            logger.info("Migrating store schema to version %s", version_key)
            migrate_fn(self.conn)
            self.conn.execute(
                "INSERT OR REPLACE INTO niobe_meta(key, value) VALUES ('schema_version', ?)",
                (version_key,),
            )
            self.conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Store is not open")
        return self._conn

    # --- Services ---

    def register_service(self, service: ServiceInfo) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO services(name, pid, port, log_paths, registered_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                service.name,
                service.pid,
                service.port,
                json.dumps(list(service.log_paths)),
                _iso(service.registered_at),
            ),
        )
        self.conn.commit()

    def unregister_service(self, name: str) -> bool:
        cur = self.conn.execute("DELETE FROM services WHERE name=?", (name,))
        self.conn.commit()
        return cur.rowcount > 0

    def get_service(self, name: str) -> ServiceInfo | None:
        cur = self.conn.execute("SELECT * FROM services WHERE name=?", (name,))
        row = cur.fetchone()
        if row is None:
            return None
        return ServiceInfo(
            name=row[0],
            pid=row[1],
            port=row[2],
            log_paths=tuple(json.loads(row[3])),
            registered_at=datetime.fromisoformat(row[4]),
        )

    def list_services(self) -> list[ServiceInfo]:
        cur = self.conn.execute("SELECT * FROM services ORDER BY name")
        return [
            ServiceInfo(
                name=r[0],
                pid=r[1],
                port=r[2],
                log_paths=tuple(json.loads(r[3])),
                registered_at=datetime.fromisoformat(r[4]),
            )
            for r in cur.fetchall()
        ]

    # --- Snapshots ---

    def save_snapshot(self, snap: HealthSnapshot) -> None:
        self.conn.execute(
            """INSERT INTO snapshots(snapshot_id, service_name, snapshot_at, metrics, error_count, log_rate)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                snap.snapshot_id,
                snap.service_name,
                _iso(snap.snapshot_at),
                _metrics_to_json(snap.metrics),
                snap.error_count,
                snap.log_rate,
            ),
        )
        self.conn.commit()

    def get_snapshot(self, snapshot_id: str) -> HealthSnapshot | None:
        # Support prefix match (8+ chars)
        cur = self.conn.execute(
            "SELECT * FROM snapshots WHERE snapshot_id LIKE ? ORDER BY snapshot_at DESC LIMIT 1",
            (snapshot_id + "%",),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return HealthSnapshot(
            snapshot_id=row[0],
            service_name=row[1],
            snapshot_at=datetime.fromisoformat(row[2]),
            metrics=_metrics_from_json(row[3]),
            error_count=row[4],
            log_rate=row[5],
        )

    def list_snapshots(
        self, service_name: str | None = None, limit: int = 20
    ) -> list[HealthSnapshot]:
        if service_name:
            cur = self.conn.execute(
                "SELECT * FROM snapshots WHERE service_name=? ORDER BY snapshot_at DESC LIMIT ?",
                (service_name, limit),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM snapshots ORDER BY snapshot_at DESC LIMIT ?",
                (limit,),
            )
        return [
            HealthSnapshot(
                snapshot_id=r[0],
                service_name=r[1],
                snapshot_at=datetime.fromisoformat(r[2]),
                metrics=_metrics_from_json(r[3]),
                error_count=r[4],
                log_rate=r[5],
            )
            for r in cur.fetchall()
        ]

    # --- Logs ---

    def insert_log_entries(self, entries: list[LogEntry]) -> int:
        if not entries:
            return 0
        self.conn.executemany(
            """INSERT INTO log_entries(service_name, timestamp, level, message, source_file, raw_line, ingested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    e.service_name,
                    _iso(e.timestamp) if e.timestamp else None,
                    e.level,
                    e.message,
                    e.source_file,
                    e.raw_line,
                    _iso(e.ingested_at),
                )
                for e in entries
            ],
        )
        self.conn.commit()
        return len(entries)

    def search_logs(
        self,
        query: str,
        service_name: str | None = None,
        level: str | None = None,
        limit: int = 50,
    ) -> list[LogEntry]:
        # FTS5 MATCH query joined back to log_entries
        sql = """
            SELECT le.service_name, le.timestamp, le.level, le.message,
                   le.source_file, le.raw_line, le.ingested_at
            FROM log_fts
            JOIN log_entries le ON le.id = log_fts.rowid
            WHERE log_fts MATCH ?
        """
        params: list = [query]
        if service_name:
            sql += " AND le.service_name = ?"
            params.append(service_name)
        if level:
            sql += " AND le.level = ?"
            params.append(level)
        sql += " ORDER BY le.ingested_at DESC LIMIT ?"
        params.append(limit)

        cur = self.conn.execute(sql, params)
        return [
            LogEntry(
                service_name=r[0],
                timestamp=_parse_dt(r[1]),
                level=r[2],
                message=r[3],
                source_file=r[4],
                raw_line=r[5],
                ingested_at=datetime.fromisoformat(r[6]),
            )
            for r in cur.fetchall()
        ]

    def recent_errors(
        self,
        service_name: str | None = None,
        since_minutes: int = 5,
        limit: int = 50,
    ) -> list[LogEntry]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

        sql = """
            SELECT service_name, timestamp, level, message,
                   source_file, raw_line, ingested_at
            FROM log_entries
            WHERE level IN ('critical', 'error')
              AND ingested_at >= ?
        """
        params: list = [_iso(cutoff)]
        if service_name:
            sql += " AND service_name = ?"
            params.append(service_name)
        sql += " ORDER BY ingested_at DESC LIMIT ?"
        params.append(limit)

        cur = self.conn.execute(sql, params)
        return [
            LogEntry(
                service_name=r[0],
                timestamp=_parse_dt(r[1]),
                level=r[2],
                message=r[3],
                source_file=r[4],
                raw_line=r[5],
                ingested_at=datetime.fromisoformat(r[6]),
            )
            for r in cur.fetchall()
        ]

    def count_errors_since(
        self, service_name: str, since: datetime
    ) -> int:
        """Count error/critical log entries since a given time."""
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE service_name=? AND level IN ('critical','error') AND ingested_at>=?",
            (service_name, _iso(since)),
        )
        return cur.fetchone()[0]

    def count_logs_since(
        self, service_name: str, since: datetime
    ) -> int:
        """Count all log entries since a given time."""
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM log_entries WHERE service_name=? AND ingested_at>=?",
            (service_name, _iso(since)),
        )
        return cur.fetchone()[0]

    # --- Meta ---

    def get_meta(self, key: str) -> str | None:
        cur = self.conn.execute(
            "SELECT value FROM niobe_meta WHERE key=?", (key,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO niobe_meta(key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()
