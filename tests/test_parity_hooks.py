"""`mac memory`, `mac vault_map` and `mac hooks` (task:5ab623ca).

These wrap claude-hooks' handlers through mac/groups/_hooks.py. Here: the exact
kwargs each verb forwards, the structured --links/--memories forms, the write
modes, and a live round trip against a *copy* of MEMORY.sqlite (never the real
one) showing that a re-add which passes `related` keeps it and one that omits it
resets it, as the MCP tool does.

scratch and think are not ported: scratch is a dict inside the long-lived MCP
server, so a per-call process would lose every value, and think echoes its input.
Neither was ever called (task:5ab623ca decision).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parent.parent), str(Path(__file__).resolve().parent)]

from mac.cli import default_registry, main
from mac.groups import _hooks
import io


def run(*argv, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch("sys.stdin", io.StringIO(stdin or "")):
        status = main(list(argv), default_registry(), out, err)
    return status, out.getvalue(), err.getvalue()


class ForwardingTest(unittest.TestCase):
    CASES = [
        (["memory", "add", "s", "--type", "user", "--body", "b"], "memory", "add",
         {"name": "s", "type": "user", "body": "b"}),
        (["memory", "add", "s", "--type", "feedback", "--body", "b", "--tags", "t", "--related", "a,b",
          "--links", '[{"to":"a","type":"extends"}]'], "memory", "add",
         {"name": "s", "type": "feedback", "body": "b", "tags": "t", "related": "a,b",
          "links": [{"to": "a", "type": "extends"}]}),
        (["memory", "add_batch", "--memories", '[{"name":"x","type":"user","body":"y"}]'], "memory", "add_batch",
         {"memories": [{"name": "x", "type": "user", "body": "y"}]}),
        (["memory", "search", "q", "--type", "project", "--detail", "full"], "memory", "search",
         {"query": "q", "type": "project", "detail": "full"}),
        (["memory", "list"], "memory", "list", {}),
        (["memory", "get", "s"], "memory", "get", {"name": "s"}),
        (["memory", "tool_hints", "--top-n", "5"], "memory", "tool_hints", {"top_n": 5}),
        (["memory", "read_compact", "sid"], "memory", "read_compact", {"session_id": "sid"}),
        (["memory", "delete", "s"], "memory", "delete", {"name": "s"}),
        (["memory", "stale", "--unhit-days", "9", "--limit", "3"], "memory", "stale",
         {"unhit_days": 9, "limit": 3}),
        (["memory", "validate", "a", "b"], "memory", "validate", {"names": ["a", "b"]}),
        (["vault_map", "overview", "--dir", "Market", "--depth", "2"], "vault_map", "overview",
         {"dir": "Market", "depth": 2}),
        (["vault_map", "node", "n"], "vault_map", "node", {"id": "n"}),
        (["vault_map", "tag", "t"], "vault_map", "tag", {"tag": "t"}),
        (["vault_map", "find", "q", "--limit", "4"], "vault_map", "find", {"query": "q", "limit": 4}),
        (["hooks", "server_memory", "--n-events", "7"], "hooks", "server_memory", {"n_events": 7}),
        (["hooks", "session_id"], "hooks", "session_id", {}),
        (["hooks", "checkpoint_query", "--thread-id", "t"], "hooks", "checkpoint_query", {"thread_id": "t"}),
        (["hooks", "read_logs_sqlite", "--level", "ERROR", "--search", "x", "--format", "json"], "hooks",
         "read_logs_sqlite", {"level": "ERROR", "search": "x", "format": "json"}),
    ]

    def test_each_verb_forwards_exactly_what_was_given(self):
        for argv, module, action, kwargs in self.CASES:
            with self.subTest(argv=argv), mock.patch(f"mac.groups.{argv[0]}.call", return_value={"ok": 1}) as call:
                status, out, _ = run(*argv)
                self.assertEqual(status, 0, out)
                call.assert_called_once_with(module, action, **kwargs)

    def test_body_and_memories_can_come_from_stdin(self):
        with mock.patch("mac.groups.memory.call", return_value={"ok": 1}) as call:
            run("memory", "add", "s", "--type", "user", "--body-file", "-", stdin="multi\nline")
            call.assert_called_once_with("memory", "add", name="s", type="user", body="multi\nline")
        with mock.patch("mac.groups.memory.call", return_value={"ok": 1}) as call:
            run("memory", "add_batch", "--memories-file", "-", stdin='[{"name":"x"}]')
            call.assert_called_once_with("memory", "add_batch", memories=[{"name": "x"}])

    def test_usage_errors_before_any_call(self):
        with mock.patch("mac.groups.memory.call") as call:
            for argv in (["memory", "add", "s", "--type", "user"],
                         ["memory", "add", "s", "--type", "bogus", "--body", "b"],
                         ["memory", "add", "s", "--type", "user", "--body", "b", "--body-file", "-"],
                         ["memory", "add", "s", "--type", "user", "--body", "b", "--links", "{}"],
                         ["memory", "add_batch", "--memories", "{}"],
                         ["memory", "add_batch"]):
                with self.subTest(argv=argv):
                    self.assertEqual(run(*argv, stdin="x")[0], 2)
            call.assert_not_called()


class ModesTest(unittest.TestCase):
    def test_write_verbs_are_marked_write(self):
        modes = {(v.area, v.name): v.mode for a in ("memory", "vault_map", "hooks")
                 for v in default_registry().verbs(a)}
        self.assertEqual({k for k, m in modes.items() if m == "write"},
                         {("memory", "add"), ("memory", "add_batch"), ("memory", "delete"),
                          ("memory", "validate")})

    def test_scratch_and_think_are_not_ported(self):
        areas = default_registry().areas()
        self.assertNotIn("scratch", areas)
        self.assertNotIn("think", areas)


class BackendFailureTest(unittest.TestCase):
    def test_missing_interpreter_is_backend_missing(self):
        with mock.patch.dict(os.environ, {"MAC_HOOKS_ROOT": "/nonexistent-claude-hooks"}):
            status, _, err = run("hooks", "session_id")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "backend_missing")


@unittest.skipUnless((_hooks.DEFAULT_ROOT / ".venv/bin/python").exists()
                     and (Path.home() / ".claude/MEMORY.sqlite").exists(), "needs claude-hooks and MEMORY.sqlite")
class MemoryRoundTripTest(unittest.TestCase):
    """Runs the real handlers against a copy of MEMORY.sqlite."""

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copy(Path.home() / ".claude/MEMORY.sqlite", Path(tmp) / "MEMORY.sqlite")
        patcher = mock.patch.dict(os.environ, {"CLAUDE_HOOKS_MEMORY_DB": str(Path(tmp) / "MEMORY.sqlite")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, name):
        status, out, err = run("memory", "get", name)
        self.assertEqual(status, 0, err)
        return json.loads(out)

    def test_re_add_that_passes_related_keeps_it_and_one_that_omits_it_resets_it(self):
        run("memory", "add", "zz-parity-a", "--type", "reference", "--body", "a")
        status, _, err = run("memory", "add", "zz-parity-b", "--type", "reference", "--body", "b",
                             "--related", "zz-parity-a", "--links", '[{"to":"zz-parity-a","type":"extends"}]')
        self.assertEqual(status, 0, err)
        first = self.get("zz-parity-b")
        self.assertEqual(first["related"], "zz-parity-a")
        self.assertIn(("extends", "zz-parity-a"), [(link["type"], link["name"]) for link in first["links"]])

        run("memory", "add", "zz-parity-b", "--type", "reference", "--body", "b2", "--related", "zz-parity-a")
        again = self.get("zz-parity-b")
        self.assertEqual((again["body"], again["related"]), ("b2", "zz-parity-a"))

        run("memory", "add", "zz-parity-b", "--type", "reference", "--body", "b3")
        self.assertEqual(self.get("zz-parity-b")["related"], "")

    def test_handler_error_is_tool_error(self):
        status, _, err = run("memory", "get", "zz-no-such-memory")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "tool_error")

    def test_add_batch_and_delete(self):
        status, out, err = run("memory", "add_batch", "--memories-file", "-",
                               stdin='[{"name":"zz-parity-c","type":"reference","body":"c"}]')
        self.assertEqual(status, 0, err)
        self.assertEqual(json.loads(out)["count"], 1)
        self.assertEqual(json.loads(run("memory", "delete", "zz-parity-c")[1])["deleted"], "zz-parity-c")


if __name__ == "__main__":
    unittest.main()
