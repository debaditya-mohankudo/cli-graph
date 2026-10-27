"""Edge expansion from seed commands (task:129f1bc3).

A pure function of (seeds, graph, edges, scores). Order is fixed by the input
lists and explicit sorts, never by set or dict-of-set iteration, so output is
identical across processes.

    hop 1  hand-written edges (feeds, requires, prefer_over) touching a seed,
           in either direction
    hop 2  the same edges again from each hop-1 neighbour, then at most
           SIBLINGS commands of each seed's area (the cmd -> domain -> cmd
           path), best score first, then id, then at most GROUP_SIBLINGS
           commands from the seed's other areas in the same group
           (graph/groups.json; cmd -> domain -> group -> domain -> cmd),
           best score first, then id. Only commands that scored above 0 are
           taken, so a group never adds a verb the query did not touch;
           without scores no group neighbours are added.

alias_of edges are not followed: their `from` is not a node. Every id is
checked against the graph's command nodes, and the whole result is capped at
MAX_NODES ids (seeds included) so a broad area never floods the answer.
"""
from graph.groups import command_groups
from graph.validate_edges import command_ids

FOLLOW = ("feeds", "requires", "prefer_over")
SIBLINGS = 3
GROUP_SIBLINGS = 2
MAX_NODES = 25


def adjacency(edges, commands):
    """{id: [(neighbour, type, dir)]}, each list sorted, for followable edges."""
    adj = {}
    for e in edges:
        src, kind, dst = e["from"], e["type"], e["to"]
        if kind not in FOLLOW or src not in commands or dst not in commands:
            continue
        adj.setdefault(src, []).append((dst, kind, "out"))
        adj.setdefault(dst, []).append((src, kind, "in"))
    return {k: sorted(v) for k, v in adj.items()}


def expand(seed_ids, graph, edges=(), scores=None, hops=2,
           siblings=SIBLINGS, max_nodes=MAX_NODES, group_siblings=GROUP_SIBLINGS):
    """Neighbours of seed_ids as dicts {id, via, dir, from, hop}, in output order.

    seed_ids is ranked best first. scores ({id: score}) orders area siblings;
    without it siblings come in id order. Seeds never appear as neighbours.
    """
    commands = command_ids(graph)
    seed_ids = [s for s in seed_ids if s in commands]
    scores = scores or {}
    adj = adjacency(edges, commands)
    seen = list(seed_ids)
    out = []

    def add(cid, via, direction, origin, hop):
        if cid in commands and cid not in seen and len(seen) < max_nodes:
            seen.append(cid)
            out.append({"id": cid, "via": via, "dir": direction, "from": origin, "hop": hop})

    frontier = seed_ids
    for hop in range(1, min(hops, 2) + 1):
        start = len(out)
        for origin in frontier:
            for cid, via, direction in adj.get(origin, []):
                add(cid, via, direction, origin, hop)
        frontier = [n["id"] for n in out[start:]]

    if hops >= 2 and siblings > 0:
        area = {n["id"]: n["area"] for n in graph["nodes"] if n["kind"] == "command"}
        for origin in seed_ids:
            same = [c for c in sorted(commands) if area[c] == area[origin] and c != origin]
            same.sort(key=lambda c: (-scores.get(c, 0.0), c))
            taken = 0
            for cid in same:
                if taken == siblings:
                    break
                if cid not in seen:
                    add(cid, "in_domain", "sibling", origin, 2)
                    taken += 1

    if hops >= 2 and group_siblings > 0:
        group = command_groups(graph)
        area = {n["id"]: n["area"] for n in graph["nodes"] if n["kind"] == "command"}
        for origin in seed_ids:
            g = group.get(origin)
            if g is None:
                continue
            near = [c for c in sorted(commands) if group.get(c) == g
                    and area[c] != area[origin] and scores.get(c, 0.0) > 0]
            near.sort(key=lambda c: (-scores[c], c))
            taken = 0
            for cid in near:
                if taken == group_siblings:
                    break
                if cid not in seen:
                    add(cid, "in_group", "group", origin, 2)
                    taken += 1
    return out
