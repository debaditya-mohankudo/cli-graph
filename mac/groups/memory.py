"""`mac memory` — the persistent memory store (~/.claude/MEMORY.sqlite), wrapping claude-hooks' memory__* handlers.

Optional flags default to argparse.SUPPRESS and are forwarded with given(), so
an omitted flag is never sent and the handler's own default applies. Pass
`related` on every re-add: omitting it resets the column to empty, exactly as
with the MCP tool.

`--links` takes a JSON list of {"to": slug, "type": link_type} objects and `add_batch`
takes a JSON list of memory objects, inline or from a file (`-` for stdin).
"""
import argparse
import json

from mac.cli import json_list
from mac.contract import EXIT_USAGE, Failure
from mac.groups._backend import given
from mac.groups._hooks import call, text_or_file

UNSET = argparse.SUPPRESS
TYPES = ("user", "feedback", "project", "reference")


def register(registry):
    def add_args(p):
        p.add_argument("name", help="unique kebab-case slug; an existing entry is overwritten")
        p.add_argument("--type", required=True, choices=TYPES)
        p.add_argument("--body", default=None, help="memory text")
        p.add_argument("--body-file", default=None, metavar="PATH", help="read the body from PATH ('-' for stdin)")
        p.add_argument("--tags", default=UNSET, help="comma-separated retrieval keywords")
        p.add_argument("--files", default=UNSET, help="comma-separated source file paths")
        p.add_argument("--docs", default=UNSET, help="comma-separated vault doc paths")
        p.add_argument("--related", default=UNSET, help="comma-separated related memory slugs")
        p.add_argument("--links", default=UNSET, type=json_list,
                       help='JSON list of typed links, e.g. \'[{"to":"slug","type":"relates_to"}]\'')

    @registry.verb("memory", "add", mode="write",
                   desc="insert or update a memory (name, type, body, tags, related, typed links)", args=add_args)
    def add(ns):
        text_or_file(ns, "body", "--body", required=True)
        return call("memory", "add", **given(ns, ("name", "type", "body", "tags", "files", "docs",
                                                  "related", "links")))

    def add_batch_args(p):
        p.add_argument("--memories", default=None, help="JSON list of memory objects")
        p.add_argument("--memories-file", default=None, metavar="PATH",
                       help="read the JSON list from PATH ('-' for stdin)")

    @registry.verb("memory", "add_batch", mode="write",
                   desc="insert or update several memories in one call; each object has name, type, body, tags, links",
                   args=add_batch_args)
    def add_batch(ns):
        text_or_file(ns, "memories", "--memories", required=True)
        try:
            memories = json.loads(ns.memories)
        except json.JSONDecodeError as exc:
            raise Failure("usage", f"--memories is not valid JSON: {exc}", EXIT_USAGE)
        if not isinstance(memories, list):
            raise Failure("usage", "--memories must be a JSON list of objects", EXIT_USAGE)
        return call("memory", "add_batch", memories=memories)

    def search_args(p):
        p.add_argument("query")
        p.add_argument("--type", default=UNSET, choices=TYPES)
        p.add_argument("--detail", default=UNSET, choices=("slim", "full"))

    @registry.verb("memory", "search", mode="read",
                   desc="search memories by keyword across name, tags and body", args=search_args)
    def search(ns):
        return call("memory", "search", **given(ns, ("query", "type", "detail")))

    @registry.verb("memory", "list", mode="read", desc="list memories, optionally of one type",
                   args=lambda p: p.add_argument("--type", default=UNSET, choices=TYPES))
    def list_memories(ns):
        return call("memory", "list", **given(ns, ("type",)))

    @registry.verb("memory", "get", mode="read", desc="read one memory by slug",
                   args=lambda p: p.add_argument("name"))
    def get(ns):
        return call("memory", "get", name=ns.name)

    @registry.verb("memory", "tool_hints", mode="read", desc="the most-used tools with run counts and last use",
                   args=lambda p: p.add_argument("--top-n", dest="top_n", type=int, default=UNSET))
    def tool_hints(ns):
        return call("memory", "tool_hints", **given(ns, ("top_n",)))

    @registry.verb("memory", "read_compact", mode="read",
                   desc="read a session's compaction summary by session id",
                   args=lambda p: p.add_argument("session_id"))
    def read_compact(ns):
        return call("memory", "read_compact", session_id=ns.session_id)

    @registry.verb("memory", "delete", mode="write", desc="delete a memory by slug",
                   args=lambda p: p.add_argument("name"))
    def delete(ns):
        return call("memory", "delete", name=ns.name)

    def stale_args(p):
        p.add_argument("--unhit-days", dest="unhit_days", type=int, default=UNSET)
        p.add_argument("--unvalidated-days", dest="unvalidated_days", type=int, default=UNSET)
        p.add_argument("--type", default=UNSET, choices=TYPES)

    @registry.verb("memory", "stale", mode="read",
                   desc="memories due for review: not retrieved and not validated recently", args=stale_args)
    def stale(ns):
        return call("memory", "stale", **given(ns, ("unhit_days", "unvalidated_days", "type", "limit")))

    @registry.verb("memory", "validate", mode="write", desc="mark memories as reviewed and still correct",
                   args=lambda p: p.add_argument("names", nargs="+", metavar="name"))
    def validate(ns):
        return call("memory", "validate", names=ns.names)
