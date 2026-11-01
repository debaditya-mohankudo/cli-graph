"""Parity of `mac astrology`, `mac wyckoff` and `mac sysml` with their MCP servers (task:25e053bc).

These verbs run the server's own tool over MCP (mac/groups/_mcp_proxy.py), so
parity is mostly about the two translations around that call:
  - argv -> tool arguments: the right tool, only the arguments given, the
    right JSON types, and every required property reachable;
  - tool result -> mac output: JSON text blocks unwrapped, errors on stderr.

These servers are permanently CLI-only, so there is no MCP counterpart to
compare against: every test stubs the proxy and starts no server.
"""
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO), str(REPO / "tools"), str(REPO / "tests")]

import gen_mcp_groups
from _helpers import run
from mac.cli import default_registry, describe
from mac.contract import Failure
from mac.groups import _mcp_proxy

AREAS = gen_mcp_groups.AREAS


# Reviewed independently of gen_mcp_groups.WRITE: a verb must not turn read by an edit there.
WRITE = {
    "wyckoff": {"plot_sr_chart", "db_init_state", "update_run", "update_delivery",
                "update_fno", "update_short_volume", "classify_announcements"},
}

SYSML = "package P {\n  part def A;\n  part def B { part a : A; }\n}\n"


def text_result(*texts, is_error=False):
    blocks = [types.SimpleNamespace(type="text", text=t) for t in texts]
    return types.SimpleNamespace(content=blocks, isError=is_error)


def stub_proxy(area, returns="ok"):
    """Replace call_tool in the generated module for `area`; data_block keeps working on what it returns."""
    return mock.patch(f"mac.groups.{area}.call_tool", return_value=returns)


class UnwrapTest(unittest.TestCase):
    def test_one_json_block_is_the_result(self):
        self.assertEqual(_mcp_proxy.unwrap(text_result('{"a": 1}')), {"a": 1})
        self.assertEqual(_mcp_proxy.unwrap(text_result("[1, 2]")), [1, 2])

    def test_non_json_text_stays_a_string(self):
        self.assertEqual(_mcp_proxy.unwrap(text_result("plain words")), "plain words")

    def test_several_blocks_become_a_list(self):
        self.assertEqual(_mcp_proxy.unwrap(text_result("note", '{"a": 1}')), ["note", {"a": 1}])

    def test_is_error_is_a_tool_error(self):
        with self.assertRaises(Failure) as caught:
            _mcp_proxy.unwrap(text_result("Error executing tool x: boom", is_error=True))
        self.assertEqual((caught.exception.code, caught.exception.message),
                         ("tool_error", "Error executing tool x: boom"))

    def test_error_key_is_a_tool_error(self):
        with self.assertRaises(Failure) as caught:
            _mcp_proxy.unwrap(text_result('{"status": "error", "error": "no such slug"}'))
        self.assertEqual((caught.exception.code, caught.exception.message), ("tool_error", "no such slug"))

    def test_as_list_restores_a_one_item_list(self):
        self.assertEqual(_mcp_proxy.as_list({"a": 1}), [{"a": 1}])
        self.assertEqual(_mcp_proxy.as_list([{"a": 1}, {"a": 2}]), [{"a": 1}, {"a": 2}])
        self.assertEqual(_mcp_proxy.as_list([]), [])

    def test_data_block_drops_text_for_the_model(self):
        self.assertEqual(_mcp_proxy.data_block(["call renderMermaidDiagram", {"mermaidMarkup": "m"}]),
                         {"mermaidMarkup": "m"})

    def test_data_block_with_no_json_is_a_tool_error(self):
        with self.assertRaises(Failure) as caught:
            _mcp_proxy.data_block("No SysML source is available to visualise.")
        self.assertEqual(caught.exception.code, "tool_error")


class LaunchTest(unittest.TestCase):
    def test_cli_graph_python_settings_do_not_reach_the_server(self):
        with mock.patch.dict(os.environ, {"PYTHONPATH": "/cli-graph", "VIRTUAL_ENV": "/v", "KEEP": "k"}):
            env = _mcp_proxy._env()
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("VIRTUAL_ENV", env)
        self.assertEqual(env["KEEP"], "k")

    def test_missing_interpreter_is_backend_missing(self):
        gone = _mcp_proxy.Server(command="/nonexistent/python", args=("/nonexistent/server.py",))
        with mock.patch.dict(_mcp_proxy.SERVERS, {"astrology": gone}):
            status, out, err = run("astrology", "panchang_today")
        self.assertEqual((status, out), (1, ""))
        self.assertEqual(json.loads(err)["error"]["code"], "backend_missing")

    def test_a_server_that_dies_is_backend_missing_with_its_stderr(self):
        dies = _mcp_proxy.Server(command=sys.executable, args=("-c", "import sys; sys.exit('kaput')"))
        with mock.patch.dict(_mcp_proxy.SERVERS, {"sysml": dies}):
            with self.assertRaises(Failure) as caught:
                _mcp_proxy.call_tool("sysml", "parse", code="x")
        self.assertEqual(caught.exception.code, "backend_missing")
        self.assertIn("kaput", caught.exception.message)


