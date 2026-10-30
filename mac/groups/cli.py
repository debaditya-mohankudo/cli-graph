"""`mac cli` — the find_cli lookup as a command, for when the MCP server is down.

`mac cli find "<task>"` calls the same find_cli.service the server does, so it
returns the same result for the same input.
"""
import argparse

from find_cli import DEFAULT_LIMIT
from find_cli.service import Finder
from mac.contract import Failure

UNSET = argparse.SUPPRESS


def register(registry):
    def find_args(p):
        p.add_argument("task")
        p.add_argument("--hops", type=int, default=2,
                       help="0 seeds only, 1 adds linked commands, 2 also adds area siblings")
        p.add_argument("--area", default="", help="an area or group you already know")

    @registry.verb("cli", "find", mode="read",
                   desc="find the mac commands for a task in plain words: seeds and neighbours with usage "
                        "(--limit sets the number of seeds)",
                   args=find_args)
    def find(ns):
        result = Finder().answer(ns.task, limit=ns.limit or DEFAULT_LIMIT, hops=ns.hops, area=ns.area)
        if "error" in result:
            raise Failure(result["error"]["code"], result["error"]["message"])
        return result
