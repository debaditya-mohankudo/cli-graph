# How it works

`find_cli` is a deterministic search over a pre-generated command graph. It
has no model inside it.

## The data

- `graph/cli_graph.json` is generated from `mac`'s self-description. Each node
  is a command (`mac <area> <verb>`) with its desc, usage line and read/write
  mode.
- `graph/edges.json` is hand-written. It holds relations a description can't
  express: `feeds`, `requires`, `prefer_over` and `alias_of`.
- `graph/groups.json` assigns areas to groups, such as "communication".
- `graph/domains.json` lists, for each group, plain words that mean that
  group without naming it ("friend", "ping" mean communication). It is the
  optional domain layer, off in the server (see below).

## The call

Path: `find_cli/server.py` → `service.py` → `find()`.

The MCP tool takes `task`, `limit` (default 5), `hops` (default 2) and an
optional `area` hint. `Finder` reloads the graph when the files change and
reads usage counts on every call. `find()` itself is a pure function.

An empty `task` with an `area` skips the steps below: `browse()` returns
the area's commands (with usage, mode, edges and aliases) or, for a group,
its areas and their verb names. So the description stays an index of areas,
and verbs are read only when a task needs them. The caller-picks experiment
(`tests/pick_from_index.py`) found the area-then-verb route picks the right
command first more often than the ranker (67/77 vs 48/77), but it invents
commands when nothing fits, so search stays the way in for unclear tasks.

### 1. Seeding: BM25 ranking (`rank.py`)

Each command becomes a document made of its area, its verb split on `_`, its
desc, and the verbs of any aliases pointing at it. So "text" finds
`imessage send`. The query is tokenized and scored with these adjustments:

| Adjustment | Effect |
|---|---|
| Stopwords | Dropped. |
| Generic filler ("check", "show", "if", "any", "now") | Weighted at 0.25 instead of dropped. |
| Plural/singular forms | Count as the same term, at 0.8 weight. |
| Typo fallback | A word of 5+ letters found nowhere is matched against vocabulary words one edit away, at 0.6 weight. |
| Group and area boost | Scores above 0 are multiplied by 1.5 when the query names a group or area, or the `area` hint does. This reorders results but never admits a command the query didn't match. |
| Domain layer (optional) | With `domains` passed to `find()`, a query that uses a domain's word gets that group's boost too, unless it already names an area in that group (the area is the more specific signal). |

**The domain layer** sits between the query and the commands. The set of
domains is closed: it is exactly the groups in `graph/groups.json`.
`rank.resolve_domains` maps the query to the groups whose words it uses, and
the output reports them in a `domains` field. The layer only multiplies scores
already above 0. So a query with no domain word ranks by keywords alone,
unchanged. With `domains=None`, which is the default, the output is
byte-identical to the output without the layer. `uv run python -m graph.domains`
fails if the file names a group that doesn't exist, leaves a group with no
words, or lists a word under two groups.

The layer is off in the server. On the odd half of the eval phrases, which
was not used to write the words, top-1 stayed at 22/36 and seed hits at 34/36.
It gained only on the even half the words came from. Run
`tests/eval_find_cli.py --domains` to measure it again as the fixture grows.

### 2. Confidence (`rank.confidence`)

The result carries a `confidence` field. `coverage` is the idf-weighted share
of the query's terms that the top seed contains. `gap` is the top score minus
the runner-up's. Both low gives `level: "low"`, which means only an incidental
word matched. If nothing scored, `no_match` is true. This is advice only and
never hides a seed. Confidence is always computed without the domain layer's
boost: the layer may reorder seeds, but it never raises confidence.

### 3. Expansion (`expand.py`)

From the seeds it collects neighbours:

- **Hop 1:** commands linked to a seed by a hand-written edge, in either
  direction.
- **Hop 2:** edges again from those neighbours, then up to 3 same-area
  siblings per seed, best score first. Then up to 2 commands from other areas
  of the same group, but only ones that scored above 0.
- The total is capped at 25 ids. Alias nodes are never returned.

### 4. Output

The output has `seeds` and `neighbours`, each with usage, mode and a
count/last_used from the usage DB. The usage data never changes the ranking.
The caller then runs the chosen command through Bash. Per-verb Bash permission
rules make outbound or destructive verbs ask first.

## Measured quality

The stored eval shows the ranker at 48/77 top-1 on real hook prompts. A model
shown the whole graph index got 66/77, but it invented commands for several
no-fit phrases. So the ranker stays, because it can abstain.
