"""Parity of `mac astrology`, `mac wyckoff` and `mac sysml` with their MCP servers (task:25e053bc).

These verbs run the server's own tool over MCP (mac/groups/_mcp_proxy.py), so
parity is mostly about the two translations around that call:
  - argv -> tool arguments: the right tool, only the arguments given, the
    right JSON types, and every required property reachable;
  - tool result -> mac output: JSON text blocks unwrapped, errors on stderr.

Offline tests stub the proxy. Server-backed tests start the real servers
(skipped when one is not installed): the generated modules match each live
tools/list, and pure-compute verbs return what a direct MCP call returns.
Live tests (MAC_PARITY_LIVE=1) add reads of the private astrology.db.

Never run here: the wyckoff write verbs (update_*, db_init_state,
plot_sr_chart, classify_announcements), which write stock DBs and fetch from
NSE/FINRA/yfinance, and the wyckoff reads that fetch live prices.
"""
import functools
import io
import json
import os
import subprocess
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


@functools.cache
def live_tools(area):
    """tools/list of the area's server, fetched once per test run (each fetch is a server start)."""
    return _mcp_proxy.list_tools(area)

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


def installed(server):
    try:
        _mcp_proxy._check_installed(server, _mcp_proxy.SERVERS[server])
        return True
    except Failure:
        return False


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


def direct(server, calls):
    """[(tool, arguments)] -> the parsed text blocks of each result, from one MCP session.

    Shares only the launch and the JSON-or-text parse with `mac`, not its
    unwrapping: this is what an MCP client gets. The calls share one server
    process, as in an MCP session, so a tool that leans on state an earlier call
    left behind shows up as a mismatch with `mac`, where every call is a fresh
    process.
    """
    async def op(session):
        out = []
        for tool, arguments in calls:
            result = await session.call_tool(tool, arguments)
            out.append([_mcp_proxy._value(b.text) for b in result.content])
        return out
    return _mcp_proxy._run(server, op)


def without_timing(value):
    """sysml reports parse timings in ms, which differ between two runs."""
    if isinstance(value, dict):
        return {k: without_timing(v) for k, v in value.items() if k != "timing"}
    if isinstance(value, list):
        return [without_timing(v) for v in value]
    return value


