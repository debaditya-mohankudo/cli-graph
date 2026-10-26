# Epic 9839b040 — status (2026-10-26)

**cli-graph: replace ~300 MCP tools with a `mac` CLI plus one graph-backed `find_cli` MCP tool**

4 of 16 tasks still open. All 6 of the epic's own completion criteria are still unticked on the epic, though done tasks now cover criteria 2 and 3.

## Open tasks (suggested order)

| # | Task | Title | Checklist |
|---|---|---|---|
| 1 | `25e053bc` | Migrate the stateless non-local-mac servers (claude-hooks memory/scratch/vault_map/rag, astrology, wyckoff, sysml) and decide on taskfw | 0/4 |
| 2 | `597ac09d` | Hit-rate eval: about 20 real task phrases must find the right command | 0/3 |
| 3 | `0aa96180` | Move permissions, hooks and tool hints from MCP tool names to Bash command prefixes | 0/4 |
| 4 | `8cd14cfe` | Cutover: turn off the migrated MCP servers and keep a rollback path | 0/3 |

## Done (12)

| Task | Title |
|---|---|
| `c3d9395f` | `mac` dispatcher skeleton — subcommand registry, --json default, uniform error and exit-code contract |
| `f52bd375` | Harden mac/groups/_backend: run calls through tool_called, persisted gates, blocked refusals, empty results |
| `fd332486` | Migrate local-mac notes and reminders to `mac notes` / `mac reminders` |
| `315f6563` | Migrate simple local-mac groups (time, vpn, podcasts, music, sound, contacts, calendar, system, market, connector) |
| `2cea5538` | gen_groups.py stops copying handler defaults into generated `mac` verbs |
| `906b962e` | Hand-written `mac notes` / `mac reminders` stop copying handler defaults |
| `babafba2` | Migrate local-mac mail and imessage groups with the send/delete gates |
| `0c64fa90` | Migrate local-mac vault and safari groups; `mac safari` enforces the tab guard with --expect-host |
| `73cbda5d` | `mac vault_rag` migrated (llama_index now lazy-loaded, fts_vault ~0.26s); code_rag and ollama_agent dropped (0 calls) |
| `980f10b3` | `graph/cli_graph.json` generated from `mac --help --json` (121 commands, 17 domains); `python -m graph.generate --check` and tests/test_drift.py fail on drift |
| `821c2f7e` | `graph/edges.json` holds hand-written feeds/requires/alias_of/prefer_over edges (3 seed edges); `validate_edges` fails on any endpoint that is not a command node |
| `129f1bc3` | `find_cli` package: hand-written BM25 seeds plus edge and area-sibling expansion (≤25 ids), deterministic across processes; one-tool FastMCP server (~186 schema tokens), not yet registered |

## Where things stand

All the done tasks are migrations to `mac` commands. Every local-mac group is now migrated or deliberately dropped: `73cbda5d` migrated vault_rag and dropped code_rag and ollama_agent, which disappear at cutover (noted on `8cd14cfe`). The generated graph (`980f10b3`), the edges file (`821c2f7e`) and `find_cli` (`129f1bc3`) are done. Next: `597ac09d` (hit-rate eval), which can import `find_cli.find` directly. Expect it to start below 90%: phrasings like "text someone" or "delete an email" miss because BM25 only sees each command's own words, so the fix is alias_of edges or desc wording. `0aa96180` is also unblocked, and `25e053bc` can run in parallel.

## Epic completion criteria (all open)

- [ ] A `mac <area> <verb> --json` dispatcher runs the migrated local-mac tool groups
- [ ] A generated command graph plus hand-written edges file exists, with a drift check that fails on any command missing from the graph or the reverse
- [ ] `find_cli(task)` returns a subgraph (seeds, neighbours, usage lines, read/write mode) and never a command absent from the graph
- [ ] At least 90% of ~20 real task phrases land the right command in the returned subgraph
- [ ] Permissions and hooks work on Bash command prefixes instead of MCP tool names
- [ ] Migrated MCP servers are removed from config and computer-use, claude-in-chrome and hosted connectors are untouched
