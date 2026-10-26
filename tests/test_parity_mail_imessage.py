"""`mac mail` / `mac imessage`: argument forwarding and the send/delete gates (task:babafba2).

Coverage, modes and generated-module freshness are checked with the other
generated groups in test_parity_simple_groups.py.

The gates live in local-mac's tool_hooks and run inside dispatcher.invoke:
imessage send needs a contacts search within 120s that found someone, mail
delete needs a mail read within 120s. GateTest runs the real invoke against a
scratch DB with stubbed handlers, so the allowed path is checked without
sending a message or trashing mail. Live tests (MAC_PARITY_LIVE=1) check read
parity and that the refusals come back as 'blocked'; the allowed path is never
run live.
"""
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parent.parent), str(Path(__file__).resolve().parent)]

from _helpers import run, stub_dispatcher
from mac.groups import _backend


def handlers(module):
    return stub_dispatcher(lambda area, action: getattr(module, f"handle_{action}"))


class ForwardingTest(unittest.TestCase):
    CASES = [
        ("mail", ["read"], "read", {}),
        ("mail", ["read", "--limit", "5", "--folder", "Sent", "--account", "icloud"], "read",
         {"limit": 5, "folder": "Sent", "account": "icloud"}),
        ("mail", ["get", "42"], "get", {"message_id": 42}),
        ("mail", ["search", "invoice"], "search", {"query": "invoice"}),
        ("mail", ["compose", "a@b.c", "--subject", "s"], "compose", {"to": "a@b.c", "subject": "s"}),
        ("mail", ["delete", "7"], "delete", {"message_ids": [7]}),
        ("mail", ["delete", "7", "8", "--folder", "Spam"], "delete", {"message_ids": [7, 8], "folder": "Spam"}),
        ("mail", ["move", "7", "8", "Useful"], "move", {"message_ids": [7, 8], "dest_mailbox": "Useful"}),
        ("mail", ["move", "7", "Useful", "--src-folder", "Spam"], "move",
         {"message_ids": [7], "dest_mailbox": "Useful", "src_folder": "Spam"}),
        ("mail", ["add_local_mailbox", "Finance"], "add_local_mailbox", {"name": "Finance"}),
        ("imessage", ["send", "+15550100", "hi"], "send", {"recipient": "+15550100", "message": "hi"}),
        ("imessage", ["send", "+15550100", "hi", "--delay-seconds", "5"], "send",
         {"recipient": "+15550100", "message": "hi", "delay_seconds": 5}),
        ("imessage", ["read"], "read", {}),
        ("imessage", ["read", "--limit", "3", "--direction", "all"], "read", {"limit": 3, "direction": "all"}),
    ]

    def test_only_supplied_args_reach_the_handler(self):
        for area, argv, action, kwargs in self.CASES:
            with self.subTest(argv=[area, *argv]):
                module = mock.Mock(**{f"handle_{action}.return_value": "ok"})
                with handlers(module):
                    status, _, err = run(area, *argv)
                self.assertEqual(status, 0, err)
                getattr(module, f"handle_{action}").assert_called_once_with(**kwargs)

    def test_message_ids_must_be_integers(self):
        mail = mock.Mock()
        with handlers(mail):
            for argv in (("delete",), ("delete", "abc"), ("move", "Useful")):
                status, _, err = run("mail", *argv)
                self.assertEqual((status, json.loads(err)["error"]["code"]), (2, "usage"), argv)
        mail.handle_delete.assert_not_called()
        mail.handle_move.assert_not_called()


