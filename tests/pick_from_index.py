"""Stand-in caller that picks a mac command from the graph index (task:4df162d0).

Measures the idea of putting the cli_graph index in find_cli's tool description so the
calling model picks the command itself, against the ranker (tests/eval_find_cli.py).

    uv run python tests/pick_from_index.py --mode full|areas [--model sonnet] [--jobs 8]
                                           [--out FILE] [--retry-errors]

full   the model sees every command as `area verb - desc`, picks up to 5.
areas  step 1 shows each area with its verb names, the model picks up to 3 areas;
       step 2 shows only those areas' commands and the model picks up to 5.

The model sees the phrase and the index only, never the expected commands. Picks are
written to --out (default tests/picks_<mode>.json); score them with `--score FILE`,
which prints top-1 / top-5 / abstention next to the ranker over the same phrases.
"""
import argparse, json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import find_cli
from tests import eval_find_cli as ev

FULL = """You pick shell commands for a user request. Below is the complete list of commands, grouped by area, one per line as `verb - description`. Each is run as `mac <area> <verb>`.

{index}

Reply with one JSON object and nothing else: {{"picks": ["<area> <verb>", ...]}}.
Best match first, at most 5, only commands that exist in the list. If no command fits the
request, reply {{"picks": []}}. Do not explain.

Request: {phrase}"""

AREAS1 = """You route a user request to areas of a command-line tool. Each line is an area followed by its verbs.

{index}

Reply with one JSON object and nothing else: {{"areas": ["<area>", ...]}}.
Most likely area first, at most 3, only areas in the list. If no area fits, reply {{"areas": []}}.
Do not explain.

Request: {phrase}"""


def commands(graph):
    return [n for n in graph["nodes"] if n.get("kind") == "command"]


def index_for(cmds, areas=None):
    by = {}
    for c in cmds:
        if areas is None or c["area"] in areas:
            by.setdefault(c["area"], []).append(c)
    return "\n".join(f"## {a}\n" + "\n".join(f"{c['verb']} - {c['desc']}" for c in cs)
                     for a, cs in sorted(by.items()))


def area_index(cmds):
    by = {}
    for c in cmds:
        by.setdefault(c["area"], []).append(c["verb"])
    return "\n".join(f"{a}: {', '.join(vs)}" for a, vs in sorted(by.items()))


def ask(prompt, model):
    p = subprocess.run(["claude", "-p", prompt, "--model", model, "--tools", "",
                        "--no-session-persistence"],
                       capture_output=True, text=True, timeout=300, cwd="/tmp")
    txt = p.stdout.strip()
    try:
        return json.loads(txt[txt.rindex("{", 0, txt.rindex("}")): txt.rindex("}") + 1]), None
    except ValueError:
        return None, (txt[:200] or p.stderr[:200] or "empty")


def pick(phrase, cmds, mode, model):
    valid = {f"{c['area']} {c['verb']}" for c in cmds}
    if mode == "areas":
        d, err = ask(AREAS1.format(index=area_index(cmds), phrase=phrase), model)
        if d is None:
            return {"picks": [], "error": err}
        areas = [a for a in d.get("areas", []) if isinstance(a, str)][:3]
        if not areas:
            return {"picks": [], "areas": []}
        index = index_for(cmds, set(areas))
    else:
        areas, index = None, index_for(cmds)
    d, err = ask(FULL.format(index=index, phrase=phrase), model)
    if d is None:
        return {"picks": [], "areas": areas, "error": err}
    picks = [p.removeprefix("mac ").strip() for p in d.get("picks", []) if isinstance(p, str)]
    out = {"picks": [p for p in picks if p in valid][:5], "invalid": [p for p in picks if p not in valid]}
    if areas is not None:
        out["areas"] = areas
    return out


def run(a):
    graph, _ = find_cli.load()
    cmds = commands(graph)
    phrases = sorted({p["phrase"] for path in (ev.FIXTURE, ev.HELDOUT) for p in ev.load_fixture(path)})
    out = Path(a.out or REPO / "tests" / f"picks_{a.mode}.json")
    prior = json.loads(out.read_text())["phrases"] if a.retry_errors and out.exists() else {}
    todo = [ph for ph in phrases if "error" in prior.get(ph, {"error": 1})]
    with ThreadPoolExecutor(a.jobs) as ex:
        done = dict(zip(todo, ex.map(lambda ph: pick(ph, cmds, a.mode, a.model), todo)))
    res = {ph: done.get(ph) or prior[ph] for ph in phrases}
    out.write_text(json.dumps({"mode": a.mode, "model": a.model, "phrases": res},
                              indent=1, ensure_ascii=False) + "\n")
    print(f"{len(phrases)} phrases, {sum('error' in r for r in res.values())} errors -> {out}")


def score_file(path):
    data = json.loads(Path(path).read_text())["phrases"]
    graph, edges = find_cli.load()
    fixture = ev.load_fixture() + ev.load_fixture(ev.HELDOUT)
    rows = ev.score(fixture, graph, edges)
    pos = [p for p in fixture if p["expect"]]
    neg = [p for p in fixture if not p["expect"]]

    def full(pk):
        return [f"mac {x}" for x in pk]
    t1 = sum(bool(data[p["phrase"]]["picks"]) and full(data[p["phrase"]]["picks"])[0] in p["expect"] for p in pos)
    t5 = sum(any(c in p["expect"] for c in full(data[p["phrase"]]["picks"])) for p in pos)
    ab = sum(not data[p["phrase"]]["picks"] for p in neg)
    errs = sum("error" in data[p["phrase"]] for p in fixture)
    r = ev.rates(rows)
    n = len(pos)
    print(f"{data and json.loads(Path(path).read_text())['mode']} picks: top-1 {t1}/{n}  top-5 {t5}/{n}  "
          f"abstain {ab}/{len(neg)}  errors {errs}")
    print(f"ranker     : top-1 {r['top1_hits']}/{n}  seed {r['seed_hits']}/{n}  "
          f"abstain {r['abstained']}/{r['negatives']}")
    for p in pos:
        pk = full(data[p["phrase"]]["picks"])
        if not any(c in p["expect"] for c in pk):
            print(f"  MISS {p['phrase']!r}\n    expect {p['expect']}\n    picked {pk}")
    for p in neg:
        if data[p["phrase"]]["picks"]:
            print(f"  FALSE-POSITIVE {p['phrase']!r} -> {full(data[p['phrase']]['picks'])}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["full", "areas"], default="full")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--out")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--retry-errors", action="store_true")
    ap.add_argument("--score", metavar="FILE")
    a = ap.parse_args()
    score_file(a.score) if a.score else run(a)


if __name__ == "__main__":
    main()
