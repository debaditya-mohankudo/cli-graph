"""The find_cli MCP server: one tool, `find_cli` (task:129f1bc3).

Needs the `mcp` package, so run it through bin/find_cli, which uses
cli-graph's .venv with no `uv sync` step (like bin/mac):

    ~/workspace/cli-graph/bin/find_cli

The graph and edges are re-read when their files change (find_cli.service),
and usage counts on every call, because the server lives for a whole Claude
session. The tool description and its area list are fixed at start: a new
area works as a hint or browse target after a reload but is listed only
after a restart. The description is the index; the verbs are read on demand
by browsing an area (task:6d619bfc).
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

DESCRIPTION = """Find the `mac` CLI command for a task, then run it through Bash:
`mac <area> <verb> --json`. Two ways in:
- know the area: pass only `area` to list its commands (a group lists its
  areas). Pick from the list.
- otherwise: describe the task; get best-match seeds and neighbours.
Each command has its usage line, read/write mode and run count. no_match
true: no command covers the task, say so. confidence "low": only an
incidental word matched, check desc fits before running.

task: plain words ("text someone"); empty to list `area`
limit: seeds (default 5); hops: 0 seeds, 1 +linked, 2 +area siblings
area: area or group; boosts a search, never hides. Groups (purpose, areas):
%s
""" % AREAS


@mcp.tool(description=DESCRIPTION)
def find_cli(task: str = "", limit: int = DEFAULT_LIMIT, hops: int = 2, area: str = "") -> dict:
    return FINDER.answer(task, limit=limit, hops=hops, area=area)


if __name__ == "__main__":
    mcp.run()
