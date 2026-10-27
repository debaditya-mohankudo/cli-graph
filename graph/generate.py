"""Generate graph/cli_graph.json from each CLI's `--help --json` (task:980f10b3).

The CLI is the single source of truth: every command node comes from a row of
`<cli> --help --json`, which must be a list of {area, verb, mode, desc, usage}.
Nothing in the output is hand-edited; hand-written edges live elsewhere.

    python -m graph.generate          # rewrite graph/cli_graph.json
    python -m graph.generate --check  # exit 1 if the committed file is stale

Output shape (groups and domains come first, as an overview; nodes and edges
carry the same facts in the form find_cli reads):
    groups:  {<group>: [<area>, ...]}
    domains: {<area>: {group: <group> | null, verbs: [<verb>, ...]}}
    nodes: command  {id: "<cli> <area> <verb>", kind: "command", cli, area,
                     verb, mode, desc, usage, domain: "domain:<area>"}
           domain   {id: "domain:<area>", kind: "domain", name: <area>}
           group    {id: "group:<name>", kind: "group", name: <name>}
    edges: {from: <command id>, to: <domain id>, type: "in_domain"}
           {from: <domain id>, to: <group id>, type: "in_group"}

Groups come from the hand-written graph/groups.json (see graph/groups.py);
an area listed as ungrouped has no in_group edge.

The file is byte-stable: nodes sorted by id, edges by (from, type, to), keys
sorted, one object per line, no timestamps or paths. Adding a verb changes
only its node line and its edge line (plus a domain line for a new area).
"""
import json
import subprocess
import sys
from pathlib import Path

from graph import groups as _groups

REPO = Path(__file__).resolve().parent.parent
GRAPH = REPO / "graph" / "cli_graph.json"

# (cli name, argv that prints the --help --json rows). One CLI today.
CLIS = [("mac", [str(REPO / "bin" / "mac"), "--help", "--json"])]

FIELDS = ("area", "verb", "mode", "desc", "usage")


def read_cli(argv):
    """The `--help --json` rows of one CLI."""
    out = subprocess.run(argv, check=True, capture_output=True, text=True).stdout
    rows = json.loads(out)
    for row in rows:
        missing = [f for f in FIELDS if f not in row]
        if missing:
            raise ValueError(f"{argv[0]}: row {row!r} lacks {missing}")
    return rows


def build(clis=None, groups=None):
    """The graph dict for these CLIs, as {"nodes": [...], "edges": [...]}.

    groups is a graph/groups.json spec; it defaults to that file for the real
    CLIs and to none for clis passed in. An invalid spec raises ValueError.
    """
    if groups is None and clis is None:
        groups = _groups.load()
    nodes, edges, domains, group_areas = {}, [], {}, {}
    for cli, argv in clis or CLIS:
        for row in read_cli(argv):
            domain = f"domain:{row['area']}"
            cid = f"{cli} {row['area']} {row['verb']}"
            nodes[cid] = {"id": cid, "kind": "command", "cli": cli,
                          "domain": domain, **{f: row[f] for f in FIELDS}}
            nodes[domain] = {"id": domain, "kind": "domain", "name": row["area"]}
            edges.append({"from": cid, "to": domain, "type": "in_domain"})
            domains.setdefault(row["area"], {"group": None, "verbs": []})["verbs"].append(row["verb"])
    if groups is not None:
        areas = sorted(n["name"] for n in nodes.values() if n["kind"] == "domain")
        problems = _groups.validate(groups, areas)
        if problems:
            raise ValueError("graph/groups.json: " + "; ".join(problems))
        for area, group in _groups.area_groups(groups).items():
            gid = f"group:{group}"
            nodes[gid] = {"id": gid, "kind": "group", "name": group}
            edges.append({"from": f"domain:{area}", "to": gid, "type": "in_group"})
            domains[area]["group"] = group
            group_areas.setdefault(group, []).append(area)
    edges.sort(key=lambda e: (e["from"], e["type"], e["to"]))
    for d in domains.values():
        d["verbs"].sort()
    for areas in group_areas.values():
        areas.sort()
    return {"groups": group_areas, "domains": domains,
            "nodes": [nodes[k] for k in sorted(nodes)], "edges": edges}


def render(graph):
    """Serialise a graph so the same input always gives the same bytes."""
    def line(obj):
        return "    " + json.dumps(obj, sort_keys=True, ensure_ascii=False)

    def array(name, items):
        body = ",\n".join(line(i) for i in items)
        return f'  "{name}": [\n{body}\n  ]' if items else f'  "{name}": []'

    def mapping(name, items):
        body = ",\n".join(f"    {json.dumps(k)}: {json.dumps(v, sort_keys=True, ensure_ascii=False)}"
                          for k, v in sorted(items.items()))
        return f'  "{name}": {{\n{body}\n  }}' if items else f'  "{name}": {{}}'

    return ("{\n" + mapping("groups", graph["groups"]) + ",\n"
            + mapping("domains", graph["domains"]) + ",\n"
            + array("edges", graph["edges"]) + ",\n" + array("nodes", graph["nodes"]) + "\n}\n")


def drift(live, committed_text):
    """Problems with the committed graph text against the live graph; [] when current.

    Names CLI verbs missing from the graph and graph commands with no CLI verb
    before falling back to "the file differs" for any other change.
    """
    def commands(graph):
        return {n["id"] for n in graph["nodes"] if n["kind"] == "command"}

    try:
        committed = json.loads(committed_text)
    except ValueError as exc:
        return [f"graph is not valid JSON: {exc}"]
    problems = [f"CLI verb missing from graph: {c}" for c in sorted(commands(live) - commands(committed))]
    problems += [f"graph command has no CLI verb: {c}" for c in sorted(commands(committed) - commands(live))]
    if not problems and committed_text != render(live):
        problems.append("graph differs from the CLIs' --help or graph/groups.json "
                        "(desc, usage, mode, groups or layout)")
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    live = build()
    if "--check" in argv:
        text = GRAPH.read_text() if GRAPH.exists() else '{"nodes": [], "edges": []}'
        problems = drift(live, text)
        for p in problems:
            print(p, file=sys.stderr)
        if problems:
            print("run: python -m graph.generate", file=sys.stderr)
        return 1 if problems else 0
    text = render(live)
    GRAPH.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
