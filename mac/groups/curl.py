"""`mac curl` — allowlisted, audited outbound HTTP (task:dd73e209).

`get` is read-only. `post` is the write-mode twin (tools/gen_permissions.py
makes it prompt on every call). Both:

* https only, and only to hosts in ALLOWED_HOSTS (a host or any subdomain of one);
* follow redirects by hand, re-checking scheme and host on every hop, so an
  allowed host cannot bounce the request to a disallowed one;
* time out, cap the body returned inline (the full body goes to a file), and
  return only content type/length, never raw response headers;
* write exactly one audit row per attempt (allowed, refused or failed) to
  AUDIT_DB. The row holds no body, no query string and no request headers; it
  records a sha256 of the response body instead. A lost row never fails a fetch.
"""
import argparse
import contextlib
import hashlib
import http.client
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from mac.cli import iso_date
from mac.contract import Failure

UNSET = argparse.SUPPRESS

# Hostnames, matched as the host itself or a subdomain of it.
ALLOWED_HOSTS = (
    "nseindia.in",
    "nsearchives.nseindia.in",
    "nseindia.com",
    "api.stlouisfed.org",
    "fred.stlouisfed.org",
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
)
NSE_HOSTS = ("nseindia.in", "nseindia.com")

TIMEOUT_S = 15
MAX_REDIRECTS = 5
INLINE_CAP = 20_000        # characters of body returned in the result
HARD_CAP = 25_000_000      # bytes read at all; the rest is dropped and flagged
VPN_HINT = "403 from NSE usually means the VPN is off; check `mac vpn status`"


def _audit_db():
    return Path(os.environ.get("MAC_CURL_AUDIT_DB", Path.home() / ".claude" / "mac_curl_audit.sqlite"))


def _save_dir():
    return Path(os.environ.get("MAC_CURL_SAVE_DIR", Path.home() / ".cache" / "mac-curl"))


_SCHEMA = """CREATE TABLE IF NOT EXISTS curl_audit (
    id INTEGER PRIMARY KEY, ts TEXT NOT NULL DEFAULT (datetime('now')), session_id TEXT,
    method TEXT, host TEXT, path TEXT, status INTEGER, bytes INTEGER, duration_ms INTEGER,
    verb TEXT, body_sha256 TEXT, request_sha256 TEXT, outcome TEXT)"""


def _session_id():
    """The current session id, or None. The hook server may be down: never raise."""
    if os.environ.get("MAC_CURL_NO_SESSION"):
        return None
    try:
        from mac.groups._hooks import call
        result = call("hooks", "session_id")
        return result.get("session_id") if isinstance(result, dict) else None
    except Exception:
        return None


_COLS = ("session_id", "method", "host", "path", "status", "bytes", "duration_ms",
         "verb", "body_sha256", "request_sha256", "outcome")


def _audit(row):
    try:
        path = _audit_db()
        path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(sqlite3.connect(path, timeout=2)) as conn, conn:
            conn.execute(_SCHEMA)
            conn.execute(f"INSERT INTO curl_audit ({','.join(_COLS)}) VALUES ({','.join('?' * len(_COLS))})",
                         [row.get(c) for c in _COLS])
    except Exception as exc:  # a lost row must not change what the caller sees
        print(f"mac curl: audit write failed: {exc}", file=sys.stderr)


def _host_in(host, hosts):
    return any(host == h or host.endswith("." + h) for h in hosts)


def _check(url):
    """(host, path) of an acceptable URL, else Failure('blocked')."""
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise Failure("blocked", f"https only, got {parts.scheme or 'no'} scheme")
    if not _host_in(host, ALLOWED_HOSTS):
        raise Failure("blocked", f"host {host or '?'} is not on the allowlist")
    return host, parts.path or "/"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _open(method, url, data):
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "mac-curl/1"})
    try:
        return opener.open(req, timeout=TIMEOUT_S)
    except urllib.error.HTTPError as err:
        return err  # also a response: status, headers, body


def _is_nse(host):
    return _host_in(host, NSE_HOSTS)


