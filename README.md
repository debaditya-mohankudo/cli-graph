# cli-graph

A `mac` command-line tool and a single `find_cli` MCP tool. Together they
replace the ~300 per-tool MCP schemas that local-mac, astrology-mcp,
stock-tracker-mcp and sysml-mcp used to load into every Claude session.

Today the agent calls a single tool, `find_cli("what I want to do")`. It
returns the few `mac` commands that fit, each with its usage line. The agent
then runs the chosen command through Bash:

```bash
mac reminders list --list market-watch-reminders --json
mac safari read text --expect-host nseindia.com
mac calendar add_event --calendar market-watch --notes "..." "RBI policy" 2026-12-05T10:00:00
```

The handlers are not rewritten: `mac` calls the existing MCP implementations,
so a CLI call and an MCP call share one code path.

## Layout

| Path | What it is |
|---|---|
| `bin/mac` | Launcher. Runs `python -m mac` under this repo's uv `.venv` (`~/bin/mac` is a symlink to it). |
| `mac/` | The dispatcher: argument parsing, help, the output/error contract (`contract.py`), and one module per area under `mac/groups/`. |
| `mac/groups/_backend.py` | Runs local-mac's handlers in-process through its own `dispatcher.resolve` / `invoke`, so the same logging and safety gates apply. |
| `mac/groups/_hooks.py` | Runs claude-hooks' `src/tools` handlers (`memory`, `vault_map`, `hooks`, `code_rag`, `diff_rag`) in a subprocess of claude-hooks' own interpreter, via `_hooks_runner.py`. No MCP server and no Ollama start-up; about 0.3s a call (`code_rag`/`diff_rag`: about 1.4s, the llama_index import). |
| `mac/groups/_mcp_proxy.py` | Starts a separate MCP server over stdio for each call (`astrology`, `wyckoff`, `sysml`). These servers have their own venvs or are Node bundles. |
| `graph/cli_graph.json` | Command graph **generated** from `mac --help --json`: a `groups` and a `domains` overview first, then one node per command. Never hand-edited. |
| `graph/edges.json` | Hand-written edges between commands: `alias_of`, `requires`, `feeds`, `prefer_over`. |
| `graph/groups.json` | Hand-written groups of areas (communication, productivity, ...). `graph/generate.py` adds them to the graph's `groups` and `domains` sections. |
| `find_cli/` | The MCP server (`server.py`): BM25 ranking (`rank.py`), edge and sibling expansion (`expand.py`), usage counts (`usage.py`). |
| `tools/` | Generators: `gen_groups.py` (local-mac group modules), `gen_mcp_groups.py` (proxy group modules), `gen_permissions.py` (Claude Code permission rules). `cutover.py` turns the migrated MCP servers off or back on (one backup per cutover; pass `299daf58` for the claude-hooks one). |
| `tests/` | Unit, drift and parity tests, plus the `find_cli` hit-rate eval. |
| `concept_store/concepts.json` | Architectural notes and invariants for the repo. |

## The `mac` CLI

```
mac <area> <verb> [options]
mac --help                 # areas and verb counts
mac <area> --help          # verbs, read/write mode, usage lines
mac --help --json          # every command as JSON rows (feeds graph/generate.py)
```

There are about 204 verbs across 26 areas: `astrology`, `calendar`, `code_rag`, `connector`, `contacts`,
`diff_rag`, `git`, `hooks`, `imessage`, `mail`, `market`, `memory`, `music`, `notes`, `podcasts`, `reminders`,
`safari`, `sound`, `sysml`, `system`, `time`, `vault`, `vault_map`, `vault_rag`, `vpn`,
`wyckoff`. `memory`, `vault_map` and `hooks` wrap claude-hooks; `memory add` takes
`--links` as a JSON list and `--body-file -` for long text. `scratch` and `think`
were not ported (task:5ab623ca). `git` runs `git` directly: `add` takes explicit paths only,
`commit` takes the staged files (or only the paths listed) and refuses a message without a
`task:<id>`, and `commit` and `push` ask before running (task:fcc92c98).

**Contract.** Results go to stdout as JSON. Failures go to stderr as
`{"error": {"code": ..., "message": ...}}`, with exit code 1, or 2 for usage
errors. List results are capped at 100 items unless `--limit` is given; a
truncated result says how many were shown out of the total. Error codes
include `usage`, `unknown_verb`, `tool_error`, `blocked` (a safety gate
refused the call) and `backend_missing`.

**Gates carry over.** `imessage send` needs a recent `contacts search` and
`mail delete` needs a recent `mail read`, exactly as with the MCP tools.
Both gates read local-mac's persisted call log, so they hold even though
each `mac` call is a separate process. `safari` verbs that act on the front
tab need `--expect-host`, so a command can't act on a tab you didn't open.

**Dates.** Date arguments take `YYYY-MM-DD`. Date-time arguments take ISO-8601
with a `T` separator (`2026-10-27T15:00:00`); a space-separated value is
rejected.

## `find_cli`

```python
find_cli(task: str, limit: int = 5, hops: int = 2) -> dict
```

It returns `seeds`, the best BM25 matches for the task, and `neighbours`.
Each entry has the command id, `desc`, `usage` line, `mode` (read/write) and
a usage record: run count and `last_used`. The usage records come read-only
from claude-hooks' `~/.claude/tool_hints.sqlite`; set `FIND_CLI_USAGE_DB` to
override the path.

