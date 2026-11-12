"""`mac claude` — headless claude sessions with a root + fork topology.

`root` primes one session (system context, repo knowledge) and returns its id. `fork` runs a task
in a throwaway branch of that root (`claude -p --resume ROOT --fork-session`) and returns only the
final answer, so the root never accumulates a task's transcript and stays small and cache-warm.
The caller never resumes the root directly.

By default (`--isolation minimal`) a session drops everything the interactive setup injects: user hooks,
settings, CLAUDE.md files, auto-memory and skills. Only the `find_cli` and `taskfw` MCP servers (their
definitions are read from ~/.claude.json) and a `Bash(mac *)` allowance remain. `--isolation none` keeps
the full setup, hooks included.

A session is stored per working directory, so `fork` must run from the directory the root was
created in: pass the same --cwd to both (default: the caller's).
"""
import json
import os
import subprocess
import uuid

from mac.contract import Failure

DEFAULT_TIMEOUT_S = 1800
KEEP_MCP = ("find_cli", "taskfw")
DEFAULT_ALLOWED = "Bash(mac *),mcp__find_cli,mcp__taskfw"
CLAUDE_JSON = "~/.claude.json"


def _claude(argv, cwd, timeout, env=None):
    """Run `claude -p ... --output-format json`; returns the parsed result object."""
    full = ["claude", "-p", "--output-format", "json", *argv]
    try:
        proc = subprocess.run(full, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, env={**os.environ, **(env or {})})
    except subprocess.TimeoutExpired:
        raise Failure("tool_error", f"claude did not finish within {timeout}s")
    except OSError as exc:
        raise Failure("tool_error", f"cannot run claude: {exc}")
    try:
        out = json.loads(proc.stdout)
    except ValueError:
        raise Failure("tool_error", (proc.stderr or proc.stdout).strip() or f"claude exited {proc.returncode}")
    if proc.returncode or out.get("is_error"):
        raise Failure("tool_error", str(out.get("result") or proc.stderr).strip() or "claude reported an error")
    return out


def _common(p):
    p.add_argument("--cwd", default=None, help="working directory; root and forks must share it (default: the caller's)")
    p.add_argument("--model", default=None, help="model alias or id")
    p.add_argument("--permission-mode", default=None, help="claude --permission-mode (headless runs cannot prompt)")
    p.add_argument("--isolation", choices=("minimal", "none"), default="minimal",
                   help="minimal (default): no hooks, settings, CLAUDE.md, memory or skills; only the find_cli "
                        "and taskfw MCP servers. none: the full interactive setup")
    p.add_argument("--allowed-tools", default=DEFAULT_ALLOWED,
                   help=f"tools allowed without a prompt under minimal isolation (default {DEFAULT_ALLOWED!r})")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help=f"seconds (default {DEFAULT_TIMEOUT_S})")


def _mcp_config():
    """The find_cli and taskfw server definitions from the user's claude config, as --mcp-config JSON."""
    try:
        with open(os.path.expanduser(CLAUDE_JSON)) as fh:
            servers = json.load(fh).get("mcpServers") or {}
    except (OSError, ValueError) as exc:
        raise Failure("tool_error", f"cannot read MCP servers from {CLAUDE_JSON}: {exc}")
    missing = [n for n in KEEP_MCP if n not in servers]
    if missing:
        raise Failure("tool_error", f"MCP server(s) {', '.join(missing)} not defined in {CLAUDE_JSON}")
    return json.dumps({"mcpServers": {n: servers[n] for n in KEEP_MCP}})


def _isolation(ns):
    """(flags, env) that strip the session down to the kept MCP servers."""
    if ns.isolation == "none":
        return [], {}
    return (["--setting-sources", "project", "--strict-mcp-config", f"--mcp-config={_mcp_config()}",
             "--disable-slash-commands", f"--allowed-tools={ns.allowed_tools}"],
            {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"})


def _flags(ns):
    flags = []
    if ns.model:
        flags += ["--model", ns.model]
    if ns.permission_mode:
        flags += ["--permission-mode", ns.permission_mode]
    return flags


def _cwd(ns):
    cwd = os.path.abspath(ns.cwd) if ns.cwd else os.getcwd()
    if not os.path.isdir(cwd):
        raise Failure("usage", f"--cwd {cwd} is not a directory", 2)
    return cwd


def register(registry):
    def root_args(p):
        p.add_argument("--prompt", required=True, help="priming prompt: the context every fork should start from")
        _common(p)

    @registry.verb("claude", "root", mode="write",
                   desc="create a headless claude root session from a priming prompt and return its session id. "
                        "Never run tasks in it: branch each task with `mac claude fork`",
                   args=root_args)
    def root(ns):
        cwd = _cwd(ns)
        sid = str(uuid.uuid4())
        iso, env = _isolation(ns)
        out = _claude(["--session-id", sid, *iso, *_flags(ns), ns.prompt], cwd, ns.timeout, env)
        return {"root": out.get("session_id", sid), "cwd": cwd, "primed": True}

    def fork_args(p):
        p.add_argument("--root", required=True, help="root session id from `mac claude root`")
        p.add_argument("--task", required=True, help="the task to run in the fork")
        p.add_argument("--keep", action="store_true",
                       help="keep the fork's transcript on disk (resumable, auditable); default discards it")
        _common(p)

    @registry.verb("claude", "fork", mode="write",
                   desc="run a task in a throwaway fork of a root claude session and return only its final answer; "
                        "the root's context stays unchanged and minimal",
                   args=fork_args)
    def fork(ns):
        cwd = _cwd(ns)
        iso, env = _isolation(ns)
        argv = ["--resume", ns.root, "--fork-session", *iso, *_flags(ns)]
        if not ns.keep:
            argv.append("--no-session-persistence")
        out = _claude([*argv, ns.task], cwd, ns.timeout, env)
        return {"root": ns.root, "fork": out.get("session_id"), "kept": ns.keep,
                "result": out.get("result"), "cost_usd": out.get("total_cost_usd"),
                "turns": out.get("num_turns")}
