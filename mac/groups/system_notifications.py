"""`mac system notifications` — read macOS notification text through Accessibility (task:8fed2511).

Hand-written: `mac/groups/system.py` is generated from local-mac and is overwritten by
tools/gen_groups.py, so this module registers the extra verb in the same area.

How it reads: System Events walks the `NotificationCenter` process's window. Each notification is
an AXGroup whose AXIdentifier is a UUID; its AXStaticText children carry AXIdentifier `title` and
`body` (text is in the AXValue attribute; value/description/title return nothing) plus an unnamed
age text ("51m ago"; absent for some). App name: probed 2026-11-19, the notification group and its
AXHeading expose only AXRoleDescription (no AXTitle/AXDescription/AXValue), so `app` is null unless a
heading carries a value. That is a limit of the AX tree, not a bug; do not infer the app from the title.
Needs only the Accessibility permission the terminal already has, never Full Disk Access.

Limit (probed 2026-11-19): the NotificationCenter process exposes a window only while the
notification panel is open (or a banner is on screen). With the panel closed the list is empty, so a
read returns [] and says why on stderr. Opening the panel from code is not possible: ControlCenter
exposes no menu bars to System Events (`count of menu bars` is 0), so the clock cannot be clicked.
Open Notification Center yourself (click the clock) and run the verb, or run `--watch` while it is open.
"""
import argparse
import re
import subprocess
import sys
import time

from mac.contract import Failure, dump

UNSET = argparse.SUPPRESS
OSASCRIPT_TIMEOUT_S = 30
UUID = re.compile(r"^[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
FS, RS = "\x1f", "\x1e"          # field and record separators in the AppleScript dump
AX_HINT = ("grant the Accessibility permission to your terminal in System Settings > Privacy & "
           "Security > Accessibility, then retry")
RETRIES = 3

_WALK = f'''
set fs to ASCII character 31
set rs to ASCII character 30
tell application "System Events"
  if not (exists process "NotificationCenter") then return "NOPROCESS"
  tell process "NotificationCenter"
    if (count of windows) is 0 then return "NOWINDOW"
    set out to ""
    set els to entire contents of window 1
    repeat with n from 1 to count of els
      set e to item n of els
      try
        set r to value of attribute "AXRole" of e
        set i to ""
        try
          set i to value of attribute "AXIdentifier" of e
        end try
        set v to ""
        try
          set v to value of attribute "AXValue" of e
        end try
        if v is missing value then set v to ""
        set out to out & r & fs & i & fs & v & rs
      end try
    end repeat
    return out
  end tell
end tell
'''



def _osascript(script):
    try:
        done = subprocess.run(["osascript", "-e", script], capture_output=True, text=True,
                              timeout=OSASCRIPT_TIMEOUT_S)
    except FileNotFoundError:
        raise Failure("tool_error", "osascript not found: this verb only runs on macOS")
    except subprocess.TimeoutExpired:
        raise Failure("tool_error", f"osascript timed out after {OSASCRIPT_TIMEOUT_S}s")
    if done.returncode != 0:
        msg = done.stderr.strip()
        if "assistive" in msg.lower() or "-25211" in msg or "-1743" in msg or "not allowed" in msg.lower():
            raise Failure("permission_denied", f"Accessibility access denied ({msg}); {AX_HINT}")
        raise Failure("tool_error", f"osascript failed: {msg}")
    return done.stdout.rstrip("\n")


def parse(dump_text):
    """Turn the flat role/id/value dump into one dict per notification (UUID-identified AXGroup)."""
    notes, current = [], None
    for record in dump_text.split(RS):
        if not record.strip("\n"):
            continue
        parts = record.strip("\n").split(FS)
        if len(parts) < 3:
            continue
        role, ident, value = parts[0], parts[1], FS.join(parts[2:])
        if role == "AXGroup" and UUID.match(ident):
            current = {"id": ident, "app": None, "title": None, "body": None, "age": None}
            notes.append(current)
        elif current is None:
            continue
        elif role == "AXHeading" and value and current["app"] is None:
            current["app"] = value
        elif role == "AXStaticText":
            if ident == "title" and current["title"] is None:
                current["title"] = value
            elif ident == "body" and current["body"] is None:
                current["body"] = value
            elif ident not in ("title", "body") and value and current["age"] is None:
                current["age"] = value
    return notes


def read():
    """Current notifications as a list of dicts. [] when no notification window exists."""
    last = None
    for _ in range(RETRIES):   # a notification dismissed mid-walk makes System Events raise
        try:
            raw = _osascript(_WALK)
            break
        except Failure as failure:
            if failure.code == "permission_denied":
                raise
            last = failure
            time.sleep(0.3)
    else:
        raise last
    if raw == "NOPROCESS":
        raise Failure("tool_error", "the NotificationCenter process is not running")
    if raw == "NOWINDOW":
        return []
    return parse(raw)


def watch(interval, duration, out=None):
    """Poll and print each notification once, as a JSON line, keyed on its AXIdentifier UUID."""
    out = out or sys.stdout
    seen, emitted = set(), 0
    deadline = None if duration is None else time.monotonic() + duration
    try:
        while True:
            for note in read():
                if note["id"] not in seen:
                    seen.add(note["id"])
                    emitted += 1
                    print(dump(note), file=out, flush=True)
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    return {"watch": "stopped", "emitted": emitted}


def register(registry):
    def args(p):
        p.add_argument("--watch", action="store_true", default=UNSET,
                       help="keep polling; print each new notification once as a JSON line")
        p.add_argument("--interval", type=float, default=2.0, help="seconds between polls with --watch")
        p.add_argument("--for", dest="duration", type=float, default=None,
                       help="with --watch, stop after this many seconds (default: until interrupted)")

    @registry.verb("system", "notifications", mode="read",
                   desc="read incoming macOS notification text (title, body, age, app, id) through "
                        "Accessibility, no Full Disk Access; needs Notification Center open; app is null when AX hides it; --watch streams new ones",
                   args=args)
    def notifications(ns):
        if getattr(ns, "watch", False):
            return watch(ns.interval, ns.duration)
        found = read()
        if not found:
            print("no notification window: Notification Center is closed or empty "
                  "(click the menu-bar clock to open it, then retry)", file=sys.stderr)
        return found
