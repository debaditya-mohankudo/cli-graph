"""One opener for personal SQLite files that may be SQLCipher-encrypted.

    from mac.encdb import open_db
    con = open_db("~/.claude/MEMORY.sqlite")             # read-write
    con = open_db("~/.claude/MEMORY.sqlite", readonly=True)  # mode=ro URI

A file that is plain SQLite (or does not exist yet) opens with the stdlib
`sqlite3`, so tests and unmigrated DBs keep working. A file that is not plain
SQLite is treated as ciphertext: the key comes from the login Keychain, is
applied right after connect, and is verified with one read. Every failure
raises EncDBError with a message that says what to fix.

The key is cached per process, because a Keychain fetch costs ~20 ms and the
prompt hook cannot pay that on every open.
"""
from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

KEYCHAIN_SERVICE = "memory-sqlite-key"
KEYCHAIN_ACCOUNT = "claude"
PLAIN_HEADER = b"SQLite format 3\x00"

_key_cache: dict[tuple[str, str], str] = {}


class EncDBError(RuntimeError):
    """The encrypted DB cannot be opened; the message says why."""


def is_plain(path: Path) -> bool:
    """True when the file is absent, empty, or plain SQLite."""
    try:
        with open(path, "rb") as f:
            head = f.read(len(PLAIN_HEADER))
    except FileNotFoundError:
        return True
    return head == b"" or head == PLAIN_HEADER


def read_key(service: str = KEYCHAIN_SERVICE, account: str = KEYCHAIN_ACCOUNT) -> str:
    """Hex key from the login Keychain, cached for the life of the process."""
    ck = (service, account)
    if ck in _key_cache:
        return _key_cache[ck]
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError as e:
        raise EncDBError("`security` not found: Keychain is only available on macOS") from e
    except subprocess.TimeoutExpired as e:
        raise EncDBError("Keychain read timed out (locked, or an access prompt is waiting)") from e
    if r.returncode == 44:
        raise EncDBError(
            f"Keychain item {service!r}/{account!r} is missing; store the key from "
            "secrets/memory.key with `security add-generic-password`"
        )
    if r.returncode != 0:
        raise EncDBError(
            f"Keychain read failed (exit {r.returncode}): {r.stderr.strip() or 'locked or access denied'}"
        )
    key = r.stdout.strip()
    if len(key) != 64 or any(c not in "0123456789abcdefABCDEF" for c in key):
        raise EncDBError("Keychain key is not 64 hex characters")
    _key_cache[ck] = key
    return key


def _binding():
    try:
        import sqlcipher3  # type: ignore
    except ImportError as e:
        raise EncDBError(
            "no SQLCipher binding: install sqlcipher (brew) and sqlcipher3, "
            "then retry; the file is encrypted and plain sqlite3 cannot read it"
        ) from e
    return sqlcipher3


def open_db(path: str | Path, *, readonly: bool = False, key: str | None = None, **kwargs):
    """Open `path`, decrypting with the Keychain key when it is not plain SQLite."""
    p = Path(path).expanduser()
    if is_plain(p):
        if readonly:
            return sqlite3.connect(f"{p.as_uri()}?mode=ro", uri=True, **kwargs)
        return sqlite3.connect(str(p), **kwargs)

    cipher = _binding()
    hexkey = key or read_key()
    if len(hexkey) != 64 or any(c not in "0123456789abcdefABCDEF" for c in hexkey):
        raise EncDBError("key is not 64 hex characters")
    con = cipher.connect(f"{p.as_uri()}?mode=ro" if readonly else str(p), uri=readonly, **kwargs)
    # PRAGMA key takes no bound parameters; the value is validated hex, not user text.
    con.execute(f"PRAGMA key = \"x'{hexkey}'\"")
    try:
        con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except Exception as e:
        con.close()
        raise EncDBError(f"{p.name}: wrong key or not a SQLCipher database ({e})") from e
    return con
