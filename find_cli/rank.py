"""BM25 seeding over the command graph (task:129f1bc3).

Pure functions of (query, graph, edges): no I/O, no randomness, no set
iteration in anything that reaches the output, so the same input gives the
same ranking in any process.

Each command's document is its area and verb split on '_' plus its desc, plus
the verb of every alias_of edge that names it (so `mac imessage text` aliasing
`mac imessage send` lets "text" find send). The alias itself is never ranked:
it is not a node.

Two query-side adjustments (task:2dcdba79); documents are indexed unchanged:
  - GENERIC words ("check", "if", ...) are task filler in a request but rare in
    command text, so plain BM25 gave them a high idf and let them pick the
    seed. They score at GENERIC_WEIGHT instead of being dropped, so a command
    whose own text uses them still gets some credit.
  - A query word also matches its plural/singular (forms()). The word and its
    forms count as one term: one df, with a non-exact form adding
    VARIANT_WEIGHT to tf, so an exact match still beats a folded one.
"""
import math
import re

K1 = 1.5
B = 0.75

STOPWORDS = frozenset(
    "a an and are as at be by for from i in into is it me my of on or the "
    "this to with".split())

# "get" is not here: it is the verb of commands like get_upcoming_events.
GENERIC = frozenset("check if any now show shows".split())
GENERIC_WEIGHT = 0.25
VARIANT_WEIGHT = 0.8


def tokens(text):
    """Lowercase alphanumeric words of text, '_' splitting, stopwords dropped."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in STOPWORDS]


def forms(term):
    """term first, then the other forms it matches: term+'s', and term without
    a trailing 's' when longer than 4 letters and not '-ss' (so 'news' stays
    'news' and 'class' stays 'class')."""
    out = [term, term + "s"]
    if len(term) > 4 and term.endswith("s") and not term.endswith("ss"):
        out.append(term[:-1])
    return out


def documents(graph, edges=()):
    """{command id: token list}, in sorted id order."""
    commands = {n["id"]: n for n in graph["nodes"] if n["kind"] == "command"}
    extra = {}
    for e in edges:
        if e["type"] == "alias_of" and e["to"] in commands:
            extra.setdefault(e["to"], []).append(e["from"].rsplit(" ", 1)[-1])
    docs = {}
    for cid in sorted(commands):
        n = commands[cid]
        text = " ".join([n["area"], n["verb"], n["desc"], *sorted(extra.get(cid, []))])
        docs[cid] = tokens(text)
    return docs


def scores(query, docs):
    """{command id: BM25 score} for every document, rounded to 3 places."""
    terms = list(dict.fromkeys(tokens(query)))
    n = len(docs)
    avgdl = sum(len(d) for d in docs.values()) / n if n else 0.0
    tforms = {t: forms(t) for t in terms}
    df = {t: sum(1 for d in docs.values() if any(f in d for f in tforms[t])) for t in terms}
    out = {}
    for cid, doc in docs.items():
        dl = len(doc)
        s = 0.0
        for t in terms:
            tf = doc.count(t) + VARIANT_WEIGHT * sum(doc.count(f) for f in tforms[t][1:])
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            w = GENERIC_WEIGHT if t in GENERIC else 1.0
            s += w * idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / avgdl))
        out[cid] = round(s, 3)
    return out


def ordered(score_map):
    """Ids by score descending, then id ascending."""
    return sorted(score_map, key=lambda cid: (-score_map[cid], cid))


def seeds(query, graph, edges=(), limit=5):
    """The top `limit` commands with a positive score, as (id, score) pairs."""
    s = scores(query, documents(graph, edges))
    return [(cid, s[cid]) for cid in ordered(s) if s[cid] > 0][:max(limit, 0)]
