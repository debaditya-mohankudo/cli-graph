"""find_cli: map a task phrase to a small subgraph of `mac` commands (task:129f1bc3).

    find(task, graph, edges)  ->  {query, seeds, neighbours}

seeds       [{id, score, mode, desc, usage}]  BM25 hits, best first
neighbours  [{id, via, dir, from, hop, mode, desc, usage}]  reached from a seed
            via a hand-written edge (dir "out"/"in") or as an area sibling
            (via "in_domain", dir "sibling")

With a usage map, each seed and neighbour also carries count and last_used.

It reads only the committed graph/cli_graph.json and graph/edges.json, never a
live CLI, and every id it returns is a command node of that graph. The output
is a pure function of its inputs; server.py only loads the files once and
calls find(). The eval (task:597ac09d) can import this module directly with no
MCP dependency.
"""
import json

from graph.generate import GRAPH
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


def find(task, graph, edges=(), limit=DEFAULT_LIMIT, hops=2, usage=None):
    """Seeds and neighbours for task. See the module docstring for the shape.

    usage ({id: {"count", "last_used"}}, see find_cli.usage) is passed in by
    the caller, so find() stays a pure function of its arguments. When given,
    every returned command gets count and last_used (0 / None if it has no
    row); it never changes ranking or order. When None, the output is
    exactly what it was without usage.
    """
    commands = command_ids(graph)
    nodes = {n["id"]: n for n in graph["nodes"] if n["id"] in commands}
    scores = _rank.scores(task, _rank.documents(graph, edges))
    seed_pairs = [(cid, s) for cid, s in _rank.seeds(task, graph, edges, limit)
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

    return {
        "query": task,
        "seeds": [{"id": cid, "score": s, **info(cid)} for cid, s in seed_pairs],
        "neighbours": [{**nb, **info(nb["id"])} for nb in neighbours],
    }
