# Epic 9839b040 — status (2026-10-26)

**cli-graph: replace ~300 MCP tools with a `mac` CLI plus one graph-backed `find_cli` MCP tool**

9 of 16 tasks still open. All 6 of the epic's own completion criteria are still unticked.

## Open tasks (suggested order)

| # | Task | Title | Checklist |
|---|---|---|---|
| 1 | `0c64fa90` | Migrate local-mac vault and safari groups to `mac` verbs, keeping the safari tab guard | 0/4 |
| 2 | `73cbda5d` | Decide whether to migrate or drop the venv-only groups (code_rag, ollama_agent, vault_rag) | 0/3 |
| 3 | `25e053bc` | Migrate the stateless non-local-mac servers (claude-hooks memory/scratch/vault_map/rag, astrology, wyckoff, sysml) and decide on taskfw | 0/4 |
| 4 | `980f10b3` | Build the command graph from each CLI's `--help`, with a drift check | 0/3 |
| 5 | `821c2f7e` | Hand-written typed edges file (feeds, requires, alias_of, prefer_over), checked against the generated graph | 0/3 |
| 6 | `129f1bc3` | `find_cli(task)` MCP tool: keyword search plus 1–2 hop edge expansion | 0/5 |
| 7 | `597ac09d` | Hit-rate eval: about 20 real task phrases must find the right command | 0/3 |
| 8 | `0aa96180` | Move permissions, hooks and tool hints from MCP tool names to Bash command prefixes | 0/4 |
| 9 | `8cd14cfe` | Cutover: turn off the migrated MCP servers and keep a rollback path | 0/3 |

## Done (7)

| Task | Title |
|---|---|
| `c3d9395f` | `mac` dispatcher skeleton — subcommand registry, --json default, uniform error and exit-code contract |
| `f52bd375` | Harden mac/groups/_backend: run calls through tool_called, persisted gates, blocked refusals, empty results |
| `fd332486` | Migrate local-mac notes and reminders to `mac notes` / `mac reminders` |
| `315f6563` | Migrate simple local-mac groups (time, vpn, podcasts, music, sound, contacts, calendar, system, market, connector) |
| `2cea5538` | gen_groups.py stops copying handler defaults into generated `mac` verbs |
| `906b962e` | Hand-written `mac notes` / `mac reminders` stop copying handler defaults |
| `babafba2` | Migrate local-mac mail and imessage groups with the send/delete gates |

## Where things stand

All the done tasks are migrations to `mac` commands. The graph and `find_cli` work (rows 4–7) hasn't started. The fastest next step is `0c64fa90` (vault/safari), which finishes the local-mac migration. Alternatively, `980f10b3` (the graph) unblocks the `find_cli` work.

## Epic completion criteria (all open)

- [ ] A `mac <area> <verb> --json` dispatcher runs the migrated local-mac tool groups
- [ ] A generated command graph plus hand-written edges file exists, with a drift check that fails on any command missing from the graph or the reverse
- [ ] `find_cli(task)` returns a subgraph (seeds, neighbours, usage lines, read/write mode) and never a command absent from the graph
- [ ] At least 90% of ~20 real task phrases land the right command in the returned subgraph
- [ ] Permissions and hooks work on Bash command prefixes instead of MCP tool names
- [ ] Migrated MCP servers are removed from config and computer-use, claude-in-chrome and hosted connectors are untouched
