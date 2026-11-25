"""Log when Obsidian vault files were created, edited, deleted and read, in a SQLite file under ~/.claude.

The log lives at ``~/.claude/vault_file_log.sqlite`` (override: $VAULT_FILE_LOG_DB), off iCloud
because SQLite hit disk I/O errors on the synced path; ``mac encdb backup vault_file_log`` snapshots it
daily to iCloud. It is APPEND-ONLY: every write is an INSERT, and triggers abort any
UPDATE or DELETE on every table, so history cannot be rewritten by this script
or by a stray ``sqlite3`` session.

Tables (all insert-only; ids are AUTOINCREMENT, so a row's id is never reused and
the newest row of a path is its highest id; a log created before 2026-11-03 07:35
has plain INTEGER PRIMARY KEY ids, which the delete trigger keeps equally safe):

* ``file_versions`` -- one row each time a path's state changes (new, edited,
  deleted, back again). The current state of a path is its newest row; the
  ``files_current`` view shows that for live paths.
* ``events``        -- ``created`` / ``edited`` / ``deleted`` (written by ``scan``)
  and ``read`` (written by ``log-read`` only: the filesystem does not record
  reads, atime does not update on this volume, so whoever reads a note logs it).
* ``scans``         -- one row per scan run.

``sha256`` (hex SHA-256 of the content) is on ``file_versions`` and on created/edited
``events``. ``scan`` hashes every new or changed file, and also inserts a fresh version
row for an unchanged file whose newest version has no hash yet (old rows cannot be
updated, so a hash arrives as a new version, not an edit; no event is written). Files
iCloud has evicted are not hashed (reading would download them) and are retried on the
next scan; ``backfill`` rows carry no hash.
* ``files_baseline_2026_11_03`` -- the frozen first-scan snapshot, kept as it was.

``scan`` stats every file (skipping ``.obsidian``, ``.git``, ``.trash`` and the
log itself) against each path's newest version. The first scan on an empty log
only baselines ``file_versions`` (no events); ``birth_ts`` still answers "created
today" for older files because it is the filesystem birth time.

Moved here from stock-tracker-mcp's scripts/vault_file_log.py on 2026-11-25 (task:371976dd),
history up to 1c527a0 there. Only the location changed: `mac vault_log` (mac/groups/vault_log.py)
and local-mac's `mac vault recent` both run it as a script with -I and --json, as before, so it
stays stdlib-only. $MAC_VAULT_LOG_SCRIPT still overrides the path in both.

    mac vault_log scan                                        # record changes (and sync the vault index)
    mac vault_log recent --days 7 --kind created
    mac vault_log history "Stocks/US/MDB_tracker.md"
    mac vault_log log_read "Stocks/US/MDB_tracker.md" --by vault-search
    python -I mac/vault_file_log.py --json recent             # standalone, as local-mac runs it
    python -I mac/vault_file_log.py backfill                  # created events from birth_ts, once

Caveats: it sees a change only when a scan runs, so several edits between scans
collapse to one ``edited`` row carrying the latest mtime. Edits that sync in from
another device carry that device's mtime; ``logged_at`` is when this machine saw
it. Journal mode is DELETE (no -wal/-shm files) because iCloud syncs the folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

VAULT = Path(
    os.environ.get(
        "VAULT",
        Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents",
    )
)
DB = Path(os.environ.get("VAULT_FILE_LOG_DB", Path.home() / ".claude" / "vault_file_log.sqlite"))
SKIP_DIRS = {".obsidian", ".git", ".trash"}
SKIP_NAMES = {".DS_Store", DB.name}
SKIP_SUFFIXES = (".icloud", ".sqlite-journal")
BASELINE = "files_baseline_2026_11_03"

SCHEMA = """
CREATE TABLE IF NOT EXISTS file_versions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    path      TEXT NOT NULL,      -- relative to the vault root
    birth_ts  TEXT,               -- filesystem birth time, local ISO
    mtime_ts  TEXT NOT NULL,      -- last modified, local ISO
    mtime     REAL NOT NULL,
    size      INTEGER NOT NULL,
    deleted   INTEGER NOT NULL DEFAULT 0,
    seen_at   TEXT NOT NULL,      -- scan that recorded this state
    sha256    TEXT                -- hex SHA-256 of the content; NULL if not hashed (iCloud-evicted, unreadable, deleted)
);
CREATE INDEX IF NOT EXISTS file_versions_path ON file_versions(path, id);
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    event     TEXT NOT NULL CHECK (event IN ('created','edited','deleted','read')),
    path      TEXT NOT NULL,
    event_ts  TEXT NOT NULL,      -- birth (created), mtime (edited), scan time (deleted), read time (read)
    size      INTEGER,
    logged_at TEXT NOT NULL,      -- when a scan saw it / when the read was logged
    source    TEXT,               -- read events: who read it (vault-search, vault-save, ...)
    sha256    TEXT                -- created/edited events from 2026-11-03 on: content hash at that moment
);
CREATE INDEX IF NOT EXISTS events_ts ON events(event_ts);
CREATE INDEX IF NOT EXISTS events_path ON events(path);
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT, scanned_at TEXT NOT NULL,
    files INTEGER, created INTEGER, edited INTEGER, deleted INTEGER, baseline INTEGER
);
"""
VIEW = """CREATE VIEW files_current AS
    SELECT path, birth_ts, mtime_ts, mtime, size, seen_at, sha256
    FROM file_versions
    WHERE id IN (SELECT MAX(id) FROM file_versions GROUP BY path) AND deleted = 0"""


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def walk():
    for root, dirs, names in os.walk(VAULT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in names:
            if n in SKIP_NAMES or n.endswith(SKIP_SUFFIXES):
                continue
            p = Path(root, n)
            try:
                st = p.stat()
            except OSError:
                continue
            birth = getattr(st, "st_birthtime", None)
            yield str(p.relative_to(VAULT)), st.st_mtime, st.st_size, birth


def file_hash(rel: str) -> str | None:
    """SHA-256 of a vault file, or None when it cannot be read cheaply: an iCloud-evicted
    (dataless) file would be downloaded by reading it, so it is skipped and hashed on a later scan."""
    p = VAULT / rel
    try:
        if getattr(p.stat(), "st_flags", 0) & 0x40000000:  # SF_DATALESS
            return None
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def add_sha256(db: sqlite3.Connection) -> None:
    """Add the sha256 column to a log made before it existed (ADD COLUMN is not an UPDATE, so the
    append-only triggers allow it) and rebuild the files_current view to expose it."""
    for t in ("file_versions", "events"):
        if "sha256" not in [r[1] for r in db.execute(f"PRAGMA table_info({t})")]:
            db.execute(f"ALTER TABLE {t} ADD COLUMN sha256 TEXT")
    v = db.execute("SELECT sql FROM sqlite_master WHERE name='files_current'").fetchone()
    if not v or "sha256" not in v[0]:
        db.execute("DROP VIEW IF EXISTS files_current")
        db.execute(VIEW)
    db.commit()


def lock_down(db: sqlite3.Connection) -> None:
    """Abort every UPDATE and DELETE: the log only grows."""
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tables:
        for op in ("UPDATE", "DELETE"):
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END"
            )


def migrate(db: sqlite3.Connection) -> None:
    """Move the old mutable ``files`` table (one row per path, updated in place) to the
    insert-only ``file_versions``. Rows are copied, then the old table is renamed and
    frozen as a baseline; nothing is deleted or updated."""
    has_files = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='files'").fetchone()
    if not has_files:
        return
    db.executescript(SCHEMA)
    db.execute(
        "INSERT INTO file_versions(path,birth_ts,mtime_ts,mtime,size,deleted,seen_at) "
        "SELECT path,birth_ts,mtime_ts,mtime,size,deleted,first_seen FROM files ORDER BY path"
    )
    db.execute(f"ALTER TABLE files RENAME TO {BASELINE}")
    db.commit()


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.execute("PRAGMA journal_mode=DELETE")
    old = db.execute("SELECT sql FROM sqlite_master WHERE name='events'").fetchone()
    if old and "'read'" not in old[0]:
        raise SystemExit("events table predates the read event; run with the previous script version first")
    migrate(db)
    db.executescript(SCHEMA)
    add_sha256(db)
    lock_down(db)
    return db


def version_row(path, mtime, size, birth, deleted, now, sha=None):
    return (path, iso(birth) if birth else None, iso(mtime), mtime, size, deleted, now, sha)


def scan(as_json: bool = False):
    db = connect()
    now = iso(datetime.now().timestamp())
    baseline = db.execute("SELECT COUNT(*) FROM file_versions").fetchone()[0] == 0
    known = {
        r[0]: r
        for r in db.execute(
            "SELECT path, mtime, size, deleted, birth_ts, sha256 FROM file_versions "
            "WHERE id IN (SELECT MAX(id) FROM file_versions GROUP BY path)"
        )
    }
    ins_v = ("INSERT INTO file_versions(path,birth_ts,mtime_ts,mtime,size,deleted,seen_at,sha256) "
             "VALUES (?,?,?,?,?,?,?,?)")
    ins_e = "INSERT INTO events(event,path,event_ts,size,logged_at,sha256) VALUES (?,?,?,?,?,?)"
    seen = set()
    n_c = n_e = n_d = n_h = 0
    for path, mtime, size, birth in walk():
        seen.add(path)
        row = known.get(path)
        if row is None or row[3]:  # new path, or back after a delete
            sha = file_hash(path)
            db.execute(ins_v, version_row(path, mtime, size, birth, 0, now, sha))
            if not baseline:
                db.execute(ins_e, ("created", path, iso(birth or mtime), size, now, sha))
                n_c += 1
        elif row[1] != mtime or row[2] != size:
            sha = file_hash(path)
            db.execute(ins_v, version_row(path, mtime, size, birth, 0, now, sha))
            db.execute(ins_e, ("edited", path, iso(mtime), size, now, sha))
            n_e += 1
        elif row[5] is None and (sha := file_hash(path)):  # unchanged file not hashed yet
            db.execute(ins_v, version_row(path, mtime, size, birth, 0, now, sha))
            n_h += 1
    for path, row in known.items():
        if path not in seen and not row[3]:
            db.execute(ins_v, (path, row[4], iso(row[1]), row[1], row[2], 1, now, None))
            db.execute(ins_e, ("deleted", path, now, None, now, None))
            n_d += 1
    db.execute(
        "INSERT INTO scans(scanned_at,files,created,edited,deleted,baseline) VALUES (?,?,?,?,?,?)",
        (now, len(seen), n_c, n_e, n_d, int(baseline)),
    )
    db.commit()
    if as_json:
        return {"scanned_at": now, "files": len(seen), "created": n_c, "edited": n_e,
                "deleted": n_d, "hashed": n_h, "baseline": baseline}
    tag = " (baseline: files recorded, no events)" if baseline else ""
    print(f"scan {now}: {len(seen)} files, +{n_c} created, ~{n_e} edited, -{n_d} deleted, #{n_h} newly hashed{tag}")


def backfill(as_json: bool = False):
    """Insert a ``created`` event (event_ts = registered birth_ts) for every live path that has none.

    The baseline scan records files but no events, so pre-baseline files have no
    ``created`` row. Idempotent: a path that already has a ``created`` event is skipped.
    Rows are tagged ``source='backfill'``; ``logged_at`` is when the backfill ran."""
    db = connect()
    now = iso(datetime.now().timestamp())
    rows = db.execute(
        "SELECT path, COALESCE(birth_ts, mtime_ts), size FROM files_current "
        "WHERE path NOT IN (SELECT path FROM events WHERE event='created')"
    ).fetchall()
    db.executemany(
        "INSERT INTO events(event,path,event_ts,size,logged_at,source) VALUES ('created',?,?,?,?,'backfill')",
        [(path, ts, size, now) for path, ts, size in rows],
    )
    db.commit()
    if as_json:
        return {"backfilled": len(rows), "logged_at": now}
    print(f"backfill {now}: +{len(rows)} created events (source=backfill)")


def log_read(paths: list[str], by: str | None, as_json: bool = False):
    db = connect()
    now = iso(datetime.now().timestamp())
    out = []
    for raw in paths:
        p = Path(raw)
        rel = str(p.relative_to(VAULT)) if p.is_absolute() else raw
        f = VAULT / rel
        if not f.is_file():
            out.append({"path": rel, "logged": False, "reason": "no such file in vault"})
            if not as_json:
                print(f"skip (no such file in vault): {rel}")
            continue
        db.execute(
            "INSERT INTO events(event,path,event_ts,size,logged_at,source) VALUES ('read',?,?,?,?,?)",
            (rel, now, f.stat().st_size, now, by),
        )
        out.append({"path": rel, "logged": True, "ts": now, "source": by})
        if not as_json:
            print(f"read logged {now} | {rel}")
    db.commit()
    return out if as_json else None


def recent(days: int, since: str | None, kind: str, as_json: bool = False):
    db = connect()
    if since:
        cutoff = datetime.fromisoformat(since).isoformat(timespec="seconds")
    else:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff = (start - timedelta(days=max(days - 1, 0))).isoformat(timespec="seconds")
    # Created = filesystem birth time (works for files older than the log); edited =
    # mtime later than birth. Both read from files_current, so a baseline-only log answers.
    rows = []
    if kind in ("created", "both", "all"):
        rows += [
            (r[0], "created", r[1])
            for r in db.execute("SELECT path, birth_ts FROM files_current WHERE birth_ts>=?", (cutoff,))
        ]
    if kind in ("edited", "both", "all"):
        rows += [
            (r[0], "edited", r[1])
            for r in db.execute(
                "SELECT path, mtime_ts FROM files_current WHERE mtime_ts>=? "
                "AND (birth_ts IS NULL OR birth_ts<?)",
                (cutoff, cutoff),
            )
        ]
    if kind in ("read", "all"):
        rows += [
            (r[0], f"read:{r[2]}" if r[2] else "read", r[1])
            for r in db.execute(
                "SELECT path, event_ts, source FROM events WHERE event='read' AND event_ts>=?", (cutoff,)
            )
        ]
    last = db.execute("SELECT MAX(scanned_at) FROM scans").fetchone()[0]
    rows.sort(key=lambda r: r[2])
    if as_json:
        return {
            "since": cutoff,
            "last_scan": last,
            "rows": [{"ts": ts, "event": ev.split(":")[0], "source": ev.partition(":")[2] or None, "path": path}
                     for path, ev, ts in rows],
        }
    print(f"since {cutoff}; last scan {last or 'never -- run scan first'}")
    for path, ev, ts in rows:
        print(f"{ts} | {ev:12} | {path}")
    if not rows:
        print("(none)")


def history(path: str, as_json: bool = False):
    db = connect()
    f = db.execute(
        "SELECT birth_ts, mtime_ts, size, deleted, sha256 FROM file_versions WHERE path=? ORDER BY id DESC LIMIT 1",
        (path,),
    ).fetchone()
    ev = db.execute(
        "SELECT event_ts, event, size, logged_at, source, sha256 FROM events WHERE path=? ORDER BY id", (path,)
    ).fetchall()
    if as_json:
        return {
            "path": path,
            "file": dict(zip(("birth_ts", "mtime_ts", "size", "deleted", "sha256"), f)) if f else None,
            "events": [dict(zip(("ts", "event", "size", "logged_at", "source", "sha256"), r)) for r in ev],
        }
    print(f"{path}: {f if f else 'not in the log'}")
    for r in ev:
        print(" | ".join(str(x) for x in r))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ap.add_argument("--json", action="store_true", help="print the result as one JSON value")
    sub.add_parser("scan")
    sub.add_parser("backfill", help="add created events from birth_ts for files that have none")
    r = sub.add_parser("recent")
    r.add_argument("--days", type=int, default=1, help="1 = today only")
    r.add_argument("--since", help="local ISO datetime, overrides --days")
    r.add_argument(
        "--kind",
        choices=("created", "edited", "both", "read", "all"),
        default="both",
        help="both = created+edited; read = logged reads only; all = everything",
    )
    lr = sub.add_parser("log-read", help="record that note(s) were read")
    lr.add_argument("paths", nargs="+", help="vault-relative or absolute paths")
    lr.add_argument("--by", help="who read it, e.g. vault-search")
    h = sub.add_parser("history")
    h.add_argument("path", help="vault-relative path")
    a = ap.parse_args()
    if a.cmd == "scan":
        res = scan(a.json)
    elif a.cmd == "backfill":
        res = backfill(a.json)
    elif a.cmd == "log-read":
        res = log_read(a.paths, a.by, a.json)
    elif a.cmd == "recent":
        res = recent(a.days, a.since, a.kind, a.json)
    else:
        res = history(a.path, a.json)
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
