# Epic 9839b040 — status (2026-10-27)

**cli-graph: replace ~300 MCP tools with a `mac` CLI plus one graph-backed `find_cli` MCP tool**

3 of 26 tasks are still open. None of the epic's 6 completion criteria are ticked on the epic itself, but done tasks now cover criteria 1–5.

## Open tasks (suggested order)

| # | Task | Title | Checklist |
|---|---|---|---|
| 1 | `2dcdba79` | Widen find_cli's one-phrase margin over the 90% gate: both misses are "check ..." phrases where the generic word "check" ranks the wrong commands first | 0/4 |
| 2 | `e0ce873e` | `mac time cancel <pid>` stops a time wait/alarm timer, so the live parity test stops killing timer process groups itself | 0/4 |
| 3 | `8cd14cfe` | Cutover: turn off the migrated MCP servers and keep a rollback path | 0/3 |

## Done (23)

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
| `980f10b3` | `graph/cli_graph.json` generated from `mac --help --json`; `python -m graph.generate --check` and tests/test_drift.py fail on drift |
| `821c2f7e` | `graph/edges.json` holds hand-written feeds/requires/alias_of/prefer_over edges; `validate_edges` fails on any endpoint that is not a command node |
| `129f1bc3` | `find_cli` package: BM25 seeds plus edge and area-sibling expansion (≤25 ids), deterministic across processes; one-tool FastMCP server (~186 schema tokens) |
| `597ac09d` | Hit-rate eval: 22/24 = 92% of real transcript phrases land in the subgraph (seed-only 75%); `tests/eval_find_cli.py` reports, `tests/test_eval_fixture.py` keeps the 90% gate in the suite; no inner LLM needed |
| `2b1844d7` | cli-graph has its own uv environment (pyproject.toml + uv.lock, local-mac as a path dependency) |
| `924bfec4` | local-mac's venv resolves the same package versions as cli-graph's (mcp 1.30, pydantic 2.14, fastmcp 3.4), with mcp pinned below 2 |
| `d30c0330` | `bin/mac` runs under cli-graph's uv `.venv`, the one the suite runs under; `tests/test_bin_mac_env.py` fails if the two ever differ |
| `2ee06de6` | `bin/mac` loads local-mac's `.env` under cli-graph's venv, so mail verbs work again; `tests/test_backend_env.py` guards it |
| `8bf3185f` | The live time wait/alarm parity test matches the pid-based timers and leaves no `mac-parity` timer behind |
| `25e053bc` | `mac astrology`, `mac wyckoff` and `mac sysml` run each MCP server's tools through a stdio MCP-client proxy, generated from tools/list with parity tests; taskfw and claude-hooks stay MCP (user decision) |
| `6f4eb62c` | `mac` and the local-mac MCP tools reject malformed date arguments (`YYYY-MM-DD`; date-times joined with `T`) before a handler runs |
| `c5a222dc` | `find_cli` results carry each command's run count and `last_used`, read-only from `~/.claude/tool_hints.sqlite`; `find()` stays pure |
| `cf5d016d` | Real-use hit rate: claude-hooks logs each `find_cli` query with its seeds to `find_cli_queries` and links it to the next `mac` call in the session (seed / neighbour / miss), with a report |
| `0aa96180` | Permissions, hooks and tool hints keyed on `mac <area> <verb>` Bash prefixes: `tools/gen_permissions.py` writes one allow/ask rule per command; event log, Suggested tools and vault reindex see `mac` calls. Live check 2026-10-27 under auto mode: an allowed verb ran unprompted, and `reminders delete` prompted both as `mac` and as `~/bin/mac`. Suites: cli-graph 185 OK / 20 skipped, claude-hooks 602 passed / 1 skipped |

## Where things stand

Migration is complete: `mac` now has 173 commands across 20 areas, covering every local-mac group plus astrology, wyckoff and sysml. The graph, edges file and `find_cli` are built, and the phrase eval passes at 92%, one phrase above the gate. Since the last snapshot, `find_cli` has gained real-use telemetry. Each answer carries usage counts (`c5a222dc`), and claude-hooks now records whether the command actually run was one `find_cli` suggested (`cf5d016d`). That gives a second measure of quality beyond the fixed phrase set. Date arguments are now validated up front, in both `mac` and the MCP tools (`6f4eb62c`).

The repo docs were rewritten on 2026-10-27. `CLAUDE.md` is now the project brief, and `README.md` covers layout, contract, setup and the regenerate-on-change table.

`0aa96180` closed on 2026-10-27 after a live check: under auto mode, an `ask` rule on a `mac` write verb still prompts. Next: `2dcdba79`, which can now draw on the `find_cli_queries` misses as well as the phrase eval. `e0ce873e` still needs a cancel handler in local-mac first. The cutover, `8cd14cfe`, comes last. It disables local-mac, astrology, wyckoff-analyzer and sysml-mcp and keeps taskfw and claude-hooks. It must also drop the ~100 migrated `mcp__` allow rules, and on a fresh checkout it must rebuild sysml-mcp's gitignored `dist` bundle. `uv run python tests/eval_find_cli.py` can serve as its gate.

## Epic completion criteria (none ticked on the epic)

- [ ] A `mac <area> <verb> --json` dispatcher runs the migrated local-mac tool groups — *covered by done tasks*
- [ ] A generated command graph plus hand-written edges file exists, with a drift check that fails on any command missing from the graph or the reverse — *covered*
- [ ] `find_cli(task)` returns a subgraph (seeds, neighbours, usage lines, read/write mode) and never a command absent from the graph — *covered*
- [ ] At least 90% of ~20 real task phrases land the right command in the returned subgraph — *covered (92%)*
- [ ] Permissions and hooks work on Bash command prefixes instead of MCP tool names — *covered (`0aa96180`)*
- [ ] Migrated MCP servers are removed from config and computer-use, claude-in-chrome and hosted connectors are untouched — *open (`8cd14cfe`)*
