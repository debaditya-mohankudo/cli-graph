"""Helpers shared by the parity tests."""
import io
import sys
import types
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mac.cli import default_registry, main


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    status = main(list(argv), default_registry(), out, err)
    return status, out.getvalue(), err.getvalue()


def stub_dispatcher(resolve):
    """Replace local-mac's dispatcher: `resolve(area, action)` picks the handler, invoke skips logging."""
    ns = types.SimpleNamespace(resolve=resolve,
                               invoke=lambda area, action, handler, kwargs: handler(**kwargs))
    return mock.patch("mac.groups._backend.dispatcher", return_value=ns)
