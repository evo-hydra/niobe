# Niobe

Runtime intelligence for AI agents — local-first runtime observation via MCP.

Niobe answers: **"What is the system doing right now, and did my change make it worse?"**

Take snapshot A → deploy → snapshot B → diff. That's it.

## Install

```bash
pip install niobe
```

With MCP server support:
```bash
pip install niobe[mcp]
```

## Quick Start

```bash
# Register a service
niobe register myapp --port 8080 --log /var/log/myapp.log

# Take a snapshot (captures metrics + ingests logs)
niobe snapshot myapp

# Make a change, then snapshot again
niobe snapshot myapp

# Compare before/after
niobe compare <snapshot-id-1> <snapshot-id-2>

# Search logs
niobe logs --query "connection refused"

# View recent errors
niobe errors --service myapp --since 10
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `niobe register <name> [--pid N] [--port N] [--log PATH...]` | Register a service for observation |
| `niobe unregister <name>` | Remove a service |
| `niobe services` | List registered services |
| `niobe snapshot [service]` | Take health snapshot (one or all) |
| `niobe compare <id_a> <id_b>` | Diff two snapshots |
| `niobe logs [--query Q] [--service S] [--level L]` | Search log entries |
| `niobe errors [--service S] [--since N]` | Recent errors |
| `niobe ingest <service> [--follow]` | Ingest log files |

## MCP Tools

Niobe exposes 5 tools via [Model Context Protocol](https://modelcontextprotocol.io):

| Tool | Description |
|------|-------------|
| `niobe_register` | Register a service for observation |
| `niobe_snapshot` | Take health snapshot (one or all services) |
| `niobe_compare` | Compare two snapshots (before/after diff) |
| `niobe_errors` | Get recent errors from logs |
| `niobe_logs` | Full-text search across ingested logs |

### Claude Code Integration

Add to `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "niobe": {
      "command": "niobe-mcp",
      "args": []
    }
  }
}
```

Then in Claude Code:
- "Register my web server on port 3000" → `niobe_register`
- "How's my app doing?" → `niobe_snapshot`
- "Did my last deploy break anything?" → `niobe_compare`
- "Show me recent errors" → `niobe_errors`
- "Search logs for timeout" → `niobe_logs`

## Log Format Support

Niobe auto-detects log formats:

- **JSON** — `{"level": "error", "message": "...", "timestamp": "..."}`
- **CLF** — Apache/NGINX common log format (HTTP status mapped to levels)
- **Python** — `2024-01-15 10:30:45,123 - myapp - ERROR - message`
- **RAW** — Everything else (stored as-is with level=unknown)

## Configuration

Optional. Create `.niobe/config.toml` in your project root:

```toml
[store]
db_name = "niobe.db"

[ingestion]
tail_lines = 100
max_line_length = 8192

[snapshot]
error_window_minutes = 5
cpu_sample_interval = 0.5

[mcp]
default_error_since_minutes = 5
default_query_limit = 50
```

All values can be overridden with `NIOBE_*` environment variables.

## Architecture

- **SQLite + WAL** — single-file store, concurrent-read safe
- **FTS5** — full-text search across log messages with porter stemming
- **psutil** — process metrics (CPU, memory, threads, connections)
- **Frozen dataclasses** — immutable models, no Pydantic dependency
- **Snapshot-based** — no background monitoring, entirely on-demand

## Part of the EvoIntel Stack

Niobe is Phase 2, after [Seraph](https://pypi.org/project/seraph-reader/), [Sentinel](https://pypi.org/project/sentinel-scanner/), and [Anno](https://github.com/evo-hydra/anno).

## License

MIT
