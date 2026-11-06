"""`mac cli_log` — when each `mac` verb ran, with what arguments and outcome.

Reads mcp_tool_calls in local-mac's tool_hints.sqlite, the one call log: local-mac's
dispatcher writes a row for every verb routed through it, and mac.cli._run
writes one for every other verb (task:80010ea1). Times are shown in local time;
the table stores UTC. Rows from before 2026-11-06 have no result_id or session_id.
"""
import argparse
import sqlite3

from mac.contract import Failure
from mac.groups import _backend

UNSET = argparse.SUPPRESS
_COLUMNS = ("id, datetime(ts, 'localtime') AS ts, domain AS area, action AS verb, args_json AS args,"
            " ok, error, blocked, duration_ms, result_id, session_id")


def _query(where, params, limit):
    path = _backend.tool_hooks().db_path()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise Failure("tool_error", f"cannot open call log {path}: {exc}")
    conn.row_factory = sqlite3.Row
    with conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(mcp_tool_calls)")}
        select = _COLUMNS if "result_id" in columns else _COLUMNS.rsplit(", result_id", 1)[0]
        rows = conn.execute(f"SELECT {select} FROM mcp_tool_calls WHERE {where} ORDER BY id DESC LIMIT ?",
                            (*params, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def register(registry):
    def recent_args(p):
        p.add_argument("--days", type=int, default=1, help="1 = today only, since local midnight (default)")
        p.add_argument("--area", default=UNSET, help="only this area, e.g. reminders")
        p.add_argument("--verb", default=UNSET, help="only this verb, e.g. create")

    @registry.verb("cli_log", "recent", mode="read",
                   desc="mac verb calls today or in the last N days: time, area, verb, args, outcome, result id",
                   args=recent_args)
    def recent(ns):
        if ns.days < 1:
            raise Failure("usage", "--days must be at least 1")
        where = ["ts >= datetime('now', 'localtime', 'start of day', ?, 'utc')"]
        params = [f"-{ns.days - 1} days"]
        for flag, column in (("area", "domain"), ("verb", "action")):
            if hasattr(ns, flag):
                where.append(f"{column} = ?")
                params.append(getattr(ns, flag))
        return _query(" AND ".join(where), params, ns.limit or 100)

    @registry.verb("cli_log", "history", mode="read",
                   desc="every logged call that acted on one object id (e.g. a reminder's create, update, delete)",
                   args=lambda p: p.add_argument("id", help="object id, e.g. x-apple-reminder://..."))
    def history(ns):
        return list(reversed(_query("result_id = ?", [ns.id], ns.limit or 100)))
