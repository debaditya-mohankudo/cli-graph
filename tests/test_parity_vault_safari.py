"""`mac vault` / `mac safari`: vault containment and the safari tab guard (task:0c64fa90).

vault is generated, so its coverage, modes and freshness are checked with the
other generated groups in test_parity_simple_groups.py. Here: a path outside the
vault comes back as 'blocked', and content starting with '-' gets through after `--`.

safari is hand-written so it can enforce the tab guard: every verb acting on the
front tab requires --expect-host and refuses with 'blocked' when the front tab's
host does not match. These tests pin coverage, modes, exact forwarded kwargs and
the guard, offline with stubbed handlers.

Live tests (MAC_PARITY_LIVE=1) compare vault reads with the handlers, write,
append, move and delete a note in a scratch folder, and open example.com in a
new Safari window, read it through the guard and close it. Never run live:
safari close_all_tabs, and any guarded verb on a tab these tests did not open.
"""
import importlib
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parent.parent), str(Path(__file__).resolve().parent)]

from _helpers import run, stub_dispatcher
from mac.cli import default_registry, describe
from mac.groups import _backend
from mac.groups.safari import host_matches

GUARDED = {"navigate", "close_tab", "reload", "back", "forward", "js", "read", "screenshot"}
# Reviewed by hand, like the WRITE tables for the generated groups.
SAFARI_WRITE = {"open", "navigate", "js", "close_tab", "close_all_tabs", "reload", "back", "forward"}


def handler_module(area):
    try:
        return importlib.import_module(_backend.dispatcher().DOMAIN_MAP[area][0])
    except ImportError as exc:
        raise unittest.SkipTest(f"{area} handlers need local-mac's dependencies (run under `uv run`): {exc}")


class FakeSafari:
    """Stub dispatcher target: current_url returns `front`; every other call is recorded."""

    def __init__(self, front="https://www.example.com/page"):
        self.front = front
        self.calls = []

    def resolve(self, area, action):
        if action == "current_url":
            return lambda: self.front

        def handler(**kwargs):
            self.calls.append((action, kwargs))
            return "ok"
        return handler


class SafariCoverageTest(unittest.TestCase):
    def test_every_domain_map_tool_has_a_verb_with_the_right_mode(self):
        verbs = {e["verb"]: e["mode"] for e in describe(default_registry(), "safari")}
        self.assertEqual(set(verbs), set(_backend.dispatcher().DOMAIN_MAP["safari"][1]))
        self.assertEqual({v for v, m in verbs.items() if m == "write"}, SAFARI_WRITE)

    def test_guarded_verbs_require_expect_host(self):
        usage = {e["verb"]: e["usage"] for e in describe(default_registry(), "safari")}
        for verb, line in usage.items():
            with self.subTest(verb=verb):
                self.assertEqual("--expect-host HOST" in line and "[--expect-host" not in line,
                                 verb in GUARDED, line)

    def test_every_verb_passes_kwargs_the_real_handler_accepts(self):
        module = handler_module("safari")
        argv = {"open": ["https://example.com"], "navigate": ["https://example.com"],
                "js": ["1+1"], "read": ["title"]}
        for action in _backend.dispatcher().DOMAIN_MAP["safari"][1]:
            real = getattr(module, f"handle_{action}")
            fake = mock.create_autospec(real, return_value="ok")
            front = mock.Mock(return_value="https://example.com/")
            pick = lambda a, b: front if b == "current_url" and action != "current_url" else fake
            guard = ["--expect-host", "example.com"] if action in GUARDED else []
            with self.subTest(verb=action), stub_dispatcher(pick):
                status, out, err = run("safari", action, *argv.get(action, []), *guard)
                self.assertEqual((status, json.loads(out)), (0, "ok"), err)
                fake.assert_called_once()


class SafariForwardingTest(unittest.TestCase):
    CASES = [
        (["open", "https://a.com"], "open", {"url": "https://a.com"}),
        (["open", "https://a.com", "--new-window"], "open", {"url": "https://a.com", "new_window": True}),
        (["list_tabs"], "list_tabs", {}),
        (["close_all_tabs"], "close_all_tabs", {}),
        (["navigate", "https://b.com", "--expect-host", "example.com"], "navigate", {"url": "https://b.com"}),
        (["js", "document.title", "--expect-host", "example.com"], "js", {"js": "document.title"}),
        (["read", "text", "--expect-host", "example.com"], "read", {"mode": "text"}),
        (["screenshot", "--expect-host", "example.com"], "screenshot", {}),
        (["screenshot", "--outfile", "/tmp/x.png", "--expect-host", "example.com"], "screenshot",
         {"outfile": "/tmp/x.png"}),
        (["close_tab", "--expect-host", "example.com"], "close_tab", {}),
        (["reload", "--expect-host", "example.com"], "reload", {}),
        (["back", "--expect-host", "example.com"], "back", {}),
        (["forward", "--expect-host", "example.com"], "forward", {}),
    ]

    def test_only_supplied_args_reach_the_handler(self):
        for argv, action, kwargs in self.CASES:
            with self.subTest(argv=argv):
                fake = FakeSafari()
                with stub_dispatcher(fake.resolve):
                    status, _, err = run("safari", *argv)
                self.assertEqual(status, 0, err)
                self.assertEqual(fake.calls, [(action, kwargs)])


