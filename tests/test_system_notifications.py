"""mac system notifications: parsing, de-duplication, failures (task:8fed2511). osascript is faked."""
import io
import sys
from pathlib import Path
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mac.contract import Failure
from mac.groups import system_notifications as sn

FS, RS = sn.FS, sn.RS
U1 = "11111111-2222-3333-4444-555555555555"
U2 = "66666666-7777-8888-9999-000000000000"


def rec(role, ident="", value=""):
    return FS.join([role, ident, value]) + RS


DUMP = (rec("AXGroup", "container") + rec("AXGroup", U1) + rec("AXHeading", "", "Reminders")
        + rec("AXStaticText", "title", "Pay rent") + rec("AXStaticText", "body", "line1\nline2")
        + rec("AXStaticText", "", "51m ago") + rec("AXButton", "", "")
        + rec("AXGroup", U2) + rec("AXStaticText", "title", "Hello") + rec("AXStaticText", "", "now"))


class ParseTest(unittest.TestCase):
    def test_groups_with_uuid_ids_become_notifications(self):
        notes = sn.parse(DUMP)
        self.assertEqual([n["id"] for n in notes], [U1, U2])
        self.assertEqual(notes[0], {"id": U1, "app": "Reminders", "title": "Pay rent",
                                    "body": "line1\nline2", "age": "51m ago"})

    def test_missing_app_and_body_are_null(self):
        second = sn.parse(DUMP)[1]
        self.assertIsNone(second["app"])
        self.assertIsNone(second["body"])
        self.assertEqual(second["age"], "now")

    def test_empty_dump_is_empty(self):
        self.assertEqual(sn.parse(""), [])


class ReadTest(unittest.TestCase):
    def test_no_window_is_an_empty_list(self):
        with mock.patch.object(sn, "_osascript", return_value="NOWINDOW"):
            self.assertEqual(sn.read(), [])

    def test_absent_process_fails_clearly(self):
        with mock.patch.object(sn, "_osascript", return_value="NOPROCESS"):
            with self.assertRaisesRegex(Failure, "NotificationCenter process is not running"):
                sn.read()

    def test_permission_error_is_not_retried_and_names_the_fix(self):
        calls = mock.Mock(side_effect=Failure("permission_denied", f"denied; {sn.AX_HINT}"))
        with mock.patch.object(sn, "_osascript", calls):
            with self.assertRaisesRegex(Failure, "Accessibility"):
                sn.read()
        self.assertEqual(calls.call_count, 1)

    def test_transient_walk_error_is_retried(self):
        calls = mock.Mock(side_effect=[Failure("tool_error", "gone"), DUMP])
        with mock.patch.object(sn, "_osascript", calls), mock.patch.object(sn.time, "sleep"):
            self.assertEqual(len(sn.read()), 2)

    def test_osascript_assistive_error_maps_to_permission_denied(self):
        done = mock.Mock(returncode=1, stdout="", stderr="execution error: osascript is not allowed assistive access. (-25211)")
        with mock.patch.object(sn.subprocess, "run", return_value=done):
            with self.assertRaises(Failure) as cm:
                sn._osascript("x")
        self.assertEqual(cm.exception.code, "permission_denied")
        self.assertIn("System Settings", cm.exception.message)


class WatchTest(unittest.TestCase):
    def test_each_id_is_emitted_once_and_survives_a_missing_window(self):
        polls = [sn.parse(DUMP), [], sn.parse(DUMP), sn.parse(DUMP)[:1]]
        out = io.StringIO()
        with mock.patch.object(sn, "read", side_effect=polls), mock.patch.object(sn.time, "sleep"), \
                mock.patch.object(sn.time, "monotonic", side_effect=[0, 0, 0, 0, 99]):
            result = sn.watch(0.1, 50, out)
        self.assertEqual(result["emitted"], 2)
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
