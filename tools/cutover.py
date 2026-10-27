"""Turn the migrated MCP servers off, or back on (task:8cd14cfe).

The servers local-mac, astrology, wyckoff-analyzer and sysml-mcp are replaced
by `mac` commands. Cutover removes them from the user scope of ~/.claude.json
and removes their mcp__<server>__* allow rules from ~/.claude/settings.json.
Rollback puts both back from a backup saved beside those files.

    uv run python tools/cutover.py status     # exit 0 if cut over, 1 if not
    uv run python tools/cutover.py apply      # back up, then remove
    uv run python tools/cutover.py rollback   # restore from the backup
    uv run python tools/cutover.py count      # tools each configured server lists

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

SERVERS = ("local-mac", "astrology", "wyckoff-analyzer", "sysml-mcp")
CLAUDE_JSON = Path.home() / ".claude.json"
SETTINGS = Path.home() / ".claude" / "settings.json"
BACKUP = Path.home() / ".claude" / "cutover-9839b040-backup.json"

_MIGRATED = re.compile(r"mcp__(%s)__" % "|".join(map(re.escape, SERVERS)))


def migrated(rule):
    """True for a permission rule naming a tool of a migrated server."""
    return _MIGRATED.match(rule) is not None


def strip_rules(settings):
    """(settings without migrated allow rules, the rules removed in order)."""
    out = json.loads(json.dumps(settings))
    allow = out.get("permissions", {}).get("allow", [])
    removed = [r for r in allow if migrated(r)]
    if allow:
        out["permissions"]["allow"] = [r for r in allow if not migrated(r)]
    return out, removed


def restore_rules(settings, rules):
    """settings with any of `rules` not already allowed appended to allow."""
    out = json.loads(json.dumps(settings))
    allow = out.setdefault("permissions", {}).setdefault("allow", [])
    allow += [r for r in rules if r not in allow]
    return out


def user_servers():
    return json.loads(CLAUDE_JSON.read_text()).get("mcpServers", {})


def status():
    present = [s for s in SERVERS if s in user_servers()]
    rules = strip_rules(json.loads(SETTINGS.read_text()))[1]
    print(f"servers still configured: {', '.join(present) or 'none'}")
    print(f"migrated allow rules: {len(rules)}")
    print(f"backup: {BACKUP if BACKUP.exists() else 'none'}")
    return 0 if not present and not rules else 1


def claude(*args):
    subprocess.run(["claude", "mcp", *args], check=True, capture_output=True, text=True)


def apply():
    servers = {s: d for s, d in user_servers().items() if s in SERVERS}
    settings = json.loads(SETTINGS.read_text())
    stripped, removed = strip_rules(settings)
    if BACKUP.exists():
        # A second apply after a rollback: keep the first backup, it is the
        # pre-cutover state. Refuse if it would lose something new.
        saved = json.loads(BACKUP.read_text())
        extra = set(servers) - set(saved["servers"]) or set(removed) - set(saved["rules"])
        if extra:
            raise SystemExit(f"{BACKUP} lacks {sorted(extra)}; move it aside before applying")
    else:
        BACKUP.write_text(json.dumps({"servers": servers, "rules": removed}, indent=2) + "\n")
        print(f"backed up {len(servers)} servers and {len(removed)} rules to {BACKUP}")
    for name in servers:
        claude("remove", "-s", "user", name)
    if removed:
        SETTINGS.write_text(render(stripped))
    print(f"removed servers: {', '.join(servers) or 'none'}; removed {len(removed)} allow rules")
    return status()


def rollback():
    if not BACKUP.exists():
        raise SystemExit(f"no backup at {BACKUP}; nothing to roll back to")
    saved = json.loads(BACKUP.read_text())
    present = user_servers()
    for name, definition in saved["servers"].items():
        if name not in present:
            claude("add-json", "-s", "user", name, json.dumps(definition))
    current = SETTINGS.read_text()
    restored = render(restore_rules(json.loads(current), saved["rules"]))
    if restored != current:
        SETTINGS.write_text(restored)
    print(f"restored servers: {', '.join(saved['servers'])}; {len(saved['rules'])} allow rules present")
    return 0 if status() == 1 else 1


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
    if len(argv) != 1 or argv[0] not in verbs:
        print(__doc__, file=sys.stderr)
        return 2
    return verbs[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
