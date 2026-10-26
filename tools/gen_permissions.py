"""Claude Code permission rules for `mac`, generated from the command graph (task:0aa96180).

Every command in graph/cli_graph.json gets exactly one rule in
~/.claude/settings.json: an `ask` rule when it is in ASK below, otherwise an
`allow` rule. Read or write does not decide it; ASK does. A verb added to the
graph therefore gets an allow rule the next time this runs, and --check (run by
tests/test_permissions.py) fails until it does.

    uv run python tools/gen_permissions.py           # rewrite the mac rules in settings.json
    uv run python tools/gen_permissions.py --check   # exit 1 if they are stale

Allow rules use the bare `mac <area> <verb> *` form, which is how agents call
it. Ask rules are written for every way of naming the launcher (LAUNCHERS), so
`~/bin/mac imessage send ...` prompts just as `mac imessage send ...` does.

Rules this script owns are those shaped `Bash(<launcher> <area> <verb> *)`.
They are replaced on each run; every other rule is kept in place.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GRAPH = REPO / "graph" / "cli_graph.json"
SETTINGS = Path.home() / ".claude" / "settings.json"

# Outbound or destructive verbs: these prompt. Reviewed by hand (user decision,
# 2026-10-26; vault write added 2026-10-27, since it overwrites an existing
# note). Everything else, read or write, is allowed.
ASK = {
    "imessage": {"send"},
    "mail": {"compose", "delete", "move"},
    "calendar": {"delete_event"},
    "notes": {"delete"},
    "reminders": {"delete"},
    "vault": {"delete", "move", "write"},
    "safari": {"close_all_tabs"},
    "system": {"process_kill", "sleep_now"},
    "connector": {"execute_action"},
    "vpn": {"disconnect"},
}

# Ways a shell command can name the launcher: the bare name on PATH, the
# ~/bin symlink, and the script in this repo.
LAUNCHERS = ("mac", "~/bin/mac", str(Path.home() / "bin" / "mac"),
             str(REPO / "bin" / "mac"), "bin/mac", "./bin/mac")


def commands(graph):
    """(area, verb) for every command node, in graph order."""
    return [(n["area"], n["verb"]) for n in graph["nodes"] if n["kind"] == "command"]


def rules(graph):
    """(allow, ask) rule lists for the graph's commands."""
    known = set(commands(graph))
    missing = sorted(f"{a} {v}" for a, verbs in ASK.items() for v in verbs if (a, v) not in known)
    if missing:
        raise SystemExit(f"ASK names commands the graph does not have: {', '.join(missing)}")
    allow, ask = [], []
    for area, verb in sorted(known):
        if verb in ASK.get(area, ()):
            ask += [f"Bash({launcher} {area} {verb} *)" for launcher in LAUNCHERS]
        else:
            allow.append(f"Bash(mac {area} {verb} *)")
    return allow, ask


_OWNED = re.compile(r"Bash\((?:%s) [a-z_]+ [a-z_0-9]+ \*\)" % "|".join(map(re.escape, LAUNCHERS)))


def owned(rule):
    """True for a rule shaped like a generated one, `Bash(<launcher> <area> <verb> *)`.

    A rule for a verb since removed from the graph is owned, so it is dropped.
    A hand-written rule of any other shape (`Bash(mac --help)`) is not.
    """
    return _OWNED.fullmatch(rule) is not None


def apply(settings, graph):
    """settings with its mac rules replaced by the generated ones; other rules keep their place."""
    allow, ask = rules(graph)
    out = json.loads(json.dumps(settings))
    perms = out.setdefault("permissions", {})
    for key, generated in (("allow", allow), ("ask", ask)):
        kept = [r for r in perms.get(key, []) if not owned(r)]
        perms[key] = kept + generated
    return out


def render(settings):
    return json.dumps(settings, indent=2, ensure_ascii=False) + "\n"


def main(argv):
    graph = json.loads(GRAPH.read_text())
    current = SETTINGS.read_text()
    updated = render(apply(json.loads(current), graph))
    if updated == current:
        print("mac permission rules are current")
        return 0
    if "--check" in argv:
        print(f"{SETTINGS}: mac permission rules are stale; run tools/gen_permissions.py", file=sys.stderr)
        return 1
    SETTINGS.write_text(updated)
    allow, ask = rules(graph)
    print(f"wrote {len(allow)} allow and {len(ask)} ask rules for mac to {SETTINGS}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
