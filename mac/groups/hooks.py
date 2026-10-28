"""`mac hooks` — the hook server's event log, session id, checkpoint and hook logs, wrapping claude-hooks' hooks__* handlers.

`session_id` and `checkpoint_query` call the hook server's HTTP port (8766)
and report an error when it is not running.
"""
import argparse

from mac.groups._backend import given
from mac.groups._hooks import call

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
