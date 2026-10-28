"""Turn the migrated MCP servers off, or back on (task:8cd14cfe, task:299daf58).

The servers local-mac, astrology, wyckoff-analyzer and sysml-mcp are replaced
by `mac` commands. Cutover removes them from the user scope of ~/.claude.json
and removes their mcp__<server>__* allow rules from ~/.claude/settings.json.
Rollback puts both back from a backup saved beside those files.

claude-hooks is a second cutover with its own backup file, so its rollback
restores only claude-hooks. The cutover name is an optional second argument;
omitted, it is the first (9839b040).

    uv run python tools/cutover.py status [299daf58]   # exit 0 if cut over, 1 if not
    uv run python tools/cutover.py apply [299daf58]    # back up, then remove
    uv run python tools/cutover.py rollback [299daf58] # restore from the backup
    uv run python tools/cutover.py count               # tools each configured server lists

Servers are added and removed with `claude mcp add-json/remove -s user`, not by
editing ~/.claude.json, because running Claude Code sessions rewrite that file.
The `mac` rules in settings.json are left alone (tools/gen_permissions.py owns
them). Hosted connectors and claude-in-chrome are not in ~/.claude.json, so
nothing here touches them; nor does it touch per-project disabledMcpServers.
"""
import asyncio
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
from gen_permissions import render  # noqa: E402  (same settings.json layout)
from mac.groups._mcp_proxy import Server, _session  # noqa: E402

CLAUDE_JSON = Path.home() / ".claude.json"
SETTINGS = Path.home() / ".claude" / "settings.json"

# cutover name -> servers it removes. Each has its own backup file, so a
# rollback restores only that cutover's servers and rules.
CUTOVERS = {
    "9839b040": ("local-mac", "astrology", "wyckoff-analyzer", "sysml-mcp"),
    "299daf58": ("claude-hooks",),
}
DEFAULT = "9839b040"
SERVERS = CUTOVERS[DEFAULT]


def backup_path(cutover=DEFAULT):
    return Path.home() / ".claude" / f"cutover-{cutover}-backup.json"


BACKUP = backup_path()


def migrated(rule, servers=SERVERS):
    """True for a permission rule naming a tool of one of `servers`."""
    return re.match(r"mcp__(%s)__" % "|".join(map(re.escape, servers)), rule) is not None


def strip_rules(settings, servers=SERVERS):
    """(settings without `servers`' allow rules, the rules removed in order)."""
    out = json.loads(json.dumps(settings))
    allow = out.get("permissions", {}).get("allow", [])
    removed = [r for r in allow if migrated(r, servers)]
    if allow:
        out["permissions"]["allow"] = [r for r in allow if not migrated(r, servers)]
    return out, removed


def restore_rules(settings, rules):
    """settings with any of `rules` not already allowed appended to allow."""
    out = json.loads(json.dumps(settings))
    allow = out.setdefault("permissions", {}).setdefault("allow", [])
    allow += [r for r in rules if r not in allow]
    return out


def user_servers():
    return json.loads(CLAUDE_JSON.read_text()).get("mcpServers", {})


def status(cutover=DEFAULT):
    servers, backup = CUTOVERS[cutover], backup_path(cutover)
    present = [s for s in servers if s in user_servers()]
    rules = strip_rules(json.loads(SETTINGS.read_text()), servers)[1]
    print(f"servers still configured: {', '.join(present) or 'none'}")
    print(f"migrated allow rules: {len(rules)}")
    print(f"backup: {backup if backup.exists() else 'none'}")
    return 0 if not present and not rules else 1


def claude(*args):
    subprocess.run(["claude", "mcp", *args], check=True, capture_output=True, text=True)


def apply(cutover=DEFAULT):
    backup = backup_path(cutover)
    servers = {s: d for s, d in user_servers().items() if s in CUTOVERS[cutover]}
    settings = json.loads(SETTINGS.read_text())
    stripped, removed = strip_rules(settings, CUTOVERS[cutover])
    if backup.exists():
        # A second apply after a rollback: keep the first backup, it is the
        # pre-cutover state. Refuse if it would lose something new.
        saved = json.loads(backup.read_text())
        extra = set(servers) - set(saved["servers"]) or set(removed) - set(saved["rules"])
        if extra:
            raise SystemExit(f"{backup} lacks {sorted(extra)}; move it aside before applying")
    else:
        backup.write_text(json.dumps({"servers": servers, "rules": removed}, indent=2) + "\n")
        print(f"backed up {len(servers)} servers and {len(removed)} rules to {backup}")
    for name in servers:
        claude("remove", "-s", "user", name)
    if removed:
        SETTINGS.write_text(render(stripped))
    print(f"removed servers: {', '.join(servers) or 'none'}; removed {len(removed)} allow rules")
    return status(cutover)


def rollback(cutover=DEFAULT):
    backup = backup_path(cutover)
    if not backup.exists():
        raise SystemExit(f"no backup at {backup}; nothing to roll back to")
    saved = json.loads(backup.read_text())
    present = user_servers()
    for name, definition in saved["servers"].items():
        if name not in present:
            claude("add-json", "-s", "user", name, json.dumps(definition))
    current = SETTINGS.read_text()
    restored = render(restore_rules(json.loads(current), saved["rules"]))
    if restored != current:
        SETTINGS.write_text(restored)
    print(f"restored servers: {', '.join(saved['servers'])}; {len(saved['rules'])} allow rules present")
    return 0 if status(cutover) == 1 else 1


def _tool_count(definition):
    """How many tools a configured stdio server lists, started the way `mac` proxies start one."""
    server = Server(definition["command"], tuple(definition.get("args", ())))

    async def op(session):
        return len((await session.list_tools()).tools)

    with tempfile.TemporaryFile("w+") as errlog:  # servers' own start-up logging stays out of the report
        return asyncio.run(asyncio.wait_for(_session(server, errlog, op), 60))


def count():
    """Tools each user-scope stdio server lists, as a fresh session would load them."""
    total = 0
    for name, definition in user_servers().items():
        if definition.get("type", "stdio") != "stdio":
            print(f"{name:20} (not stdio, skipped)")
            continue
        try:
            n = _tool_count(definition)
        except Exception as exc:  # report and keep counting the rest
            print(f"{name:20} failed: {type(exc).__name__}: {exc}")
            continue
        total += n
        print(f"{name:20} {n}")
    print(f"{'total':20} {total}  (hosted connectors and claude-in-chrome not counted)")
    return 0


def main(argv):
    verbs = {"status": status, "apply": apply, "rollback": rollback, "count": count}
    if not argv or argv[0] not in verbs or len(argv) > 2:
        print(__doc__, file=sys.stderr)
        return 2
    if argv[0] == "count":
        return count() if len(argv) == 1 else 2
    cutover = argv[1] if len(argv) == 2 else DEFAULT
    if cutover not in CUTOVERS:
        print(f"unknown cutover {cutover}; known: {', '.join(CUTOVERS)}", file=sys.stderr)
        return 2
    return verbs[argv[0]](cutover)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
