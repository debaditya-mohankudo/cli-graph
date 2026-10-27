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

from graph import generate, groups

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
    def test_the_graph_is_groups_domains_and_command_nodes_only(self):
        self.assertEqual(list(LIVE), ["groups", "domains", "nodes"])
        self.assertEqual({n["kind"] for n in LIVE["nodes"]}, {"command"})

    def test_every_command_has_its_fields(self):
        self.assertTrue(LIVE["nodes"])
        for node in LIVE["nodes"]:
            self.assertEqual(set(node), {"id", "kind", "cli", "area", "verb", "mode", "desc", "usage"})
            for field in ("cli", "area", "verb", "mode", "desc", "usage"):
                self.assertTrue(node[field], f"{node['id']}: empty {field}")
            self.assertIn(node["mode"], {"read", "write"}, node["id"])
            self.assertEqual(node["id"], f"{node['cli']} {node['area']} {node['verb']}")

    def test_every_area_lists_exactly_its_verbs(self):
        want = {}
        for n in LIVE["nodes"]:
            want.setdefault(n["area"], []).append(n["verb"])
        self.assertEqual({a: d["verbs"] for a, d in LIVE["domains"].items()},
                         {a: sorted(v) for a, v in want.items()})

    def test_groups_and_domain_groups_match_the_spec(self):
        spec = groups.load()
        self.assertEqual(LIVE["groups"], {g: sorted(a) for g, a in spec["groups"].items()})
        for area, domain in LIVE["domains"].items():
            self.assertEqual(domain["group"], groups.area_groups(spec).get(area), area)
        for area in spec["ungrouped"]:
            self.assertIsNone(LIVE["domains"][area]["group"])

    def test_regeneration_is_byte_identical(self):
        self.assertEqual(generate.render(generate.build()), generate.render(LIVE))

    def test_one_new_verb_adds_its_node_and_domain_lines(self):
        node = next(n for n in LIVE["nodes"] if n["kind"] == "command")
        domains = {a: dict(d, verbs=list(d["verbs"])) for a, d in LIVE["domains"].items()}
        domains[node["area"]]["verbs"].append(node["verb"] + "_x")
        grown = {"groups": LIVE["groups"], "domains": domains,
                 "nodes": sorted(LIVE["nodes"] + [dict(node, id=node["id"] + "_x", verb=node["verb"] + "_x")],
                                 key=lambda n: n["id"])}
        before = generate.render(LIVE).splitlines()
        after = generate.render(grown).splitlines()
        self.assertEqual(len(set(after) - set(before)), 2)
        self.assertEqual(len(set(before) - set(after)), 1)  # the domain's old overview line


if __name__ == "__main__":
    unittest.main()
