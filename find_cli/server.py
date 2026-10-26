"""The find_cli MCP server: one tool, `find_cli` (task:129f1bc3).

Needs the `mcp` package, so run it under local-mac's venv, the same one bin/mac
uses:

    PYTHONPATH=~/workspace/cli-graph \
        ~/workspace/claude_for_mac_local/.venv/bin/python -m find_cli.server

The graph and edges are loaded once at start-up from the committed files.
Not yet registered in ~/.claude.json; that happens at cutover (task:8cd14cfe).
"""
from mcp.server.fastmcp import FastMCP

from find_cli import DEFAULT_LIMIT, find, load

mcp = FastMCP("find_cli")
GRAPH, EDGES = load()


@mcp.tool()
def find_cli(task: str, limit: int = DEFAULT_LIMIT, hops: int = 2) -> dict:
    """Find the `mac` CLI commands for a task. Returns seed commands (best
    match first) and their neighbours, each with its usage line and read/write
    mode. Run the chosen command through Bash: `mac <area> <verb> --json`.

    task: what you want to do, in plain words ("text someone", "read a note")
    limit: number of seed commands (default 5)
    hops: 0 seeds only, 1 adds linked commands, 2 also adds area siblings
    """
    return find(task, GRAPH, EDGES, limit=limit, hops=hops)


if __name__ == "__main__":
    mcp.run()
