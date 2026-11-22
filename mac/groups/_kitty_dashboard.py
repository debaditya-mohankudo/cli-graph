"""Renderer for `mac kitty dashboard`: a read-only view of the hook-written session state.

Moved from claude-hooks/kitty/dashboard.py (task:3f30d74d). The files below are written by
claude-hooks and are the only interface between the two repos; tests/test_kitty_dashboard.py
pins the shapes read here:

  server_memory.sqlite   table server_memory(ts, type, content, ref)       hook server event log
  dashboard_plan.json    {"title": str, "items": [{"text": str, "done": bool}]}   hooks/dashboard_plan.py
  dashboard_turn.json    {"prompt": str, "summary": str}                     hooks/dashboard_turn.py
  dashboard_note.md      free text, written by Claude (PLAN / WAITING lines)

Stdlib only. Fails soft: a missing or locked DB is one line of output, never an exception.
Env overrides (read at call time): CLAUDE_SERVER_MEMORY_DB, CLAUDE_DASHBOARD_NOTE,
CLAUDE_DASHBOARD_PLAN, CLAUDE_DASHBOARD_TURN.
"""
from __future__ import annotations

import json
import os
import select
import sqlite3
import sys
import termios
import textwrap
import time
import tty
from datetime import datetime
from pathlib import Path

SHOWN = ("prompt", "tool", "task")
GLYPH = {"prompt": "❯", "tool": "·", "task": "★"}
_DEFAULTS = {
    "db": ("CLAUDE_SERVER_MEMORY_DB", "~/.claude/server_memory.sqlite"),
    "note": ("CLAUDE_DASHBOARD_NOTE", "~/.claude/dashboard_note.md"),
    "plan": ("CLAUDE_DASHBOARD_PLAN", "~/.claude/dashboard_plan.json"),
    "turn": ("CLAUDE_DASHBOARD_TURN", "~/.claude/dashboard_turn.json"),
}


def paths() -> dict[str, Path]:
    return {k: Path(os.environ.get(env, default)).expanduser() for k, (env, default) in _DEFAULTS.items()}


def _clip(text: str | None, width: int) -> str:
    one = " ".join((text or "").split())
    return one if len(one) <= width else one[: max(width - 1, 0)] + "…"


def fetch(db: Path, n: int):
    """(latest task activation, last n shown events oldest-first)."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
    con.row_factory = sqlite3.Row
    try:
        marks = ",".join("?" * len(SHOWN))
        task = con.execute(
            "SELECT ts, content, ref FROM server_memory WHERE type='task' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        rows = con.execute(
            f"SELECT ts, type, content, ref FROM server_memory WHERE type IN ({marks}) "
            "ORDER BY ts DESC LIMIT ?", (*SHOWN, n),
        ).fetchall()
    finally:
        con.close()
    return task, rows[::-1]


def read_note(path: Path, width: int, max_lines: int = 12) -> list[str]:
    """Claude-written status (plan / waiting-on-you), shown above the event feed."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    lines = [_clip(l, width) for l in lines if l.strip()][:max_lines]
    return lines + ["─" * min(width, 60)] if lines else []


def read_plan(path: Path, width: int, max_lines: int = 12) -> list[str]:
    """Hook-mirrored plan (hooks/dashboard_plan.py): title, then [x]/[ ] items."""
    try:
        plan = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    items = plan.get("items", [])
    if not items and not plan.get("title"):
        return []
    done = sum(1 for i in items if i.get("done"))
    head = f"PLAN {done}/{len(items)}" + (f"  {plan['title']}" if plan.get("title") else "")
    lines = [_clip(head, width)]
    lines += [_clip(f"  [{'x' if i.get('done') else ' '}] {i.get('text', '')}", width) for i in items]
    return lines[:max_lines] + ["─" * min(width, 60)]


def _wrap(label: str, text: str, width: int, max_lines: int) -> list[str]:
    body = textwrap.wrap(" ".join((text or "").split()) or "(none yet)", max(width - 2, 10))
    if len(body) > max_lines:
        body = body[:max_lines - 1] + [_clip(body[max_lines - 1], width - 3) + "…"]
    return [label] + [f"  {l}" for l in body]


def read_turn(path: Path, width: int, height: int = 40) -> str:
    """Prompt + final summary of the current turn (hooks/dashboard_turn.py)."""
    try:
        turn = json.loads(path.read_text())
    except (OSError, ValueError):
        return "no turn recorded yet"
    room = max(height - 4, 6)
    out = _wrap("❯ PROMPT", turn.get("prompt", ""), width, max(room // 3, 3))
    out += ["─" * min(width, 60)]
    out += _wrap("★ SUMMARY", turn.get("summary", ""), width, room - len(out))
    return "\n".join(out)


def read_next(path: Path, width: int) -> str:
    """Pending plan items only: the next nodes still to do."""
    try:
        items = json.loads(path.read_text()).get("items", [])
    except (OSError, ValueError):
        return "no plan"
    todo = [i for i in items if not i.get("done")]
    if not todo:
        return "NEXT  nothing pending"
    return "\n".join([f"NEXT {len(todo)} pending"] + [_clip(f"  → {i.get('text', '')}", width) for i in todo])


def render(task, rows, width: int, note: list[str] | None = None) -> str:
    out = list(note or [])
    if task:
        title = _clip(task["content"], width - 14) or "(no title logged)"
        out.append(f"★ {title}  [{task['ref'] or '?'}]")
    else:
        out.append("★ no task activation in the event window")
    out.append("─" * min(width, 60))
    for r in rows:
        t = datetime.fromtimestamp(r["ts"]).strftime("%H:%M:%S")
        out.append(f"{t} {GLYPH.get(r['type'], '?')} {_clip(r['content'], width - 11)}")
    return "\n".join(out)


def snapshot(n: int, width: int, view: str = "all", p: dict[str, Path] | None = None,
             height: int = 40) -> str:
    p = p or paths()
    if view == "turn":
        return read_turn(p["turn"], width, height)
    if view == "next":
        return read_next(p["plan"], width)
    try:
        return render(*fetch(p["db"], n), width, read_plan(p["plan"], width) + read_note(p["note"], width))
    except sqlite3.Error as e:
        return f"dashboard: cannot read {p['db']}: {e}"


def _esc_pressed(wait: float) -> bool:
    """Wait up to `wait` seconds; True if a bare Esc arrived (arrow-key sequences don't count)."""
    if not select.select([sys.stdin], [], [], wait)[0]:
        return False
    return os.read(sys.stdin.fileno(), 32) == b"\x1b"


def _size() -> tuple[int, int]:
    if sys.stdout.isatty():
        s = os.get_terminal_size()
        return s.columns, s.lines
    return 80, 40


def run_live(n: int, interval: float, view: str) -> None:
    """Redraw until Esc or Ctrl-C. Writes to the terminal itself; the verb returns nothing."""
    fd = sys.stdin.fileno() if sys.stdin.isatty() else None
    saved = termios.tcgetattr(fd) if fd is not None else None
    try:
        if fd is not None:
            tty.setcbreak(fd)
        while True:
            width, height = _size()
            sys.stdout.write("\x1b[H\x1b[2J" + snapshot(n, width, view, height=height) + "\n")
            sys.stdout.flush()
            if fd is None:
                time.sleep(interval)
            elif _esc_pressed(interval):
                return
    except KeyboardInterrupt:
        return
    finally:
        if saved is not None:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
