"""`mac vault_log scan` brings claude-hooks' vault index up to date from the scan (task:371976dd).

The scan is the one walk of the vault; the index re-parses only what it saw change.
An index failure must not fail the scan, whose events are already committed.
"""
import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parent.parent), str(Path(__file__).resolve().parent)]

from _helpers import run
from mac.contract import Failure
from mac.groups import _backend, vault_log

SCAN = {"scanned_at": "2026-11-25T09:00:00", "files": 3, "created": 1, "edited": 0, "deleted": 0}


class ScanSyncsTheIndexTest(unittest.TestCase):
    def scan(self, hooks):
        err = io.StringIO()
        with mock.patch.object(vault_log, "_run", return_value=dict(SCAN)) as runner, \
                mock.patch.object(vault_log, "hooks_call", side_effect=hooks) as synced, \
                contextlib.redirect_stderr(err):
            status, out, cli_err = run("vault_log", "scan")
        runner.assert_called_once_with("scan")
        synced.assert_called_once_with("vault_index", "sync_from_log")
        return status, json.loads(out), err.getvalue() + cli_err

    def test_scan_result_carries_the_index_sync(self):
        status, out, _ = self.scan(lambda *a: {"mode": "log", "indexed": 1, "removed": 0, "log_event_id": 7})
        self.assertEqual(status, 0)
        self.assertEqual(out["created"], 1)
        self.assertEqual(out["index"]["indexed"], 1)

    def test_an_index_failure_leaves_the_scan_succeeding(self):
        def boom(*a):
            raise Failure("tool_error", "vault index sync failed: disk")
        status, out, err = self.scan(boom)
        self.assertEqual(status, 0)
        self.assertEqual(out["files"], 3)
        self.assertEqual(out["index"], {"error": "vault index sync failed: disk"})
        self.assertIn("index sync failed", err)


class RemovedHandlerTest(unittest.TestCase):
    def test_a_verb_without_a_handler_is_backend_missing_not_a_keyerror(self):
        def resolve(area, action):
            raise KeyError(f"{area}__{action}")
        ns = mock.Mock(resolve=resolve)
        with mock.patch.object(_backend, "dispatcher", return_value=ns), \
                mock.patch.object(_backend, "tool_hooks"):
            with self.assertRaises(Failure) as cm:
                _backend.call("vault_rag", "index_status")
        self.assertEqual(cm.exception.code, "backend_missing")
        self.assertIn("vault_rag__index_status", cm.exception.message)
        ns.invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()
