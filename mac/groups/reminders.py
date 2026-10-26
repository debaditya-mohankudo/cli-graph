"""`mac reminders` — Reminders.app, wrapping the local-mac reminders__* handlers."""
from mac.groups._backend import call


def _items(result, key):
    """The MCP tools wrap lists as {key: [...]}; the CLI returns the bare list so --limit applies."""
    return result[key] if isinstance(result, dict) and key in result else result


def register(registry):
    @registry.verb("reminders", "lists", mode="read", desc="list reminder lists with open counts")
    def lists(ns):
        return _items(call("reminders", "lists"), "lists")

    def list_args(p):
        p.add_argument("--list", dest="list_name", default=None)
        p.add_argument("--include-completed", action="store_true")

    @registry.verb("reminders", "list", mode="read", desc="list reminders, optionally from one list",
                   args=list_args)
    def list_reminders(ns):
        result = call("reminders", "list", list=ns.list_name,
                      include_completed=ns.include_completed)
        return _items(result, "reminders")

    def create_args(p):
        p.add_argument("title")
        p.add_argument("--list", dest="list_name", default=None)
        p.add_argument("--due-date", default=None, help="ISO-8601, e.g. 2026-04-11T09:00:00")
        p.add_argument("--notes", default=None)
        p.add_argument("--recurrence", default=None, help="accepted but ignored (AppleScript limit)")

    @registry.verb("reminders", "create", mode="write", desc="create a reminder", args=create_args)
    def create(ns):
        return call("reminders", "create", title=ns.title, list=ns.list_name,
                    due_date=ns.due_date, notes=ns.notes, recurrence=ns.recurrence)

    def update_args(p):
        p.add_argument("id")
        p.add_argument("--title", default=None)
        p.add_argument("--due-date", default=None, help="ISO-8601; a due date can be moved, not removed")
        p.add_argument("--notes", default=None)

    @registry.verb("reminders", "update", mode="write", desc="edit a reminder in place by id",
                   args=update_args)
    def update(ns):
        return call("reminders", "update", id=ns.id, title=ns.title,
                    due_date=ns.due_date, notes=ns.notes)

    @registry.verb("reminders", "complete", mode="write", desc="mark a reminder complete by id",
                   args=lambda p: p.add_argument("id"))
    def complete(ns):
        return call("reminders", "complete", id=ns.id)

    @registry.verb("reminders", "delete", mode="write", desc="delete a reminder by id",
                   args=lambda p: p.add_argument("id"))
    def delete(ns):
        return call("reminders", "delete", id=ns.id)
