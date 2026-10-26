"""Hand-written edges are valid against the generated graph (task:821c2f7e).

The committed graph/edges.json must validate against the committed
graph/cli_graph.json, which test_drift pins to the live CLIs. So a regenerated
graph that drops or renames a verb an edge uses fails here, by name.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from graph import validate_edges as v
from graph.generate import GRAPH

COMMITTED = json.loads(GRAPH.read_text())
SEND, SEARCH = "mac imessage send", "mac contacts search"


def edge(src, kind, dst):
    return {"from": src, "type": kind, "to": dst}


def problems(*edges, graph=COMMITTED):
    return v.validate(list(edges), graph)


class CommittedEdgesTest(unittest.TestCase):
    def test_committed_edges_validate(self):
        self.assertEqual(v.validate(v.load(), COMMITTED), [])

    def test_command_line_passes_on_the_committed_file(self):
        run = subprocess.run([sys.executable, "-m", "graph.validate_edges"],
                             cwd=REPO, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_only_the_four_hand_written_types_are_used(self):
        self.assertTrue({e["type"] for e in v.load()} <= set(v.TYPES))

    def test_seed_edges_exist(self):
        have = {(e["from"], e["type"], e["to"]) for e in v.load()}
        for seed in [("mac vault outline", "feeds", "mac vault read"),
                     (SEND, "requires", SEARCH),
                     ("mac mail delete", "requires", "mac mail read")]:
            self.assertIn(seed, have)


class DanglingEndpointTest(unittest.TestCase):
    def test_a_graph_that_drops_a_used_verb_fails_on_that_edge(self):
        dropped = dict(COMMITTED, nodes=[n for n in COMMITTED["nodes"] if n["id"] != SEARCH])
        found = v.validate(v.load(), dropped)
        self.assertEqual(len(found), 1)
        self.assertIn(SEARCH, found[0])

    def test_an_unknown_from_fails(self):
        self.assertEqual(len(problems(edge("mac imessage sned", "requires", SEARCH))), 1)

    def test_an_unknown_to_fails(self):
        self.assertEqual(len(problems(edge(SEND, "requires", "mac contacts serch"))), 1)

    def test_a_domain_node_endpoint_fails(self):
        self.assertEqual(len(problems(edge(SEND, "requires", "domain:contacts"))), 1)


class ShapeRulesTest(unittest.TestCase):
    def test_in_domain_is_rejected(self):
        self.assertEqual(len(problems(edge(SEND, "in_domain", SEARCH))), 1)

    def test_an_unknown_type_is_rejected(self):
        self.assertEqual(len(problems(edge(SEND, "needs", SEARCH))), 1)

    def test_a_misspelled_or_extra_key_is_rejected(self):
        self.assertEqual(len(problems({"from": SEND, "tp": "requires", "to": SEARCH})), 1)
        self.assertEqual(len(problems(dict(edge(SEND, "requires", SEARCH), weight=1))), 1)

    def test_a_self_loop_is_rejected(self):
        self.assertEqual(len(problems(edge(SEND, "prefer_over", SEND))), 1)

    def test_a_duplicate_triple_is_rejected(self):
        self.assertEqual(len(problems(edge(SEND, "requires", SEARCH),
                                      edge(SEND, "requires", SEARCH))), 1)


class AliasTest(unittest.TestCase):
    def test_an_alias_need_not_be_a_node(self):
        self.assertEqual(problems(edge("mac vault fetch", "alias_of", "mac vault read")), [])

    def test_an_alias_must_share_cli_and_area(self):
        self.assertEqual(len(problems(edge("mac mail fetch", "alias_of", "mac vault read"))), 1)
        self.assertEqual(len(problems(edge("fetch", "alias_of", "mac vault read"))), 1)

    def test_an_alias_must_not_be_an_existing_command(self):
        found = problems(edge("mac vault outline", "alias_of", "mac vault read"))
        self.assertEqual(len(found), 1)
        self.assertIn("already a command", found[0])

    def test_the_canonical_end_must_be_a_node(self):
        self.assertEqual(len(problems(edge("mac vault fetch", "alias_of", "mac vault gone"))), 1)

    def test_one_alias_names_one_command(self):
        found = problems(edge("mac vault fetch", "alias_of", "mac vault read"),
                         edge("mac vault fetch", "alias_of", "mac vault outline"))
        self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main()
