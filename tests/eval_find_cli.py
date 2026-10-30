"""Hit-rate eval for find_cli over tests/eval_phrases.json (task:597ac09d).

    uv run python tests/eval_find_cli.py [--threshold 0.9] [--seed-threshold 0.84]
                                         [--limit 5] [--hops 2]

A phrase is a hit when any of its expected commands is in the returned
subgraph (seeds or neighbours); a seed hit when one is among the seeds. Both
rates are printed, then every miss with the subgraph find_cli returned. A
phrase whose expect is [] says no command covers the task: it is scored as an
abstention (correct when find_cli returns no seeds, or no_match), and left out
of the hit rates.

The tuning set (eval_phrases.json) is what the ranker is tuned on and gated.
The held-out set (eval_heldout.json, task:9d42faae) is real logged queries,
never tuned on; it is printed after the tuning set and never changes the exit
code, since a handful of phrases moves its rate too far per phrase to gate on.

A confident wrong answer (task:e720fe9a) is a phrase find_cli answers at high
confidence with none of the expected commands among the seeds; for a negative,
any seed at high confidence. Both sets list them with the wrong top command and
its score; only the tuning set's count is gated, against CONFIDENT_WRONG_CEILING.

Exit codes: 0 when the tuning set's subgraph hit rate is at least --threshold,
its seed hit rate at least --seed-threshold and its confident-wrong count at
most the ceiling, 1 when any is breached, 2 when
either fixture names a command that is not in the committed graph (the fixture
is stale, so no rate is computed).

Not named test_*.py, so unittest discovery does not run it; tests/test_eval_fixture.py
keeps the fixtures valid against the graph.
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
HELDOUT = REPO / "tests" / "eval_heldout.json"
THRESHOLD = 0.9
# A ratchet at the current 53/63: raise it when seed hits rise, never lower it.
SEED_THRESHOLD = 0.84
# A ratchet at the current 7 (1 negative + 6 positives): lower it when a
# confident wrong answer is fixed, never raise it (task:e720fe9a).
CONFIDENT_WRONG_CEILING = 7


def load_fixture(path=FIXTURE):
    with open(path) as f:
        return json.load(f)["phrases"]


def unknown_ids(phrases, graph):
    """Expected ids that are not command nodes, as (phrase, id) pairs."""
    commands = command_ids(graph)
    return [(p["phrase"], cid) for p in phrases for cid in p["expect"] if cid not in commands]


def score(phrases, graph, edges, limit=find_cli.DEFAULT_LIMIT, hops=2):
    """One result row per phrase: {phrase, expect, hit, seed_hit, rank, abstained, result}.

    rank is the 1-based seed position of the best-placed expected id, or None.
    abstained is true when find_cli returned no seeds (or said no_match); it is
    the right answer only for a phrase whose expect is [].
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
            "abstained": bool(r.get("no_match")) or not seeds,
            "low": r["confidence"]["level"] != "high",
            "result": r,
        })
    return rows


def rates(rows):
    """{n, hits, seed_hits, subgraph_rate, seed_rate, negatives, abstained} for scored rows.

    Rates are over phrases that expect a command; None when there are none.
    """
    pos = [r for r in rows if r["expect"]]
    neg = [r for r in rows if not r["expect"]]
    n = len(pos)
    hits = sum(r["hit"] for r in pos)
    seed_hits = sum(r["seed_hit"] for r in pos)
    return {
        "n": n, "hits": hits, "seed_hits": seed_hits,
        "subgraph_rate": hits / n if n else None,
        "seed_rate": seed_hits / n if n else None,
        "negatives": len(neg), "abstained": sum(r["abstained"] for r in neg),
        # confidence calibration (task:d08ebd55): low should land on misses, not hits
        "top1_hits": sum(r["rank"] == 1 for r in pos),
        "low_top1_hits": sum(r["low"] and r["rank"] == 1 for r in pos),
        "low_top1_misses": sum(r["low"] and r["rank"] != 1 for r in pos),
        "low_negatives": sum(r["low"] for r in neg),
        "confident_wrong": len(confident_wrong(rows)),
    }


