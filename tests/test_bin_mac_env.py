"""bin/mac runs under the interpreter the suite runs under (task:d30c0330).

A green suite only speaks for the `mac` users run if both use the same
environment. Each test runs the real bin/mac with a sitecustomize on PYTHONPATH
that prints the interpreter's sys.prefix and exits before `mac` starts, so it
observes which interpreter bin/mac picks rather than reading the script's text.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BIN_MAC = REPO / "bin" / "mac"
PROBE = "import os, sys\nprint(sys.prefix, flush=True)\nos._exit(0)\n"


def prefix_bin_mac_uses(**env):
    with tempfile.TemporaryDirectory() as probe_dir:
        Path(probe_dir, "sitecustomize.py").write_text(PROBE)
        run_env = {k: v for k, v in os.environ.items() if k != "MAC_PYTHON"}
        run_env.update(env, PYTHONPATH=probe_dir)
        out = subprocess.run([str(BIN_MAC), "--help"], env=run_env,
                             capture_output=True, text=True, check=True)
    return Path(out.stdout.strip()).resolve()


class BinMacEnvironmentTest(unittest.TestCase):
    def test_default_interpreter_is_the_suites(self):
        self.assertEqual(
            prefix_bin_mac_uses(), Path(sys.prefix).resolve(),
            "bin/mac and the suite run under different environments; "
            "run the suite with `uv run` and keep bin/mac's default on cli-graph's .venv")

    def test_mac_python_overrides_the_default(self):
        with tempfile.TemporaryDirectory() as other:
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", other], check=True)
            self.assertEqual(prefix_bin_mac_uses(MAC_PYTHON=f"{other}/bin/python"),
                             Path(other).resolve())


if __name__ == "__main__":
    unittest.main()
