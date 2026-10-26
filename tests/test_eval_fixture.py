"""The find_cli hit-rate fixture stays valid and its rate stays at the gate (task:597ac09d).

tests/eval_find_cli.py is the report; this keeps it honest inside the suite, so
a regenerated graph that renames a verb, or a rank/expand change that drops
retrieval below the gate, fails `unittest discover` instead of waiting for
someone to run the eval by hand.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_find_cli as ev
import find_cli


class FixtureTest(unittest.TestCase):
    def setUp(self):
        self.graph, self.edges = find_cli.load()
        self.phrases = ev.load_fixture()

    def test_about_twenty_phrases_each_with_an_expectation(self):
        self.assertGreaterEqual(len(self.phrases), 20)
        for p in self.phrases:
            self.assertTrue(p["phrase"].strip())
            self.assertTrue(p["expect"], p["phrase"])
            self.assertIn(p["source"], ("transcript", "paraphrase", "synonym"))

    def test_every_expected_id_is_a_command_in_the_committed_graph(self):
        self.assertEqual(ev.unknown_ids(self.phrases, self.graph), [])

    def test_unknown_id_is_reported(self):
        bad = [{"phrase": "x", "expect": ["mac nope verb"], "source": "paraphrase"}]
        self.assertEqual(ev.unknown_ids(bad, self.graph), [("x", "mac nope verb")])

    def test_subgraph_hit_rate_meets_the_gate(self):
        rows = ev.score(self.phrases, self.graph, self.edges)
        rate = sum(r["hit"] for r in rows) / len(rows)
        misses = [r["phrase"] for r in rows if not r["hit"]]
        self.assertGreaterEqual(rate, ev.THRESHOLD, misses)


class MainTest(unittest.TestCase):
    def test_exit_code_follows_the_threshold(self):
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ev.main(["--threshold", "0"]), 0)
            self.assertEqual(ev.main(["--threshold", "1.01"]), 1)


if __name__ == "__main__":
    unittest.main()
