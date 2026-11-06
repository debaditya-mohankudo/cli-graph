"""The find_cli MCP server: one tool, `find_cli` (task:129f1bc3).

Needs the `mcp` package, so run it through bin/find_cli, which uses
cli-graph's .venv with no `uv sync` step (like bin/mac):

    ~/workspace/cli-graph/bin/find_cli

The graph and edges are re-read when their files change (find_cli.service),
and usage counts on every call, because the server lives for a whole Claude
session. The tool description and its area list are fixed at start: a new
area works as a hint after a reload but is listed only after a restart.
"""
from mcp.server.fastmcp import FastMCP

from find_cli import DEFAULT_LIMIT
from find_cli.service import Finder

mcp = FastMCP("find_cli")
FINDER = Finder()


def area_lines(graph):
    """The description's area list: groups with their purpose from
    graph/groups.json, areas from the graph; bare names if groups.json
    cannot be read."""
    areas = sorted(graph["domains"])
    try:
        from graph import groups
        return groups.describe(groups.load(), areas)
    except (ImportError, OSError, KeyError, ValueError):
        return [", ".join(areas)]


AREAS = "\n".join("    " + line for line in area_lines(FINDER.current()[0]))

DESCRIPTION = """Find the `mac` CLI commands for a task. Returns seed commands (best
match first) and their neighbours, each with its usage line, read/write
mode and how often it has been run (count, last_used). Run the chosen
command through Bash: `mac <area> <verb> --json`. no_match true means no
command covers the task: say so rather than run something. confidence
level "low" means the top seed matched only an incidental word: check its
desc fits the task before running it.

task: what you want to do, in plain words ("text someone", "read a note")
limit: number of seed commands (default 5)
hops: 0 seeds only, 1 adds linked commands, 2 also adds area siblings
area: optional area or group you already know; boosts its commands, never
    hides others; an unknown value is reported in hint. Groups (purpose,
    then areas):
%s
""" % AREAS


@mcp.tool(description=DESCRIPTION)
def find_cli(task: str, limit: int = DEFAULT_LIMIT, hops: int = 2, area: str = "") -> dict:
    return FINDER.answer(task, limit=limit, hops=hops, area=area)


if __name__ == "__main__":
    mcp.run()
