"""`mac notes` — Apple Notes, wrapping the local-mac notes__* handlers."""
from mac.contract import DEFAULT_LIMIT
from mac.groups._backend import call


def register(registry):
    @registry.verb("notes", "folders", mode="read", desc="list Notes folders with note counts")
    def folders(ns):
        return call("notes", "folders")

    @registry.verb("notes", "list", mode="read", desc="list notes, optionally from one folder",
                   args=lambda p: p.add_argument("--folder", default=""))
    def list_notes(ns):
        return call("notes", "list", folder=ns.folder, limit=ns.limit or DEFAULT_LIMIT)

    @registry.verb("notes", "read", mode="read", desc="read a note by id or title",
                   args=lambda p: p.add_argument("id"))
    def read(ns):
        return call("notes", "read", id=ns.id)

    def add_args(p):
        p.add_argument("title")
        p.add_argument("--body", default="", help="HTML body")
        p.add_argument("--folder", default="Notes")
        p.add_argument("--tags", default="", help="comma/space separated; needs Accessibility")

    @registry.verb("notes", "add", mode="write", desc="create a note", args=add_args)
    def add(ns):
        return call("notes", "add", title=ns.title, body=ns.body,
                    folder=ns.folder, tags=ns.tags)

    def update_args(p):
        p.add_argument("id")
        p.add_argument("--body", required=True, help="HTML body")
        p.add_argument("--mode", default="replace", choices=("replace", "append"))
        p.add_argument("--title", default="")

    @registry.verb("notes", "update", mode="write", desc="edit a note in place by id",
                   args=update_args)
    def update(ns):
        return call("notes", "update", id=ns.id, body=ns.body,
                    mode=ns.mode, title=ns.title)

    def delete_args(p):
        p.add_argument("title")
        p.add_argument("--folder", default="Notes")

    @registry.verb("notes", "delete", mode="write", desc="delete notes by title in a folder",
                   args=delete_args)
    def delete(ns):
        return call("notes", "delete", title=ns.title, folder=ns.folder)
