"""Domain vocabulary: words that signal one of the closed groups (task:a70134dd).

    {"about": "...", "domains": {"<group>": ["<word>", ...], ...}}

The set of domains is closed: it is exactly the groups of graph/groups.json.
This file adds no new idea, only the plain words a task uses when it means a
group without naming it ("ping my friend" means communication). find_cli
resolves a query to the domains whose words it contains and boosts those
domains' commands like a group the query names (find_cli.rank).

Rules, each checked by validate():
  - every key is a group in graph/groups.json;
  - every group has at least one word;
  - words are lowercase alphanumeric and listed under one domain only.

    uv run python -m graph.domains     # exit 1 and name each problem
"""
import json
import re
import sys
from pathlib import Path

from graph import groups as _groups

DOMAINS = Path(__file__).resolve().parent / "domains.json"


def load(path=DOMAINS):
    """{group: [word, ...]} from a domains file."""
    return json.loads(Path(path).read_text())["domains"]


def validate(domains, group_names):
    """Problems with domains against these group names; [] when valid."""
    problems, owner = [], {}
    for g in sorted(domains):
        if g not in group_names:
            problems.append(f"domain {g!r}: not a group in graph/groups.json")
        if not domains[g]:
            problems.append(f"domain {g!r}: needs at least one word")
        for w in domains[g]:
            if not re.fullmatch(r"[a-z0-9]+", w):
                problems.append(f"domain {g!r}: word {w!r} must be lowercase alphanumeric")
            if w in owner and owner[w] != g:
                problems.append(f"word {w!r}: listed under {owner[w]!r} and {g!r}")
            owner.setdefault(w, g)
    for g in sorted(set(group_names) - set(domains)):
        problems.append(f"group {g!r}: has no domain vocabulary")
    return problems


def main():
    problems = validate(load(), set(_groups.load()["groups"]))
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
