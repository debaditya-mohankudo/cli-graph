"""`mac kitty` addresses tabs by id, refuses claude tabs and types one visible command (task:f4bc132e).

No real kitty is touched: `_kitten` is replaced by a fake that records calls and serves a fixed `ls`.
"""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mac.cli import default_registry, main  # noqa: E402
from mac.contract import Failure  # noqa: E402
from mac.groups import kitty  # noqa: E402

LS = [{"id": 1, "tabs": [
    {"id": 1, "title": "✓ claude", "windows": [
        {"id": 1, "cwd": "/w", "is_self": False,
         "foreground_processes": [{"cmdline": ["/usr/local/bin/claude"]}]}]},
    {"id": 5, "title": "job: 19:30", "windows": [
        {"id": 9, "cwd": "/w", "foreground_processes": [{"cmdline": ["sleep", "20"]}]}]},
]}]


class Fake:
    def __init__(self, screen=None):
        self.calls, self.screen = [], screen

    def __call__(self, *args, stdin=None):
        self.calls.append((args, stdin))
        if args[0] == "ls":
            return json.dumps(LS)
        if args[0] == "get-text":
            return self.screen if self.screen is not None else self.typed()
        if args[0] == "launch":
            return "9\n"
        return ""

    def typed(self):
        return "".join(s or "" for a, s in self.calls if a[0] == "send-text")

    def verbs(self):
        return [a[0] for a, _ in self.calls]


RULE = "─" * 40


def box(text=""):
    return f"history ❯ old\n{RULE}\n❯\xa0{text}\n{RULE}\n  status\n"


class ClaudeFake(Fake):
    """Screen of claude tab 1 modelled as a prompt box: send-text fills it, enter submits (empties) it."""

    def __init__(self, unsent="", enter_works_on=1):
        super().__init__()
        self.unsent, self.enters, self.enter_works_on = unsent, 0, enter_works_on

    def __call__(self, *args, stdin=None):
        out = super().__call__(*args, stdin=stdin)
        if args[0] == "send-text":
            self.unsent += stdin
        if args[0] == "send-key" and args[-1] == "enter":
            self.enters += 1
            if self.enters >= self.enter_works_on:
                self.unsent = ""
        if args[0] == "get-text":
            return box(self.unsent)
        return out


def mac(fake, *argv):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(kitty, "_kitten", fake), mock.patch.object(kitty, "SETTLE_S", 0):
        status = main(["kitty", *argv], default_registry(), out, err)
    return status, out.getvalue(), err.getvalue()


