"""_backend loads local-mac's .env even when src is already on sys.path (task:2ee06de6).

cli-graph's venv installs local-mac in editable mode, which puts src on
sys.path before `mac` starts. .env loading used to be tied to inserting src,
so under that venv it never ran and every `mac mail` verb failed. Each test
runs in a fresh interpreter so module state and os.environ start clean.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROBE = """
import os, sys
src = sys.argv[1]
if sys.argv[2] == "preloaded":
    sys.path.insert(0, src)
from mac.groups import _backend
_backend._src()
_backend._src()
print(os.environ.get("MAC_ENV_PROBE", "<unset>"))
"""


def probe(preloaded):
    with tempfile.TemporaryDirectory() as root:
        src = Path(root, "src")
        src.mkdir()
        Path(root, ".env").write_text("MAC_ENV_PROBE=loaded\n")
        env = {k: v for k, v in os.environ.items() if k != "MAC_ENV_PROBE"}
        env.update(MAC_MCP_SRC=str(src), PYTHONPATH=str(REPO))
        out = subprocess.run([sys.executable, "-c", PROBE, str(src), preloaded],
                             env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip()


class BackendEnvTest(unittest.TestCase):
    def test_env_loaded_when_src_is_already_on_sys_path(self):
        self.assertEqual(probe("preloaded"), "loaded")

    def test_env_loaded_when_backend_adds_src(self):
        self.assertEqual(probe("fresh"), "loaded")


if __name__ == "__main__":
    unittest.main()
