"""Validate graph/edges.json against the generated command graph (task:821c2f7e).

graph/cli_graph.json is generated and holds no edges. The edges
that descriptions cannot carry (ordering, prerequisites, the canonical choice
among duplicates) are hand-written in graph/edges.json:

    {"edges": [{"from": "<command id>", "type": "<type>", "to": "<command id>"}, ...]}

Every edge is directed from -> to, and its type is one of:

    feeds        `from` is usually run before `to` and its result informs the
                 `to` call. An ordering hint: the output need not become an
                 argument of `to` (vault outline feeds vault read, which takes
                 only a path).
    requires     `from` may only run after `to` has run: a gate
                 (imessage send requires contacts search).
    alias_of     `from` is another name for the command `to`.
    prefer_over  choose `from` instead of `to` when both would fit.

Rules, each checked by validate():
  - an edge has exactly the keys from, type, to, all strings;
  - the type is one of the four above;
  - both endpoints are command nodes of the committed graph. Exception: an alias_of `from` is a name the CLI may not have, so it
    only has to share `to`'s "<cli> <area> " prefix with a different verb,
    and it must not be a command the graph already has;
  - an alias names one canonical command;
  - no self-loops and no duplicate (from, type, to) triples.

    python -m graph.validate_edges    # exit 1 and print each problem
"""
import json
import sys
from pathlib import Path

from graph.generate import GRAPH

EDGES = Path(__file__).resolve().parent / "edges.json"

TYPES = ("feeds", "requires", "alias_of", "prefer_over")
KEYS = {"from", "type", "to"}


def command_ids(graph):
    """Ids of the command nodes in a graph dict."""
    return {n["id"] for n in graph["nodes"] if n["kind"] == "command"}


def load(path=EDGES):
    """The edge list from an edges file."""
    return json.loads(Path(path).read_text())["edges"]


def validate(edges, graph):
    """Problems with these edges against this graph; [] when valid."""
    commands = command_ids(graph)
    problems, seen, alias_targets = [], set(), {}
    for i, edge in enumerate(edges):
        where = f"edge {i} {edge!r}"
        if not isinstance(edge, dict) or set(edge) != KEYS:
            problems.append(f"{where}: needs exactly the keys {sorted(KEYS)}")
            continue
        if not all(isinstance(edge[k], str) for k in KEYS):
            problems.append(f"{where}: from, type and to must be strings")
            continue
        src, kind, dst = edge["from"], edge["type"], edge["to"]
        if kind not in TYPES:
            problems.append(f"{where}: type {kind!r} is not one of {list(TYPES)}")
            continue
        if dst not in commands:
            problems.append(f"{where}: `to` is not a command in the graph: {dst}")
        if kind == "alias_of":
            prefix = dst.rsplit(" ", 1)[0] + " "
            verb = src[len(prefix):] if src.startswith(prefix) else ""
            if not verb or " " in verb or src == dst:
                problems.append(f"{where}: alias must be `{prefix}<verb>` with a different verb")
            elif src in commands:
                problems.append(f"{where}: alias {src} is already a command in the graph")
            elif alias_targets.setdefault(src, dst) != dst:
                problems.append(f"{where}: alias {src} already names {alias_targets[src]}")
        elif src not in commands:
            problems.append(f"{where}: `from` is not a command in the graph: {src}")
        if src == dst:
            problems.append(f"{where}: self-loop")
        if (src, kind, dst) in seen:
            problems.append(f"{where}: duplicate edge")
        seen.add((src, kind, dst))
    return problems


def main():
    problems = validate(load(), json.loads(GRAPH.read_text()))
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