class KittyTest(unittest.TestCase):
    def test_tabs_lists_ids_and_flags_the_claude_tab(self):
        status, out, _ = mac(Fake(), "tabs")
        rows = json.loads(out)
        self.assertEqual(status, 0)
        self.assertEqual([(r["tab"], r["window"], r["guarded"]) for r in rows], [(1, 1, True), (5, 9, False)])

    def test_run_types_then_submits_with_a_separate_enter_and_verifies(self):
        fake = Fake()
        status, out, _ = mac(fake, "run", "--tab", "5", "echo 'a:b' \"q\"")
        self.assertEqual(status, 0)
        self.assertTrue(json.loads(out)["verified"])
        self.assertEqual(fake.typed(), "echo 'a:b' \"q\"")
        self.assertEqual(fake.verbs(), ["ls", "send-text", "send-key", "get-text"])
        matches = [a[a.index("--match") + 1] for a, _ in fake.calls if a[0] in ("send-text", "send-key")]
        self.assertEqual(matches, ["id:9", "id:9"])  # the window id, not the tab id

    def test_run_fails_when_the_command_is_not_on_screen(self):
        status, out, _ = mac(Fake(screen="$ "), "run", "--tab", "5", "echo hi")
        self.assertNotEqual(status, 0)
        self.assertIn("not on screen", out + _)

    def test_a_wrapped_line_still_verifies(self):
        status, _, _ = mac(Fake(screen="$ echo he\nllo wor\nld"), "run", "--tab", "5", "echo hello world")
        self.assertEqual(status, 0)

    def test_claude_tab_is_refused_by_every_acting_verb(self):
        for argv in (("run", "--tab", "1", "x"), ("read", "--tab", "1"),
                     ("interrupt", "--tab", "1"), ("close", "--tab", "1")):
            fake = Fake()
            status, out, err = mac(fake, *argv)
            self.assertNotEqual(status, 0, argv)
            self.assertIn("refused", out + err)
            self.assertEqual(fake.verbs(), ["ls"], argv)

    def test_unknown_tab_is_not_found(self):
        status, out, err = mac(Fake(), "close", "--tab", "42")
        self.assertNotEqual(status, 0)
        self.assertIn("not_found", out + err)

    def test_title_is_not_an_address(self):
        status, _, _ = mac(Fake(), "close", "--tab", "job: 19:30")
        self.assertNotEqual(status, 0)

    def test_close_matches_the_tab_id(self):
        fake = Fake()
        mac(fake, "close", "--tab", "5")
        self.assertEqual(fake.calls[-1][0], ("close-tab", "--match", "id:5"))

    def test_interrupt_sends_ctrl_c(self):
        fake = Fake()
        mac(fake, "interrupt", "--tab", "5")
        self.assertEqual(fake.calls[-1][0], ("send-key", "--match", "id:9", "ctrl+c"))

    def test_read_returns_the_last_lines(self):
        _, out, _ = mac(Fake(screen="a\nb\nc\n"), "read", "--tab", "5", "--lines", "2")
        self.assertEqual(json.loads(out)["text"], "b\nc")

    def test_open_returns_tab_and_window_ids(self):
        fake = Fake()
        _, out, _ = mac(fake, "open", "--title", "t", "--cwd", "/w")
        self.assertEqual(fake.calls[0][0], ("launch", "--type=tab", "--tab-title=t", "--cwd=/w"))
        self.assertEqual(json.loads(out)["window"], 9)

    def test_scheduled_retry_is_one_visible_one_liner(self):
        _, out, _ = mac(Fake(), "run", "--tab", "5", "fetch", "--at", "19:30", "--retry", "4",
                        "--every", "10m", "--until", "test -s out.json", "--dry-run")
        self.assertEqual(
            json.loads(out)["command"],
            "until [ $(date +%H%M) -ge 1930 ]; do sleep 20; done; for i in $(seq 1 4); do fetch; "
            "test -s out.json && echo DONE && break; sleep 600; done")

    def test_bad_time_and_interval_are_usage_errors(self):
        for extra in (("--at", "25:00"), ("--retry", "2", "--every", "ten")):
            status, _, _ = mac(Fake(), "run", "--tab", "5", "x", "--dry-run", *extra)
            self.assertEqual(status, 2, extra)


