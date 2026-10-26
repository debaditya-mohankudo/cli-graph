"""`mac` date arguments are checked before any handler runs, with the MCP path's verdicts.

local-mac's tools/arg_types.py validates IsoDate / IsoDateTime through pydantic
on the MCP path; mac.cli's iso_date / iso_datetime check the same rule for
argparse. These tests hold the two copies to the same verdicts and check that a
rejected value never reaches the backend.
"""
import argparse
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO), str(REPO / "tools"), str(REPO / "tests")]

from _helpers import run  # noqa: F401  (imports local-mac, or fails with the fix)
from mac.cli import iso_date, iso_datetime
from tools.arg_types import check_date, check_datetime

SAMPLES = [
    "2026-10-27", "2026-10-27T15:00", "2026-10-27T15:00:00", "2026-10-27T15:00:00Z",
    "2026-10-27T15:00:00+05:30", "2026-10-27 15:00", "2026-02-30", "2026-02-30T09:00",
    "2026-10-27T25:00", "20261027", "2026-W44-2", "next tuesday", "", "2026-10-27Tx",
]


def _verdict(fn, value, errors):
    try:
        fn(value)
        return True
    except errors:
        return False


class SameVerdictTest(unittest.TestCase):
    def test_cli_types_agree_with_local_mac(self):
        for cli, mcp in ((iso_date, check_date), (iso_datetime, check_datetime)):
            for value in SAMPLES:
                with self.subTest(fn=cli.__name__, value=value):
                    self.assertEqual(_verdict(cli, value, argparse.ArgumentTypeError),
                                     _verdict(mcp, value, ValueError))


class EveryDatedParameterIsCheckedTest(unittest.TestCase):
    def test_generated_and_hand_written_groups_use_the_format_type(self):
        """A handler parameter annotated IsoDate / IsoDateTime gets the matching mac.cli type in
        every group, generated or hand-written, so a new dated parameter can't slip through."""
        import mac.cli
        from mac.cli import build_parser, default_registry
        from mac.groups import _backend
        from gen_groups import FORMAT_TYPES, kind, parameters

        registry, dispatcher = default_registry(), _backend.dispatcher()
        checked = 0
        for area, (_, actions) in dispatcher.DOMAIN_MAP.items():
            for action in actions:
                verb = registry.get(area, action)
                if verb is None:
                    continue
                params = {p.name: p for p in parameters(dispatcher.resolve(area, action))}
                for action_obj in build_parser(verb)._actions:
                    p = params.get(action_obj.dest)
                    if p is None or kind(p.annotation)[0] not in FORMAT_TYPES.values():
                        continue
                    with self.subTest(verb=f"{area} {action}", param=p.name):
                        self.assertIs(action_obj.type, getattr(mac.cli, kind(p.annotation)[0]))
                    checked += 1
        self.assertGreaterEqual(checked, 9)  # calendar's 7 date parameters and reminders' 2


class ProxiedSchemaFormatTest(unittest.TestCase):
    """gen_mcp_groups reads a proxied server's JSON-schema `format` the way gen_groups reads
    local-mac's annotation."""

    def test_date_format_maps_to_the_cli_type(self):
        from gen_mcp_groups import kind
        date = {"type": "string", "format": "date"}
        self.assertEqual(kind(date), ("iso_date", None))
        self.assertEqual(kind({"anyOf": [date, {"type": "null"}], "default": None}), ("iso_date", None))
        self.assertEqual(kind({"type": "string", "format": "date-or-datetime"}), ("iso_datetime", None))

    def test_unknown_format_stops_the_generator(self):
        from gen_mcp_groups import kind
        for prop in ({"type": "string", "format": "date-time"}, {"type": "integer", "format": "date"}):
            with self.subTest(prop=prop), self.assertRaises(SystemExit):
                kind(prop)


class RejectBeforeBackendTest(unittest.TestCase):
    CASES = [
        ("calendar", "add_event", "t", "2026-10-27 15:00"),
        ("calendar", "list_events", "2026-02-30", "2026-03-01"),
        ("calendar", "get_events_by_date", "next tuesday"),
        ("calendar", "get_upcoming_events", "--from-date", "2026-10-27T09:00"),
        ("reminders", "create", "t", "--due-date", "tomorrow 9am"),
        ("reminders", "update", "some-id", "--due-date", "2026-10-27 09:00"),
    ]

    def test_bad_dates_exit_usage_without_calling_the_backend(self):
        for argv in self.CASES:
            # Patch the group modules, not _backend.call: a group first imported
            # under that patch would bind the mock for the rest of the suite.
            call = mock.Mock(return_value="ok")
            with self.subTest(argv=argv), mock.patch("mac.groups.calendar.call", call), \
                    mock.patch("mac.groups.reminders.call", call):
                status, out, err = run(*argv)
                self.assertEqual(status, 2, err)
                self.assertIn('"code": "usage"', err)
                call.assert_not_called()

    PROXIED = [
        ("astrology", "mahadasha", "120.5", "2026-02-30"),
        ("astrology", "aq_predict_events", "someone", "7", "--from-date", "next tuesday"),
        ("astrology", "aq_predict_events_batch", "someone", "--to-date", "20291027"),
    ]

    def test_bad_dates_never_start_a_proxied_server(self):
        for argv in self.PROXIED:
            call_tool = mock.Mock(return_value="ok")
            with self.subTest(argv=argv), mock.patch("mac.groups.astrology.call_tool", call_tool):
                status, out, err = run(*argv)
                self.assertEqual(status, 2, err)
                self.assertIn('"code": "usage"', err)
                call_tool.assert_not_called()

    def test_good_dates_reach_the_backend_unchanged(self):
        with mock.patch("mac.groups.reminders.call", return_value="ok") as call:
            status, _, err = run("reminders", "create", "t", "--due-date", "2026-10-27T09:00:00")
        self.assertEqual(status, 0, err)
        call.assert_called_once_with("reminders", "create", title="t", due_date="2026-10-27T09:00:00")


if __name__ == "__main__":
    unittest.main()
