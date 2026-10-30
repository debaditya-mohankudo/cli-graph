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
            self.assertIn(p["source"], ("transcript", "paraphrase", "synonym", "negative"))
            # only a negative may expect nothing, and a negative must (task:d08ebd55)
            self.assertEqual(not p["expect"], p["source"] == "negative", p["phrase"])

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

    def test_seed_hit_rate_meets_its_gate(self):
        # task:9d42faae: the subgraph rate alone passes while seeds slip.
        s = ev.rates(ev.score(self.phrases, self.graph, self.edges))
        self.assertGreaterEqual(s["seed_rate"], ev.SEED_THRESHOLD, s)


class HeldoutTest(unittest.TestCase):
    """eval_heldout.json: logged real queries, scored apart and never tuned on (task:9d42faae)."""

    def setUp(self):
        self.graph, self.edges = find_cli.load()
        self.heldout = ev.load_fixture(ev.HELDOUT)

    def test_every_phrase_is_logged_and_may_expect_nothing(self):
        self.assertTrue(self.heldout)
        for p in self.heldout:
            self.assertTrue(p["phrase"].strip())
            self.assertIsInstance(p["expect"], list, p["phrase"])
            self.assertEqual(p["source"], "logged", p["phrase"])

    def test_every_expected_id_is_a_command_in_the_committed_graph(self):
        self.assertEqual(ev.unknown_ids(self.heldout, self.graph), [])

    def test_no_held_out_phrase_is_in_the_tuning_set(self):
        tuning = {p["phrase"].strip().lower() for p in ev.load_fixture()}
        self.assertEqual([p["phrase"] for p in self.heldout
                          if p["phrase"].strip().lower() in tuning], [])


class AbstainTest(unittest.TestCase):
    def setUp(self):
        self.graph, self.edges = find_cli.load()

    def test_empty_expect_is_scored_as_abstention_and_left_out_of_hit_rates(self):
        phrases = [{"phrase": "book a flight to delhi", "expect": []},
                   {"phrase": "list reminder lists", "expect": ["mac reminders lists"]}]
        rows = ev.score(phrases, self.graph, self.edges)
        self.assertTrue(rows[0]["abstained"])
        s = ev.rates(rows)
        self.assertEqual((s["n"], s["hits"], s["negatives"], s["abstained"]), (1, 1, 1, 1))

    def test_returning_seeds_for_an_empty_expect_is_not_an_abstention(self):
        rows = ev.score([{"phrase": "list reminder lists", "expect": []}], self.graph, self.edges)
        self.assertFalse(rows[0]["abstained"])
        self.assertEqual(ev.rates(rows)["abstained"], 0)


class MainTest(unittest.TestCase):
    def test_exit_code_follows_the_threshold(self):
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ev.main(["--threshold", "0"]), 0)
            self.assertEqual(ev.main(["--threshold", "1.01"]), 1)

    def test_seed_threshold_alone_fails_the_gate(self):
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ev.main(["--threshold", "0", "--seed-threshold", "1.01"]), 1)

    def test_held_out_misses_never_change_the_exit_code(self):
        import io
        import contextlib
        import json
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "heldout.json"
            path.write_text(json.dumps({"phrases": [
                {"phrase": "list reminder lists", "expect": ["mac git push"], "source": "logged"},
                {"phrase": "list reminder lists", "expect": [], "source": "logged"}]}))
            buf = io.StringIO()
            with mock.patch.object(ev, "HELDOUT", path), contextlib.redirect_stdout(buf):
                self.assertEqual(ev.main([]), 0)
        held = buf.getvalue().split("== held-out")[1]
        self.assertIn("subgraph hit rate  0/1", held)
        self.assertIn("abstention         0/1", held)


if __name__ == "__main__":
    unittest.main()
