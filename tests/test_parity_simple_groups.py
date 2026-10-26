"""Parity of the generated simple `mac` groups with their local-mac handlers (task:315f6563).

Offline tests check coverage of DOMAIN_MAP, the read/write table, that the
generated modules are current, and that every verb passes arguments the real
handler signature accepts. Live tests (MAC_PARITY_LIVE=1) compare read verbs
against direct handler calls and run the writes that can be undone.

Not run live, by design: system sleep_now/sleep_in/sleep_winddown/sleep_cancel
(sleeps the Mac or touches a real schedule), vpn connect/disconnect/pause (drops
the network), sound set_output (switches the audio device), music playback and
volume (audible, launches Music), connector execute_action (external side
effects; container is down), time play_sound (audible).
"""
import importlib
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO), str(REPO / "tools"), str(REPO / "tests")]

import gen_groups
from _helpers import run, stub_dispatcher
from mac.cli import default_registry, describe
from mac.groups import _backend

AREAS = gen_groups.AREAS

# Reviewed independently of gen_groups.WRITE: a verb must not turn read by an edit there.
WRITE = {
    "calendar": {"add_event", "delete_event"},
    "system": {"process_kill", "sleep_now", "sleep_in", "sleep_cancel",
               "sleep_winddown", "clipboard_write", "notify"},
    "vpn": {"connect", "disconnect", "pause"},
    "sound": {"set_output", "set_volume", "mute", "unmute"},
    "music": {"play", "pause", "next", "previous", "volume", "search_play",
              "play_playlist", "play_track"},
    "time": {"alarm", "wait", "play_sound"},
    "connector": {"execute_action"},
    "mail": {"compose", "delete", "move", "add_local_mailbox"},
    "imessage": {"send"},
    "vault": {"write", "append", "delete", "move"},
}

SAMPLE = {"int": "3", "float": "1.5", "list_int": "3"}


def domain_map():
    return _backend.dispatcher().DOMAIN_MAP


def real_handler(area, action):
    try:
        module = importlib.import_module(domain_map()[area][0])
    except ImportError as exc:
        raise unittest.SkipTest(f"{area} handlers need local-mac's venv: {exc}")
    return getattr(module, f"handle_{action}")


class CoverageTest(unittest.TestCase):
    def test_every_domain_map_tool_has_a_verb_with_the_right_mode(self):
        entries = describe(default_registry())
        for area in AREAS:
            verbs = {e["verb"]: e["mode"] for e in entries if e["area"] == area}
            self.assertEqual(set(verbs), set(domain_map()[area][1]), area)
            writes = {v for v, mode in verbs.items() if mode == "write"}
            self.assertEqual(writes, WRITE.get(area, set()), area)

    def test_generated_modules_are_current(self):
        for area in AREAS:
            module_path, actions = domain_map()[area]
            try:
                expected = gen_groups.render(area, module_path, actions)
            except ImportError as exc:
                self.skipTest(f"needs local-mac's venv: {exc}")
            actual = (REPO / "mac" / "groups" / f"{area}.py").read_text()
            self.assertEqual(actual, expected, f"{area}: rerun tools/gen_groups.py")


class TranslationTest(unittest.TestCase):
    def _argv(self, fn):
        """Sample argv for every required parameter, so the verb reaches the handler."""
        return [SAMPLE.get(gen_groups.kind(p.annotation)[0], "x")
                for p in gen_groups.parameters(fn)
                if p.default is p.empty and p.name != "limit"]

    def test_every_verb_calls_its_handler_with_accepted_kwargs(self):
        for area in AREAS:
            for action in domain_map()[area][1]:
                real = real_handler(area, action)
                fake = mock.create_autospec(real, return_value="ok")
                with self.subTest(verb=f"{area} {action}"), stub_dispatcher(lambda a, b: fake):
                    status, out, err = run(area, action, *self._argv(real))
                    self.assertEqual((status, json.loads(out)), (0, "ok"), err)
                    fake.assert_called_once()

    def test_only_supplied_arguments_reach_the_handler(self):
        # task:2cea5538: an omitted flag must not reach the handler, so the handler's
        # own default applies. A copied default goes stale when the handler changes.
        fake = mock.Mock(return_value=[])
        cases = [
            (("podcasts", "recent"), {}),
            (("podcasts", "recent", "--limit", "5"), {"limit": 5}),
            (("podcasts", "episodes", "--podcast-title", "Odd", "--unplayed", "--limit", "5"),
             {"podcast_title": "Odd", "unplayed": True, "limit": 5}),
            (("calendar", "add_event", "t", "2026-11-01T09:00:00"),
             {"title": "t", "start_date": "2026-11-01T09:00:00"}),
            (("calendar", "add_event", "t", "2026-11-01T09:00:00", "--calendar", "Home"),
             {"title": "t", "start_date": "2026-11-01T09:00:00", "calendar": "Home"}),
            (("calendar", "delete_event", "t", "--days", "3"), {"title": "t", "days": 3}),
            (("time", "wait", "2.5"), {"minutes": 2.5}),
            (("system", "process_kill", "42"), {"pid": 42}),
            (("system", "process_kill", "42", "--force"), {"pid": 42, "force": True}),
            (("connector", "execute_action", "gmail.search", "--input", '{"q": "x"}'),
             {"action_id": "gmail.search", "input": {"q": "x"}}),
        ]
        with stub_dispatcher(lambda a, b: fake):
            for argv, kwargs in cases:
                with self.subTest(argv=argv):
                    status, _, err = run(*argv)
                    self.assertEqual(status, 0, err)
                    fake.assert_called_with(**kwargs)

    def test_bad_arguments_are_usage_errors(self):
        fake = mock.Mock()
        with stub_dispatcher(lambda a, b: fake):
            for argv in (("sound", "list_devices", "--type", "bogus"),
                         ("sound", "set_volume", "loud"),
                         ("connector", "execute_action", "a", "--input", "{nope"),
                         ("connector", "execute_action", "a", "--input", "[1]")):
                status, _, err = run(*argv)
                self.assertEqual((status, json.loads(err)["error"]["code"]), (2, "usage"), argv)
        fake.assert_not_called()

    def test_connector_down_is_internal(self):
        # requests' ConnectionError is an OSError; _backend leaves OS errors as 'internal'.
        down = mock.Mock(side_effect=ConnectionError("localhost:3000 refused"))
        with stub_dispatcher(lambda a, b: down):
            status, _, err = run("connector", "health")
        self.assertEqual((status, json.loads(err)["error"]["code"]), (1, "internal"))


