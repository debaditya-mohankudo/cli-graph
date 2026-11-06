"""`mac graph_metrics`: what reaches graph_metrics, and how its JSON comes back (task:a7ff9fc6)."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _helpers import run


class MetricsVerbs(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        (self.repo / "stock_tracker" / "utils").mkdir(parents=True)
        (self.repo / "stock_tracker" / "utils" / "graph_metrics.py").touch()
        env = mock.patch.dict(os.environ, {"MAC_STOCK_TRACKER_DIR": str(self.repo)})
        env.start()
        self.addCleanup(env.stop)

    def call(self, *argv, stdout='{"cmd": "x", "rows": 0}', returncode=0):
        done = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")
        with mock.patch("mac.groups.stock.subprocess.run", return_value=done) as sp:
            status, out, err = run("graph_metrics", *argv)
        args = sp.call_args.args[0] if sp.called else None
        # everything after `-m <module> --json` is graph_metrics' own argv
        return status, out, err, (args[args.index("--json") + 1:] if args else None)

    def test_unset_options_are_not_passed_so_graph_metrics_keeps_its_defaults(self):
        self.assertEqual(self.call("load_kalshi")[3], ["load-kalshi"])
        self.assertEqual(self.call("load_treasury_par")[3], ["load-treasury-par"])
        self.assertEqual(self.call("latest")[3], ["latest"])
        self.assertEqual(self.call("freshness")[3], ["freshness"])
        self.assertEqual(self.call("series", "us_treasury_yields")[3], ["series", "us_treasury_yields"])

    def test_set_options_are_passed_through(self):
        self.assertEqual(self.call("load_fed", "--start", "2026-10-01")[3], ["load-fed", "--start", "2026-10-01"])
        self.assertEqual(self.call("freshness", "--stale-only", "--node", "par")[3],
                         ["freshness", "--stale-only", "--node", "par"])
        self.assertEqual(self.call("record", "n", "m", "2026-11-05", "4.5", "pct", "src",
                                   "--confidence", "primary")[3],
                         ["record", "n", "m", "2026-11-05", "4.5", "pct", "src", "--confidence", "primary"])

    def test_rows_maps_to_graph_metrics_limit(self):
        # mac's own --limit caps list results, so series' row cap is --rows on the verb
        self.assertEqual(self.call("series", "n", "--rows", "5")[3], ["series", "n", "--limit", "5"])

    def test_file_arguments_are_made_absolute(self):
        # graph_metrics runs with cwd = its repo, where the caller's relative path means nothing
        argv = self.call("ingest_fred", "pull.json")[3]
        self.assertEqual(argv, ["ingest-fred", str(Path("pull.json").resolve())])

    def test_the_last_json_line_is_the_result(self):
        status, out, _, _ = self.call("load_us_open", stdout='yfinance noise\n{"cmd": "load-us-open", "rows": 7}\n')
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out)["rows"], 7)

    def test_a_graph_metrics_error_object_is_a_tool_error(self):
        status, _, err, _ = self.call("record", "bogus", "m", "2026-11-05", "1", "pct", "s",
                                      stdout='{"cmd": "record", "error": "ValueError: pass --graph-file"}',
                                      returncode=1)
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "tool_error")
        self.assertIn("pass --graph-file", json.loads(err)["error"]["message"])

    def test_no_output_is_a_tool_error(self):
        status, _, err, _ = self.call("freshness", stdout="", returncode=1)
        self.assertEqual((status, json.loads(err)["error"]["code"]), (1, "tool_error"))

    def test_missing_repo_is_backend_missing(self):
        with mock.patch.dict(os.environ, {"MAC_STOCK_TRACKER_DIR": str(self.repo / "nope")}):
            status, _, err, argv = self.call("freshness")
        self.assertEqual((status, json.loads(err)["error"]["code"], argv), (1, "backend_missing", None))


if __name__ == "__main__":
    unittest.main()
