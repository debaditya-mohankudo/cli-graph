"""`mac claude` roots a headless session and runs each task in a throwaway fork of it.

No real claude is run: `_claude` is replaced by a fake that records its argv.
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mac.cli import main  # noqa: E402
from mac.groups import claude  # noqa: E402


def run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["claude", *argv, "--json"])
    return code, buf.getvalue()


class Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd, timeout, env=None):
        self.calls.append((argv, cwd, timeout))
        self.env = env
        return {"session_id": "fork-1", "result": "done", "total_cost_usd": 0.1, "num_turns": 1}


class ClaudeForkTest(unittest.TestCase):
    def test_fork_resumes_root_forks_and_discards(self):
        fake = Fake()
        with mock.patch.object(claude, "_claude", fake):
            code, out = run("fork", "--root", "r-1", "--task", "do it", "--cwd", "/tmp")
        self.assertEqual(code, 0)
        argv = fake.calls[0][0]
        self.assertEqual(argv[:3], ["--resume", "r-1", "--fork-session"])
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual(argv[-1], "do it")
        self.assertIn('"result": "done"', out)

    def test_fork_keep_drops_no_persistence(self):
        fake = Fake()
        with mock.patch.object(claude, "_claude", fake):
            run("fork", "--root", "r-1", "--task", "t", "--keep", "--cwd", "/tmp")
        self.assertNotIn("--no-session-persistence", fake.calls[0][0])

    def test_root_passes_a_fresh_session_id(self):
        fake = Fake()
        with mock.patch.object(claude, "_claude", fake):
            code, out = run("root", "--prompt", "prime", "--cwd", "/tmp")
        self.assertEqual(code, 0)
        argv = fake.calls[0][0]
        self.assertEqual(argv[0], "--session-id")
        self.assertEqual(json.loads(out)["root"], "fork-1")

    def test_minimal_isolation_keeps_only_the_two_mcp_servers(self):
        fake = Fake()
        servers = {"mcpServers": {"find_cli": {"command": "a"}, "taskfw": {"command": "b"}, "other": {"command": "c"}}}
        with mock.patch.object(claude, "_claude", fake), \
                mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(servers))):
            run("fork", "--root", "r", "--task", "t", "--cwd", "/tmp")
        argv = fake.calls[0][0]
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project")
        cfg = json.loads(next(a for a in argv if a.startswith("--mcp-config="))[len("--mcp-config="):])
        self.assertEqual(sorted(cfg["mcpServers"]), ["find_cli", "taskfw"])
        self.assertEqual(fake.env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"], "1")

    def test_isolation_none_adds_no_flags(self):
        fake = Fake()
        with mock.patch.object(claude, "_claude", fake):
            run("fork", "--root", "r", "--task", "t", "--cwd", "/tmp", "--isolation", "none")
        self.assertNotIn("--strict-mcp-config", fake.calls[0][0])
        self.assertFalse(fake.env)

    def test_bad_cwd_is_a_usage_error(self):
        code, _ = run("fork", "--root", "r", "--task", "t", "--cwd", "/no/such/dir")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