def _transport(method, url, data):
    """(status, content_type, body, dropped, hops, host, path); redirects re-checked every hop."""
    hops = 0
    while True:
        host, path = _check(url)
        resp = _open(method, url, data)
        status = resp.status if hasattr(resp, "status") else resp.getcode()
        location = resp.headers.get("Location")
        if status in (301, 302, 303, 307, 308) and location:
            resp.close()
            hops += 1
            if hops > MAX_REDIRECTS:
                raise Failure("tool_error", f"more than {MAX_REDIRECTS} redirects")
            url = urllib.parse.urljoin(url, location)
            if status in (301, 302, 303):
                method, data = "GET", None
            continue
        body = resp.read(HARD_CAP + 1)
        ctype = resp.headers.get("Content-Type")
        resp.close()
        return status, ctype, body[:HARD_CAP], len(body) > HARD_CAP, hops, host, path


def _run(method, url, data, verb):
    started = time.monotonic()
    row = {"method": method, "verb": verb, "outcome": "error", "host": urllib.parse.urlsplit(url).hostname,
           "path": urllib.parse.urlsplit(url).path or "/",
           "request_sha256": hashlib.sha256(data).hexdigest() if data else None}
    try:
        status, ctype, body, dropped, hops, row["host"], row["path"] = _transport(method, url, data)
    except Failure as failure:
        row["outcome"] = "refused" if failure.code == "blocked" else "error"
        raise
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        raise Failure("tool_error", f"request failed: {getattr(exc, 'reason', exc)}")
    else:
        row.update(status=status, bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest(),
                   outcome="ok" if status < 400 else "http_error")
    finally:
        row["duration_ms"] = int((time.monotonic() - started) * 1000)
        row["session_id"] = _session_id()
        _audit(row)

    text = body.decode("utf-8", errors="replace")
    out = {"host": row["host"], "status": status, "bytes": len(body), "content_type": ctype,
           "redirects": hops, "body": text[:INLINE_CAP]}
    if len(text) > INLINE_CAP or dropped:
        directory = _save_dir()
        directory.mkdir(parents=True, exist_ok=True)
        saved = directory / f"{row['body_sha256'][:16]}.body"
        saved.write_bytes(body)
        out.update(truncated=True, saved_to=str(saved))
        if dropped:
            out["dropped_beyond_bytes"] = HARD_CAP
    if status == 403 and _is_nse(row["host"]):
        out["hint"] = VPN_HINT
    return out


def register(registry):
    def get_args(p):
        p.add_argument("url", help="https URL on the allowlist")
        p.add_argument("--via", default=UNSET, help="calling verb recorded in the audit row (default: curl get)")

    @registry.verb("curl", "get", mode="read",
                   desc="HTTP GET an allowlisted https URL (NSE, FRED, Yahoo); audited, redirects re-checked, body capped",
                   args=get_args)
    def get(ns):
        return _run("GET", ns.url, None, getattr(ns, "via", "curl get"))

    def post_args(p):
        p.add_argument("url", help="https URL on the allowlist")
        p.add_argument("--data", required=True, help="request body, sent as-is")

    @registry.verb("curl", "post", mode="write",
                   desc="HTTP POST to an allowlisted https URL; audited, asks for confirmation on every call",
                   args=post_args)
    def post(ns):
        return _run("POST", ns.url, ns.data.encode(), "curl post")

    def log_args(p):
        p.add_argument("--host", default=UNSET, help="only this host (exact)")
        p.add_argument("--since", default=UNSET, type=iso_date, help="YYYY-MM-DD, UTC; only rows on or after it")

    @registry.verb("curl", "log", mode="read",
                   desc="audit log of mac curl requests: time, session, method, host, path, status, bytes, outcome",
                   args=log_args)
    def log(ns):
        path = _audit_db()
        if not path.exists():
            return []
        where, params = ["1=1"], []
        if hasattr(ns, "host"):
            where.append("host = ?")
            params.append(ns.host.lower())
        if hasattr(ns, "since"):
            where.append("ts >= ?")
            params.append(ns.since)
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            with conn:
                rows = conn.execute(f"SELECT * FROM curl_audit WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
                                    (*params, ns.limit or 100)).fetchall()
            conn.close()
        except sqlite3.Error as exc:
            raise Failure("tool_error", f"cannot read audit log {path}: {exc}")
        return [dict(r) for r in rows]
