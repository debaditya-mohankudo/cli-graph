"""`mac encdb` — which personal SQLite DBs are encrypted at rest, and migrate one (task:8b0561d1).

`status` is read-only. `migrate` is the write verb (tools/gen_permissions.py makes it
ask): it backs the file up first, writes an encrypted copy beside it, checks table row
counts and integrity_check on the copy, and only then swaps it into place. Any mismatch
leaves the original untouched and removes the copy.

REGISTRY lists every personal DB with a decision. A DB moves to "migrate" only once every
reader of it opens through mac.encdb; until then a migrated file would break that reader.
"""
import argparse
import os
import time
from pathlib import Path

from mac import encdb
from mac.contract import Failure

ICLOUD = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Databases"
CLAUDE = Path.home() / ".claude"

# name -> (path, decision, why)
REGISTRY = {
    "memory": (CLAUDE / "MEMORY.sqlite", "migrate",
               "the goal of the task; migrate once the prompt hook, mac memory and the scripts open via mac.encdb"),
    "tasks": (Path.home() / ".taskfw" / "tasks.db", "leave",
              "taskfw store, 31 MB, plaintext live; daily snapshots to iCloud are encrypted. Live file to be encrypted once task-framework opens via an encrypted-aware opener (task:8b0561d1)"),
    "server_memory": (CLAUDE / "server_memory.sqlite", "leave",
                      "hook-server event log, rolling ~1000 events, not synced; readers not yet on the opener"),
    "tool_hints": (ICLOUD / "tool_hints.sqlite", "leave",
                   "tool usage counts, low sensitivity; read by the prompt hook and find_cli"),
    "astrology": (ICLOUD / "astrology.db", "leave",
                  "birth data lives here and it syncs to iCloud: migrate next, after the astrology server opens via mac.encdb"),
    "vault_index": (CLAUDE / "vault_index.sqlite", "leave",
                    "derived index of vault notes, rebuildable; read by several vault tools"),
}


def _state(path: Path) -> str:
    if not path.exists():
        return "missing"
    if not path.stat().st_size:
        return "empty"
    return "plain" if encdb.is_plain(path) else "encrypted"


def _resolve(target: str) -> Path:
    if target in REGISTRY:
        return REGISTRY[target][0]
    return Path(target).expanduser()


def _counts(con) -> dict[str, int]:
    names = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
    return {n: con.execute(f'SELECT count(*) FROM "{n}"').fetchone()[0] for n in names}


def _integrity(con) -> str:
    return "; ".join(str(r[0]) for r in con.execute("PRAGMA integrity_check").fetchall())


def migrate(path: Path, key: str | None = None) -> dict:
    """Encrypt `path` in place. Returns a report; raises Failure and leaves `path` untouched on any problem."""
    if not path.exists():
        raise Failure("not_found", f"{path} does not exist")
    if _state(path) == "encrypted":
        raise Failure("usage", f"{path.name} is already encrypted")
    if _state(path) == "empty":
        raise Failure("usage", f"{path.name} is empty; nothing to migrate")
    apsw = encdb._binding()
    hexkey = key or encdb.read_key()
    if not encdb._valid_key(hexkey):
        raise Failure("usage", "key is not 64 hex characters")

    stamp = time.strftime("%Y%m%dT%H%M%S")
    backup = path.with_name(f"{path.name}.pre-encrypt.{stamp}")
    tmp = path.with_name(f"{path.name}.enc.{stamp}")
    src = apsw.Connection(str(path), flags=apsw.SQLITE_OPEN_READWRITE | apsw.SQLITE_OPEN_URI)
    try:
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        before_counts, before_check = _counts(src), _integrity(src)
        if before_check != "ok":
            raise Failure("tool_error", f"{path.name} fails integrity_check before migration: {before_check}")
        # Backup first: a consistent copy through the backup API, not a file copy of a live DB.
        bk = apsw.Connection(str(backup))
        with bk.backup("main", src, "main") as b:
            b.step()
        bk.close()

        # The backup API cannot cross ciphers, so VACUUM INTO a keyed URI writes the ciphertext.
        src.execute("VACUUM INTO ?", (f"{tmp.as_uri()}?cipher=sqlcipher&hexkey={hexkey}",))
        dst = apsw.Connection(str(tmp))
        try:
            dst.pragma("cipher", "sqlcipher")
            dst.pragma("hexkey", hexkey)
            after_counts, after_check = _counts(dst), _integrity(dst)
        finally:
            dst.close()
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        src.close()

    if after_counts != before_counts or after_check != "ok":
        tmp.unlink(missing_ok=True)
        raise Failure("tool_error",
                      f"{path.name}: encrypted copy does not match (counts {before_counts} vs {after_counts}, "
                      f"integrity {after_check}); original untouched, backup at {backup}")

    for side in ("-wal", "-shm"):  # stale sidecars of the plaintext file must not outlive it
        Path(str(path) + side).unlink(missing_ok=True)
    os.replace(tmp, path)
    return {"path": str(path), "state": "encrypted", "backup": str(backup),
            "tables": len(after_counts), "rows": sum(after_counts.values()), "integrity": "ok"}


BACKUP_DIR = ICLOUD / "backups"