class EnvTest(unittest.TestCase):
    def test_dotenv_fills_missing_vars_without_overriding(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("MAC_TEST_FROM_FILE=file\nMAC_TEST_SET=file\n")
            with mock.patch.dict(os.environ, {"MAC_TEST_SET": "shell"}):
                os.environ.pop("MAC_TEST_FROM_FILE", None)
                _backend._load_env(env)
                self.assertEqual(os.environ["MAC_TEST_FROM_FILE"], "file")
                self.assertEqual(os.environ["MAC_TEST_SET"], "shell")
            os.environ.pop("MAC_TEST_FROM_FILE", None)


class GateTest(unittest.TestCase):
    """Real dispatcher.invoke and tool_hooks gates against a scratch DB; only resolve is stubbed."""

    def setUp(self):
        hooks = _backend.tool_hooks()
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.db = Path(scratch.name) / "tool_hints.sqlite"
        for patcher in (mock.patch.object(hooks, "_DB_PATH", self.db),):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.mods = mock.Mock(**{"handle_send.return_value": "sent", "handle_delete.return_value": {"deleted": [7]},
                                 "handle_read.return_value": [], "handle_search.return_value": [{"name": "A"}]})
        resolve = mock.patch.object(_backend.dispatcher(), "resolve",
                                    lambda area, action: getattr(self.mods, f"handle_{action}"))
        resolve.start()
        self.addCleanup(resolve.stop)

    def blocked(self, *argv):
        status, _, err = run(*argv)
        self.assertEqual(status, 1, err)
        error = json.loads(err)["error"]
        self.assertEqual(error["code"], "blocked")
        return error["message"]

    def rows(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute("SELECT domain, action, ok, blocked FROM mcp_tool_calls").fetchall()

    def test_imessage_send_refused_without_contacts_search(self):
        self.assertIn("contacts__search", self.blocked("imessage", "send", "A", "hi"))
        self.mods.handle_send.assert_not_called()
        self.assertEqual(self.rows(), [("imessage", "send", 0, 1)])

    def test_imessage_send_allowed_after_contacts_search(self):
        self.assertEqual(run("contacts", "search", "A")[0], 0)
        status, out, err = run("imessage", "send", "A", "hi")
        self.assertEqual((status, json.loads(out)), (0, "sent"), err)

    def test_mail_delete_refused_without_mail_read(self):
        self.assertIn("mail__read", self.blocked("mail", "delete", "7"))
        self.mods.handle_delete.assert_not_called()
        self.assertEqual(self.rows(), [("mail", "delete", 0, 1)])

    def test_mail_delete_allowed_after_mail_read(self):
        self.assertEqual(run("mail", "read")[0], 0)
        status, out, err = run("mail", "delete", "7")
        self.assertEqual((status, json.loads(out)), (0, {"deleted": [7]}), err)
        self.mods.handle_delete.assert_called_once_with(message_ids=[7])


def real_handler(area, action):
    module_path = _backend.dispatcher().DOMAIN_MAP[area][0]
    return getattr(importlib.import_module(module_path), f"handle_{action}")


@unittest.skipUnless(os.environ.get("MAC_PARITY_LIVE") == "1", "set MAC_PARITY_LIVE=1 to touch the Mac")
class LiveTest(unittest.TestCase):
    def cli(self, *argv):
        status, out, err = run(*argv)
        self.assertEqual(status, 0, err)
        return json.loads(out)

    def same(self, area, action, *argv, **kwargs):
        self.assertEqual(self.cli(area, action, *argv), real_handler(area, action)(**kwargs))

    def test_reads_match_handlers(self):
        self.same("mail", "list_mailboxes")
        self.same("mail", "list_drafts", "--limit", "3", limit=3)
        self.same("mail", "read", "--limit", "3", limit=3)
        self.same("imessage", "read", "--limit", "3", "--direction", "sent", limit=3, direction="sent")

    def test_send_refused_after_a_search_that_found_nobody(self):
        self.assertEqual(self.cli("contacts", "search", f"zz-no-such-contact-{os.getpid()}"), [])
        status, _, err = run("imessage", "send", "nobody@invalid.example", "mac parity")
        self.assertEqual((status, json.loads(err)["error"]["code"]), (1, "blocked"), err)
        self.assertIn("found no matching contact", err)

    def test_delete_refused_without_a_recent_read(self):
        hooks = _backend.tool_hooks()
        if hooks._called_recently("mail__read"):
            self.skipTest("a mail read ran in the last 120s, so the gate would pass")
        # id 0 matches no message, so even a gate regression trashes nothing.
        status, _, err = run("mail", "delete", "0")
        self.assertEqual((status, json.loads(err)["error"]["code"]), (1, "blocked"), err)


if __name__ == "__main__":
    unittest.main()
