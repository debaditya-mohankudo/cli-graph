# Epic 9839b040 — status (2026-10-26)

**cli-graph: replace ~300 MCP tools with a `mac` CLI plus one graph-backed `find_cli` MCP tool**

5 of 22 tasks still open. All 6 of the epic's own completion criteria are still unticked on the epic, though done tasks now cover criteria 2, 3 and 4.

## Open tasks (suggested order)

| # | Task | Title | Checklist |
|---|---|---|---|
| 1 | `25e053bc` | Migrate the stateless non-local-mac servers (claude-hooks memory/scratch/vault_map/rag, astrology, wyckoff, sysml) and decide on taskfw | 0/4 |
| 2 | `0aa96180` | Move permissions, hooks and tool hints from MCP tool names to Bash command prefixes | 0/4 |
| 3 | `2dcdba79` | Widen find_cli's one-phrase margin over the 90% gate: both misses are "check ..." phrases where the generic word "check" ranks the wrong commands first | 0/4 |
| 4 | `e0ce873e` | `mac time cancel <pid>` stops a time wait/alarm timer, so the live parity test stops killing timer process groups itself | 0/4 |
| 5 | `8cd14cfe` | Cutover: turn off the migrated MCP servers and keep a rollback path | 0/3 |

## Done (17)

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
| `597ac09d` | Hit-rate eval: 22/24 = 92% of real transcript phrases land in the subgraph (seed-only 75%); `tests/eval_find_cli.py` reports, `tests/test_eval_fixture.py` keeps the 90% gate in the suite; no inner LLM needed |
| `2b1844d7` | cli-graph has its own uv environment (pyproject.toml + uv.lock, local-mac as a path dependency); `uv run python -m unittest discover -s tests` is the suite, and plain python3 fails once per parity module naming that command |
| `924bfec4` | local-mac's venv resolves the same package versions as cli-graph's (mcp 1.30, pydantic 2.14, fastmcp 3.4), with mcp pinned below 2 |
| `d30c0330` | `bin/mac` runs under cli-graph's uv `.venv`, the one the suite runs under; `tests/test_bin_mac_env.py` fails if the two ever differ |
| `2ee06de6` | `bin/mac` loads local-mac's `.env` under cli-graph's venv, so mail verbs work again; `tests/test_backend_env.py` guards it |
| `8bf3185f` | The live time wait/alarm parity test matches the pid-based timers and leaves no `mac-parity` timer behind, even when it fails |

## Where things stand

All the done tasks are migrations to `mac` commands. Every local-mac group is now migrated or deliberately dropped: `73cbda5d` migrated vault_rag and dropped code_rag and ollama_agent, which disappear at cutover (noted on `8cd14cfe`). The generated graph (`980f10b3`), the edges file (`821c2f7e`) and `find_cli` (`129f1bc3`) are done. The hit-rate eval (`597ac09d`) passed at 92% with no change to ranking, so the no-inner-LLM design stands. The margin is one phrase, and the remaining misses come from the generic word "check"; `2dcdba79` tracks widening it. `2b1844d7` gave the repo its own uv environment, so the suite and the eval run the same way everywhere; `d30c0330` and `924bfec4` made `bin/mac` run under that same environment, and `2ee06de6` restored the `.env` loading that move broke for mail. `8bf3185f` fixed the live time parity test, which surfaced that no timer can be cancelled through `mac`; `e0ce873e` adds `mac time cancel` and needs a new handler in local-mac first. Next: `0aa96180` (permissions and hooks on Bash prefixes); `25e053bc` can run in parallel; `2dcdba79` is independent of both; `8cd14cfe` (cutover) can use `uv run python tests/eval_find_cli.py` as a gate.

## Epic completion criteria (all open)

- [ ] A `mac <area> <verb> --json` dispatcher runs the migrated local-mac tool groups
- [ ] A generated command graph plus hand-written edges file exists, with a drift check that fails on any command missing from the graph or the reverse
- [ ] `find_cli(task)` returns a subgraph (seeds, neighbours, usage lines, read/write mode) and never a command absent from the graph
- [ ] At least 90% of ~20 real task phrases land the right command in the returned subgraph
- [ ] Permissions and hooks work on Bash command prefixes instead of MCP tool names
- [ ] Migrated MCP servers are removed from config and computer-use, claude-in-chrome and hosted connectors are untouched
