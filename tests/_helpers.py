"""Helpers shared by the parity tests."""
import io
import sys
import types
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mac.cli import default_registry, main
from mac.contract import Failure
from mac.groups import _backend

# Every parity test runs local-mac's handlers in-process. Without its
# dependencies (e.g. plain Homebrew python3 has no pydantic) each test would
# fail on its own with backend_missing, so fail the import once, with the fix.
try:
    _backend.dispatcher()
    _backend.tool_hooks()
except Failure as exc:
    raise ImportError(
        f"local-mac backend unavailable ({exc}). "
        "Run the suite with `uv run python -m unittest discover -s tests`.") from exc


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    status = main(list(argv), default_registry(), out, err)
    return status, out.getvalue(), err.getvalue()


def stub_dispatcher(resolve):
    """Replace local-mac's dispatcher: `resolve(area, action)` picks the handler, invoke skips logging."""
    ns = types.SimpleNamespace(resolve=resolve,
                               invoke=lambda area, action, handler, kwargs: handler(**kwargs))
    return mock.patch("mac.groups._backend.dispatcher", return_value=ns)
