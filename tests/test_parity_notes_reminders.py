"""Parity of `mac notes` / `mac reminders` with the local-mac MCP handlers.

Offline tests stub the handlers and check the contract translation. Live tests
(MAC_PARITY_LIVE=1) run both sides against a scratch Notes folder and Reminders
list that the test creates and removes.
"""
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mac.cli import default_registry, describe, main
from mac.groups import _backend

SCRATCH = "mac-parity-scratch"

READ_VERBS = {
    "notes": {"folders", "list", "read"},
    "reminders": {"lists", "list"},
}
WRITE_VERBS = {
    "notes": {"add", "delete", "update"},
    "reminders": {"complete", "create", "delete", "update"},
}


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    status = main(list(argv), default_registry(), out, err)
    return status, out.getvalue(), err.getvalue()


class ModeTest(unittest.TestCase):
    def test_verb_sets_and_modes(self):
        entries = describe(default_registry())
        for area in ("notes", "reminders"):
            by_mode = {"read": set(), "write": set()}
            for e in entries:
                if e["area"] == area:
                    by_mode[e["mode"]].add(e["verb"])
            self.assertEqual(by_mode["read"], READ_VERBS[area], area)
            self.assertEqual(by_mode["write"], WRITE_VERBS[area], area)


class TranslationTest(unittest.TestCase):
    def test_error_dict_becomes_failure(self):
        notes = mock.Mock(handle_read=mock.Mock(return_value={"error": "Note not found: x"}))
        with mock.patch("mac.groups.notes.tools", return_value=notes):
            status, out, err = run("notes", "read", "x")
        self.assertEqual((status, out), (1, ""))
        self.assertEqual(json.loads(err)["error"], {"code": "tool_error", "message": "Note not found: x"})

    def test_raised_value_error_becomes_failure(self):
        reminders = mock.Mock(handle_complete=mock.Mock(side_effect=RuntimeError("Reminder not found: z")))
        with mock.patch("mac.groups.reminders.tools", return_value=reminders):
            status, _, err = run("reminders", "complete", "z")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "tool_error")

    def test_empty_strings_become_empty_lists(self):
        notes = mock.Mock(handle_list=mock.Mock(return_value="No notes found."),
                     handle_folders=mock.Mock(return_value="No folders found."))
        reminders = mock.Mock(handle_list=mock.Mock(return_value="No reminders found."))
        with mock.patch("mac.groups.notes.tools", return_value=notes), \
                mock.patch("mac.groups.reminders.tools", return_value=reminders):
            for argv in (("notes", "list"), ("notes", "folders"), ("reminders", "list")):
                status, out, _ = run(*argv)
                self.assertEqual((status, json.loads(out)), (0, []), argv)

    def test_reminder_wrappers_are_unwrapped_so_limit_applies(self):
        rows = [{"id": str(i)} for i in range(3)]
        reminders = mock.Mock(handle_list=mock.Mock(return_value={"reminders": rows}),
                         handle_lists=mock.Mock(return_value={"lists": [{"name": "a", "open": 1}]}))
        with mock.patch("mac.groups.reminders.tools", return_value=reminders):
            _, out, err = run("reminders", "list", "--limit", "2")
            self.assertEqual(json.loads(out), rows[:2])
            self.assertEqual(json.loads(err), {"truncated": {"shown": 2, "total": 3}})
            _, out, _ = run("reminders", "lists")
            self.assertEqual(json.loads(out), [{"name": "a", "open": 1}])

    def test_success_data_passes_through_unchanged(self):
        added = {"status": "created", "id": "n1", "title": "t", "folder": "Notes"}
        notes = mock.Mock(handle_add=mock.Mock(return_value=added))
        with mock.patch("mac.groups.notes.tools", return_value=notes):
            status, out, _ = run("notes", "add", "t", "--body", "<b>x</b>", "--tags", "a b")
        self.assertEqual((status, json.loads(out)), (0, added))
        notes.handle_add.assert_called_once_with(title="t", body="<b>x</b>", folder="Notes", tags="a b")

    def test_string_results_pass_through(self):
        reminders = mock.Mock(handle_create=mock.Mock(return_value="Created reminder 'r' in 'L'"))
        with mock.patch("mac.groups.reminders.tools", return_value=reminders):
            status, out, _ = run("reminders", "create", "r", "--list", "L", "--due-date", "2026-11-01T09:00:00")
        self.assertEqual((status, json.loads(out)), (0, "Created reminder 'r' in 'L'"))
        reminders.handle_create.assert_called_once_with(
            title="r", list="L", due_date="2026-11-01T09:00:00", notes=None, recurrence=None)

    def test_missing_source_tree_is_a_failure(self):
        with mock.patch.dict(os.environ, {"MAC_MCP_SRC": "/nonexistent/src"}):
            status, _, err = run("notes", "folders")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "backend_missing")


