"""`mac hooks` — the hook server's event log, session id, checkpoint and hook logs, wrapping claude-hooks' hooks__* handlers.

`last_response` reads the file claude-hooks' Stop hook overwrites after every
response (~/.claude/last_response.md; CLAUDE_LAST_RESPONSE overrides).
`session_id` and `checkpoint_query` call the hook server's HTTP port (8766)
and report an error when it is not running.
"""
import argparse
import os
from datetime import datetime
from pathlib import Path

from mac.groups._backend import given
from mac.groups._hooks import call, text_or_file
from mac.contract import Failure

UNSET = argparse.SUPPRESS


def register(registry):
    @registry.verb("hooks", "server_memory", mode="read",
                   desc="recent session activity: the last prompts, tool calls and task activations across sessions",
                   args=lambda p: p.add_argument("--n-events", dest="n_events", type=int, default=UNSET))
    def server_memory(ns):
        return call("hooks", "server_memory", **given(ns, ("n_events",)))

    @registry.verb("hooks", "session_id", mode="read", desc="the current session's id and turn")
    def session_id(ns):
        return call("hooks", "session_id")

    @registry.verb("hooks", "checkpoint_query", mode="read",
                   desc="the live checkpoint for a session: injected memories, tool hints, context, keywords",
                   args=lambda p: p.add_argument("--thread-id", dest="thread_id", default=UNSET,
                                                 help="session id (default: the current session)"))
    def checkpoint_query(ns):
        return call("hooks", "checkpoint_query", **given(ns, ("thread_id",)))

    def logs_args(p):
        p.add_argument("--level", default=UNSET, help="INFO, WARNING, ERROR ...")
        p.add_argument("--logger", default=UNSET, help="logger name substring")
        p.add_argument("--search", default=UNSET, help="substring of the message")
        p.add_argument("--format", default=UNSET, choices=("toon", "json"))

    @registry.verb("hooks", "read_logs_sqlite", mode="read",
                   desc="query the hook server's log table by level, logger or message text", args=logs_args)
    def read_logs_sqlite(ns):
        return call("hooks", "read_logs_sqlite", **given(ns, ("level", "logger", "search", "limit", "format")))

    @registry.verb("hooks", "last_response", mode="read",
                   desc="the last assistant reply, saved by the Stop hook and overwritten each turn")
    def last_response(ns):
        path = Path(os.environ.get("CLAUDE_LAST_RESPONSE") or "~/.claude/last_response.md").expanduser()
        try:
            text = path.read_text()
        except OSError:
            raise Failure("not_found", f"no saved response at {path} (the Stop hook writes it)")
        return {"path": str(path), "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"), "text": text.rstrip("\n")}


    # WebSearch result cache (claude-hooks src/tools/web_search_cache.py, SQLite).
    # The PostToolUse hook stores every WebSearch; the PreToolUse hook serves fresh hits.
    @registry.verb("hooks", "web_search_get", mode="read",
                   desc="a cached WebSearch result for a query (hit or miss, with its age); --allow-stale also returns an expired one",
                   args=lambda p: (p.add_argument("query"),
                                   p.add_argument("--mode", default=UNSET, choices=("standard", "extended")),
                                   p.add_argument("--allow-stale", dest="allow_stale", action="store_true", default=UNSET)))
    def web_search_get(ns):
        return call("web_search_cache", "get", query=ns.query, **given(ns, ("mode", "allow_stale")))

    @registry.verb("hooks", "web_search_find", mode="read",
                   desc="stored WebSearch queries or results containing a text, newest first, fresh or not",
                   args=lambda p: p.add_argument("text"))
    def web_search_find(ns):
        return call("web_search_cache", "find", text=ns.text, **given(ns, ("limit",)))

    @registry.verb("hooks", "web_search_stats", mode="read",
                   desc="WebSearch cache row counts: total, fresh, stale and hits served")
    def web_search_stats(ns):
        return call("web_search_cache", "stats")

    def put_args(p):
        p.add_argument("query")
        p.add_argument("--result", default=None, help="the result text")
        p.add_argument("--result-file", dest="result_file", default=None, help="read the result from PATH (- for stdin)")
        p.add_argument("--mode", default=UNSET, choices=("standard", "extended"))
        p.add_argument("--ttl-s", dest="ttl_s", type=int, default=UNSET, help="override the TTL rule, in seconds")

    @registry.verb("hooks", "web_search_put", mode="write",
                   desc="store a WebSearch result under a query (the hook does this automatically; use for results found another way)",
                   args=put_args)
    def web_search_put(ns):
        text_or_file(ns, "result", "--result", required=True)
        return call("web_search_cache", "put", query=ns.query, result=ns.result, **given(ns, ("mode", "ttl_s")))

    @registry.verb("hooks", "web_search_purge", mode="write",
                   desc="delete cached WebSearch rows older than --days (0 clears the cache)",
                   args=lambda p: p.add_argument("--days", type=float, required=True))
    def web_search_purge(ns):
        return call("web_search_cache", "purge", days=ns.days)