class NotifyTest(unittest.TestCase):
    def test_types_the_tagged_line_then_a_separate_enter_and_verifies(self):
        fake = ClaudeFake()
        status, out, _ = mac(fake, "notify", "--to", "1", "--from", "tab 4", "--body", "PASS 1 stored")
        res = json.loads(out)
        self.assertEqual(status, 0)
        self.assertTrue(res["sent"] and res["verified"])
        self.assertEqual(res["message"], "[AUTOMATED from tab 4, not the user] PASS 1 stored")
        self.assertEqual(fake.typed(), res["message"])
        self.assertEqual(fake.verbs(), ["ls", "get-text", "send-text", "send-key", "get-text"])
        matches = [a[a.index("--match") + 1] for a, _ in fake.calls if a[0] in ("send-text", "send-key")]
        self.assertEqual(matches, ["id:1", "id:1"])

    def test_a_line_break_in_body_or_sender_is_refused_before_any_kitten_call(self):
        for argv in (("--from", "s", "--body", "a\nb"), ("--from", "s\r", "--body", "a"),
                     ("--from", "s", "--body", "a\x1bb"), ("--from", "s", "--body", "  ")):
            fake = ClaudeFake()
            status, _, _ = mac(fake, "notify", "--to", "1", *argv)
            self.assertEqual(status, 2, argv)
            self.assertEqual(fake.calls, [], argv)

    def test_unsent_text_in_the_prompt_is_busy_and_nothing_is_typed(self):
        fake = ClaudeFake(unsent="half a thought")
        status, out, _ = mac(fake, "notify", "--to", "1", "--from", "s", "--body", "hi")
        res = json.loads(out)
        self.assertEqual(status, 0)
        self.assertTrue(res["busy"] and not res["sent"])
        self.assertNotIn("send-text", fake.verbs())
        self.assertNotIn("send-key", fake.verbs())

    def test_force_sends_despite_unsent_text(self):
        fake = ClaudeFake(unsent="half")
        status, out, _ = mac(fake, "notify", "--to", "1", "--from", "s", "--body", "hi", "--force")
        self.assertEqual(status, 0)
        self.assertTrue(json.loads(out)["sent"])
        self.assertIn("send-text", fake.verbs())

    def test_enter_is_retried_once_then_succeeds(self):
        fake = ClaudeFake(enter_works_on=2)
        status, out, _ = mac(fake, "notify", "--to", "1", "--from", "s", "--body", "hi")
        self.assertEqual(status, 0)
        self.assertTrue(json.loads(out)["enter_retried"])
        self.assertEqual(fake.enters, 2)

    def test_fails_when_the_prompt_never_empties(self):
        fake = ClaudeFake(enter_works_on=99)
        status, out, err = mac(fake, "notify", "--to", "1", "--from", "s", "--body", "hi")
        self.assertNotEqual(status, 0)
        self.assertIn("did not empty", out + err)
        self.assertEqual(fake.enters, 2)

    def test_non_claude_tab_is_refused_by_notify(self):
        fake = Fake()
        status, out, err = mac(fake, "notify", "--to", "5", "--from", "s", "--body", "hi")
        self.assertNotEqual(status, 0)
        self.assertIn("refused", out + err)
        self.assertEqual(fake.verbs(), ["ls"])

    def test_no_prompt_box_on_screen_is_an_error_not_a_send(self):
        fake = Fake(screen="plain output\n")
        status, _, _ = mac(fake, "notify", "--to", "1", "--from", "s", "--body", "hi")
        self.assertNotEqual(status, 0)
        self.assertNotIn("send-text", fake.verbs())

    def test_prompt_text_reads_only_the_last_box(self):
        self.assertEqual(kitty.prompt_text(box()), "")
        self.assertEqual(kitty.prompt_text(box("abc")), "abc")
        self.assertIsNone(kitty.prompt_text("no box"))


COMM_ROWS = [
    {"id": "x-apple-reminder://A", "title": "[reader -> you] auction read failed", "list": "kitty-comm",
     "completed": False, "dueDate": "d", "notes": "{}"},
    {"id": "x-apple-reminder://B", "title": "[reader -> 5] hi", "list": "kitty-comm", "completed": False},
    {"id": "x-apple-reminder://C", "title": "[reader -> 15] hi", "list": "kitty-comm", "completed": False},
    {"id": "x-apple-reminder://D", "title": "not a tab message", "list": "kitty-comm", "completed": False},
]


COMM_LIST_NAME = "kitty-comm"


class FakeReminders:
    def __init__(self, lists=("kitty-comm", "Reminders"), rows=COMM_ROWS,
                 created="Created reminder 'x' in 'kitty-comm' (id x-apple-reminder://NEW)"):
        self.calls, self.lists, self.rows, self.created = [], lists, rows, created

    def __call__(self, area, verb, **kw):
        self.calls.append((verb, kw))
        if verb == "list":
            if COMM_LIST_NAME not in self.lists:
                raise Failure("tool_error", f"Reminder list not found: {kw['list']}")
            return [r for r in self.rows if kw.get("include_completed") or not r["completed"]]
        if verb == "create":
            if COMM_LIST_NAME not in self.lists:
                raise Failure("tool_error", "Reminders got an error: Can’t get list \"kitty-comm\". (-1728)")
            return self.created
        return "ok"