def _prefix(path: Path) -> str:
    return {"MEMORY.sqlite": "MEMORY_", "tasks.db": "tasks_"}.get(path.name, path.stem + "_")


def snapshot(path: Path, dest: Path, key: str | None = None, encrypt: bool = False) -> dict:
    """Write a consistent snapshot of `path` to `dest` and verify it. Encrypted when the source is, or `encrypt`.

    VACUUM INTO writes a single file with no -wal/-shm sidecars. A keyed URI makes the output
    ciphertext, so an encrypted source never leaves a plaintext copy. The copy is reopened and its
    table row counts and integrity_check must match the source or it is removed.
    """
    if not path.exists():
        raise Failure("not_found", f"{path} does not exist")
    if dest.exists():
        raise Failure("usage", f"{dest} already exists")
    apsw = encdb._binding()
    enc_src = _state(path) == "encrypted"
    enc_dst = enc_src or encrypt
    hexkey = (key or encdb.read_key()) if (enc_dst or enc_src) else None
    if hexkey is not None and not encdb._valid_key(hexkey):
        raise Failure("usage", "key is not 64 hex characters")
    src = apsw.Connection(str(path), flags=(apsw.SQLITE_OPEN_READONLY if enc_src else apsw.SQLITE_OPEN_READWRITE) | apsw.SQLITE_OPEN_URI)
    try:
        if enc_src:
            src.pragma("cipher", "sqlcipher")
            src.pragma("hexkey", hexkey)
        src.setbusytimeout(10000)
        target = f"{dest.as_uri()}?cipher=sqlcipher&hexkey={hexkey}" if enc_dst else dest.as_uri()
        try:
            src.execute("VACUUM INTO ?", (target,))
            before = _counts(src)
            dst = apsw.Connection(str(dest), flags=apsw.SQLITE_OPEN_READONLY)
            try:
                if enc_dst:
                    dst.pragma("cipher", "sqlcipher")
                    dst.pragma("hexkey", hexkey)
                after, check = _counts(dst), _integrity(dst)
            finally:
                dst.close()
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
    finally:
        src.close()
    if after != before or check != "ok":
        dest.unlink(missing_ok=True)
        raise Failure("tool_error", f"{dest.name}: snapshot does not match source ({before} vs {after}, integrity {check})")
    return {"source": str(path), "snapshot": str(dest), "encrypted": enc_dst,
            "tables": len(after), "rows": sum(after.values()), "integrity": "ok"}


def prune(dest_dir: Path, prefix: str, keep: int) -> list[str]:
    """Delete all but the `keep` newest `prefix*.sqlite` in dest_dir; a failed delete raises, never silent."""
    files = sorted(dest_dir.glob(f"{prefix}*.sqlite"), key=lambda f: f.stat().st_mtime, reverse=True)
    gone = []
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError as e:
            raise Failure("tool_error", f"could not prune {old}: {e}") from e
        gone.append(str(old))
    return gone


def register(registry):
    def status_args(p):
        p.add_argument("--path", default=argparse.SUPPRESS, help="check this file instead of the registry")

    @registry.verb("encdb", "status", mode="read",
                   desc="which personal SQLite DBs are encrypted at rest or plaintext, with the migrate-or-leave decision for each",
                   args=status_args)
    def status(ns):
        if hasattr(ns, "path"):
            p = Path(ns.path).expanduser()
            return [{"name": p.name, "path": str(p), "state": _state(p)}]
        out = []
        for name, (p, decision, why) in REGISTRY.items():
            sidecars = [s for s in ("-wal", "-shm") if Path(str(p) + s).exists()]
            out.append({"name": name, "path": str(p), "state": _state(p), "decision": decision,
                        "why": why, **({"sidecars": sidecars} if sidecars else {})})
        return out

    def migrate_args(p):
        p.add_argument("target", help="a registered name (see `mac encdb status`) or a file path")

    @registry.verb("encdb", "migrate", mode="write",
                   desc="encrypt a plaintext SQLite DB in place with the memory key; backs up first and checks row counts and integrity",
                   args=migrate_args)
    def migrate_verb(ns):
        return migrate(_resolve(ns.target))


    def backup_args(p):
        p.add_argument("target", help="a registered name (see `mac encdb status`) or a file path")
        p.add_argument("--dest-dir", default=str(BACKUP_DIR), help="where snapshots go (default: iCloud Databases/backups)")
        p.add_argument("--keep", type=int, default=3, help="newest snapshots to keep per DB (default 3)")
        p.add_argument("--encrypt", action="store_true", help="encrypt the snapshot even if the source is plaintext")

    @registry.verb("encdb", "backup", mode="write",
                   desc="write a verified snapshot of a personal SQLite DB, encrypted when the source is, and prune old ones",
                   args=backup_args)
    def backup_verb(ns):
        path = _resolve(ns.target)
        dest_dir = Path(ns.dest_dir).expanduser()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{_prefix(path)}{time.strftime('%Y%m%d_%H%M%S')}.sqlite"
        report = snapshot(path, dest, encrypt=ns.encrypt)
        report["pruned"] = prune(dest_dir, _prefix(path), ns.keep)
        return report