def osascript(script):
    return subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=60)


@unittest.skipUnless(os.environ.get("MAC_PARITY_LIVE") == "1", "set MAC_PARITY_LIVE=1 to touch Notes and Reminders")
class LiveParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notes = _backend.tools("notes")
        cls.reminders = _backend.tools("reminders")
        osascript(f'tell application "Reminders" to make new list with properties {{name:"{SCRATCH}"}}')

    @classmethod
    def tearDownClass(cls):
        osascript(f'tell application "Reminders" to delete list "{SCRATCH}"')
        osascript(f'tell application "Notes" to delete folder "{SCRATCH}"')

    def cli(self, *argv):
        status, out, err = run(*argv)
        self.assertEqual(status, 0, err)
        return json.loads(out)

    def test_notes_round_trip(self):
        cli_note = self.cli("notes", "add", "cli note", "--body", "<div>one</div>", "--folder", SCRATCH)
        mcp_note = self.notes.handle_add("mcp note", "<div>one</div>", SCRATCH)
        self.assertEqual(cli_note.keys(), mcp_note.keys())
        self.assertEqual((cli_note["status"], cli_note["folder"]), (mcp_note["status"], mcp_note["folder"]))

        self.assertEqual(self.cli("notes", "folders"), self.notes.handle_folders())
        listed = self.cli("notes", "list", "--folder", SCRATCH, "--limit", "20")
        self.assertEqual(listed, self.notes.handle_list(SCRATCH, 20))
        self.assertEqual(self.cli("notes", "read", cli_note["id"]), self.notes.handle_read(cli_note["id"]))

        for note in (cli_note, mcp_note):
            cli_up = self.cli("notes", "update", note["id"], "--body", "<div>two</div>", "--mode", "append")
            self.assertEqual((cli_up["status"], cli_up["mode"]), ("updated", "append"))
        self.assertEqual(self.cli("notes", "delete", "cli note", "--folder", SCRATCH)["status"], "deleted")
        self.assertEqual(self.notes.handle_delete("mcp note", SCRATCH)["status"], "deleted")
        self.assertEqual(self.cli("notes", "delete", "cli note", "--folder", SCRATCH)["status"], "not_found")

    def test_notes_missing_id_fails(self):
        status, _, err = run("notes", "update", "x-coredata://nope", "--body", "x")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "tool_error")

    def test_reminders_round_trip(self):
        self.assertEqual(self.cli("reminders", "list", "--list", SCRATCH), [])
        lists = {l["name"]: l["open"] for l in self.cli("reminders", "lists")}
        self.assertEqual(lists[SCRATCH], 0)

        due = "2026-11-01T09:00:00"
        cli_msg = self.cli("reminders", "create", "cli reminder", "--list", SCRATCH, "--due-date", due)
        mcp_msg = self.reminders.handle_create("mcp reminder", SCRATCH, due)
        self.assertEqual(cli_msg.replace("cli", "mcp"), mcp_msg)

        rows = self.cli("reminders", "list", "--list", SCRATCH)
        self.assertEqual(rows, self.reminders.handle_list(SCRATCH)["reminders"])
        self.assertEqual({r["title"] for r in rows}, {"cli reminder", "mcp reminder"})
        target = next(r for r in rows if r["title"] == "cli reminder")

        self.assertIn("title", self.cli("reminders", "update", target["id"], "--title", "cli renamed"))
        self.assertEqual(self.cli("reminders", "complete", target["id"]), "Completed: 'cli renamed'")
        done = self.cli("reminders", "list", "--list", SCRATCH, "--include-completed")
        self.assertEqual(done, self.reminders.handle_list(SCRATCH, True)["reminders"])

        for row in done:
            self.assertTrue(self.cli("reminders", "delete", row["id"]).startswith("Deleted reminder"))
        self.assertEqual(self.cli("reminders", "list", "--list", SCRATCH, "--include-completed"), [])

    def test_reminders_missing_id_fails(self):
        status, _, err = run("reminders", "complete", "x-apple-reminder://nope")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "tool_error")


if __name__ == "__main__":
    unittest.main()
