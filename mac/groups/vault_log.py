"""`mac vault_log` — when vault files were created, edited and read, from the log kept inside the vault.

The log is a SQLite file (`Claude/vault_file_log.sqlite` in the vault) kept by
stock-tracker-mcp's scripts/vault_file_log.py, which stays the one
implementation: each verb runs it with --json and returns its result. The log is
append-only (every write is an INSERT; triggers abort UPDATE and DELETE), so the
write verbs only add rows. Reads are
not detectable on disk, so `read` events exist only where a caller logged them
with `log_read`. `scan` must run to see changes made since the last scan.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from mac.contract import Failure

UNSET = argparse.SUPPRESS
DEFAULT_SCRIPT = Path.home() / "workspace" / "stock-tracker-mcp" / "scripts" / "vault_file_log.py"


def _run(*args):
    script = Path(os.environ.get("MAC_VAULT_LOG_SCRIPT", DEFAULT_SCRIPT))
    if not script.is_file():
        raise Failure("backend_missing", f"vault file log script not found: {script} (set MAC_VAULT_LOG_SCRIPT)")
    proc = subprocess.run([sys.executable, "-I", str(script), "--json", *args], capture_output=True, text=True)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        tail = " | ".join(proc.stderr.strip().splitlines()[-5:])
        raise Failure("tool_error", "vault_file_log gave no result" + (f" (stderr: {tail})" if tail else ""))


def register(registry):
    def recent_args(p):
        p.add_argument("--days", type=int, default=UNSET, help="1 = today only (default)")
        p.add_argument("--since", default=UNSET, help="local ISO datetime; overrides --days")
        p.add_argument("--kind", choices=("created", "edited", "both", "read", "all"), default=UNSET,
                       help="both = created+edited (default); read = logged reads; all = everything")

    @registry.verb("vault_log", "recent", mode="read",
                   desc="vault files created, edited or read today or in the last N days, from the vault's file log",
                   args=recent_args)
    def recent(ns):
        args = ["recent"]
        for flag in ("days", "since", "kind"):
            if hasattr(ns, flag):
                args += [f"--{flag}", str(getattr(ns, flag))]
        return _run(*args)["rows"]

    @registry.verb("vault_log", "history", mode="read",
                   desc="one vault file's creation, edit and read trail from the vault's file log",
                   args=lambda p: p.add_argument("path", help="vault-relative path"))
    def history(ns):
        return _run("history", ns.path)

    @registry.verb("vault_log", "scan", mode="write",
                   desc="record vault files created, edited or deleted since the last scan into the vault's file log")
    def scan(ns):
        return _run("scan")

    def log_read_args(p):
        p.add_argument("paths", nargs="+", help="vault-relative paths that were read")
        p.add_argument("--by", default=UNSET, help="who read them, e.g. vault-search")

    @registry.verb("vault_log", "log_read", mode="write",
                   desc="record that vault files were read (reads are not visible on disk)", args=log_read_args)
    def log_read(ns):
        args = ["log-read", *ns.paths]
        if hasattr(ns, "by"):
            args += ["--by", ns.by]
        return _run(*args)
