"""`mac kitty` — drive other kitty tabs through kitty remote control (`kitten @`).

Every verb addresses a tab by its numeric id, never by title: a title can contain a colon, which
breaks kitty's `--match`, and titles are not unique. Tab ids and window ids are different
namespaces; `--tab` takes a TAB id (the `id` that `mac kitty tabs` prints) and each verb resolves
it to that tab's window before acting. A tab that runs `claude` (this session's tab included) is
refused, so a verb can never type into or close a live agent session. The one exception is `notify`,
which accepts ONLY a claude tab and types one tagged line into it.

Commands typed by `run` are visible at the tab's prompt: no hidden script files.
"""
import os
import re
import shutil
import subprocess
import sys
import time
import json
from datetime import datetime, timedelta

from mac.cli import iso_datetime
from pathlib import Path

from mac.contract import Failure, Plain
from mac.groups import _kitty_dashboard as dash
from mac.groups._backend import call

KITTEN_TIMEOUT_S = 20
GUARDED_COMMANDS = {"claude"}
HHMM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
EVERY = re.compile(r"(\d+)([smh])")
SETTLE_S = 0.4
COMM_LIST = "kitty-comm"
COMM_TITLE = re.compile(r"\[([^\]]+?) -> ([^\]]+?)\] (.*)")
COMM_ID = re.compile(r"\(id (x-apple-reminder://[^)\s]+)\)\s*$")
COMM_DUE_MIN = 1


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


def _resolve(tab_id, claude=False):
    """The tab row for a tab id; refuses an unknown tab and a claude session tab.

    `claude=True` flips the guard (only `notify` uses it): a claude tab is accepted, any other refused.
    """
    for row in _tabs():
        if row["tab"] == tab_id:
            if claude:
                if not row["guarded"]:
                    raise Failure("refused", f"tab {tab_id} is not a claude session; notify only targets claude tabs")
            elif row["guarded"]:
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


def prompt_text(screen):
    """Text typed in a claude prompt box, or None when no box is found.

    The box is the last block between two lines of `─`; its first line starts with `❯`.
    """
    lines = screen.rstrip("\n").splitlines()
    rules = [i for i, ln in enumerate(lines) if ln.strip() and set(ln.strip()) == {"─"}]
    if len(rules) < 2:
        return None
    block = lines[rules[-2] + 1:rules[-1]]
    if not block or not block[0].lstrip().startswith("❯"):
        return None
    first = block[0].lstrip()[1:]
    return " ".join([first, *block[1:]]).replace("\xa0", " ").strip()


def notify_line(sender, body):
    """The one tagged line `notify` types; a body with a line break is refused, not collapsed."""
    if re.search(r"[\r\n\x00-\x08\x0b-\x1f\x7f\u2028\u2029]", body + sender):
        raise Failure("usage", "--from and --body must be one line with no control characters", 2)
    body, sender = body.strip(), sender.strip()
    if not body or not sender:
        raise Failure("usage", "--from and --body must be non-empty", 2)
    return f"[AUTOMATED from {sender}, not the user] {body}"


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


def _comm_tag(value, flag):
    """A mailbox tag (sender or recipient): one line, no `]` or ` -> `, so the title parses back exactly."""
    value = (value or "").strip()
    if not value or re.search(r"[\x00-\x1f\x7f\u2028\u2029\]]| -> ", value):
        raise Failure("usage", f"{flag} must be a non-empty one-line tag without ']' or ' -> '", 2)
    return value


def comm_parse(row):
    """One kitty-comm reminder row as {id, from, to, body, due, completed}, or None if it is not a tab message."""
    m = COMM_TITLE.fullmatch(row.get("title", ""))
    if not m:
        return None
    return {"id": row["id"], "from": m.group(1), "to": m.group(2), "body": m.group(3),
            "due": row.get("dueDate"), "completed": row.get("completed", False)}


def _comm_rows(include_completed=False):
    extra = {"include_completed": True} if include_completed else {}
    rows = call("reminders", "list", list=COMM_LIST, **extra)
    return rows["reminders"] if isinstance(rows, dict) else rows


