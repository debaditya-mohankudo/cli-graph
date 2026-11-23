"""`mac cli` — the find_cli lookup as a command, for when the MCP server is down.

`mac cli find "<task>"` calls the same find_cli.service the server does, so it
returns the same result for the same input.
"""
import argparse
from pathlib import Path

import yaml

from find_cli import DEFAULT_LIMIT
from find_cli.service import Finder
from mac.contract import Failure

UNSET = argparse.SUPPRESS


def _skill_roots():
    """(scope, dir) for the global skills dir and every ~/workspace/*/.claude/skills."""
    home = Path.home()
    yield "global", home / ".claude" / "skills"
    for d in sorted((home / "workspace").glob("*/.claude/skills")):
        yield d.parent.parent.name, d


def _read_skill(md):
    """Frontmatter of one SKILL.md as (name, one-line description), or None if unparseable."""
    try:
        text = md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None
        meta = yaml.safe_load(text.split("---", 2)[1]) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError, IndexError):
        return None
    if not isinstance(meta, dict):
        return None
    desc = " ".join(str(meta.get("description") or "").split())
    return str(meta.get("name") or md.parent.name), desc


def list_skills(roots=None):
    """Installed skills; symlinked dirs are followed, dirs without SKILL.md (any case) are skipped."""
    out = []
    for scope, root in (_skill_roots() if roots is None else roots):
        for d in sorted(Path(root).glob("*")):
            md = next((f for f in sorted(d.glob("*")) if f.name.lower() == "skill.md"), None) if d.is_dir() else None
            got = _read_skill(md) if md else None
            if got:
                out.append({"name": got[0], "description": got[1], "scope": scope, "path": str(md)})
    return out


def register(registry):
    def find_args(p):
        p.add_argument("task", nargs="?", default="",
                       help="omit it and pass --area to list that area's commands")
        p.add_argument("--hops", type=int, default=2,
                       help="0 seeds only, 1 adds linked commands, 2 also adds area siblings")
        p.add_argument("--area", default="", help="an area or group you already know")

    @registry.verb("cli", "find", mode="read",
                   desc="find the mac commands for a task in plain words: seeds and neighbours with usage "
                        "(--limit sets the number of seeds); with only --area, list that area's commands",
                   args=find_args)
    def find(ns):
        result = Finder().answer(ns.task, limit=ns.limit or DEFAULT_LIMIT, hops=ns.hops, area=ns.area)
        if "error" in result:
            raise Failure(result["error"]["code"], result["error"]["message"])
        return result

    def skills_args(p):
        p.add_argument("--query", default="", help="words; keep skills whose name or description has all of them")
        p.add_argument("--name", default="", help="one skill by exact name")
        p.add_argument("--scope", default="", help="global, or a repo directory name under ~/workspace")

    @registry.verb("cli", "skills", mode="read",
                   desc="list the installed Claude skills (name, one-line description, scope, path), read-only; "
                        "filter by --query words, one --name or --scope global or a repo",
                   args=skills_args)
    def skills(ns):
        rows = list_skills()
        if ns.scope:
            rows = [r for r in rows if r["scope"] == ns.scope]
        if ns.name:
            rows = [r for r in rows if r["name"] == ns.name]
        words = ns.query.lower().split()
        rows = [r for r in rows if all(w in f"{r['name']} {r['description']}".lower() for w in words)]
        return {"count": len(rows), "skills": rows}