def comm(rem, *argv, fake=None):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(kitty, "call", rem), mock.patch.object(kitty, "_kitten", fake or Fake()), \
            mock.patch.object(kitty, "SETTLE_S", 0):
        status = main(["kitty", *argv], default_registry(), out, err)
    return status, out.getvalue(), err.getvalue()


class CommTest(unittest.TestCase):
    def test_send_creates_a_titled_reminder_with_json_notes_and_returns_the_id(self):
        rem = FakeReminders()
        status, out, _ = comm(rem, "comm_send", "--from", "reader", "--to", "you", "read failed")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)["id"], "x-apple-reminder://NEW")
        verb, kw = [c for c in rem.calls if c[0] == "create"][0]
        self.assertEqual((kw["title"], kw["list"]), ("[reader -> you] read failed", "kitty-comm"))
        self.assertEqual(json.loads(kw["notes"])["to"], "you")
        self.assertRegex(kw["due_date"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")

    def test_send_refuses_tags_that_would_not_parse_back(self):
        for flag, bad in (("--from", "a]b"), ("--to", "x -> y"), ("--to", " ")):
            argv = {"--from": "r", "--to": "you"} | {flag: bad}
            status, _, _ = comm(FakeReminders(), "comm_send", "--from", argv["--from"], "--to", argv["--to"], "b")
            self.assertNotEqual(status, 0, (flag, bad))

    def test_send_fails_clearly_when_the_list_is_missing(self):
        rem = FakeReminders(lists=("Reminders",))
        status, _, err = comm(rem, "comm_send", "--from", "r", "--to", "you", "b")
        self.assertNotEqual(status, 0)
        self.assertIn("does not exist", err)

    def test_send_fails_loudly_if_the_id_cannot_be_read(self):
        status, _, err = comm(FakeReminders(created="Created reminder"), "comm_send", "--from", "r", "--to", "you", "b")
        self.assertNotEqual(status, 0)
        self.assertIn("id", err)

    def test_inbox_matches_the_recipient_tag_exactly(self):
        status, out, _ = comm(FakeReminders(), "comm_inbox", "--to", "5")
        self.assertEqual([m["id"] for m in json.loads(out)], ["x-apple-reminder://B"])
        _, out, _ = comm(FakeReminders(), "comm_inbox", "--to", "you")
        self.assertEqual(json.loads(out)[0]["body"], "auction read failed")

    def test_inbox_include_completed_is_forwarded(self):
        rem = FakeReminders()
        comm(rem, "comm_inbox", "--to", "you", "--include-completed")
        self.assertTrue([c for c in rem.calls if c[0] == "list"][0][1]["include_completed"])

    def test_ack_completes_by_id(self):
        rem = FakeReminders()
        status, out, _ = comm(rem, "comm_ack", "x-apple-reminder://A")
        self.assertEqual((status, json.loads(out)["acked"]), (0, True))
        self.assertIn(("complete", {"id": "x-apple-reminder://A"}), rem.calls)

    def test_ack_refuses_an_id_outside_kitty_comm_and_completes_nothing(self):
        rem = FakeReminders()
        for rid in ("x-apple-reminder://ELSEWHERE", "x-apple-reminder://D"):  # D is a non-message row
            status, _, err = comm(rem, "comm_ack", rid)
            self.assertNotEqual(status, 0)
        self.assertNotIn("complete", [c[0] for c in rem.calls])

    def test_a_busy_doorbell_never_fails_the_send(self):
        status, out, _ = comm(FakeReminders(), "comm_send", "--from", "r", "--to", "you", "b", "--notify", "1",
                              fake=ClaudeFake(unsent="typing"))
        row = json.loads(out)
        self.assertEqual(status, 0)
        self.assertTrue(row["id"])
        self.assertTrue(row["doorbell"]["busy"])

    def test_doorbell_rings_a_free_claude_tab_with_the_reminder_id(self):
        fake = ClaudeFake()
        status, out, _ = comm(FakeReminders(), "comm_send", "--from", "r", "--to", "you", "b", "--notify", "1", fake=fake)
        self.assertEqual(status, 0)
        self.assertIn("x-apple-reminder://NEW", fake.typed())


if __name__ == "__main__":
    unittest.main()
