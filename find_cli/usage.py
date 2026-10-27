"""Per-command usage counts for find_cli results (task:c5a222dc).

    load(path=DB) -> {"mac <area> <verb>": {"count": int, "last_used": str | None}}

Reads the claude-hooks PostToolUse counters in ~/.claude/tool_hints.sqlite
(table mcp_tool_hints, keyed by the same `mac <area> <verb>` id as the graph's
command nodes). Read-only: the file is opened with mode=ro and never written.
A missing file, a missing table or any SQLite error gives {} so find_cli still
answers. FIND_CLI_USAGE_DB overrides the path.
"""
import os
import sqlite3
from pathlib import Path

DB = Path(os.environ.get("FIND_CLI_USAGE_DB",
                         Path.home() / ".claude" / "tool_hints.sqlite"))


def load(path=None):
    """{command id: {count, last_used}} for every `mac ...` row, or {}."""
    path = Path(path or DB)
    if not path.is_file():
        return {}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        try:
            rows = conn.execute(
                "SELECT tool_name, count, last_used FROM mcp_tool_hints "
                "WHERE tool_name LIKE 'mac %'").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return {}
    return {name: {"count": count or 0, "last_used": last_used}
            for name, count, last_used in rows}
