"""Parity of the generated simple `mac` groups with their local-mac handlers (task:315f6563).

Offline tests check coverage of DOMAIN_MAP, the read/write table, that the
generated modules are current, and that every verb passes arguments the real
handler signature accepts.
"""
import importlib
import json
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
    "time": {"alarm", "wait", "cancel", "play_sound"},
    "connector": {"execute_action"},
    "mail": {"compose", "delete", "move", "add_local_mailbox"},
    "imessage": {"send"},
    "vault": {"write", "append", "delete", "move"},
    "vault_rag": {"index_vault", "index_file", "remove_section"},
}

SAMPLE = {"int": "3", "float": "1.5", "list_int": "3",
          "iso_date": "2026-11-01", "iso_datetime": "2026-11-01T09:00:00"}


def domain_map():
    return _backend.dispatcher().DOMAIN_MAP


def real_handler(area, action):
    try:
        module = importlib.import_module(domain_map()[area][0])
    except ImportError as exc:
        raise unittest.SkipTest(f"{area} handlers need local-mac's dependencies (run under `uv run`): {exc}")
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
                self.skipTest(f"needs local-mac's dependencies (run under `uv run`): {exc}")
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


if __name__ == "__main__":
    unittest.main()
