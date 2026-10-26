"""`mac vault_rag` (task:73cbda5d).

vault_rag is generated, so its coverage, modes and freshness are checked with the
other generated groups in test_parity_simple_groups.py. Here: the exact kwargs
each verb forwards, and that loading the handlers does not import llama_index.
That import costs about 1.2s and only the embedding verbs need it, so a
regression would make every `mac vault_rag fts_vault` call slow without failing.

Live tests (MAC_PARITY_LIVE=1) compare the sqlite-only reads with the handlers.
They never run index_vault, index_file or remove_section, which change the
shared index, or query_vault/smart_search, which need a running Ollama.
"""
import importlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parent.parent), str(Path(__file__).resolve().parent)]

from _helpers import run, stub_dispatcher
from mac.groups import _backend


def handler_module():
    try:
        return importlib.import_module(_backend.dispatcher().DOMAIN_MAP["vault_rag"][0])
    except ImportError as exc:
        raise unittest.SkipTest(f"vault_rag handlers need local-mac's dependencies (run under `uv run`): {exc}")


class ForwardingTest(unittest.TestCase):
    CASES = [
        (["fts_vault", "swift"], "fts_vault", {"query": "swift"}),
        (["fts_vault", "swift", "--limit", "3", "--folder", "Projects"], "fts_vault",
         {"query": "swift", "limit": 3, "folder": "Projects"}),
        (["query_vault", "q", "--top-k", "2"], "query_vault", {"query": "q", "top_k": 2}),
        (["smart_search", "q", "--fts-candidate-limit", "20"], "smart_search",
         {"query": "q", "fts_candidate_limit": 20}),
        (["index_status"], "index_status", {}),
        (["contains_section", "7"], "contains_section", {"section_id": 7}),
        (["remove_section", "7"], "remove_section", {"section_id": 7}),
        (["index_file", "Projects/a.md"], "index_file", {"path": "Projects/a.md"}),
        (["index_vault"], "index_vault", {}),
        (["index_vault", "--force"], "index_vault", {"force": True}),
        (["unindexed_files", "--folder", "Projects"], "unindexed_files", {"folder": "Projects"}),
    ]

    def test_only_supplied_args_reach_the_handler(self):
        for argv, action, kwargs in self.CASES:
            with self.subTest(argv=argv):
                fake = mock.Mock(return_value="ok")
                picked = []
                with stub_dispatcher(lambda area, act: picked.append(act) or fake):
                    status, _, err = run("vault_rag", *argv)
                self.assertEqual(status, 0, err)
                self.assertEqual(picked, [action])
                fake.assert_called_once_with(**kwargs)


class ImportCostTest(unittest.TestCase):
    def test_handlers_load_without_llama_index(self):
        src = os.environ.get("MAC_MCP_SRC", str(_backend.DEFAULT_SRC))
        if not Path(src).is_dir():
            self.skipTest(f"local-mac source tree not found: {src}")
        # The interpreter bin/mac runs under: MAC_PYTHON, else cli-graph's own venv.
        repo = Path(__file__).resolve().parent.parent
        python = Path(os.environ.get("MAC_PYTHON", repo / ".venv" / "bin" / "python"))
        if not python.exists():
            self.skipTest(f"bin/mac's interpreter not found: {python} (set MAC_PYTHON)")
        probe = ("import sys; sys.path.insert(0, sys.argv[1]); import tools.vault_rag; "
                 "print(any(m.startswith('llama_index') for m in sys.modules))")
        out = subprocess.run([str(python), "-c", probe, src], capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "False")


@unittest.skipUnless(os.environ.get("MAC_PARITY_LIVE") == "1", "set MAC_PARITY_LIVE=1 to touch the Mac")
class LiveParityTest(unittest.TestCase):
    def cli(self, *argv):
        status, out, err = run(*argv)
        self.assertEqual(status, 0, err)
        return json.loads(out)

    def test_sqlite_reads_match_handlers(self):
        module = handler_module()
        self.assertEqual(self.cli("vault_rag", "fts_vault", "sqlite", "--limit", "5"),
                         module.handle_fts_vault(query="sqlite", limit=5))
        self.assertEqual(self.cli("vault_rag", "fts_vault", "sqlite", "--folder", "Projects"),
                         module.handle_fts_vault(query="sqlite", folder="Projects"))
        self.assertEqual(self.cli("vault_rag", "index_status"), module.handle_index_status())
        self.assertEqual(self.cli("vault_rag", "contains_section", "1"),
                         module.handle_contains_section(section_id=1))
        self.assertEqual(self.cli("vault_rag", "unindexed_files", "--folder", "Projects"),
                         module.handle_unindexed_files(folder="Projects"))


if __name__ == "__main__":
    unittest.main()
