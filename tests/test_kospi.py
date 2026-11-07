"""`mac kospi`: what reaches stock-tracker-mcp's krx / nifty_kospi_pair modules, and how the JSON comes back."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _helpers import run


class KospiVerbs(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        utils = self.repo / "stock_tracker" / "utils"
        utils.mkdir(parents=True)
        (utils / "krx.py").touch()
        (utils / "nifty_kospi_pair.py").touch()
        env = mock.patch.dict(os.environ, {"MAC_STOCK_TRACKER_DIR": str(self.repo)})
        env.start()
        self.addCleanup(env.stop)

    def call(self, *argv, stdout='{"cmd": "x", "rows": []}'):
        done = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
        with mock.patch("mac.groups.stock.subprocess.run", return_value=done) as sp:
            status, out, err = run("kospi", *argv)
        args = sp.call_args.args[0] if sp.called else None
        return status, out, err, args

    def module_argv(self, args):
        i = args.index("-m")
        return args[i + 1], args[args.index("--json") + 1:]

    def test_krx_verbs_reach_the_krx_module_without_unset_options(self):
        for verb in ("index", "flows", "hold", "backfill"):
            module, argv = self.module_argv(self.call(verb)[3])
            self.assertEqual(module, "stock_tracker.utils.krx")
            self.assertEqual(argv, [verb])

    def test_set_options_are_passed_through(self):
        self.assertEqual(self.module_argv(self.call("flows", "--days", "31")[3])[1], ["flows", "--days", "31"])
        self.assertEqual(self.module_argv(self.call("hold", "--code", "005930", "--days", "5")[3])[1],
                         ["hold", "--code", "005930", "--days", "5"])

    def test_pair_verbs_reach_the_pair_module(self):
        module, argv = self.module_argv(self.call("pair")[3])
        self.assertEqual((module, argv), ("stock_tracker.utils.nifty_kospi_pair", ["pair"]))
        _, argv = self.module_argv(self.call("pair_history", "--sessions", "22")[3])
        self.assertEqual(argv, ["history", "--sessions", "22"])

    def test_the_last_json_line_is_the_result(self):
        status, out, _, _ = self.call("index", stdout='noise\n{"cmd": "index", "rows": [1]}\n')
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)["rows"], [1])

    def test_a_module_error_object_is_a_tool_error(self):
        status, _, err, _ = self.call("flows", stdout='{"error": "URLError: offline"}')
        self.assertNotEqual(status, 0)
        self.assertIn("offline", err)


if __name__ == "__main__":
    unittest.main()
