"""find_cli.service: reload on file change, last good graph kept, contract errors (task:d430f68b)."""
import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

import find_cli
from find_cli.service import Finder
from mac import cli


class FinderTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        graph, edges = find_cli.load()
        self.graph_path, self.edges_path = tmp / "g.json", tmp / "e.json"
        self.graph_path.write_text(json.dumps(graph))
        self.edges_path.write_text(json.dumps({"edges": edges}))
        self.finder = Finder(self.graph_path, self.edges_path)

    def bump(self, path, text):
        path.write_text(text)
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))

    def test_changed_graph_is_seen_by_the_next_call(self):
        first = self.finder.answer("play a song")
        graph = json.loads(self.graph_path.read_text())
        graph["nodes"] = [n for n in graph["nodes"] if n.get("id") != first["seeds"][0]["id"]]
        self.bump(self.graph_path, json.dumps(graph))
        self.assertNotEqual(self.finder.answer("play a song")["seeds"][0]["id"], first["seeds"][0]["id"])

    def test_half_written_graph_keeps_the_last_good_one(self):
        first = self.finder.answer("play a song")
        self.bump(self.graph_path, '{"nodes": [')
        self.assertEqual(self.finder.answer("play a song"), first)

    def test_invalid_edges_keep_the_last_good_pair(self):
        first = self.finder.answer("play a song")
        self.bump(self.edges_path, "not json")
        self.assertEqual(self.finder.answer("play a song"), first)

    def test_unloadable_first_graph_is_a_contract_error(self):
        self.graph_path.write_text("{")
        got = Finder(self.graph_path, self.edges_path).answer("x")
        self.assertEqual(set(got["error"]), {"code", "message"})

    def test_failure_inside_find_is_a_contract_error(self):
        with mock.patch("find_cli.service.find", side_effect=RuntimeError("boom")):
            got = self.finder.answer("x")
        self.assertEqual(got, {"error": {"code": "internal", "message": "RuntimeError: boom"}})


class MacCliFindTests(unittest.TestCase):
    def run_mac(self, *args):
        out, err = StringIO(), StringIO()
        status = cli.main(list(args), out=out, err=err)
        return status, out.getvalue(), err.getvalue()

    def test_same_result_as_the_server(self):
        from find_cli import server
        status, out, _ = self.run_mac("cli", "find", "play a song", "--limit", "3", "--hops", "1")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(out), json.loads(json.dumps(server.find_cli("play a song", limit=3, hops=1))))

    def test_failure_uses_the_mac_error_shape(self):
        with mock.patch("find_cli.service.find", side_effect=RuntimeError("boom")):
            status, _, err = self.run_mac("cli", "find", "x")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "internal")


if __name__ == "__main__":
    unittest.main()