class CoverageTest(unittest.TestCase):
    def test_modes_match_the_reviewed_write_table(self):
        entries = describe(default_registry())
        for area in AREAS:
            verbs = {e["verb"]: e["mode"] for e in entries if e["area"] == area}
            self.assertTrue(verbs, area)
            writes = {v for v, mode in verbs.items() if mode == "write"}
            self.assertEqual(writes, WRITE.get(area, set()), area)

    def test_verb_names(self):
        cases = [("astrology", "astrology__d9", "d9"), ("astrology", "panchang__today", "panchang_today"),
                 ("astrology", "aq__current_dasha", "aq_current_dasha"),
                 ("sysml", "getModelSummary", "get_model_summary"), ("wyckoff", "next_step", "next_step")]
        for area, tool, verb in cases:
            self.assertEqual(gen_mcp_groups.verb_name(area, tool), verb)


class ForwardingTest(unittest.TestCase):
    CASES = [
        (["astrology", "panchang_today"], "panchang__today", {}),
        (["astrology", "panchang_date", "2026", "10", "26", "--lat", "19.07"], "panchang__date",
         {"year": 2026, "month": 10, "day": 26, "lat": 19.07}),
        (["astrology", "tarabala", "4", "Rohini"], "astrology__tarabala",
         {"janma_nakshatra": 4, "target_nakshatra": "Rohini"}),
        (["astrology", "d9", '{"Sun": 10.5}'], "astrology__d9", {"planets": {"Sun": 10.5}}),
        (["astrology", "aq_current_dasha", "someone", "--as-of", "2026-01-01"], "aq__current_dasha",
         {"person": "someone", "as_of": "2026-01-01"}),
        (["astrology", "gochar_summary"], "gochar__summary", {}),
        (["wyckoff", "next_step", "tcs", "--done", "step_0", "step_1"], "next_step",
         {"slug": "tcs", "done": ["step_0", "step_1"]}),
        (["wyckoff", "classify_announcements", "tcs", "--items", '[{"headline": "h"}]', "--threshold", "0.5"],
         "classify_announcements", {"slug": "tcs", "items": [{"headline": "h"}], "threshold": 0.5}),
        (["wyckoff", "update_short_volume", "aapl", "--backfill-sessions", "3"], "update_short_volume",
         {"slug": "aapl", "backfill_sessions": 3}),
        (["wyckoff", "signal_weight_table"], "signal_weight_table", {}),
        (["sysml", "get_symbols", "--kind", "part def", "--definitions-only"], "getSymbols",
         {"kind": "part def", "definitionsOnly": True}),
        (["sysml", "parse", "--code", "package P;"], "parse", {"code": "package P;"}),
        (["sysml", "get_definition", "A", "--uri", "m.sysml"], "getDefinition", {"name": "A", "uri": "m.sysml"}),
    ]

    def test_only_supplied_arguments_reach_the_tool(self):
        for argv, tool, arguments in self.CASES:
            with self.subTest(argv=argv), stub_proxy(argv[0]) as fake:
                status, out, err = run(*argv)
                self.assertEqual(status, 0, err)
                fake.assert_called_once_with(argv[0], tool, **arguments)

    def test_code_file_and_stdin(self):
        path = REPO / "tests" / "_tmp_model.sysml"
        path.write_text(SYSML)
        self.addCleanup(path.unlink)
        with stub_proxy("sysml", returns={}) as fake:
            self.assertEqual(run("sysml", "validate", "--code-file", str(path))[0], 0)
            fake.assert_called_with("sysml", "validate", code=SYSML)
            with mock.patch("sys.stdin", io.StringIO("package S;")):
                self.assertEqual(run("sysml", "parse", "--code-file", "-")[0], 0)
            fake.assert_called_with("sysml", "parse", code="package S;")
            self.assertEqual(run("sysml", "preview", "--original-code-file", str(path))[0], 0)
            fake.assert_called_with("sysml", "preview", originalCode=SYSML)

    def test_code_usage_errors(self):
        with stub_proxy("sysml") as fake:
            for argv in (["sysml", "parse"],
                         ["sysml", "parse", "--code", "x", "--code-file", "-"],
                         ["sysml", "parse", "--code-file", "/nonexistent/m.sysml"],
                         ["sysml", "preview", "--diagram-type", "bogus"],
                         ["astrology", "d9", "[1]"],
                         ["wyckoff", "classify_announcements", "s", "--items", '{"a": 1}']):
                with self.subTest(argv=argv):
                    status, _, err = run(*argv)
                    self.assertEqual((status, json.loads(err)["error"]["code"]), (2, "usage"))
            fake.assert_not_called()

    def test_a_list_tool_returning_one_item_is_still_a_list(self):
        with stub_proxy("astrology", returns={"planet": "Moon"}):
            status, out, err = run("astrology", "aq_vargottama", "someone")
        self.assertEqual((status, json.loads(out)), (0, [{"planet": "Moon"}]), err)
        with stub_proxy("astrology", returns={"tithi": 1}):
            self.assertEqual(json.loads(run("astrology", "panchang_today")[1]), {"tithi": 1})

    def test_preview_returns_only_the_data_block(self):
        with stub_proxy("sysml", returns=["ACTION REQUIRED: call renderMermaidDiagram", {"mermaidMarkup": "m"}]):
            status, out, err = run("sysml", "preview", "--code", "package P;")
        self.assertEqual((status, json.loads(out)), (0, {"mermaidMarkup": "m"}), err)


if __name__ == "__main__":
    unittest.main()
