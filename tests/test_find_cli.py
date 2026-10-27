"""find_cli: BM25 seeds plus edge expansion over the committed graph (task:129f1bc3).

Imports only find_cli, rank and expand at module level; the server test needs
the `mcp` package and skips without it (run it under `uv run`).
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import find_cli
from find_cli import expand, rank
from graph.validate_edges import command_ids


def cmd(area, verb, desc, mode="read"):
    cid = f"mac {area} {verb}"
    return {"id": cid, "kind": "command", "cli": "mac", "area": area, "verb": verb,
            "mode": mode, "desc": desc, "usage": cid, "domain": f"domain:{area}"}


def toy_graph(*commands):
    nodes = list(commands)
    for area in sorted({c["area"] for c in commands}):
        nodes.append({"id": f"domain:{area}", "kind": "domain", "name": area})
    return {"nodes": nodes, "edges": [
        {"from": c["id"], "to": c["domain"], "type": "in_domain"} for c in commands]}


TOY = toy_graph(
    cmd("imessage", "send", "send an iMessage", "write"),
    cmd("imessage", "read", "read recent iMessages"),
    cmd("contacts", "search", "search contacts by name"),
    cmd("contacts", "get", "get one contact"),
    cmd("vault", "read", "read a vault note"),
    cmd("vault", "outline", "headings of a vault note"),
    cmd("vault", "write", "write a vault note", "write"),
    cmd("vault", "tags", "list vault tags"),
    cmd("vault", "stats", "vault statistics"),
)
TOY_EDGES = [
    {"from": "mac imessage send", "type": "requires", "to": "mac contacts search"},
    {"from": "mac vault outline", "type": "feeds", "to": "mac vault read"},
    {"from": "mac imessage text", "type": "alias_of", "to": "mac imessage send"},
]


class RankTest(unittest.TestCase):
    def test_tokens_split_underscores_and_drop_stopwords(self):
        self.assertEqual(rank.tokens("Get_Events by the Date!"), ["get", "events", "date"])

    def test_best_match_is_first_and_zero_scores_are_dropped(self):
        got = rank.seeds("read vault note", TOY, TOY_EDGES)
        self.assertEqual(got[0][0], "mac vault read")
        self.assertTrue(all(s > 0 for _, s in got))
        self.assertNotIn("mac contacts get", [c for c, _ in got])

    def test_alias_name_finds_its_canonical_command_and_is_never_returned(self):
        got = [c for c, _ in rank.seeds("text", TOY, TOY_EDGES)]
        self.assertEqual(got, ["mac imessage send"])
        self.assertEqual(rank.seeds("text", TOY, []), [])

    def test_ties_break_by_id(self):
        g = toy_graph(cmd("b", "x", "same words"), cmd("a", "x", "same words"))
        self.assertEqual([c for c, _ in rank.seeds("same", g)], ["mac a x", "mac b x"])

    def test_limit(self):
        self.assertEqual(len(rank.seeds("vault", TOY, limit=2)), 2)
        self.assertEqual(rank.seeds("vault", TOY, limit=0), [])

    def test_no_query_terms_gives_no_seeds(self):
        self.assertEqual(rank.seeds("the a of", TOY), [])


class ExpandTest(unittest.TestCase):
    def ids(self, out):
        return [n["id"] for n in out]

    def test_hop1_follows_hand_edges_in_both_directions(self):
        out = expand.expand(["mac contacts search"], TOY, TOY_EDGES, hops=1)
        self.assertEqual(out, [{"id": "mac imessage send", "via": "requires", "dir": "in",
                                "from": "mac contacts search", "hop": 1}])
        out = expand.expand(["mac imessage send"], TOY, TOY_EDGES, hops=1)
        self.assertEqual(self.ids(out), ["mac contacts search"])
        self.assertEqual(out[0]["dir"], "out")

    def test_hops_zero_returns_nothing(self):
        self.assertEqual(expand.expand(["mac imessage send"], TOY, TOY_EDGES, hops=0), [])

    def test_alias_edges_are_not_followed(self):
        out = expand.expand(["mac imessage send"], TOY, TOY_EDGES, hops=2, siblings=0)
        self.assertNotIn("mac imessage text", self.ids(out))

    def test_area_siblings_are_capped_and_ordered_by_score_then_id(self):
        scores = {"mac vault tags": 2.0}
        out = expand.expand(["mac vault read"], TOY, TOY_EDGES, scores=scores, siblings=2)
        sib = [n["id"] for n in out if n["via"] == "in_domain"]
        # outline is already a hop-1 neighbour; tags scores best; then stats by id.
        self.assertEqual(self.ids(out)[0], "mac vault outline")
        self.assertEqual(sib, ["mac vault tags", "mac vault stats"])

    def test_seeds_never_reappear_and_ids_are_unique(self):
        out = expand.expand(["mac vault read", "mac vault outline"], TOY, TOY_EDGES)
        ids = self.ids(out)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse({"mac vault read", "mac vault outline"} & set(ids))

    def test_max_nodes_caps_seeds_plus_neighbours(self):
        out = expand.expand(["mac vault read"], TOY, TOY_EDGES, max_nodes=3)
        self.assertEqual(len(out), 2)

    def test_ids_outside_the_graph_are_dropped(self):
        edges = [{"from": "mac vault read", "type": "feeds", "to": "mac ghost verb"}]
        out = expand.expand(["mac vault read", "mac ghost seed"], TOY, edges, siblings=0)
        self.assertEqual(out, [])


class FindOnCommittedGraphTest(unittest.TestCase):
    PHRASES = ["send a message to a contact", "read a note in my vault",
               "find calendar events", "delete an email", "play a song",
               "what is my battery level", "", "zzzz nonsense qqq"]

    @classmethod
    def setUpClass(cls):
        cls.graph, cls.edges = find_cli.load()
        cls.commands = command_ids(cls.graph)

    def test_shape_carries_usage_and_mode(self):
        r = find_cli.find("read a note in my vault", self.graph, self.edges)
        self.assertEqual(r["seeds"][0]["id"], "mac vault read")
        for item in r["seeds"] + r["neighbours"]:
            self.assertIn(item["mode"], ("read", "write"))
            self.assertTrue(item["usage"].startswith(item["id"]))
            self.assertTrue(item["desc"])
        self.assertIn("mac vault outline", [n["id"] for n in r["neighbours"]])

    def test_never_returns_a_command_absent_from_the_graph(self):
        # An alias edge whose `from` is not a node must not leak through.
        edges = self.edges + [{"from": "mac imessage text", "type": "alias_of",
                               "to": "mac imessage send"}]
        for phrase in self.PHRASES + ["text someone"]:
            r = find_cli.find(phrase, self.graph, edges)
            ids = [x["id"] for x in r["seeds"] + r["neighbours"]]
            self.assertLessEqual(set(ids), self.commands, phrase)
            self.assertEqual(len(ids), len(set(ids)), phrase)
            self.assertLessEqual(len(ids), expand.MAX_NODES, phrase)

    def test_empty_and_unmatched_queries_return_nothing(self):
        for phrase in ("", "zzzz nonsense qqq"):
            r = find_cli.find(phrase, self.graph, self.edges)
            self.assertEqual((r["seeds"], r["neighbours"]), ([], []))

    def test_same_output_across_processes_with_different_hash_seeds(self):
        code = ("import json,sys,find_cli as f;g,e=f.load();"
                "print(json.dumps([f.find(p,g,e) for p in json.loads(sys.argv[1])]))")
        outs = set()
        for seed in ("1", "2", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(REPO))
            outs.add(subprocess.run([sys.executable, "-c", code, json.dumps(self.PHRASES)],
                                    env=env, cwd=REPO, check=True,
                                    capture_output=True, text=True).stdout)
        self.assertEqual(len(outs), 1)
        in_process = json.dumps([find_cli.find(p, self.graph, self.edges) for p in self.PHRASES])
        self.assertEqual(outs.pop().strip(), in_process)


try:
    import mcp  # noqa: F401
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


@unittest.skipUnless(HAVE_MCP, "needs the mcp package (run under `uv run`)")
class UsageTest(unittest.TestCase):
    """Usage counts are an input to find(), never read by it (task:c5a222dc)."""

    COUNTS = {"mac vault read": {"count": 7, "last_used": "2026-10-27 01:00:00"}}

    def test_without_usage_the_output_has_no_usage_fields(self):
        got = find_cli.find("read vault note", TOY, TOY_EDGES)
        for row in got["seeds"] + got["neighbours"]:
            self.assertNotIn("count", row)
            self.assertNotIn("last_used", row)

    def test_usage_adds_fields_and_never_changes_order(self):
        plain = find_cli.find("read vault note", TOY, TOY_EDGES)
        got = find_cli.find("read vault note", TOY, TOY_EDGES, usage=self.COUNTS)
        self.assertEqual([r["id"] for r in got["seeds"]], [r["id"] for r in plain["seeds"]])
        self.assertEqual([r["id"] for r in got["neighbours"]],
                         [r["id"] for r in plain["neighbours"]])
        by_id = {r["id"]: r for r in got["seeds"] + got["neighbours"]}
        self.assertEqual(by_id["mac vault read"]["count"], 7)
        self.assertEqual(by_id["mac vault read"]["last_used"], "2026-10-27 01:00:00")
        others = [r for cid, r in by_id.items() if cid != "mac vault read"]
        self.assertTrue(others)
        self.assertTrue(all(r["count"] == 0 and r["last_used"] is None for r in others))

    def test_loader_reads_mac_rows_only(self):
        import sqlite3
        import tempfile
        from find_cli import usage
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "hints.sqlite"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE mcp_tool_hints (tool_name TEXT PRIMARY KEY, "
                         "count INTEGER, last_used TIMESTAMP)")
            conn.executemany("INSERT INTO mcp_tool_hints VALUES (?, ?, ?)", [
                ("mac vault read", 7, "2026-10-27 01:00:00"),
                ("mac vault tags", None, None),
                ("mcp__find_cli__find_cli", 8, "2026-10-26 23:10:25"),
            ])
            conn.commit()
            conn.close()
            self.assertEqual(usage.load(db), {
                "mac vault read": {"count": 7, "last_used": "2026-10-27 01:00:00"},
                "mac vault tags": {"count": 0, "last_used": None},
            })

    def test_loader_gives_empty_map_for_missing_file_or_table(self):
        import sqlite3
        import tempfile
        from find_cli import usage
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(usage.load(Path(d) / "absent.sqlite"), {})
            empty = Path(d) / "empty.sqlite"
            sqlite3.connect(empty).close()
            self.assertEqual(usage.load(empty), {})


class ServerTest(unittest.TestCase):
    def test_server_exposes_exactly_one_small_tool(self):
        import asyncio
        from find_cli import server
        tools = asyncio.run(server.mcp.list_tools())
        self.assertEqual([t.name for t in tools], ["find_cli"])
        schema = json.dumps({"name": tools[0].name, "description": tools[0].description,
                             "inputSchema": tools[0].inputSchema})
        self.assertLess(len(schema) / 4, 400)  # ~tokens, chars/4

    def test_tool_call_returns_the_pure_result(self):
        from unittest import mock
        from find_cli import server
        counts = {"mac music play": {"count": 3, "last_used": "2026-10-27 03:00:00"}}
        with mock.patch.object(server._usage, "load", return_value=counts):
            got = server.find_cli("play a song")
        self.assertEqual(got, find_cli.find("play a song", server.GRAPH, server.EDGES,
                                            usage=counts))


if __name__ == "__main__":
    unittest.main()
