import sqlite3

import pytest

from mac import encdb


def _plain(path):
    con = sqlite3.connect(path)
    con.execute("create table t(x)")
    con.execute("insert into t values (1)")
    con.commit()
    con.close()


def test_plain_file_opens_read_write(tmp_path):
    p = tmp_path / "a.sqlite"
    _plain(p)
    con = encdb.open_db(p)
    assert con.execute("select x from t").fetchone() == (1,)
    con.close()


def test_plain_file_readonly_rejects_writes(tmp_path):
    p = tmp_path / "a.sqlite"
    _plain(p)
    con = encdb.open_db(p, readonly=True)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("insert into t values (2)")
    con.close()


def test_missing_file_is_created_plain(tmp_path):
    con = encdb.open_db(tmp_path / "new.sqlite")
    con.execute("create table t(x)")
    con.close()


def test_ciphertext_without_binding_fails_clearly(tmp_path, monkeypatch):
    p = tmp_path / "enc.sqlite"
    p.write_bytes(b"\x8f" * 4096)
    monkeypatch.setitem(__import__("sys").modules, "sqlcipher3", None)
    with pytest.raises(encdb.EncDBError, match="no SQLCipher binding"):
        encdb.open_db(p, key="a" * 64)


def test_bad_key_is_rejected_before_use(tmp_path, monkeypatch):
    p = tmp_path / "enc.sqlite"
    p.write_bytes(b"\x8f" * 4096)

    class Fake:
        @staticmethod
        def connect(*a, **k):
            raise AssertionError("must not connect with a bad key")

    monkeypatch.setattr(encdb, "_binding", lambda: type("M", (), {"connect": Fake.connect}))
    with pytest.raises(encdb.EncDBError, match="64 hex"):
        encdb.open_db(p, key="not-hex")


def test_missing_keychain_item_message(monkeypatch):
    class R:
        returncode = 44
        stdout = ""
        stderr = ""

    monkeypatch.setattr(encdb.subprocess, "run", lambda *a, **k: R())
    encdb._key_cache.clear()
    with pytest.raises(encdb.EncDBError, match="missing"):
        encdb.read_key("svc-x", "acct-x")
