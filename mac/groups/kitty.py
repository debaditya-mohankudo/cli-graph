"""`mac kitty` — drive other kitty tabs through kitty remote control (`kitten @`).

Every verb addresses a tab by its numeric id, never by title: a title can contain a colon, which
breaks kitty's `--match`, and titles are not unique. Tab ids and window ids are different
namespaces; `--tab` takes a TAB id (the `id` that `mac kitty tabs` prints) and each verb resolves
it to that tab's window before acting. A tab that runs `claude` (this session's tab included) is
refused, so a verb can never type into or close a live agent session.

Commands typed by `run` are visible at the tab's prompt: no hidden script files.
"""
import os
import re
import subprocess
import sys
import time
from datetime import datetime

from mac.contract import Failure

KITTEN_TIMEOUT_S = 20
GUARDED_COMMANDS = {"claude"}
HHMM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
EVERY = re.compile(r"(\d+)([smh])")
SETTLE_S = 0.4


def _socket():
    """KITTY_LISTEN_ON, else the newest /tmp/kitty-* socket."""
    env = os.environ.get("KITTY_LISTEN_ON")
    if env:
        return env if env.startswith(("unix:", "tcp:")) else f"unix:{env}"
    socks = sorted((os.path.join("/tmp", n) for n in os.listdir("/tmp") if n.startswith("kitty-")),
                   key=os.path.getmtime, reverse=True)
    if not socks:
        raise Failure("tool_error", "no kitty socket: KITTY_LISTEN_ON is unset and /tmp/kitty-* is empty")
    return f"unix:{socks[0]}"


def _kitten(*args, stdin=None):
    """Run `kitten @ --to <socket> ...`; a missing or wedged kitten is a Failure, not a hang."""
    argv = ["kitten", "@", "--to", _socket(), *args]
    try:
        proc = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=KITTEN_TIMEOUT_S,
                              **({} if stdin is not None else {"stdin": subprocess.DEVNULL}))
    except subprocess.TimeoutExpired:
        raise Failure("tool_error", f"kitten did not answer within {KITTEN_TIMEOUT_S}s")
    except OSError as exc:
        raise Failure("tool_error", f"cannot run kitten: {exc}")
    if proc.returncode:
        raise Failure("tool_error", (proc.stderr or proc.stdout).strip() or f"kitten {args[0]} failed")
    return proc.stdout


def _ls():
    import json
    return json.loads(_kitten("ls") or "[]")


def _tabs(raw=None):
    rows = []
    for osw in raw if raw is not None else _ls():
        for tab in osw.get("tabs") or []:
            windows = tab.get("windows") or []
            first = windows[0] if windows else {}
            procs = [p for w in windows for p in (w.get("foreground_processes") or [])]
            cmds = [" ".join(p.get("cmdline") or []) for p in procs]
            guarded = any(w.get("is_self") for w in windows) or any(
                os.path.basename((p.get("cmdline") or [""])[0]) in GUARDED_COMMANDS for p in procs)
            rows.append({
                "tab": tab["id"], "window": first.get("id"), "title": tab.get("title") or "",
                "cwd": first.get("cwd") or "", "foreground": cmds[0] if cmds else "",
                "guarded": guarded,
            })
    return rows


def _resolve(tab_id):
    """The tab row for a tab id; refuses an unknown tab and a claude session tab."""
    for row in _tabs():
        if row["tab"] == tab_id:
            if row["guarded"]:
                raise Failure("refused", f"tab {tab_id} runs a claude session; mac kitty will not act on it")
            if row["window"] is None:
                raise Failure("tool_error", f"tab {tab_id} has no window")
            return row
    raise Failure("not_found", f"no kitty tab with id {tab_id}; run `mac kitty tabs`")


def _screen(window, lines=None):
    text = _kitten("get-text", "--match", f"id:{window}")
    if lines:
        text = "\n".join(text.rstrip("\n").splitlines()[-lines:])
    return text


def _squash(text):
    """Whitespace-free form of text, so a command the terminal wrapped still matches."""
    return re.sub(r"\s+", "", text)


def _seconds(text):
    m = EVERY.fullmatch(text)
    if not m:
        raise Failure("usage", f"--every must look like 30s, 10m or 1h, got {text!r}", 2)
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2)]


def build_command(cmd, at=None, retry=None, every="10m", until=None):
    """The one visible shell one-liner `run` types.

    Plain `cmd` when there is no --at/--retry. Otherwise: wait until HH:MM, then run cmd up to
    `retry` times, stopping at the first time the shell test `until` succeeds.
    """
    if not (at or retry):
        return cmd
    wait = ""
    if at:
        m = HHMM.fullmatch(at)
        if not m:
            raise Failure("usage", f"--at must be HH:MM (24-hour), got {at!r}", 2)
        wait = f"until [ $(date +%H%M) -ge {m.group(1)}{m.group(2)} ]; do sleep 20; done; "
    tries = retry or 1
    secs = _seconds(every)
    test = until or "true"
    return (f"{wait}for i in $(seq 1 {tries}); do {cmd}; {test} && echo DONE && break; "
            f"sleep {secs}; done")