class SafariGuardTest(unittest.TestCase):
    def test_missing_expect_host_is_a_usage_error_and_runs_nothing(self):
        for verb, extra in (("navigate", ["https://b.com"]), ("js", ["1"]), ("read", ["text"]),
                            ("screenshot", []), ("close_tab", []), ("reload", []),
                            ("back", []), ("forward", [])):
            with self.subTest(verb=verb):
                fake = FakeSafari()
                with stub_dispatcher(fake.resolve):
                    status, _, err = run("safari", verb, *extra)
                self.assertEqual((status, json.loads(err)["error"]["code"]), (2, "usage"))
                self.assertEqual(fake.calls, [])

    def test_wrong_front_tab_is_blocked_and_the_action_never_runs(self):
        # The 2026-10-15 failure: js meant for FRED ran in the user's YouTube tab.
        fake = FakeSafari(front="https://www.youtube.com/watch?v=x")
        with stub_dispatcher(fake.resolve):
            status, _, err = run("safari", "js", "window.x=1", "--expect-host", "fred.stlouisfed.org")
        error = json.loads(err)["error"]
        self.assertEqual((status, error["code"]), (1, "blocked"))
        self.assertIn("youtube.com", error["message"])
        self.assertEqual(fake.calls, [])

    def test_no_front_tab_url_is_blocked(self):
        fake = FakeSafari(front="")
        with stub_dispatcher(fake.resolve):
            status, _, err = run("safari", "close_tab", "--expect-host", "example.com")
        self.assertEqual((status, json.loads(err)["error"]["code"]), (1, "blocked"))
        self.assertEqual(fake.calls, [])

    def test_host_matching(self):
        yes = [("https://example.com/", "example.com"), ("https://www.example.com", "example.com"),
               ("https://example.com", "www.example.com"), ("https://fred.stlouisfed.org/x", "stlouisfed.org"),
               ("https://EXAMPLE.com\n", "example.com"), ("https://a.example.com:8443/p", "example.com")]
        no = [("https://evil-example.com", "example.com"), ("https://example.com.evil.io", "example.com"),
              ("https://example.com", "fred.example.com"), ("about:blank", "example.com"),
              ("", "example.com"), ("https://example.com", "")]
        for url, want in yes:
            self.assertTrue(host_matches(url, want), (url, want))
        for url, want in no:
            self.assertFalse(host_matches(url, want), (url, want))


class VaultTest(unittest.TestCase):
    def test_path_outside_the_vault_is_blocked(self):
        module = handler_module("vault")
        with stub_dispatcher(lambda a, b: getattr(module, f"handle_{b}")):
            for argv in (("read", "../../../etc/passwd"), ("write", "/tmp/escape", "x"),
                         ("filename_search", "x", "--folder", "../..")):
                with self.subTest(argv=argv):
                    status, _, err = run("vault", *argv)
                    self.assertEqual((status, json.loads(err)["error"]["code"]), (1, "blocked"), err)
        self.assertFalse(Path("/tmp/escape.md").exists())

    def test_content_starting_with_a_dash_passes_after_double_dash(self):
        fake = mock.Mock(return_value="ok")
        with stub_dispatcher(lambda a, b: fake):
            status, _, err = run("vault", "append", "Inbox", "--", "- [ ] buy milk")
        self.assertEqual(status, 0, err)
        fake.assert_called_once_with(path="Inbox", content="- [ ] buy milk")


@unittest.skipUnless(os.environ.get("MAC_PARITY_LIVE") == "1", "set MAC_PARITY_LIVE=1 to touch the Mac")
class LiveParityTest(unittest.TestCase):
    SCRATCH = "_cli-graph-parity"

    def cli(self, *argv):
        status, out, err = run(*argv)
        self.assertEqual(status, 0, err)
        return json.loads(out)

    def test_vault_reads_match_handlers(self):
        module = handler_module("vault")
        self.assertEqual(self.cli("vault", "stats"), module.handle_stats())
        self.assertEqual(self.cli("vault", "list"), module.handle_list())
        self.assertEqual(self.cli("vault", "tags_search", "--limit", "10"), module.handle_tags_search(limit=10))
        self.assertEqual(self.cli("vault", "filename_search", "daily"), module.handle_filename_search(query="daily"))

    def test_vault_write_append_move_delete_in_scratch_folder(self):
        module = handler_module("vault")
        note, moved = f"{self.SCRATCH}/note", f"{self.SCRATCH}/moved"
        folder = module.VAULT_PATH / self.SCRATCH
        self.addCleanup(lambda: [p.unlink() for p in folder.glob("*.md")] and None)
        self.addCleanup(lambda: folder.exists() and not any(folder.iterdir()) and folder.rmdir())
        self.cli("vault", "write", note, "# parity\n")
        self.cli("vault", "append", note, "--", "- line")
        self.assertEqual(self.cli("vault", "read", note), module.handle_read(path=note))
        self.assertIn("- line", self.cli("vault", "read", note))
        self.cli("vault", "move", note, moved)
        self.cli("vault", "delete", moved)
        self.assertEqual(list(folder.glob("*.md")), [])

    def test_safari_guard_on_a_window_of_our_own(self):
        self.cli("safari", "open", "https://example.com/", "--new-window")
        for _ in range(20):  # wait for the page to load
            if host_matches(self.cli("safari", "current_url"), "example.com"):
                break
            time.sleep(0.5)
        status, _, err = run("safari", "read", "title", "--expect-host", "not-this-host.org")
        self.assertEqual((status, json.loads(err)["error"]["code"]), (1, "blocked"))
        self.assertIn("Example", self.cli("safari", "read", "title", "--expect-host", "example.com"))
        self.cli("safari", "close_tab", "--expect-host", "example.com")
