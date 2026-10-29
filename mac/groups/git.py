"""`mac git` — the everyday git cases (status, diff, log, add, commit, push) with the repo as an argument.

Runs `git` directly. Staging and committing are scoped on purpose: `add` stages only the paths it is
given, `commit` takes only what is staged (or only the paths listed), and a commit message needs a
`task:<id>` reference, the same rule the commit gate enforces on raw `git commit`.
"""
import argparse
import re
import subprocess

from mac.contract import Failure

UNSET = argparse.SUPPRESS
TASK_REF = re.compile(r"\btask:[0-9a-f]{8}\b")
DIFF_CHARS = 100_000


def _git(repo, *args, check=True):
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and proc.returncode:
        raise Failure("tool_error", (proc.stderr or proc.stdout).strip() or f"git {args[0]} failed")
    return proc.stdout


def _root(repo):
    proc = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if proc.returncode:
        raise Failure("tool_error", f"not a git repository: {repo}")
    return proc.stdout.strip()


def _repo_arg(p):
    p.add_argument("--repo", default=".", help="path of the repo (default: current directory)")


def _paths_arg(p):
    p.add_argument("paths", nargs="*", help="limit to these paths")


def _staged_files(repo):
    return [f for f in _git(repo, "diff", "--cached", "--name-only").splitlines() if f]


def register(registry):
    def status_args(p):
        _repo_arg(p)

    @registry.verb("git", "status", mode="read",
                   desc="what changed in the repo: branch, ahead/behind and staged, modified and untracked files",
                   args=status_args)
    def status(ns):
        root = _root(ns.repo)
        lines = _git(root, "status", "--porcelain=v1", "-b").splitlines()
        head, files = lines[0][3:], lines[1:]
        branch, _, tracking = head.partition("...")
        ahead = behind = 0
        if m := re.search(r"ahead (\d+)", tracking):
            ahead = int(m.group(1))
        if m := re.search(r"behind (\d+)", tracking):
            behind = int(m.group(1))
        return {"repo": root, "branch": branch, "upstream": tracking.split(" ")[0] or None,
                "ahead": ahead, "behind": behind,
                "files": [{"status": f[:2], "path": f[3:]} for f in files]}

    def diff_args(p):
        _repo_arg(p)
        _paths_arg(p)
        p.add_argument("--staged", action="store_true", help="diff what is staged instead of the working tree")
        p.add_argument("--stat", action="store_true", help="file-level summary instead of the patch")

    @registry.verb("git", "diff", mode="read",
                   desc="show the changes in the working tree or staged area, as a patch or a --stat summary",
                   args=diff_args)
    def diff(ns):
        cmd = ["diff"] + (["--cached"] if ns.staged else []) + (["--stat"] if ns.stat else [])
        text = _git(_root(ns.repo), *cmd, "--", *ns.paths)
        if len(text) > DIFF_CHARS:
            return {"diff": text[:DIFF_CHARS], "truncated": {"shown": DIFF_CHARS, "total": len(text)}}
        return {"diff": text}

    def log_args(p):
        _repo_arg(p)
        _paths_arg(p)
        p.add_argument("-n", type=int, default=10, help="number of commits (default 10)")

    @registry.verb("git", "log", mode="read",
                   desc="recent commits of the repo or of some paths: sha, author, date and subject",
                   args=log_args)
    def log(ns):
        out = _git(_root(ns.repo), "log", f"-{ns.n}", "--format=%H%x1f%an%x1f%aI%x1f%s", "--", *ns.paths)
        rows = (line.split("\x1f") for line in out.splitlines())
        return [{"sha": s, "author": a, "date": d, "subject": subj} for s, a, d, subj in rows]

    def add_args(p):
        _repo_arg(p)
        p.add_argument("paths", nargs="+", help="files to stage; there is no stage-everything form")

    @registry.verb("git", "add", mode="write",
                   desc="stage the named files for the next commit (never stages everything)",
                   args=add_args)
    def add(ns):
        root = _root(ns.repo)
        _git(root, "add", "--", *ns.paths)
        return {"repo": root, "staged": _staged_files(root)}

    def commit_args(p):
        _repo_arg(p)
        p.add_argument("-m", "--message", required=True, help="commit message; must contain task:<id>")
        p.add_argument("paths", nargs="*", help="commit only these paths, leaving other staged changes alone")

    @registry.verb("git", "commit", mode="write",
                   desc="commit the staged changes (or only the listed paths) with a task:<id> message",
                   args=commit_args)
    def commit(ns):
        if not TASK_REF.search(ns.message):
            raise Failure("tool_error", "commit message needs a task:<id> reference (8 hex digits), "
                                        "e.g. 'task:3aaa1343 what changed'")
        root = _root(ns.repo)
        if not ns.paths and not _staged_files(root):
            raise Failure("tool_error", "nothing staged; run `mac git add <paths>` or list paths to commit")
        _git(root, "commit", "-m", ns.message, *(["--", *ns.paths] if ns.paths else []))
        sha = _git(root, "rev-parse", "HEAD").strip()
        files = _git(root, "show", "--name-only", "--format=", sha).split()
        return {"repo": root, "sha": sha, "subject": ns.message.splitlines()[0], "files": files}

    def push_args(p):
        _repo_arg(p)
        p.add_argument("remote", nargs="?", help="remote name (default: the branch's upstream)")
        p.add_argument("branch", nargs="?", help="branch to push (default: the current branch)")

    @registry.verb("git", "push", mode="write",
                   desc="push the current branch to its remote and report the commits sent",
                   args=push_args)
    def push(ns):
        root = _root(ns.repo)
        branch = ns.branch or _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        remote_ref = f"{ns.remote}/{branch}" if ns.remote else "@{u}"
        before = _git(root, "rev-parse", "--verify", "-q", remote_ref, check=False).strip()
        _git(root, "push", *([ns.remote, branch] if ns.remote else []))
        after = _git(root, "rev-parse", "HEAD").strip()
        sent = _git(root, "rev-list", f"{before}..{after}").split() if before else None
        return {"repo": root, "branch": branch, "from": before or None, "to": after,
                "commits": len(sent) if sent is not None else None}