def _tab_arg(p):
    p.add_argument("--tab", type=int, required=True, help="tab id from `mac kitty tabs` (never a title)")


def register(registry):
    @registry.verb("kitty", "tabs", mode="read",
                   desc="list kitty tabs: tab id, window id, title, cwd, foreground command, guarded "
                        "(true for a claude session tab, which the other verbs refuse)")
    def tabs(ns):
        return _tabs()

    def open_args(p):
        p.add_argument("--title", required=True, help="tab title")
        p.add_argument("--cwd", default=None, help="working directory (default: the caller's)")

    @registry.verb("kitty", "open", mode="write",
                   desc="open a new shell tab in kitty with a title; returns its tab and window ids",
                   args=open_args)
    def open_tab(ns):
        cwd = os.path.abspath(ns.cwd) if ns.cwd else os.getcwd()
        window = int(_kitten("launch", "--type=tab", f"--tab-title={ns.title}", f"--cwd={cwd}").strip())
        for row in _tabs():
            if row["window"] == window:
                return {"tab": row["tab"], "window": window, "title": row["title"], "cwd": row["cwd"]}
        raise Failure("tool_error", f"launched window {window} but found no tab for it")

    def run_args(p):
        _tab_arg(p)
        p.add_argument("command", nargs="?", help="shell command to type (or --file / --stdin)")
        p.add_argument("--file", help="read the command from this file (keeps quoting intact)")
        p.add_argument("--stdin", action="store_true", help="read the command from standard input")
        p.add_argument("--at", help="wait until this local time, HH:MM (24-hour), before running")
        p.add_argument("--retry", type=int, help="run up to N times, stopping when --until succeeds")
        p.add_argument("--every", default="10m", help="pause between retries: 30s, 10m, 1h (default 10m)")
        p.add_argument("--until", help="shell test that ends the retries, e.g. 'test -s out.json'")
        p.add_argument("--dry-run", action="store_true", help="return the one-liner without typing it")

    @registry.verb("kitty", "run", mode="write",
                   desc="type a shell command visibly at a tab's prompt, press enter, and verify it "
                        "appears on screen. --at HH:MM / --retry N --every 10m --until TEST wrap it in "
                        "one visible wait-and-retry one-liner",
                   args=run_args)
    def run(ns):
        sources = [s for s in (ns.command, ns.file, ns.stdin or None) if s]
        if len(sources) != 1:
            raise Failure("usage", "give the command as exactly one of: argument, --file, --stdin", 2)
        if ns.file:
            cmd = open(ns.file).read()
        elif ns.stdin:
            cmd = sys.stdin.read()
        else:
            cmd = ns.command
        cmd = cmd.strip()
        if not cmd or "\n" in cmd:
            raise Failure("usage", "the command must be a single non-empty line", 2)
        line = build_command(cmd, ns.at, ns.retry, ns.every, ns.until)
        if ns.dry_run:
            return {"tab": ns.tab, "command": line, "sent": False}
        row = _resolve(ns.tab)
        match = f"id:{row['window']}"
        _kitten("send-text", "--match", match, "--stdin", stdin=line)
        _kitten("send-key", "--match", match, "enter")
        time.sleep(SETTLE_S)
        visible = _squash(line) in _squash(_screen(row["window"]))
        if not visible:
            raise Failure("tool_error", f"typed the command into tab {ns.tab} but it is not on screen")
        return {"tab": ns.tab, "window": row["window"], "command": line, "sent": True, "verified": True,
                "at": datetime.now().isoformat(timespec="seconds")}

    def read_args(p):
        _tab_arg(p)
        p.add_argument("--lines", type=int, default=None, help="only the last N lines of the screen")

    @registry.verb("kitty", "read", mode="read",
                   desc="what is currently on a tab's screen. A hint only: real state lives in the database "
                        "or logs the command wrote, not on the screen",
                   args=read_args)
    def read(ns):
        row = _resolve(ns.tab)
        return {"tab": ns.tab, "window": row["window"], "text": _screen(row["window"], ns.lines)}

    @registry.verb("kitty", "interrupt", mode="write",
                   desc="send ctrl+c to a tab", args=_tab_arg)
    def interrupt(ns):
        row = _resolve(ns.tab)
        _kitten("send-key", "--match", f"id:{row['window']}", "ctrl+c")
        return {"tab": ns.tab, "window": row["window"], "interrupted": True}

    @registry.verb("kitty", "close", mode="write",
                   desc="close a tab (and anything running in it)", args=_tab_arg)
    def close(ns):
        _resolve(ns.tab)
        _kitten("close-tab", "--match", f"id:{ns.tab}")
        return {"tab": ns.tab, "closed": True}
