# cli-graph

## Epic status

The work here is tracked under taskfw epic `9839b040` (replace ~300 MCP tools with a `mac` CLI plus one graph-backed `find_cli` MCP tool).

A snapshot of open and done tasks, the suggested next step and the epic's completion criteria is in [`epic-9839b040-status.md`](epic-9839b040-status.md). It was taken on 2026-10-26 and is not updated automatically: run `tasks__list(parent="9839b040", status="")` for the live state, and refresh the file when tasks close.

## Running the suite

The Python environment is managed with uv (`pyproject.toml`, `uv.lock`, Python 3.12). The `mac` backend runs local-mac's handlers in-process, so the project takes local-mac's dependencies from `../claude_for_mac_local` as a path dependency.

```bash
uv run python -m unittest discover -s tests   # whole suite
uv run python tests/eval_find_cli.py          # find_cli hit-rate eval (90% gate)
uv run python -m graph.generate --check       # graph drift check
```

`bin/mac` (and `~/bin/mac`, a symlink to it) runs under this same uv `.venv`, so the suite tests the `mac` users run. `MAC_PYTHON` overrides it. Without the `.venv` it falls back to `python3`, which reports `backend_missing` as JSON; it never falls back to local-mac's venv. `tests/test_bin_mac_env.py` fails if `bin/mac` and the suite pick different interpreters. The `find_cli` server runs the same way: `uv run --directory ~/workspace/cli-graph python -m find_cli.server`.

`mac astrology`, `mac wyckoff` and `mac sysml` run a separate MCP server per call (`mac/groups/_mcp_proxy.py`): astrology-mcp's and stock-tracker-mcp's own venvs, and sysml-mcp's Node bundle. Their modules are generated from each server's `tools/list`; after a server's tools change, run `uv run python tools/gen_mcp_groups.py` (`--check` reports staleness, and `tests/test_parity_mcp_servers.py` fails on it).

Plain `python3` (Homebrew 3.15) has no pydantic. The five parity modules then fail to import, each with one message pointing here. Live parity tests stay skipped unless `MAC_PARITY_LIVE=1` is set.
