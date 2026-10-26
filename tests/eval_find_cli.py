"""Hit-rate eval for find_cli over tests/eval_phrases.json (task:597ac09d).

    python3 tests/eval_find_cli.py [--threshold 0.9] [--limit 5] [--hops 2]

A phrase is a hit when any of its expected commands is in the returned
subgraph (seeds or neighbours); a seed hit when one is among the seeds. Both
rates are printed, then every miss with the subgraph find_cli returned.

Exit codes: 0 when the subgraph hit rate is at least the threshold, 1 below
it, 2 when the fixture names a command that is not in the committed graph
(the fixture is stale, so no rate is computed).

Not named test_*.py, so unittest discovery does not run it; tests/test_eval_fixture.py
keeps the fixture valid against the graph.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import find_cli
from graph.validate_edges import command_ids

FIXTURE = REPO / "tests" / "eval_phrases.json"
THRESHOLD = 0.9


def load_fixture(path=FIXTURE):
    with open(path) as f:
        return json.load(f)["phrases"]


def unknown_ids(phrases, graph):
    """Expected ids that are not command nodes, as (phrase, id) pairs."""
    commands = command_ids(graph)
    return [(p["phrase"], cid) for p in phrases for cid in p["expect"] if cid not in commands]


def score(phrases, graph, edges, limit=find_cli.DEFAULT_LIMIT, hops=2):
    """One result row per phrase: {phrase, expect, hit, seed_hit, rank, result}.

    rank is the 1-based seed position of the best-placed expected id, or None.
    """
    rows = []
    for p in phrases:
        r = find_cli.find(p["phrase"], graph, edges, limit=limit, hops=hops)
        seeds = [s["id"] for s in r["seeds"]]
        ids = seeds + [n["id"] for n in r["neighbours"]]
        ranks = [seeds.index(c) + 1 for c in p["expect"] if c in seeds]
        rows.append({
            "phrase": p["phrase"],
            "expect": p["expect"],
            "hit": any(c in ids for c in p["expect"]),
            "seed_hit": bool(ranks),
            "rank": min(ranks) if ranks else None,
            "result": r,
        })
    return rows


def report(rows, out=None):
    out = out or sys.stdout
    n = len(rows)
    hits = sum(r["hit"] for r in rows)
    seed_hits = sum(r["seed_hit"] for r in rows)
    print(f"subgraph hit rate  {hits}/{n} = {hits / n:.0%}", file=out)
    print(f"seed hit rate      {seed_hits}/{n} = {seed_hits / n:.0%}", file=out)
    for r in rows:
        mark = "seed#%d" % r["rank"] if r["rank"] else ("nbr" if r["hit"] else "MISS")
        print(f"  {mark:7} {r['phrase']}", file=out)
    misses = [r for r in rows if not r["hit"]]
    for r in misses:
        res = r["result"]
        print(f"\nMISS {r['phrase']!r}\n  expected  {', '.join(r['expect'])}", file=out)
        if not res["seeds"]:
            print("  (empty subgraph: no command scored above 0)", file=out)
        for s in res["seeds"]:
            print(f"  seed      {s['id']}  {s['score']}", file=out)
        for nb in res["neighbours"]:
            print(f"  nbr       {nb['id']}  via {nb['via']} from {nb['from']}", file=out)
    return hits / n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--limit", type=int, default=find_cli.DEFAULT_LIMIT)
    ap.add_argument("--hops", type=int, default=2)
    args = ap.parse_args(argv)

    graph, edges = find_cli.load()
    phrases = load_fixture()
    bad = unknown_ids(phrases, graph)
    if bad:
        for phrase, cid in bad:
            print(f"fixture names {cid!r} (for {phrase!r}), not a command in the graph",
                  file=sys.stderr)
        return 2
    rate = report(score(phrases, graph, edges, args.limit, args.hops))
    return 0 if rate >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