def _notify(to, sender, body, force):
    line = notify_line(sender, body)
    row = _resolve(to, claude=True)
    window = row["window"]
    match = f"id:{window}"
    before = prompt_text(_screen(window))
    if before is None:
        raise Failure("tool_error", f"tab {to}: no claude prompt box on screen; not sending")
    if before and not force:
        return {"tab": to, "window": window, "sent": False, "busy": True,
                "unsent": before[:80]}
    _kitten("send-text", "--match", match, "--stdin", stdin=line)
    time.sleep(SETTLE_S)
    _kitten("send-key", "--match", match, "enter")
    for attempt in (1, 2):
        time.sleep(SETTLE_S)
        if not prompt_text(_screen(window)):
            return {"tab": to, "window": window, "sent": True, "verified": True, "message": line,
                    "enter_retried": attempt == 2}
        if attempt == 1:
            _kitten("send-key", "--match", match, "enter")
    raise Failure("tool_error", f"typed into tab {to} but its prompt did not empty after a retry")


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

    def dashboard_args(p):
        p.add_argument("--view", choices=("all", "turn", "next"), default="all",
                       help="all: event feed; turn: prompt + final summary; next: pending plan items")
        p.add_argument("-n", type=int, default=15, help="events to show")
        p.add_argument("-i", "--interval", type=float, default=2.0, help="seconds between redraws")
        p.add_argument("--once", action="store_true", help="print once and exit (use this from a script)")

    @registry.verb("kitty", "dashboard", mode="read",
                   desc="read-only live view of the claude-hooks session state (task, prompts, tool calls, "
                        "plan, turn summary) for a kitty split; redraws until Esc. --once prints one "
                        "screen and exits; without it the call does not return",
                   args=dashboard_args)
    def dashboard(ns):
        if ns.once:
            width, height = dash._size()
            return Plain(dash.snapshot(ns.n, width, ns.view, height=height))
        dash.run_live(ns.n, ns.interval, ns.view)
        return Plain("")

    @registry.verb("kitty", "layout", mode="write",
                   desc="open the claude dashboard in kitty: one 'turn' tab (prompt + final summary) with "
                        "the pending next steps in a parallel vsplit; returns the two window ids",
                   args=lambda p: p.add_argument("-i", "--interval", type=float, default=1.0,
                                                 help="seconds between redraws in both panes"))
    def layout(ns):
        mac = shutil.which("mac") or str(Path(__file__).resolve().parents[2] / "bin" / "mac")
        if not os.access(mac, os.X_OK):
            raise Failure("tool_error", f"cannot find an executable mac to run in the panes: {mac}")

        def pane(view):
            return [mac, "kitty", "dashboard", "--view", view, "-i", str(ns.interval)]

        turn = int(_kitten("launch", "--type=tab", "--tab-title", "turn", *pane("turn")).strip())
        nxt = int(_kitten("launch", "--location=vsplit", "--keep-focus", *pane("next")).strip())
        return {"turn": turn, "next": nxt}

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

    def notify_args(p):
        p.add_argument("--to", type=int, required=True, help="claude tab id from `mac kitty tabs` (guarded=true)")
        p.add_argument("--from", dest="sender", required=True, help="who is sending, shown in the tag")
        p.add_argument("--body", required=True, help="one-line message")
        p.add_argument("--force", action="store_true", help="send even if the prompt holds unsent text")

    @registry.verb("kitty", "notify", mode="write",
                   desc="send a message to a claude tab: type one tagged line "
                        "('[AUTOMATED from <sender>, not the user] ...') into a claude session's prompt and "
                        "submit it, so a shell side tab can hand a result to its parent session. Reports "
                        "busy and sends nothing if the prompt holds unsent text (--force overrides)",
                   args=notify_args)
    def notify(ns):
        return _notify(ns.to, ns.sender, ns.body, ns.force)

    def send_args(p):
        p.add_argument("body", help="one-line message")
        p.add_argument("--from", dest="sender", required=True, help="sender tag, e.g. 'india-open reader'")
        p.add_argument("--to", required=True, help="recipient tag: 'you' or a tab tag; exact match in comm_inbox")
        p.add_argument("--due", default=None, type=iso_datetime, help="ISO-8601 due time (default: about 1 minute out)")
        p.add_argument("--notify", type=int, default=None,
                       help="claude tab id to ring with the reminder id; a busy tab never fails the send")

    @registry.verb("kitty", "comm_send", mode="write",
                   desc="leave a durable message for the user or another tab: a reminder in the kitty-comm "
                        "list titled '[from -> to] body'. --notify TAB also rings a claude tab. Returns the id",
                   args=send_args)
    def comm_send(ns):
        sender, to = _comm_tag(ns.sender, "--from"), _comm_tag(ns.to, "--to")
        notify_line(sender, ns.body)  # the one-line / non-empty rules, shared with notify
        body = ns.body.strip()
        due = ns.due or (datetime.now() + timedelta(minutes=COMM_DUE_MIN)).strftime("%Y-%m-%dT%H:%M:%S")
        payload = json.dumps({"from": sender, "to": to, "body": body,
                              "sent": datetime.now().isoformat(timespec="seconds")})
        try:
            text = call("reminders", "create", title=f"[{sender} -> {to}] {body}", list=COMM_LIST,
                        due_date=due, notes=payload)
        except Failure as exc:
            if "Can’t get list" in str(exc) or "Can't get list" in str(exc):
                raise Failure("tool_error", f"Reminders list '{COMM_LIST}' does not exist; create it in "
                                            "Reminders.app (mac has no list-creation verb)")
            raise
        m = COMM_ID.search(str(text))
        if not m:
            raise Failure("tool_error", f"reminder created but its id could not be read from: {text!r}")
        out = {"id": m.group(1), "from": sender, "to": to, "body": body, "due": due}
        if ns.notify is not None:
            try:
                out["doorbell"] = _notify(ns.notify, sender, f"{to}: {body} (reminder {m.group(1)})", False)
            except Failure as exc:
                out["doorbell"] = {"sent": False, "error": str(exc)}
        return out

    def inbox_args(p):
        p.add_argument("--to", required=True, help="recipient tag")
        p.add_argument("--include-completed", action="store_true")

    @registry.verb("kitty", "comm_inbox", mode="read",
                   desc="messages left for a recipient in the kitty-comm list (open ones; "
                        "--include-completed adds acknowledged ones)",
                   args=inbox_args)
    def comm_inbox(ns):
        msgs = [m for m in map(comm_parse, _comm_rows(ns.include_completed)) if m and m["to"] == ns.to.strip()]
        return msgs

    @registry.verb("kitty", "comm_ack", mode="write", desc="acknowledge a kitty-comm message: complete its reminder by id",
                   args=lambda p: p.add_argument("id"))
    def comm_ack(ns):
        # Only a message in kitty-comm may be completed: `reminders complete` takes any id in Reminders.
        if ns.id not in {m["id"] for m in map(comm_parse, _comm_rows(True)) if m}:
            raise Failure("usage", f"{ns.id} is not a message in the '{COMM_LIST}' list; nothing completed", 2)
        call("reminders", "complete", id=ns.id)
        return {"id": ns.id, "acked": True}
