"""The find_cli MCP server: one tool, `find_cli` (task:129f1bc3).

Needs the `mcp` package, so run it under cli-graph's uv venv, the same one
bin/mac and the suite use:

    uv run --directory ~/workspace/cli-graph python -m find_cli.server

The graph and edges are loaded once at start-up from the committed files.
Usage counts (find_cli.usage) are read on every call, because the server
lives for a whole Claude session and the counts change under it.
"""
from mcp.server.fastmcp import FastMCP

from find_cli import DEFAULT_LIMIT, find, load
from find_cli import usage as _usage

mcp = FastMCP("find_cli")
GRAPH, EDGES = load()


@mcp.tool()
def find_cli(task: str, limit: int = DEFAULT_LIMIT, hops: int = 2) -> dict:
    """Find the `mac` CLI commands for a task. Returns seed commands (best
    match first) and their neighbours, each with its usage line, read/write
    mode and how often it has been run (count, last_used). Run the chosen
    command through Bash: `mac <area> <verb> --json`.

    task: what you want to do, in plain words ("text someone", "read a note")
    limit: number of seed commands (default 5)
    hops: 0 seeds only, 1 adds linked commands, 2 also adds area siblings
    """
    return find(task, GRAPH, EDGES, limit=limit, hops=hops, usage=_usage.load())


if __name__ == "__main__":
    mcp.run()