- **hops 0**: seeds only.

- **hops 1**: adds commands linked to a seed by a `feeds`, `requires` or
  `prefer_over` edge.

- **hops 2**: follows those edges once more, then adds up to 3 other commands
  from each seed's area, then up to 2 matching commands from the other areas
  in the seed's group.

**Groups.** `graph/groups.json` gathers related areas into groups:

| Group | Areas |
|---|---|
| astrology | astrology |
| communication | contacts, imessage, mail |
| development | git |
| productivity | calendar, notes, reminders, time |
| knowledge | code_rag, diff_rag, memory, sysml, vault, vault_map, vault_rag |
| media | music, podcasts, sound |
| markets | market, wyckoff |
| system | hooks, system, vpn |
| web | connector, safari |

Every area has to be listed once, either in
a group or under `ungrouped`, so a new area can't be left out by accident. A
query word that names a group ("communication") ranks that group's matching
commands higher. Neither the boost nor the group neighbours can add a
command the rest of the query didn't match.

The result is capped at 25 commands and only names commands that exist in
the graph. The `alias_of` edges add their alias words to the target's search
terms: for example, "text" helps find `imessage send`. The ranking is
deterministic, and no LLM runs inside it.

Run the server:

```bash
uv run --directory ~/workspace/cli-graph python -m find_cli.server
```

## Setup and tests

The repo needs Python 3.12 and [uv](https://docs.astral.sh/uv/). local-mac is
a path dependency (`../claude_for_mac_local`), so check it out next to this
repo.

```bash
uv sync
uv run python -m unittest discover -s tests   # whole suite
uv run python tests/eval_find_cli.py          # find_cli hit-rate eval (90% subgraph + 84% seed gate)
uv run python -m graph.generate --check       # graph drift check
```

The eval gates the tuning set, `tests/eval_phrases.json`, on its subgraph
and seed hit rates. It then prints `tests/eval_heldout.json` on its own:
real queries from the claude-hooks `find_cli_queries` log, checked by hand
for personal data before they're copied in. That set is never used for
tuning and never changes the exit code. A phrase with `expect: []` means no
command fits, and it counts as correct only when `find_cli` returns no seeds.

Run everything through `uv run`. Plain `python3` lacks pydantic, so the
parity modules fail to import. Live parity tests, which really call the
handlers, are skipped unless `MAC_PARITY_LIVE=1` is set.

Environment overrides:

| Variable | Effect |
|---|---|
| `MAC_PYTHON` | Interpreter `bin/mac` uses instead of `.venv/bin/python`. |
| `MAC_MCP_SRC` | local-mac source tree (default `~/workspace/claude_for_mac_local/src`). |
| `FIND_CLI_USAGE_DB` | Usage-count database `find_cli` reads. |

## Keeping things in sync

Most of the repo is generated. When something changes, rerun its generator.
Each has a test that fails while its output is out of date.

| When this changes | Run | Guarded by |
|---|---|---|
| A local-mac handler signature | `~/workspace/claude_for_mac_local/.venv/bin/python tools/gen_groups.py` | parity tests |
| A proxied server's tools (`astrology`, `wyckoff`, `sysml`) | `uv run python tools/gen_mcp_groups.py` | `tests/test_parity_mcp_servers.py` |
| Any verb added or removed | `uv run python -m graph.generate` | `tests/test_drift.py` |
| Any verb added or removed | `uv run python tools/gen_permissions.py` | `tests/test_permissions.py` |
| Hand-written edges | edit `graph/edges.json` | `graph/validate_edges.py`, `tests/test_edges.py` |
| An area added, or its group changed | edit `graph/groups.json`, then `uv run python -m graph.generate` | `tests/test_groups.py`, `tests/test_drift.py` |

`gen_permissions.py` writes one `Bash(mac <area> <verb> *)` rule per command
into `~/.claude/settings.json`. Outbound or destructive verbs listed in its
hand-reviewed `ASK` table get an `ask` rule; every other verb gets `allow`.

## Cutover and rollback

The MCP servers that `mac` replaces (local-mac, astrology, wyckoff-analyzer,
sysml-mcp) were turned off on 2026-10-27. A fresh session now loads
claude-hooks, taskfw and `find_cli`: 67 tools instead of 245 (stdio servers
only; hosted connectors and claude-in-chrome are unchanged). local-mac is still
loaded inside `claude_for_mac_local`, through that repo's `.mcp.json`.

```bash
uv run python tools/cutover.py status     # exit 0 when cut over
uv run python tools/cutover.py rollback   # turn the old servers back on
uv run python tools/cutover.py apply      # turn them off again
uv run python tools/cutover.py count      # tools each configured server lists
```

`apply` saves the four server definitions and their 99 `mcp__<server>__*`
allow rules to `~/.claude/cutover-9839b040-backup.json`, then removes them
with `claude mcp remove -s user` and from `~/.claude/settings.json`.
`rollback` restores both from that file. The `mac` permission rules are not
touched. Start a new session after either step, so the tool list reloads.

## Status

This work is tracked under taskfw epic `9839b040`.
[`epic-9839b040-status.md`](epic-9839b040-status.md) is a snapshot from
2026-10-27; for the live state, run `tasks__list(parent="9839b040")`. The
migrated MCP servers are off (task:8cd14cfe); taskfw and claude-hooks stay as
MCP servers.
