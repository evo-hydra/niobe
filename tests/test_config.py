"""Tests for NiobeConfig."""

import os
from pathlib import Path

from niobe.config import IngestionConfig, NiobeConfig, SnapshotConfig, StoreConfig


class TestDefaults:
    def test_store_defaults(self):
        c = StoreConfig()
        assert c.db_name == "niobe.db"

    def test_ingestion_defaults(self):
        c = IngestionConfig()
        assert c.tail_lines == 100
        assert c.max_line_length == 8192

    def test_snapshot_defaults(self):
        c = SnapshotConfig()
        assert c.error_window_minutes == 5
        assert c.cpu_sample_interval == 0.5


class TestNiobeConfig:
    def test_properties(self, tmp_path):
        config = NiobeConfig(project_path=tmp_path)
        assert config.niobe_dir == tmp_path / ".niobe"
        assert config.db_path == tmp_path / ".niobe" / "niobe.db"

    def test_load_defaults(self, tmp_path):
        config = NiobeConfig.load(tmp_path)
        assert config.store.db_name == "niobe.db"
        assert config.project_path == tmp_path

    def test_load_from_toml(self, tmp_path):
        niobe_dir = tmp_path / ".niobe"
        niobe_dir.mkdir()
        (niobe_dir / "config.toml").write_text(
            '[store]\ndb_name = "custom.db"\n'
            '[ingestion]\ntail_lines = 50\n'
        )
        config = NiobeConfig.load(tmp_path)
        assert config.store.db_name == "custom.db"
        assert config.ingestion.tail_lines == 50

    def test_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NIOBE_DB_NAME", "env.db")
        config = NiobeConfig.load(tmp_path)
        assert config.store.db_name == "env.db"

    def test_env_overrides_toml(self, tmp_path, monkeypatch):
        niobe_dir = tmp_path / ".niobe"
        niobe_dir.mkdir()
        (niobe_dir / "config.toml").write_text('[store]\ndb_name = "toml.db"\n')
        monkeypatch.setenv("NIOBE_DB_NAME", "env.db")
        config = NiobeConfig.load(tmp_path)
        assert config.store.db_name == "env.db"
