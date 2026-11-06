"""mac.cli._run logs each verb call into mcp_tool_calls exactly once (task:80010ea1).

A verb routed through local-mac's dispatcher is logged there by tool_called, so
_run must not log it again; every other verb is logged by _run. Logging can
never change a verb's output or exit status.
"""
import io
import json
import os
import unittest
from unittest import mock

from mac.cli import main
from mac.contract import ROUTED, Failure
from mac.registry import Registry


def _registry():
    r = Registry()
    r.verb("native", "make", mode="write", desc="d",
           args=lambda p: p.add_argument("--token"))(lambda ns: {"id": "obj-1"})
    r.verb("native", "big", mode="write", desc="d",
           args=lambda p: p.add_argument("text"))(lambda ns: "ok")

    def fails(ns):
        raise Failure("tool_error", "nope")
    r.verb("native", "fail", mode="write", desc="d")(fails)

    def routed(ns):
        ROUTED.set(True)  # what _backend.call does before dispatcher.invoke
        return "done"
    r.verb("routed", "go", mode="write", desc="d")(routed)
    r.verb("cli_log", "recent", mode="read", desc="d")(lambda ns: [])
    return r


class CallLogTest(unittest.TestCase):
    def setUp(self):
        self.hooks = mock.Mock()
        patches = [
            mock.patch.dict(os.environ, {"MAC_NO_CALL_LOG": ""}),
            mock.patch("mac.groups._backend.tool_hooks", return_value=self.hooks),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_mac(self, *args):
        out, err = io.StringIO(), io.StringIO()
        status = main(list(args), registry=_registry(), out=out, err=err)
        return status, out.getvalue(), err.getvalue()

    def logged(self):
        return [(c.args[:2], c.kwargs) for c in self.hooks.log_call.call_args_list]

    def test_native_success_is_logged_with_args_and_result(self):
        status, out, _ = self.run_mac("native", "make", "--token", "s3cret")
        self.assertEqual((status, json.loads(out)), (0, {"id": "obj-1"}))
        [(names, kw)] = self.logged()
        self.assertEqual(names, ("native", "make"))
        self.assertEqual(self.hooks.log_call.call_args.args[2], {"token": "[redacted]"})
        self.assertEqual((kw["ok"], kw["error"], kw["result"]), (True, None, {"id": "obj-1"}))

    def test_native_failure_is_logged_and_still_fails(self):
        status, _, err = self.run_mac("native", "fail")
        self.assertEqual(status, 1)
        self.assertIn("nope", err)
        [(_, kw)] = self.logged()
        self.assertEqual((kw["ok"], kw["error"]), (False, "tool_error: nope"))

    def test_long_text_is_truncated(self):
        self.run_mac("native", "big", "x" * 500)
        text = self.hooks.log_call.call_args.args[2]["text"]
        self.assertTrue(text.startswith("x" * 200) and text.endswith("[500 chars]"))

    def test_routed_call_is_not_logged_twice(self):
        self.assertEqual(self.run_mac("routed", "go")[0], 0)
        self.assertEqual(self.logged(), [])

    def test_routed_flag_does_not_leak_into_next_call(self):
        self.run_mac("routed", "go")
        self.run_mac("native", "make")
        self.assertEqual([n for n, _ in self.logged()], [("native", "make")])

    def test_reading_the_log_is_not_logged(self):
        self.run_mac("cli_log", "recent")
        self.assertEqual(self.logged(), [])

    def test_logging_failure_changes_nothing(self):
        self.hooks.log_call.side_effect = RuntimeError("db locked")
        status, out, err = self.run_mac("native", "make")
        self.assertEqual((status, json.loads(out), err), (0, {"id": "obj-1"}, ""))

    def test_opt_out_env_disables_logging(self):
        with mock.patch.dict(os.environ, {"MAC_NO_CALL_LOG": "1"}):
            self.run_mac("native", "make")
        self.assertEqual(self.logged(), [])


if __name__ == "__main__":
    unittest.main()
