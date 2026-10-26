"""BM25 seeding over the command graph (task:129f1bc3).

Pure functions of (query, graph, edges): no I/O, no randomness, no set
iteration in anything that reaches the output, so the same input gives the
same ranking in any process.

Each command's document is its area and verb split on '_' plus its desc, plus
the verb of every alias_of edge that names it (so `mac imessage text` aliasing
`mac imessage send` lets "text" find send). The alias itself is never ranked:
it is not a node.
"""
import math
import re

K1 = 1.5
B = 0.75

STOPWORDS = frozenset(
    "a an and are as at be by for from i in into is it me my of on or the "
    "this to with".split())


def tokens(text):
    """Lowercase alphanumeric words of text, '_' splitting, stopwords dropped."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in STOPWORDS]


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
    df = {t: sum(1 for d in docs.values() if t in d) for t in terms}
    out = {}
    for cid, doc in docs.items():
        dl = len(doc)
        s = 0.0
        for t in terms:
            tf = doc.count(t)
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / avgdl))
        out[cid] = round(s, 3)
    return out


def ordered(score_map):
    """Ids by score descending, then id ascending."""
    return sorted(score_map, key=lambda cid: (-score_map[cid], cid))


def seeds(query, graph, edges=(), limit=5):
    """The top `limit` commands with a positive score, as (id, score) pairs."""
    s = scores(query, documents(graph, edges))
    return [(cid, s[cid]) for cid in ordered(s) if s[cid] > 0][:max(limit, 0)]