def confident_wrong(rows):
    """Rows find_cli answered at high confidence without any expected command in the seeds.

    A negative counts when it returned any seed at high confidence. Rank 2-5
    hits are not counted: the agent still sees the expected command.
    """
    return [r for r in rows
            if not r["low"] and (r["result"]["seeds"] if not r["expect"] else not r["rank"])]


def _mark(r):
    if not r["expect"]:
        return "abstain" if r["abstained"] else "MISS"
    return "seed#%d" % r["rank"] if r["rank"] else ("nbr" if r["hit"] else "MISS")


def report(rows, out=None):
    """Print rates, one line per phrase, then each miss in detail. Returns rates(rows)."""
    out = out or sys.stdout
    s = rates(rows)
    n = s["n"]
    if n:
        print(f"subgraph hit rate  {s['hits']}/{n} = {s['subgraph_rate']:.0%}", file=out)
        print(f"seed hit rate      {s['seed_hits']}/{n} = {s['seed_rate']:.0%}", file=out)
    if s["negatives"]:
        print(f"abstention         {s['abstained']}/{s['negatives']} phrases with no fitting command",
              file=out)
    if n:
        misses = n - s["top1_hits"]
        print(f"low confidence     {s['low_top1_hits']}/{s['top1_hits']} top-1 hits, "
              f"{s['low_top1_misses']}/{misses} top-1 misses"
              + (f", {s['low_negatives']}/{s['negatives']} negatives" if s["negatives"] else ""),
              file=out)
    for r in rows:
        print(f"  {_mark(r):7} {'low ' if r['low'] else 'high'} {r['phrase']}", file=out)
    wrong = confident_wrong(rows)
    print(f"confident wrong    {len(wrong)}", file=out)
    for r in wrong:
        top = r["result"]["seeds"][0] if r["result"]["seeds"] else None
        print(f"  {r['phrase']!r} -> {top['id']}  {top['score']}" if top
              else f"  {r['phrase']!r} -> (no seeds)", file=out)
    for r in rows:
        if _mark(r) != "MISS":
            continue
        res = r["result"]
        expected = ", ".join(r["expect"]) or "(no command: should abstain)"
        print(f"\nMISS {r['phrase']!r}\n  expected  {expected}", file=out)
        if not res["seeds"]:
            print("  (empty subgraph: no command scored above 0)", file=out)
        for sd in res["seeds"]:
            print(f"  seed      {sd['id']}  {sd['score']}", file=out)
        for nb in res["neighbours"]:
            print(f"  nbr       {nb['id']}  via {nb['via']} from {nb['from']}", file=out)
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    ap.add_argument("--seed-threshold", type=float, default=SEED_THRESHOLD)
    ap.add_argument("--confident-wrong-ceiling", type=int, default=CONFIDENT_WRONG_CEILING)
    ap.add_argument("--limit", type=int, default=find_cli.DEFAULT_LIMIT)
    ap.add_argument("--hops", type=int, default=2)
    args = ap.parse_args(argv)

    graph, edges = find_cli.load()
    phrases = load_fixture()
    heldout = load_fixture(HELDOUT) if HELDOUT.exists() else []
    bad = unknown_ids(phrases + heldout, graph)
    if bad:
        for phrase, cid in bad:
            print(f"fixture names {cid!r} (for {phrase!r}), not a command in the graph",
                  file=sys.stderr)
        return 2
    s = report(score(phrases, graph, edges, args.limit, args.hops))
    if heldout:
        print("\n== held-out: logged real queries, never tuned on, reported not gated ==")
        report(score(heldout, graph, edges, args.limit, args.hops))
    ok = (s["subgraph_rate"] >= args.threshold and s["seed_rate"] >= args.seed_threshold
          and s["confident_wrong"] <= args.confident_wrong_ceiling)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
