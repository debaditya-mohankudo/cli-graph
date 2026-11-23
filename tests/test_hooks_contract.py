"""Pins the claude-hooks handlers that mac calls (task:65891ed8).

c239f888 deleted src/tools/code_rag.py and diff_rag.py; `mac diff_rag` kept routing to them and failed at run
time with ModuleNotFoundError. This test reads every `call("<module>", "<action>")` literal in a group that runs
claude-hooks handlers and checks `src/tools/<module>.py` still defines `handle_<action>`.
"""
import ast
import re
import unittest
from pathlib import Path

from mac.groups._hooks import root

GROUPS = Path(__file__).resolve().parent.parent / "mac" / "groups"


def hook_calls():
    """{(module, action): 'file:line'} for each literal call() in a group that imports mac.groups._hooks."""
    found = {}
    for path in sorted(GROUPS.glob("*.py")):
        tree = ast.parse(path.read_text())
        if not any(isinstance(n, ast.ImportFrom) and n.module == "mac.groups._hooks" for n in ast.walk(tree)):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "call":
                args = n.args[:2]
                if len(args) == 2 and all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in args):
                    found.setdefault((args[0].value, args[1].value), f"{path.name}:{n.lineno}")
    return found


class HookHandlerContractTest(unittest.TestCase):
    def test_scan_finds_the_calls(self):
        calls = hook_calls()
        self.assertIn(("memory", "add"), calls)
        self.assertIn(("vault_map", "overview"), calls)

    @unittest.skipUnless((root() / "src" / "tools").is_dir(), "claude-hooks tree not present")
    def test_every_called_handler_exists_in_claude_hooks(self):
        missing = []
        for (module, action), where in hook_calls().items():
            src = root() / "src" / "tools" / f"{module}.py"
            if not src.is_file() or not re.search(rf"^def handle_{action}\b", src.read_text(), re.M):
                missing.append(f"{module}.handle_{action} (called at {where})")
        self.assertEqual(missing, [], "claude-hooks no longer defines these handlers")


if __name__ == "__main__":
    unittest.main()
