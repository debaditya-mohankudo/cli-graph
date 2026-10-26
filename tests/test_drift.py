"""The committed command graph matches the live CLIs (task:980f10b3).

Regenerates the graph from each CLI's `--help --json` and compares it with
graph/cli_graph.json. Drift is reported by name (a CLI verb missing from the
graph, a graph command with no CLI verb), so a failure says which verb drifted.
"""
import copy
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from graph import generate

LIVE = generate.build()


class DriftTest(unittest.TestCase):
    def test_committed_graph_matches_the_clis(self):
        self.assertEqual(generate.drift(LIVE, generate.GRAPH.read_text()), [])

    def test_check_mode_passes_on_the_committed_graph(self):
        run = subprocess.run([sys.executable, "-m", "graph.generate", "--check"],
                             cwd=REPO, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_a_cli_verb_missing_from_the_graph_fails(self):
        stale = copy.deepcopy(LIVE)
        gone = next(n for n in stale["nodes"] if n["kind"] == "command")
        stale["nodes"].remove(gone)
        stale["edges"] = [e for e in stale["edges"] if e["from"] != gone["id"]]
        self.assertEqual(generate.drift(LIVE, generate.render(stale)),
                         [f"CLI verb missing from graph: {gone['id']}"])

    def test_a_graph_command_with_no_cli_verb_fails(self):
        stale = copy.deepcopy(LIVE)
        node = next(n for n in stale["nodes"] if n["kind"] == "command")
        ghost = dict(node, id=node["id"] + "_gone", verb=node["verb"] + "_gone")
        stale["nodes"].append(ghost)
        self.assertEqual(generate.drift(LIVE, generate.render(stale)),
                         [f"graph command has no CLI verb: {ghost['id']}"])

    def test_a_changed_desc_fails(self):
        stale = copy.deepcopy(LIVE)
        next(n for n in stale["nodes"] if n["kind"] == "command")["desc"] = "edited by hand"
        self.assertEqual(len(generate.drift(LIVE, generate.render(stale))), 1)


class ShapeTest(unittest.TestCase):
    def test_every_command_has_its_fields_and_an_in_domain_edge(self):
        ids = {n["id"] for n in LIVE["nodes"]}
        edges = {(e["from"], e["type"], e["to"]) for e in LIVE["edges"]}
        commands = [n for n in LIVE["nodes"] if n["kind"] == "command"]
        self.assertTrue(commands)
        for node in commands:
            for field in ("cli", "area", "verb", "mode", "desc", "usage", "domain"):
                self.assertTrue(node[field], f"{node['id']}: empty {field}")
            self.assertIn(node["mode"], {"read", "write"}, node["id"])
            self.assertEqual(node["id"], f"{node['cli']} {node['area']} {node['verb']}")
            self.assertEqual(node["domain"], f"domain:{node['area']}")
            self.assertIn((node["id"], "in_domain", node["domain"]), edges)
        self.assertEqual(len(edges), len(commands))
        for src, _, dst in edges:
            self.assertIn(src, ids)
            self.assertIn(dst, ids)

    def test_regeneration_is_byte_identical(self):
        self.assertEqual(generate.render(generate.build()), generate.render(LIVE))

    def test_one_new_verb_adds_only_its_node_and_edge_lines(self):
        node = next(n for n in LIVE["nodes"] if n["kind"] == "command")
        new_id = node["id"] + "_x"
        grown = {"nodes": sorted(LIVE["nodes"] + [dict(node, id=new_id, verb=node["verb"] + "_x")],
                                 key=lambda n: n["id"]),
                 "edges": sorted(LIVE["edges"] + [{"from": new_id, "to": node["domain"], "type": "in_domain"}],
                                 key=lambda e: (e["from"], e["type"], e["to"]))}
        before = generate.render(LIVE).splitlines()
        after = generate.render(grown).splitlines()
        self.assertEqual(len(set(after) - set(before)), 2)
        self.assertEqual(set(before) - set(after), set())


if __name__ == "__main__":
    unittest.main()
