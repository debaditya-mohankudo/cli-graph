"""Area groups: the hand-written layer above areas (graph/groups.json).

    {"groups": {"<group>": ["<area>", ...], ...}, "ungrouped": ["<area>", ...]}

A group gathers related areas (mail, imessage and contacts are all
communication). graph/generate.py turns it into `group:<name>` nodes and
`domain:<area> -> group:<name>` edges of type `in_group`; find_cli uses it to
reach verbs in neighbouring areas and to favour a group a query names.

Rules, each checked by validate():
  - every area of the CLI is listed exactly once, either in one group or in
    `ungrouped` (so a new area cannot be left out by accident);
  - no group or `ungrouped` names an area the CLI does not have;
  - a group has at least two areas, and its name is a lowercase word.
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
    if not isinstance(spec, dict) or set(spec) != {"groups", "ungrouped"}:
        return ["groups file needs exactly the keys groups, ungrouped"]
    problems, placed = [], {}
    listings = [(f"group {g!r}", g, a) for g, a in sorted(spec["groups"].items())]
    listings.append(("ungrouped", None, spec["ungrouped"]))
    for where, name, members in listings:
        if name is not None:
            if not re.fullmatch(r"[a-z]+", name):
                problems.append(f"{where}: name must be a lowercase word")
            if len(members) < 2:
                problems.append(f"{where}: needs at least two areas")
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


def area_groups(spec):
    """{area: group} for the grouped areas of a spec."""
    return {a: g for g, members in spec["groups"].items() for a in members}


def command_groups(graph):
    """{command id: group name} from a graph's in_group edges; ungrouped
    commands are absent."""
    of_domain = {e["from"]: e["to"].split(":", 1)[1]
                 for e in graph["edges"] if e["type"] == "in_group"}
    return {n["id"]: of_domain[n["domain"]] for n in graph["nodes"]
            if n["kind"] == "command" and n["domain"] in of_domain}
