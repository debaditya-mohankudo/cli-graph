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


KEY = "ab" * 32


def _encrypted(path, key=KEY):
    import apsw

    c = apsw.Connection(str(path))
    c.pragma("cipher", "sqlcipher")
    c.pragma("hexkey", key)
    c.execute("create table t(x, y)")
    c.execute("insert into t values (1, 'a')")
    c.close()


def test_ciphertext_round_trip_and_stdlib_cannot_read(tmp_path):
    p = tmp_path / "enc.sqlite"
    _encrypted(p)
    assert not p.read_bytes().startswith(encdb.PLAIN_HEADER)
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(p).execute("select * from t")
    con = encdb.open_db(p, key=KEY)
    assert con.execute("select x from t").fetchone() == (1,)
    con.close()


def test_encrypted_write_commits_and_readonly_rejects(tmp_path):
    p = tmp_path / "enc.sqlite"
    _encrypted(p)
    con = encdb.open_db(p, key=KEY)
    con.execute("insert into t values (2, 'b')")
    con.commit()
    con.close()
    ro = encdb.open_db(p, readonly=True, key=KEY)
    assert ro.execute("select count(*) from t").fetchone() == (2,)
    with pytest.raises(Exception):
        ro.execute("insert into t values (3, 'c')")
    ro.close()


def test_encrypted_rollback_discards(tmp_path):
    p = tmp_path / "enc.sqlite"
    _encrypted(p)
    con = encdb.open_db(p, key=KEY)
    con.execute("insert into t values (9, 'z')")
    con.rollback()
    assert con.execute("select count(*) from t").fetchone() == (1,)
    con.close()


def test_encrypted_row_factory_name_access(tmp_path):
    p = tmp_path / "enc.sqlite"
    _encrypted(p)
    con = encdb.open_db(p, key=KEY)
    con.row_factory = sqlite3.Row
    r = con.execute("select x, y from t").fetchone()
    assert r["y"] == "a" and r[0] == 1
    con.close()


def test_wrong_key_is_a_clear_error(tmp_path):
    p = tmp_path / "enc.sqlite"
    _encrypted(p)
    with pytest.raises(encdb.EncDBError, match="wrong key"):
        encdb.open_db(p, key="cd" * 32)


def test_bad_key_is_rejected_before_connect(tmp_path):
    p = tmp_path / "enc.sqlite"
    _encrypted(p)
    with pytest.raises(encdb.EncDBError, match="64 hex"):
        encdb.open_db(p, key="not-hex")


def test_key_file_missing_is_a_clear_error(tmp_path):
    with pytest.raises(encdb.EncDBError, match="missing"):
        encdb.read_key(tmp_path / "nope.key")


def test_key_file_still_git_crypt_ciphertext_fails_closed(tmp_path):
    k = tmp_path / "k"
    k.write_bytes(encdb.GITCRYPT_MAGIC + b"GITCRYPT" + b"\x01" * 40)
    with pytest.raises(encdb.EncDBError, match="git-crypt"):
        encdb.read_key(k)


def test_key_file_read_and_trimmed(tmp_path):
    k = tmp_path / "k"
    k.write_text(KEY + "\n")
    assert encdb.read_key(k) == KEY


def test_encrypted_cursor_has_rowcount_lastrowid_and_sqlite3_errors(tmp_path):
    p = tmp_path / "enc.sqlite"
    _encrypted(p)
    con = encdb.open_db(p, key=KEY)
    cur = con.execute("insert into t values (2, 'b')")
    assert cur.rowcount == 1 and cur.lastrowid == 2
    assert con.execute("update t set y='z' where x=99").rowcount == 0
    assert con.execute("select x from t").rowcount == -1
    con.commit()
    with pytest.raises(sqlite3.OperationalError):
        con.execute("select * from no_such_table")
    con.close()
