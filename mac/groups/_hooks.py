"""Runs claude-hooks tool handlers (src/tools/*.handle_*) and maps their results onto the mac contract (task:5ab623ca).

The handlers are plain functions over SQLite files and the hook server's HTTP
port, so `mac` runs each one directly, without the claude-hooks MCP server.
The server's start-up is what costs: its `_bootstrap()` starts Ollama and
seeds tool_hints on every launch. Importing the handler skips that, and the
handler stays the one implementation, so a verb returns what the MCP tool
returned.

Each call is a subprocess of claude-hooks' own interpreter (its dependencies
and top-level `config` / `src` modules would clash with cli-graph's), running
_hooks_runner.py. Measured 2026-10-28: 0.2-0.6s per call, in-process would
save about 0.1s but import claude-hooks' config into every `mac` call.

Result mapping, the same as _backend's: a dict with an "error" key becomes
Failure('tool_error'); an exception inside the handler too; an interpreter
or tree that is missing becomes Failure('backend_missing').
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from mac.contract import EXIT_USAGE, Failure, raise_if_error

DEFAULT_ROOT = Path.home() / "workspace" / "claude-hooks"
RUNNER = Path(__file__).with_name("_hooks_runner.py")

# Set by bin/mac or cli-graph's venv; they must not leak into claude-hooks' interpreter.
_DROP_ENV = ("PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME")


def root():
    return Path(os.environ.get("MAC_HOOKS_ROOT", DEFAULT_ROOT))


def call(module, action, /, **kwargs):
    """Run `src/tools/<module>.handle_<action>(**kwargs)` and return its result."""
    tree = root()
    python = tree / ".venv" / "bin" / "python"
    if not python.exists():
        raise Failure("backend_missing", f"claude-hooks interpreter not found: {python} (set MAC_HOOKS_ROOT)")
    env = {k: v for k, v in os.environ.items() if k not in _DROP_ENV}
    env["MAC_HOOKS_ROOT"] = str(tree)
    proc = subprocess.run([str(python), "-I", str(RUNNER), f"tools.{module}", action],
                          input=json.dumps(kwargs), capture_output=True, text=True,
                          cwd=tree, env=env)
    try:
        # The result is the last stdout line; a library may print above it.
        reply = json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        tail = " | ".join(proc.stderr.strip().splitlines()[-5:])
        raise Failure("backend_missing", f"claude-hooks {module} {action} gave no result"
                                         + (f" (stderr: {tail})" if tail else ""))
    if "exception" in reply:
        raise Failure("tool_error", reply["exception"])
    return raise_if_error(reply["result"])


def text_or_file(ns, name, flag, required=False):
    """Fill ns.<name> from `<flag>-file PATH` (`-` for stdin) when given; the text may be long or multi-line."""
    path = getattr(ns, f"{name}_file", None)
    inline = getattr(ns, name, None)
    if path is None:
        if required and inline is None:
            raise Failure("usage", f"{name} is required: pass {flag} or {flag}-file", EXIT_USAGE)
        return
    if inline is not None:
        raise Failure("usage", f"pass {flag} or {flag}-file, not both", EXIT_USAGE)
    try:
        setattr(ns, name, sys.stdin.read() if path == "-" else Path(path).read_text())
    except OSError as exc:
        raise Failure("usage", f"cannot read {path}: {exc.strerror}", EXIT_USAGE)
