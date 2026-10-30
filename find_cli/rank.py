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
  - A long query word found in no document in any form is tried as a typo:
    vocabulary words one edit away join its forms at FUZZY_WEIGHT (fuzzy()).
    Short words never fuzz; "msg" and "txt" are alias_of words instead.

Group boost: a query word that names an area group (graph/groups.json, e.g.
"communication") multiplies the score of that group's commands by
GROUP_BOOST. Only scores already above 0 are boosted, so the group word
reorders matches but never admits a command the rest of the query missed.
Group names are not added to documents.

Area boost (task:fcaad255): the same multiplier for the commands of an area the
query names (every token of the area name appears, e.g. "vault" or "notes") and
for an area or group the caller's hint names. The hint is plain input resolved
by string match; an unknown one is reported by hint_info(), never applied.
"""
import math
import re

from graph.groups import command_groups

K1 = 1.5
B = 0.75

STOPWORDS = frozenset(
    "a an and are as at be by for from i in into is it me my of on or the "
    "this to with".split())

# "get" is not here: it is the verb of commands like get_upcoming_events.
GENERIC = frozenset("check if any now show shows".split())
GENERIC_WEIGHT = 0.25
VARIANT_WEIGHT = 0.8
# Typo fallback (task:82640303): a query word of FUZZY_MIN_LEN+ letters that has
# no exact or plural/singular form in the vocabulary matches vocabulary words
# one edit away, at FUZZY_WEIGHT (below VARIANT_WEIGHT, so never above exact).
FUZZY_MIN_LEN = 5
FUZZY_WEIGHT = 0.6
GROUP_BOOST = 1.5
# confidence() thresholds, measured on the eval (task:d08ebd55).
LOW_COVERAGE = 0.3
LOW_GAP = 0.5


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


def one_edit(a, b):
    """True when a and b differ by exactly one insertion, deletion, substitution
    or adjacent swap."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:] or (a[i] == b[i + 1] and a[i + 1] == b[i]
                                          and a[i + 2:] == b[i + 2:])
    short, long_ = sorted((a, b), key=len)
    return short[i:] == long_[i + 1:]


def fuzzy(term, docs):
    """Sorted vocabulary words one edit from term; [] unless term is
    FUZZY_MIN_LEN+ letters and no form of it occurs in any document."""
    if len(term) < FUZZY_MIN_LEN:
        return []
    vocab = {w for d in docs.values() for w in d}
    if any(f in vocab for f in forms(term)):
        return []
    return sorted(w for w in vocab if one_edit(term, w))


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


def norm_hint(hint):
    """A hint as a lowercase area/group name: 'Code-RAG ' -> 'code_rag'."""
    return re.sub(r"[\s-]+", "_", (hint or "").strip().lower())


def hint_info(hint, graph):
    """{value, known, valid} for a caller's hint; valid is the sorted areas and
    group names it can be. known is false when hint matches neither."""
    valid = sorted(set(graph["domains"]) | {d["group"] for d in graph["domains"].values()
                                            if d["group"]})
    value = norm_hint(hint)
    return {"value": value, "known": value in valid, "valid": valid}


def scores(query, docs, groups=None, hint=None):
    """{command id: BM25 score} for every document, rounded to 3 places.

    groups ({command id: group name}, see graph.groups.command_groups) turns
    on the group boost: a query word naming a group multiplies the positive
    scores of that group's commands by GROUP_BOOST. The same factor applies once
    to a command whose area the query names or whose area or group the hint
    names (hint, see norm_hint).
    """
    hint = norm_hint(hint)
    terms = list(dict.fromkeys(tokens(query)))
    named = {g for g in set((groups or {}).values())
             if hint == g or any(g in forms(t) or t in forms(g) for t in terms)}
    areas = {a for a in {c.split()[1] for c in docs}
             if hint == a or all(any(w in forms(t) or t in forms(w) for t in terms)
                                 for w in tokens(a))}
    n = len(docs)
    avgdl = sum(len(d) for d in docs.values()) / n if n else 0.0
    tforms = {t: forms(t) for t in terms}
    typos = {t: fuzzy(t, docs) for t in terms}
    df = {t: sum(1 for d in docs.values() if any(f in d for f in tforms[t] + typos[t]))
          for t in terms}
    out = {}
    for cid, doc in docs.items():
        dl = len(doc)
        s = 0.0
        for t in terms:
            tf = (doc.count(t) + VARIANT_WEIGHT * sum(doc.count(f) for f in tforms[t][1:])
                  + FUZZY_WEIGHT * sum(doc.count(f) for f in typos[t]))
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            w = GENERIC_WEIGHT if t in GENERIC else 1.0
            s += w * idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / avgdl))
        if s and ((groups and groups.get(cid) in named) or cid.split()[1] in areas):
            s *= GROUP_BOOST
        out[cid] = round(s, 3)
    return out


def confidence(query, docs, score_map):
    """{level, coverage, gap} for the top seed of score_map (task:d08ebd55).

    coverage is the idf-weighted share of the query's non-GENERIC terms that
    the top seed's document contains (any form); gap is the top score minus
    the runner-up's. level is "none" when nothing scored, "low" when coverage
    < LOW_COVERAGE and gap < LOW_GAP (one incidental word matched and nothing
    stands out), else "high". It is advice only: it never removes a seed.
    """
    order = [c for c in ordered(score_map) if score_map[c] > 0]
    if not order:
        return {"level": "none", "coverage": 0.0, "gap": 0.0}
    top = docs[order[0]]
    n = len(docs)
    weights = {}
    for t in dict.fromkeys(tokens(query)):
        if t in GENERIC:
            continue
        fs = forms(t) + fuzzy(t, docs)
        df = sum(1 for d in docs.values() if any(f in d for f in fs))
        weights[t] = math.log(1 + (n - df + 0.5) / (df + 0.5))
    total = sum(weights.values())
    covered = sum(w for t, w in weights.items() if any(f in top for f in forms(t) + fuzzy(t, docs)))
    coverage = round(covered / total, 3) if total else 0.0
    gap = round(score_map[order[0]] - (score_map[order[1]] if len(order) > 1 else 0.0), 3)
    level = "low" if coverage < LOW_COVERAGE and gap < LOW_GAP else "high"
    return {"level": level, "coverage": coverage, "gap": gap}


def ordered(score_map):
    """Ids by score descending, then id ascending."""
    return sorted(score_map, key=lambda cid: (-score_map[cid], cid))


def seeds(query, graph, edges=(), limit=5, hint=None):
    """The top `limit` commands with a positive score, as (id, score) pairs.

    With a hint the list is reordered by the boost, but the best seed without
    the hint always stays: if the boost pushed it out, it takes the last slot.
    """
    docs = documents(graph, edges)
    groups = command_groups(graph)
    s = scores(query, docs, groups, hint)
    out = [(cid, s[cid]) for cid in ordered(s) if s[cid] > 0][:max(limit, 0)]
    if norm_hint(hint) and out:
        plain = scores(query, docs, groups)
        best = ordered(plain)[0]
        if plain[best] > 0 and best not in [c for c, _ in out]:
            out[-1] = (best, s[best])
    return out
