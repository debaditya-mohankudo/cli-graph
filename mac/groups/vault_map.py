"""`mac vault_map` — route to the right place in the Obsidian vault, wrapping claude-hooks' vault_map__* handlers.

Run these before a vault search or save: they say which folder, note or tag
holds a topic, so the search that follows stays small.
"""
import argparse

from mac.groups._backend import given
from mac.groups._hooks import call

UNSET = argparse.SUPPRESS


def register(registry):
    def overview_args(p):
        p.add_argument("--dir", default=UNSET, help="vault folder to summarise (default: the vault root)")
        p.add_argument("--depth", type=int, default=UNSET)

    @registry.verb("vault_map", "overview", mode="read",
                   desc="what the vault holds in a folder: sub-folders, file counts, top words and tags",
                   args=overview_args)
    def overview(ns):
        return call("vault_map", "overview", **given(ns, ("dir", "depth")))

    @registry.verb("vault_map", "node", mode="read", desc="one vault folder or note: its links and neighbours",
                   args=lambda p: p.add_argument("id"))
    def node(ns):
        return call("vault_map", "node", id=ns.id)

    @registry.verb("vault_map", "tag", mode="read", desc="the vault folders and notes carrying a tag",
                   args=lambda p: p.add_argument("tag"))
    def tag(ns):
        return call("vault_map", "tag", tag=ns.tag)

    @registry.verb("vault_map", "find", mode="read",
                   desc="find which vault folders or notes hold a topic, id or detail",
                   args=lambda p: p.add_argument("query"))
    def find(ns):
        return call("vault_map", "find", **given(ns, ("query", "limit")))
