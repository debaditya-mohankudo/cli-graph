"""`mac reminders` — Reminders.app, wrapping the local-mac reminders__* handlers.

Optional flags default to argparse.SUPPRESS and are forwarded with given(), so
an omitted flag is never sent and the handler's own default applies. --list
uses dest="list" because given() reads attributes by handler parameter name.
"""
import argparse

from mac.groups._backend import call, given

UNSET = argparse.SUPPRESS


def _items(result, key):
    """The MCP tools wrap lists as {key: [...]}; the CLI returns the bare list so --limit applies."""
    return result[key] if isinstance(result, dict) and key in result else result


def register(registry):
    @registry.verb("reminders", "lists", mode="read", desc="list reminder lists with open counts")
    def lists(ns):
        return _items(call("reminders", "lists"), "lists")

    def list_args(p):
        p.add_argument("--list", default=UNSET)
        p.add_argument("--include-completed", action="store_true", default=UNSET)

    @registry.verb("reminders", "list", mode="read", desc="list reminders, optionally from one list",
                   args=list_args)
    def list_reminders(ns):
        result = call("reminders", "list", **given(ns, ("list", "include_completed")))
        return _items(result, "reminders")

    def create_args(p):
        p.add_argument("title")
        p.add_argument("--list", default=UNSET)
        p.add_argument("--due-date", default=UNSET, help="ISO-8601, e.g. 2026-04-11T09:00:00")
        p.add_argument("--notes", default=UNSET)
        p.add_argument("--recurrence", default=UNSET, help="accepted but ignored (AppleScript limit)")

    @registry.verb("reminders", "create", mode="write", desc="create a reminder", args=create_args)
    def create(ns):
        return call("reminders", "create",
                    **given(ns, ("title", "list", "due_date", "notes", "recurrence")))

    def update_args(p):
        p.add_argument("id")
        p.add_argument("--title", default=UNSET)
        p.add_argument("--due-date", default=UNSET, help="ISO-8601; a due date can be moved, not removed")
        p.add_argument("--notes", default=UNSET)

    @registry.verb("reminders", "update", mode="write", desc="edit a reminder in place by id",
                   args=update_args)
    def update(ns):
        return call("reminders", "update", **given(ns, ("id", "title", "due_date", "notes")))

    @registry.verb("reminders", "complete", mode="write", desc="mark a reminder complete by id",
                   args=lambda p: p.add_argument("id"))
    def complete(ns):
        return call("reminders", "complete", id=ns.id)

    @registry.verb("reminders", "delete", mode="write", desc="delete a reminder by id",
                   args=lambda p: p.add_argument("id"))
    def delete(ns):
        return call("reminders", "delete", id=ns.id)
