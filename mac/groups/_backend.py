"""Loads the local-mac MCP tool handlers and maps their results onto the mac contract.

The handlers stay the single implementation, so a verb returns what its MCP tool
returns for the same inputs, except where the contract overrides the MCP shape:
an `{"error": ...}` result or a raised ValueError/RuntimeError becomes a Failure
(JSON on stderr, non-zero exit), and the "No ... found." strings become [].
"""
import importlib
import os
import sys
from pathlib import Path

from mac.contract import Failure

DEFAULT_SRC = Path.home() / "workspace" / "claude_for_mac_local" / "src"
EMPTY_RESULTS = {"No notes found.", "No folders found.", "No reminders found."}


def tools(name):
    """Import `tools.<name>` from the MCP source tree (MAC_MCP_SRC overrides the path)."""
    src = os.environ.get("MAC_MCP_SRC", str(DEFAULT_SRC))
    if not Path(src).is_dir():
        raise Failure("backend_missing", f"MCP source tree not found: {src} (set MAC_MCP_SRC)")
    if src not in sys.path:
        sys.path.insert(0, src)
    return importlib.import_module(f"tools.{name}")


def call(handler, **kwargs):
    """Run an MCP handler and translate its result."""
    try:
        result = handler(**kwargs)
    except (ValueError, RuntimeError) as exc:
        raise Failure("tool_error", str(exc))
    if isinstance(result, dict) and "error" in result:
        raise Failure("tool_error", str(result["error"]))
    if isinstance(result, str) and result in EMPTY_RESULTS:
        return []
    return result
