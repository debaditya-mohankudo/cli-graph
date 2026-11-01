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

## The call

Path: `find_cli/server.py` → `service.py` → `find()`.

The MCP tool takes `task`, `limit` (default 5), `hops` (default 2) and an
optional `area` hint. `Finder` reloads the graph when the files change and
reads usage counts on every call. `find()` itself is a pure function.

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

### 2. Confidence (`rank.confidence`)

The result carries a `confidence` field. `coverage` is the idf-weighted share
of the query's terms that the top seed contains. `gap` is the top score minus
the runner-up's. Both low gives `level: "low"`, which means only an incidental
word matched. If nothing scored, `no_match` is true. This is advice only and
never hides a seed.

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
