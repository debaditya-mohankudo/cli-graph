"""mac curl: allowlist, redirects, audit row, caps (task:dd73e209). No network: _open is faked."""
import hashlib
import io
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from mac.contract import Failure
from mac.groups import curl


class FakeResp:
    def __init__(self, status=200, body=b"hello", headers=None):
        self.status, self._body = status, body
        self.headers = {"Content-Type": "text/plain", **(headers or {})}

    def read(self, n=-1):
        return self._body[:n] if n >= 0 else self._body

    def close(self):
        pass

    def getcode(self):
        return self.status


class CurlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {"MAC_CURL_AUDIT_DB": os.path.join(self.tmp.name, "audit.sqlite"),
               "MAC_CURL_SAVE_DIR": os.path.join(self.tmp.name, "saved"), "MAC_CURL_NO_SESSION": "1"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = env["MAC_CURL_AUDIT_DB"]

    def rows(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        out = [dict(r) for r in conn.execute("SELECT * FROM curl_audit ORDER BY id")]
        conn.close()
        return out

    def get(self, url, *responses):
        with mock.patch.object(curl, "_open", side_effect=list(responses)) as opened:
            return curl._run("GET", url, None, "curl get"), opened

    def test_get_returns_body_and_writes_one_row_without_body(self):
        (out, opened) = self.get("https://nseindia.in/api/x?token=SECRET", FakeResp(body=b"hello"))
        self.assertEqual((out["status"], out["body"]), (200, "hello"))
        (row,) = self.rows()
        self.assertEqual((row["host"], row["path"], row["method"], row["status"], row["bytes"], row["outcome"]),
                         ("nseindia.in", "/api/x", "GET", 200, 5, "ok"))
        self.assertEqual(row["body_sha256"], hashlib.sha256(b"hello").hexdigest())
        self.assertNotIn("SECRET", repr(row))
        self.assertNotIn("hello", repr(row))

    def test_http_and_unlisted_hosts_are_refused_before_any_request(self):
        for url in ("http://nseindia.in/x", "https://evil.example/x", "https://nseindia.in.evil.example/x"):
            with mock.patch.object(curl, "_open") as opened, self.assertRaises(Failure) as ctx:
                curl._run("GET", url, None, "curl get")
            self.assertEqual(ctx.exception.code, "blocked")
            opened.assert_not_called()
        self.assertEqual([r["outcome"] for r in self.rows()], ["refused"] * 3)

    def test_redirect_to_unlisted_host_is_not_fetched(self):
        redirect = FakeResp(302, headers={"Location": "https://evil.example/steal"})
        with mock.patch.object(curl, "_open", side_effect=[redirect, FakeResp()]) as opened:
            with self.assertRaises(Failure) as ctx:
                curl._run("GET", "https://nseindia.in/a", None, "curl get")
        self.assertEqual(ctx.exception.code, "blocked")
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(self.rows()[0]["outcome"], "refused")

    def test_redirect_to_http_is_refused_and_allowed_redirect_is_followed(self):
        with mock.patch.object(curl, "_open", side_effect=[
                FakeResp(302, headers={"Location": "http://nseindia.in/a"})]), self.assertRaises(Failure):
            curl._run("GET", "https://nseindia.in/a", None, "curl get")
        ok = FakeResp(302, headers={"Location": "/b"})
        (out, opened) = self.get("https://nseindia.in/a", ok, FakeResp(body=b"final"))
        self.assertEqual((out["body"], out["redirects"]), ("final", 1))

    def test_oversized_body_is_capped_inline_and_saved_in_full(self):
        big = b"x" * (curl.INLINE_CAP + 50)
        (out, _) = self.get("https://nseindia.in/big", FakeResp(body=big))
        self.assertEqual(len(out["body"]), curl.INLINE_CAP)
        self.assertTrue(out["truncated"])
        with open(out["saved_to"], "rb") as fh:
            self.assertEqual(fh.read(), big)

    def test_403_on_nse_hints_vpn_and_other_hosts_do_not(self):
        (nse, _) = self.get("https://nseindia.in/a", FakeResp(403))
        (fred, _) = self.get("https://api.stlouisfed.org/a", FakeResp(403))
        self.assertIn("vpn", nse["hint"].lower())
        self.assertNotIn("hint", fred)
        self.assertEqual(self.rows()[0]["outcome"], "http_error")

    def test_no_raw_headers_in_result(self):
        (out, _) = self.get("https://nseindia.in/a", FakeResp(headers={"Set-Cookie": "sid=abc"}))
        self.assertNotIn("abc", repr(out))

    def test_audit_failure_does_not_fail_the_fetch(self):
        with mock.patch.object(curl, "_audit_db", return_value=os.path.join(self.tmp.name, "no", "such", "x")), \
                mock.patch("sqlite3.connect", side_effect=sqlite3.OperationalError("locked")):
            (out, _) = self.get("https://nseindia.in/a", FakeResp())
        self.assertEqual(out["status"], 200)

    def test_missing_session_id_is_recorded_as_null(self):
        self.get("https://nseindia.in/a", FakeResp())
        self.assertIsNone(self.rows()[0]["session_id"])

    def test_post_hashes_request_body_and_log_filters_by_host(self):
        with mock.patch.object(curl, "_open", return_value=FakeResp(body=b"ok")):
            curl._run("POST", "https://nseindia.in/p", b"payload", "curl post")
        self.get("https://api.stlouisfed.org/a", FakeResp())
        post = self.rows()[0]
        self.assertEqual(post["request_sha256"], hashlib.sha256(b"payload").hexdigest())
        self.assertNotIn("payload", repr(post))
        from mac.registry import Registry
        r = Registry()
        curl.register(r)
        log = r.get("curl", "log").handler
        ns = mock.Mock(limit=None, spec=["limit", "host"], host="nseindia.in")
        self.assertEqual([x["host"] for x in log(ns)], ["nseindia.in"])


if __name__ == "__main__":
    unittest.main()
