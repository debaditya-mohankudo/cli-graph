"""Area groups: the hand-written layer above areas (graph/groups.json).

    {"groups": {"<group>": ["<area>", ...], ...},
     "purposes": {"<group>": "<one line>", ...},
     "ungrouped": ["<area>", ...]}

A group gathers related areas (mail, imessage and contacts are all
communication). graph/generate.py turns it into the `groups` and `domains`
sections of cli_graph.json; find_cli uses them to
reach verbs in neighbouring areas and to favour a group a query names.
The purposes go only into the find_cli tool description (describe()).

Rules, each checked by validate():
  - every group has a non-empty one-line purpose, and every purpose names a
    group;
  - every area of the CLI is listed exactly once, either in one group or in
    `ungrouped` (so a new area cannot be left out by accident);
  - no group or `ungrouped` names an area the CLI does not have;
  - a group has at least one area, and its name is a lowercase word.
"""
import json
import re
from pathlib import Path

GROUPS = Path(__file__).resolve().parent / "groups.json"


def load(path=GROUPS):
    """The groups spec from a groups file."""
    return json.loads(Path(path).read_text())


def validate(spec, areas):
    """Problems with this spec against these CLI areas; [] when valid."""
    if not isinstance(spec, dict) or set(spec) != {"groups", "purposes", "ungrouped"}:
        return ["groups file needs exactly the keys groups, purposes, ungrouped"]
    problems, placed = [], {}
    for g in sorted(set(spec["groups"]) | set(spec["purposes"])):
        if g not in spec["groups"]:
            problems.append(f"purpose {g!r} names no group")
        elif not str(spec["purposes"].get(g, "")).strip():
            problems.append(f"group {g!r}: needs a one-line purpose")
    listings = [(f"group {g!r}", g, a) for g, a in sorted(spec["groups"].items())]
    listings.append(("ungrouped", None, spec["ungrouped"]))
    for where, name, members in listings:
        if name is not None:
            if not re.fullmatch(r"[a-z]+", name):
                problems.append(f"{where}: name must be a lowercase word")
            if not members:
                problems.append(f"{where}: needs at least one area")
        for area in members:
            if area not in areas:
                problems.append(f"{where}: {area!r} is not a CLI area")
            elif area in placed:
                problems.append(f"{where}: {area!r} is already in {placed[area]}")
            else:
                placed[area] = where
    problems += [f"area {a!r} is in no group and not in ungrouped"
                 for a in sorted(set(areas) - set(placed))]
    return problems


def describe(spec, areas):
    """One line per group, `group: purpose (area, ...)`, for these CLI areas;
    areas in no group follow on an `other:` line."""
    lines, placed = [], set()
    for g, members in spec["groups"].items():
        members = [a for a in members if a in areas]
        placed.update(members)
        if members:
            lines.append(f"{g}: {spec['purposes'].get(g, '')} ({', '.join(members)})")
    rest = sorted(set(areas) - placed)
    if rest:
        lines.append(f"other: ({', '.join(rest)})")
    return lines


def area_groups(spec):
    """{area: group} for the grouped areas of a spec."""
    return {a: g for g, members in spec["groups"].items() for a in members}


def command_groups(graph):
    """{command id: group name} from a graph's domains; ungrouped commands
    are absent."""
    return {n["id"]: graph["domains"][n["area"]]["group"] for n in graph["nodes"]
            if n["kind"] == "command" and graph["domains"][n["area"]]["group"]}
