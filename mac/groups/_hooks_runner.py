"""Child side of mac/groups/_hooks.py: runs one claude-hooks tool handler and prints its result.

Runs under claude-hooks' own interpreter, never cli-graph's, so it imports
nothing from cli-graph. It runs with -I: this file sits beside mac's `memory`
and `hooks` groups, which would otherwise shadow claude-hooks' modules of the same name. argv is `<module> <action>`; the handler's keyword
arguments arrive as a JSON object on stdin. The result goes to stdout as one
JSON line: {"result": ...} or {"exception": "..."}.

The handler runs with stdout pointed at stderr, so anything a tool prints
cannot corrupt the result line.
"""
import importlib
import json
import os
import sys

ROOT = os.environ["MAC_HOOKS_ROOT"]


def main():
    module, action = sys.argv[1:3]
    kwargs = json.loads(sys.stdin.read() or "{}")
    sys.path[:0] = [ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "hooks")]
    real_stdout, sys.stdout = sys.stdout, sys.stderr
    try:
        result = getattr(importlib.import_module(module), f"handle_{action}")(**kwargs)
        line = json.dumps({"result": result}, default=str)
    except Exception as exc:
        line = json.dumps({"exception": f"{type(exc).__name__}: {exc}"})
    finally:
        sys.stdout = real_stdout
    print(line)


main()