class ServerTest(unittest.TestCase):
    """Starts the real servers; each area is skipped when its server is not installed."""

    def area(self, area):
        if not installed(area):
            self.skipTest(f"{area} server not installed")
        return area

    def cli(self, *argv):
        status, out, err = run(*argv)
        self.assertEqual(status, 0, err)
        return json.loads(out)

    def test_generated_modules_match_the_live_tool_lists(self):
        for area in AREAS:
            with self.subTest(area=area):
                self.area(area)
                expected = gen_mcp_groups.render(area, live_tools(area))
                actual = gen_mcp_groups.module_path(area).read_text()
                self.assertEqual(actual, expected, f"{area}: rerun tools/gen_mcp_groups.py")

    def test_every_verb_sends_arguments_its_schema_accepts(self):
        sample = {"integer": "3", "number": "1.5", "object": "{}", "boolean": None}
        for area in AREAS:
            self.area(area)
            for tool in live_tools(area):
                schema = tool.inputSchema or {}
                props, required = schema.get("properties", {}), schema.get("required", [])
                file_args = gen_mcp_groups.FILE_ARGS.get(area, ())
                argv = []
                for name in required:
                    prop = props[name]
                    t = next((v.get("type") for v in prop.get("anyOf", [prop]) if v.get("type") != "null"), "string")
                    if name in file_args:
                        argv += [gen_mcp_groups.flag(name), "x"]
                    else:
                        argv.append(sample.get(t, "x"))
                verb = gen_mcp_groups.verb_name(area, tool.name)
                with self.subTest(verb=f"{area} {verb}"), stub_proxy(area, returns={}) as fake:
                    status, _, err = run(area, verb, *argv)
                    self.assertEqual(status, 0, err)
                    (srv, name), arguments = fake.call_args.args, fake.call_args.kwargs
                    self.assertEqual((srv, name), (area, tool.name))
                    self.assertLessEqual(set(arguments), set(props))
                    self.assertEqual(set(required) - set(arguments), set())

    def test_list_result_table_matches_the_handlers(self):
        # Run under each server's own interpreter: its handlers cannot be imported here.
        probes = {
            "astrology": "import importlib, inspect, json, sys; sys.path.insert(0, '.');"
                         "from dispatcher import DOMAIN_MAP;"
                         "print(json.dumps({f'{d}__{a}': str(inspect.signature(getattr("
                         "importlib.import_module(m), 'handle_' + a)).return_annotation)"
                         " for d, (m, acts) in DOMAIN_MAP.items() for a in acts}))",
            "wyckoff": "import inspect, json, sys; sys.path.insert(0, '.');"
                       "import stock_tracker.mcp_server as s;"
                       "print(json.dumps({n: str(inspect.signature(f).return_annotation)"
                       " for n, f in vars(s).items() if inspect.isfunction(f)"
                       " and f.__module__ == s.__name__ and not n.startswith('_')}))",
        }
        for area, code in probes.items():
            with self.subTest(area=area):
                self.area(area)
                server = _mcp_proxy.SERVERS[area]
                out = subprocess.run([server.command, "-c", code], cwd=server.cwd, capture_output=True,
                                     text=True, env=_mcp_proxy._env(), check=True).stdout
                returns = json.loads(out.strip().splitlines()[-1])
                lists = {gen_mcp_groups.verb_name(area, tool) for tool, ann in returns.items() if "list" in ann}
                self.assertEqual(lists, gen_mcp_groups.LIST_RESULT.get(area, set()))

    def test_astrology_pure_compute_matches_mcp(self):
        self.area("astrology")
        calls = [("panchang__date", {"year": 2026, "month": 10, "day": 26}),
                 ("planets__date", {"year": 2026, "month": 10, "day": 26}),
                 ("astrology__mahadasha", {"moon_abs_degree": 45.0, "birth_date": "1990-01-01"}),
                 ("astrology__tarabala", {"janma_nakshatra": 1, "target_nakshatra": 5})]
        expected = [blocks[0] for blocks in direct("astrology", calls)]
        got = [self.cli("astrology", "panchang_date", "2026", "10", "26"),
               self.cli("astrology", "planets_date", "2026", "10", "26"),
               self.cli("astrology", "mahadasha", "45.0", "1990-01-01"),
               self.cli("astrology", "tarabala", "1", "5")]
        self.assertEqual(got, expected)

    def test_wyckoff_static_table_matches_mcp(self):
        self.area("wyckoff")
        [[expected]] = direct("wyckoff", [("signal_weight_table", {})])
        self.assertEqual(self.cli("wyckoff", "signal_weight_table"), expected)

    def test_sysml_matches_mcp(self):
        self.area("sysml")
        calls = [("parse", {"code": SYSML}), ("validate", {"code": SYSML}),
                 ("getSymbols", {"code": SYSML, "definitionsOnly": True}),
                 ("getComplexity", {"code": SYSML}), ("preview", {"code": SYSML})]
        expected = direct("sysml", calls)
        got = [self.cli("sysml", "parse", "--code", SYSML),
               self.cli("sysml", "validate", "--code", SYSML),
               self.cli("sysml", "get_symbols", "--code", SYSML, "--definitions-only"),
               self.cli("sysml", "get_complexity", "--code", SYSML),
               self.cli("sysml", "preview", "--code", SYSML)]
        self.assertEqual(without_timing(got[:4]), without_timing([b[0] for b in expected[:4]]))
        self.assertEqual(got[4], expected[4][-1])  # preview: the data block, without the render instruction

    def test_bin_mac_runs_a_server_verb(self):
        # End to end through bin/mac, so the environment it sets does not break a server start.
        self.area("sysml")
        out = subprocess.run([str(REPO / "bin" / "mac"), "sysml", "get_model_summary", "--code", SYSML],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("documents", json.dumps(json.loads(out.stdout)).lower())


@unittest.skipUnless(os.environ.get("MAC_PARITY_LIVE") == "1", "set MAC_PARITY_LIVE=1 to read astrology.db")
class LiveParityTest(unittest.TestCase):
    def test_astrology_db_reads_match_mcp(self):
        if not installed("astrology"):
            self.skipTest("astrology server not installed")
        calls = [("gochar__summary", {"as_of": "2026-10-26"}),
                 ("aq__upcoming_transitions", {"days": 30, "as_of": "2026-10-26"})]
        summary, transitions = direct("astrology", calls)
        expected = [summary[0], transitions]  # a list comes back as one block per item
        got = []
        for argv in (["gochar_summary", "--as-of", "2026-10-26"],
                     ["aq_upcoming_transitions", "--days", "30", "--as-of", "2026-10-26"]):
            status, out, err = run("astrology", *argv)
            self.assertEqual(status, 0, err)
            got.append(json.loads(out))
        self.assertEqual(got, expected)


if __name__ == "__main__":
    unittest.main()
