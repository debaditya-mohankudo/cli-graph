"""Runs local-mac MCP tool handlers and maps their results onto the mac contract.

The handlers stay the single implementation, and so does the routing: a verb
goes through local-mac's dispatcher.resolve (DOMAIN_MAP) and dispatcher.invoke,
the same path the MCP tools use. So a CLI call is logged to mcp_tool_calls and
passes the same gates (imessage send needs a recent contacts search, mail delete
a recent mail read). Those gates read the persisted log, so they hold even
though each `mac` call is its own process.

The contract overrides the MCP shape in two places: an `{"error": ...}` result
or a raised ValueError/RuntimeError becomes Failure('tool_error'), and a
tool_hooks.Refused (a gate, or a handler refusing a path) becomes
Failure('blocked'). Both go to stderr as JSON with a non-zero exit.
"""
import functools
import importlib
import os
import sys
from pathlib import Path

from mac.contract import Failure, raise_if_error

DEFAULT_SRC = Path.home() / "workspace" / "claude_for_mac_local" / "src"


def _src():
    src = os.environ.get("MAC_MCP_SRC", str(DEFAULT_SRC))
    if not Path(src).is_dir():
        raise Failure("backend_missing", f"MCP source tree not found: {src} (set MAC_MCP_SRC)")
    if src not in sys.path:
        sys.path.insert(0, src)
    # Not tied to the sys.path insert: cli-graph's venv installs local-mac in
    # editable mode, so src is often on sys.path already (task:2ee06de6).
    _load_env(Path(src).parent / ".env")


@functools.cache  # once per process; _src runs on every call
def _load_env(path):
    """Load local-mac's .env the way mcp_server.py does, without overriding the environment.

    Handlers read config such as MAIL_ACCOUNTS from the environment at import,
    and the MCP server gets it from this file. Without it every `mac mail` verb
    fails with 'No mail accounts configured' (task:babafba2).
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # no python-dotenv (e.g. plain python3); handlers that need .env say so themselves
        return
    load_dotenv(path, override=False)


def _load(name):
    _src()
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise Failure("backend_missing", f"cannot load local-mac {name}: {exc}")


def dispatcher():
    """local-mac's dispatcher. Without it the gates would not run, so a missing one is a failure."""
    return _load("dispatcher")


def tool_hooks():
    """local-mac's tool_hooks: the gates and the Refused they raise."""
    return _load("tool_hooks")


def given(ns, names):
    """The handler arguments the user actually supplied: `names` present on ns and not None.

    Optional flags default to argparse.SUPPRESS, so an omitted one is absent and
    the handler's own default applies. The global --limit defaults to None, so
    it reaches a handler's `limit` only when passed.
    """
    return {n: v for n in names if (v := getattr(ns, n, None)) is not None}


def call(area, action, /, **kwargs):
    """Run the `<area>__<action>` handler through the dispatcher and translate its result."""
    d = dispatcher()
    refused = tool_hooks().Refused
    try:
        result = d.invoke(area, action, d.resolve(area, action), kwargs)
    except refused as exc:
        raise Failure("blocked", str(exc))
    except (ValueError, RuntimeError) as exc:
        raise Failure("tool_error", str(exc))
    return raise_if_error(result)
