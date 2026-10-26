"""Runs a tool of a separate MCP server and maps its result onto the mac contract (task:25e053bc).

Used for servers whose code cannot run inside `mac`'s own process:
astrology-mcp and stock-tracker-mcp each have their own venv (astrology's
top-level `tools`, `dispatcher` and `config` modules would clash with
local-mac's), and sysml-mcp is a Node bundle. Each `mac` call starts the
server over stdio, as an MCP client would, makes one tools/call and exits. The
server stays the only implementation, so a verb returns what the MCP tool
returns. The cost is the server's start-up: about 0.4s for sysml, 1s for
astrology and 2s for wyckoff, measured 2026-10-26.

Result mapping, the same as _backend's for local-mac handlers:
  - each text block is parsed as JSON (left as a string if it is not JSON);
    one block becomes the result, several become a list;
  - isError, or a dict result with an "error" key, becomes Failure('tool_error');
  - a server that cannot start becomes Failure('backend_missing'), with the
    tail of its stderr.

The server's stderr goes to a temp file, not `mac`'s stderr, which carries
only the contract's JSON.
"""
import json
import os
import sys
from pathlib import Path
from typing import NamedTuple

from mac.contract import EXIT_USAGE, Failure, raise_if_error

HOME = Path.home()


class Server(NamedTuple):
    command: str
    args: tuple = ()
    cwd: str | None = None


# The same launch commands as the MCP config entries they replace, except the
# Python servers run their venv's interpreter directly instead of `uv run`,
# which saves a sync check on every call.
SERVERS = {
    "astrology": Server(
        command=str(HOME / "workspace/astrology-mcp/.venv/bin/python"),
        args=(str(HOME / "workspace/astrology-mcp/mcp_server.py"),),
        cwd=str(HOME / "workspace/astrology-mcp")),
    "wyckoff": Server(
        command=str(HOME / "workspace/stock-tracker-mcp/.venv/bin/python"),
        args=(str(HOME / "workspace/stock-tracker-mcp/stock_tracker/mcp_server.py"),),
        cwd=str(HOME / "workspace/stock-tracker-mcp")),
    "sysml": Server(
        command="node",
        args=(str(HOME / "workspace/mbse-claude-hooks-model/sysml-mcp/dist/server/mcpServer.js"),)),
}

# Set by bin/mac or cli-graph's venv; they must not leak into another project's interpreter.
_DROP_ENV = ("PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME")


def _env():
    return {k: v for k, v in os.environ.items() if k not in _DROP_ENV}


def _check_installed(name, server):
    cmd = Path(server.command)
    if cmd.is_absolute() and not cmd.exists():
        raise Failure("backend_missing", f"{name} server interpreter not found: {cmd}")
    for arg in server.args:
        if arg.startswith("/") and not Path(arg).exists():
            raise Failure("backend_missing", f"{name} server entry point not found: {arg}")


def _value(text):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def unwrap(result):
    """The mac result for a CallToolResult; raises Failure for an error result."""
    texts = [block.text for block in result.content if getattr(block, "type", None) == "text"]
    if result.isError:
        raise Failure("tool_error", " ".join(texts) or "tool reported an error")
    values = [_value(t) for t in texts]
    return raise_if_error(values[0] if len(values) == 1 else values)


def as_list(data):
    """The result of a tool that returns a list.

    FastMCP sends a list as one text block per item, so a one-item list
    arrives looking like a lone object and unwrap() cannot tell them apart.
    For the verbs listed in gen_mcp_groups.LIST_RESULT this puts it back.
    """
    return data if isinstance(data, list) else [data]


def data_block(data):
    """The last JSON block of a multi-block result, dropping text addressed to the model.

    sysml's preview answers with an instruction to call renderMermaidDiagram
    (a VS Code tool Claude Code does not have) followed by the data. A reply
    with no JSON block at all is the server saying it had nothing to work on.
    """
    blocks = data if isinstance(data, list) else [data]
    for block in reversed(blocks):
        if isinstance(block, (dict, list)):
            return block
    raise Failure("tool_error", " ".join(str(b) for b in blocks))


async def _session(server, errlog, op):
    # Imported here: the mcp client stack costs ~0.2s and only these verbs need it.
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=server.command, args=list(server.args),
                                   cwd=server.cwd, env=_env())
    async with stdio_client(params, errlog=errlog) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await op(session)


def _tail(errlog, lines=5):
    errlog.seek(0)
    return " | ".join(errlog.read().strip().splitlines()[-lines:])


def _run(server_name, op):
    """Start the named server, run `op(session)` and stop it; a failure to talk to it is backend_missing."""
    # Imported here, not at module load: every `mac` call imports this module, and asyncio alone is ~35ms.
    import asyncio
    import tempfile

    server = SERVERS[server_name]
    _check_installed(server_name, server)
    with tempfile.TemporaryFile("w+") as errlog:
        try:
            return asyncio.run(_session(server, errlog, op))
        except Exception as exc:
            detail = _tail(errlog)
            raise Failure("backend_missing",
                          f"{server_name} server failed: {type(exc).__name__}: {exc}"
                          + (f" (server stderr: {detail})" if detail else ""))


def call_tool(server_name, tool, /, **arguments):
    """Run `tool` on the named server with these arguments and return its unwrapped result."""
    return unwrap(_run(server_name, lambda session: session.call_tool(tool, arguments)))


def list_tools(server_name):
    """The server's tools/list, for tools/gen_mcp_groups.py and the freshness test."""
    async def op(session):
        return (await session.list_tools()).tools
    return _run(server_name, op)


def code_from(ns, flags, required=()):
    """Read `<flag>-file PATH` (`-` for stdin) into ns.<name>, for servers that take source text.

    `flags` maps each property name to its --flag; a name in `required` must
    arrive one way or the other.
    """
    for name, flag in flags.items():
        path = getattr(ns, f"{name}_file", None)
        given_inline = getattr(ns, name, None) is not None
        if path is not None:
            if given_inline:
                raise Failure("usage", f"pass {flag} or {flag}-file, not both", EXIT_USAGE)
            try:
                setattr(ns, name, sys.stdin.read() if path == "-" else Path(path).read_text())
            except OSError as exc:
                raise Failure("usage", f"cannot read {path}: {exc.strerror}", EXIT_USAGE)
        elif name in required and not given_inline:
            raise Failure("usage", f"{name} is required: pass {flag} or {flag}-file", EXIT_USAGE)
    return ns
