"""find_cli: map a task phrase to a small subgraph of `mac` commands (task:129f1bc3).

    find(task, graph, edges)  ->  {query, no_match, confidence, seeds, neighbours[, hint]}

no_match    true when no command scored above 0: nothing covers the task
confidence  {level, coverage, gap} for the top seed (rank.confidence); level
            "low" means only an incidental word matched, so check the result
            before running it. Advice only: it never hides a seed.
seeds       [{id, score, mode, desc, usage}]  BM25 hits, best first
neighbours  [{id, via, dir, from, hop, mode, desc, usage}]  reached from a seed
            via a hand-written edge (dir "out"/"in"), as an area sibling
            (via "in_domain", dir "sibling") or from another area of the
            seed's group (via "in_group", dir "group")

hint        only when the caller passed an area/group hint: {value, known, valid}.
            A known hint multiplies the scores of that area's (or group's)
            commands (rank.GROUP_BOOST); it reorders seeds but the best seed
            without it is kept. An unknown one is reported with the valid
            names and changes nothing.

domains     only when the caller passed a domains map (graph/domains.json,
            task:a70134dd): the sorted groups the query resolved to. Their
            commands are boosted like a group the query names; [] means the
            query used no domain word and ranking is plain keyword ranking.
            confidence is always computed without the domain boost.

With a usage map, each seed and neighbour also carries count and last_used.

It reads only the committed graph/cli_graph.json and graph/edges.json, never a
live CLI, and every id it returns is a command node of that graph. The output
is a pure function of its inputs; server.py only loads the files once and
calls find(). The eval (task:597ac09d) can import this module directly with no
MCP dependency.
"""
import json

from graph.generate import GRAPH
from graph.groups import command_groups
from graph.validate_edges import EDGES, command_ids

from . import expand as _expand
from . import rank as _rank

DEFAULT_LIMIT = 5


def load(graph_path=GRAPH, edges_path=EDGES):
    """(graph, edges) from the committed files."""
    with open(graph_path) as f:
        graph = json.load(f)
    with open(edges_path) as f:
        edges = json.load(f)["edges"]
    return graph, edges


def find(task, graph, edges=(), limit=DEFAULT_LIMIT, hops=2, usage=None, area=None,
         domains=None):
    """Seeds and neighbours for task. See the module docstring for the shape.

    usage ({id: {"count", "last_used"}}, see find_cli.usage) is passed in by
    the caller, so find() stays a pure function of its arguments. When given,
    every returned command gets count and last_used (0 / None if it has no
    row); it never changes ranking or order. area is the caller's optional
    area or group hint (task:fcaad255). domains ({group: [words]}, see
    graph.domains) is passed in the same way (task:a70134dd). When usage,
    area and domains are None, the output is exactly what it was without them.
    """
    commands = command_ids(graph)
    nodes = {n["id"]: n for n in graph["nodes"] if n["id"] in commands}
    docs = _rank.documents(graph, edges)
    info_hint = _rank.hint_info(area, graph) if area else None
    hint = info_hint["value"] if info_hint and info_hint["known"] else None
    scores = _rank.scores(task, docs, command_groups(graph), hint, domains)
    seed_pairs = [(cid, s) for cid, s in _rank.seeds(task, graph, edges, limit, hint, domains)
                  if cid in commands]
    neighbours = _expand.expand([cid for cid, _ in seed_pairs], graph, edges,
                                scores=scores, hops=hops)

    def info(cid):
        n = nodes[cid]
        out = {"mode": n["mode"], "desc": n["desc"], "usage": n["usage"]}
        if usage is not None:
            u = usage.get(cid) or {}
            out["count"] = u.get("count", 0)
            out["last_used"] = u.get("last_used")
        return out

    # The domain layer reorders but never certifies: confidence reads the
    # scores without it, so a domain word alone cannot turn "low" into "high".
    plain = _rank.scores(task, docs, command_groups(graph), hint) if domains else scores
    conf = _rank.confidence(task, docs, plain)
    result = {
        "query": task,
        "no_match": not seed_pairs,
        "confidence": conf,
        "seeds": [{"id": cid, "score": s, **info(cid)} for cid, s in seed_pairs],
        "neighbours": [{**nb, **info(nb["id"])} for nb in neighbours],
    }
    if info_hint:
        result["hint"] = info_hint
    if domains is not None:
        result["domains"] = _rank.resolve_domains(task, domains)
    return result


def browse(area, graph, edges=(), usage=None):
    """Every command of one area, or the areas of one group (task:6d619bfc).

    The read-on-demand half of find_cli: the tool description lists groups
    and areas, and a caller who knows the area lists its verbs here instead
    of searching. Pure, like find().

    area   ->  {browse, area, commands: [{id, mode, desc, usage, links?, aliases?}]}
               links are the hand-written edges ({type, dir, to}); aliases are
               the words alias_of maps onto the command.
    group  ->  {browse, group, areas: [{area, verbs}]}  names only, since a
               whole group's usage lines would be thousands of tokens; browse
               one of its areas next.
    unknown -> {browse, hint: {value, known: false, valid}} and nothing else.
    """
    info = _rank.hint_info(area, graph)
    value = info["value"]
    if not info["known"]:
        return {"browse": value, "hint": info}
    domains = graph["domains"]
    if value not in domains:
        return {"browse": value, "group": value,
                "areas": [{"area": a, "verbs": domains[a]["verbs"]}
                          for a in sorted(domains) if domains[a]["group"] == value]}
    commands = command_ids(graph)
    nodes = [n for n in graph["nodes"] if n["id"] in commands and n["area"] == value]
    out = []
    for n in sorted(nodes, key=lambda n: n["id"]):
        cmd = {"id": n["id"], "mode": n["mode"], "desc": n["desc"], "usage": n["usage"]}
        aliases = sorted(e["from"].split()[-1] for e in edges
                         if e["type"] == "alias_of" and e["to"] == n["id"])
        links = [{"type": e["type"], "dir": "out", "to": e["to"]} for e in edges
                 if e["type"] != "alias_of" and e["from"] == n["id"]]
        links += [{"type": e["type"], "dir": "in", "to": e["from"]} for e in edges
                  if e["type"] != "alias_of" and e["to"] == n["id"]]
        if links:
            cmd["links"] = links
        if aliases:
            cmd["aliases"] = aliases
        if usage is not None:
            u = usage.get(n["id"]) or {}
            cmd["count"] = u.get("count", 0)
            cmd["last_used"] = u.get("last_used")
        out.append(cmd)
    return {"browse": value, "area": value, "commands": out}
