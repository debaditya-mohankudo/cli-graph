"""`mac notes` — Apple Notes, wrapping the local-mac notes__* handlers.

Optional flags default to argparse.SUPPRESS and are forwarded with given(), so
an omitted flag is never sent and the handler's own default applies.
"""
import argparse

from mac.groups._backend import call, given

UNSET = argparse.SUPPRESS


def register(registry):
    @registry.verb("notes", "folders", mode="read", desc="list Notes folders with note counts")
    def folders(ns):
        return call("notes", "folders")

    @registry.verb("notes", "list", mode="read", desc="list notes, optionally from one folder",
                   args=lambda p: p.add_argument("--folder", default=UNSET))
    def list_notes(ns):
        return call("notes", "list", **given(ns, ("folder", "limit")))

    @registry.verb("notes", "read", mode="read", desc="read a note by id or title",
                   args=lambda p: p.add_argument("id"))
    def read(ns):
        return call("notes", "read", id=ns.id)

    def add_args(p):
        p.add_argument("title")
        p.add_argument("--body", default=UNSET, help="HTML body")
        p.add_argument("--folder", default=UNSET)
        p.add_argument("--tags", default=UNSET, help="comma/space separated; needs Accessibility")

    @registry.verb("notes", "add", mode="write", desc="create a note", args=add_args)
    def add(ns):
        return call("notes", "add", **given(ns, ("title", "body", "folder", "tags")))

    def update_args(p):
        p.add_argument("id")
        p.add_argument("--body", required=True, help="HTML body")
        p.add_argument("--mode", default=UNSET, choices=("replace", "append"))
        p.add_argument("--title", default=UNSET)

    @registry.verb("notes", "update", mode="write", desc="edit a note in place by id",
                   args=update_args)
    def update(ns):
        return call("notes", "update", **given(ns, ("id", "body", "mode", "title")))

    def delete_args(p):
        p.add_argument("title")
        p.add_argument("--folder", default=UNSET)

    @registry.verb("notes", "delete", mode="write", desc="delete notes by title in a folder",
                   args=delete_args)
    def delete(ns):
        return call("notes", "delete", **given(ns, ("title", "folder")))