@unittest.skipUnless(os.environ.get("MAC_PARITY_LIVE") == "1", "set MAC_PARITY_LIVE=1 to touch the Mac")
class LiveParityTest(unittest.TestCase):
    def cli(self, *argv):
        status, out, err = run(*argv)
        self.assertEqual(status, 0, err)
        return json.loads(out)

    def same(self, area, action, *argv, **kwargs):
        self.assertEqual(self.cli(area, action, *argv), real_handler(area, action)(**kwargs))

    def test_stable_reads_match_handlers(self):
        self.same("sound", "get_output")
        self.same("sound", "list_devices", "--type", "all", type="all")
        self.same("podcasts", "list")
        self.same("music", "list_playlists")
        self.same("contacts", "search", "Debaditya", name="Debaditya")
        self.same("calendar", "list_events", "2026-10-01", "2026-10-31",
                  start_date="2026-10-01", end_date="2026-10-31")
        self.same("calendar", "get_events_by_date", "2026-10-26", date="2026-10-26")
        self.same("system", "icloud_list")
        self.same("system", "sleep_status")
        self.same("market", "gold_regime_history")

    def test_volatile_reads_have_handler_shape(self):
        for area, action in (("system", "battery_status"), ("system", "cpu_status"),
                             ("system", "memory_status"), ("vpn", "status"), ("sound", "get_volume")):
            self.assertEqual(self.cli(area, action).keys(), real_handler(area, action)().keys())

    def test_calendar_add_then_delete_leaves_day_unchanged(self):
        title, cal, day = f"mac-parity-{os.getpid()}", "market-watch", "2026-10-28"
        before = self.cli("calendar", "list_events", day, day, "--limit", "1000")
        self.assertIn("Added", self.cli("calendar", "add_event", title, f"{day}T10:00:00", "--calendar", cal))
        try:
            rows = self.cli("calendar", "list_events", day, day, "--calendar", cal)
            self.assertIn(title, {r["title"] for r in rows})
        finally:
            self.assertIn("Deleted", self.cli("calendar", "delete_event", title, "--calendar", cal))
        self.assertEqual(self.cli("calendar", "list_events", day, day, "--limit", "1000"), before)

    def test_volume_and_mute_restore(self):
        start = self.cli("sound", "get_volume")
        try:
            self.cli("sound", "set_volume", "30")
            self.assertEqual(self.cli("sound", "get_volume")["volume"], 30)
            self.cli("sound", "mute")
            self.assertTrue(self.cli("sound", "get_volume")["muted"])
        finally:
            self.cli("sound", "set_volume", str(start["volume"]))
            self.cli("sound", "mute" if start["muted"] else "unmute")

    def test_clipboard_write_restores(self):
        saved = subprocess.run(["pbpaste"], capture_output=True).stdout
        try:
            self.cli("system", "clipboard_write", "mac-parity")
            self.assertEqual(self.cli("system", "clipboard_read"), "mac-parity")
        finally:
            subprocess.run(["pbcopy"], input=saved)

    def test_process_kill_on_own_child(self):
        child = subprocess.Popen(["sleep", "300"])
        self.addCleanup(child.kill)
        self.assertIn(str(child.pid), self.cli("system", "process_kill", str(child.pid)))
        self.assertIsNotNone(child.wait(timeout=5))

    def test_notify(self):
        self.assertIn("Notification sent", self.cli("system", "notify", "mac parity", "--body", "live test"))

    def test_wait_and_alarm_schedule_at_jobs_that_are_removed(self):
        for argv in (("time", "wait", "600", "--label", "mac-parity"),
                     ("time", "alarm", "23:59", "--label", "mac-parity")):
            message = self.cli(*argv)
            job = re.search(r"job (\d+) at", message)
            self.assertIsNotNone(job, message)
            subprocess.run(["atrm", job.group(1)], check=True)


if __name__ == "__main__":
    unittest.main()
