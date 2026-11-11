import sqlite3

import pytest

from mac import encdb
from mac.contract import Failure
from mac.groups import encdb as grp

KEY = "ab" * 32


def _plain(path, rows=3):
    con = sqlite3.connect(path)
    con.execute("create table t(x)")
    con.execute("create table u(y)")
    con.executemany("insert into t values (?)", [(i,) for i in range(rows)])
    con.commit()
    con.close()


def test_migrate_encrypts_keeps_rows_and_backs_up(tmp_path):
    p = tmp_path / "m.sqlite"
    _plain(p)
    rep = grp.migrate(p, key=KEY)
    assert rep["rows"] == 3 and rep["integrity"] == "ok"
    assert grp._state(p) == "encrypted"
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(p).execute("select * from t")
    con = encdb.open_db(p, key=KEY)
    assert con.execute("select count(*) from t").fetchone() == (3,)
    con.close()
    bk = sqlite3.connect(rep["backup"])
    assert bk.execute("select count(*) from t").fetchone() == (3,)
    assert not list(tmp_path.glob("*.enc.*"))


def test_migrate_refuses_already_encrypted(tmp_path):
    p = tmp_path / "m.sqlite"
    _plain(p)
    grp.migrate(p, key=KEY)
    with pytest.raises(Failure, match="already encrypted"):
        grp.migrate(p, key=KEY)


def test_migrate_missing_file_fails(tmp_path):
    with pytest.raises(Failure):
        grp.migrate(tmp_path / "nope.sqlite", key=KEY)


def test_failed_verification_leaves_original_plain(tmp_path, monkeypatch):
    p = tmp_path / "m.sqlite"
    _plain(p)
    real = grp._counts
    calls = []

    def lying(con):
        calls.append(1)
        out = real(con)
        return out if len(calls) == 1 else {**out, "t": out["t"] + 1}

    monkeypatch.setattr(grp, "_counts", lying)
    with pytest.raises(Failure, match="does not match"):
        grp.migrate(p, key=KEY)
    assert grp._state(p) == "plain"
    assert sqlite3.connect(p).execute("select count(*) from t").fetchone() == (3,)
    assert not list(tmp_path.glob("*.enc.*"))


def test_wal_sidecars_are_folded_in(tmp_path):
    p = tmp_path / "m.sqlite"
    con = sqlite3.connect(p)
    con.execute("pragma journal_mode=wal")
    con.execute("create table t(x)")
    con.execute("insert into t values (1)")
    con.commit()
    # keep the connection open so -wal holds the row
    rep = grp.migrate(p, key=KEY)
    con.close()
    assert rep["rows"] == 1
    assert not (tmp_path / "m.sqlite-wal").exists()


def test_registry_covers_each_db_with_a_decision():
    assert {"memory", "server_memory", "tool_hints", "astrology", "vault_index"} <= set(grp.REGISTRY)
    assert all(v[1] in ("migrate", "leave") for v in grp.REGISTRY.values())


def test_snapshot_of_encrypted_source_is_encrypted_and_prune_keeps_newest(tmp_path):
    import os
    import apsw
    from mac import encdb
    from mac.groups import encdb as g

    key = "cd" * 32
    src = tmp_path / "MEMORY.sqlite"
    c = apsw.Connection(str(src))
    c.pragma("cipher", "sqlcipher")
    c.pragma("hexkey", key)
    c.execute("create table t(x)")
    c.execute("insert into t values (1),(2)")
    c.close()
    snaps = []
    for i in range(4):
        d = tmp_path / f"MEMORY_2026010{i}_000000.sqlite"
        r = g.snapshot(src, d, key=key)
        os.utime(d, (1000 + i, 1000 + i))
        snaps.append(d)
        assert r["encrypted"] and r["rows"] == 2
        assert not d.read_bytes().startswith(encdb.PLAIN_HEADER)
    gone = g.prune(tmp_path, "MEMORY_", 2)
    assert sorted(gone) == sorted(str(s) for s in snaps[:2])
    assert snaps[3].exists() and not snaps[0].exists()
