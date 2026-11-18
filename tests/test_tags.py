"""graph/tags.json (task:802cfc3e): valid against the graph, feeds BM25 ranking
but not confidence, hot-reloads in the Finder, and leaves cli_graph.json alone."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import find_cli
from find_cli import rank
from find_cli.service import Finder
from graph import tags

SEND = "mac imessage send"


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.graph, _ = find_cli.load()

    def test_committed_file_is_valid(self):
        self.assertEqual(tags.validate(tags.load(), self.graph), [])

    def test_orphaned_id_is_a_problem(self):
        self.assertTrue(tags.validate({"mac nope nothing": ["x"]}, self.graph))

    def test_empty_uppercase_and_duplicate_are_problems(self):
        for bad in ([], ["Text"], ["a b"], ["x", "x"], [""]):
            self.assertTrue(tags.validate({SEND: bad}, self.graph), bad)

    def test_missing_file_means_no_tags(self):
        self.assertEqual(tags.load(Path("/nonexistent/tags.json")), {})


class RankTest(unittest.TestCase):
    def setUp(self):
        self.graph, self.edges = find_cli.load()
        self.word = "zzqword"

    def top(self, tag_map):
        r = find_cli.find(self.word, self.graph, self.edges, tags=tag_map)
        return r["seeds"][0]["id"] if r["seeds"] else None

    def test_tag_only_word_finds_its_command(self):
        self.assertIsNone(self.top(None))
        self.assertEqual(self.top({SEND: [self.word]}), SEND)

    def test_untagged_ranking_is_unchanged(self):
        for q in ("play a song", "send a text message to a contact"):
            a = find_cli.find(q, self.graph, self.edges)
            b = find_cli.find(q, self.graph, self.edges, tags={})
            self.assertEqual(a, b)

    def test_tags_do_not_feed_confidence(self):
        r = find_cli.find(self.word, self.graph, self.edges, tags={SEND: [self.word]})
        self.assertNotEqual(r["confidence"]["level"], "high")
        self.assertEqual(r["confidence"]["coverage"], 0.0)

    def test_documents_carry_the_tags(self):
        docs = rank.documents(self.graph, self.edges, {SEND: [self.word]})
        self.assertIn(self.word, docs[SEND])
        self.assertNotIn(self.word, rank.documents(self.graph, self.edges)[SEND])


class FinderReloadTest(unittest.TestCase):
    def test_edited_tags_file_is_seen_by_the_next_call(self):
        path = Path(tempfile.mkdtemp()) / "tags.json"
        finder = Finder(tags_path=path)
        self.assertEqual(finder.tags(), {})
        path.write_text(json.dumps({"tags": {SEND: ["zzqword"]}}))
        self.assertEqual(finder.answer("zzqword")["seeds"][0]["id"], SEND)
        path.write_text('{"tags": ')
        os.utime(path, ns=(1, 2 * 10**18))
        self.assertEqual(finder.tags(), {SEND: ["zzqword"]})
        path.write_text(json.dumps({"tags": {}}))
        os.utime(path, ns=(1, 3 * 10**18))
        self.assertTrue(finder.answer("zzqword")["no_match"])


class GraphUntouchedTest(unittest.TestCase):
    def test_generate_check_passes(self):
        out = subprocess.run([sys.executable, "-m", "graph.generate", "--check"],
                             cwd=REPO, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
