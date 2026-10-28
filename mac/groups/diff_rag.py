"""`mac diff_rag` — semantic search over a repo's indexed git diffs, wrapping claude-hooks' diff_rag__* handlers.

Answers "which commit changed X" from the diff hunks, not from the current code.
"""
import argparse

from mac.groups._backend import given
from mac.groups._hooks import call

UNSET = argparse.SUPPRESS


def register(registry):
    def repo_k(p):
        p.add_argument("--repo", default=UNSET, help="absolute path of the repo (default: claude-hooks)")
        p.add_argument("--k", type=int, default=UNSET, help="number of results (default 5)")

    def query_args(p):
        p.add_argument("query")
        repo_k(p)

    def smart_args(p):
        query_args(p)
        p.add_argument("--author", default=UNSET, help="only commits by this author")
        p.add_argument("--file-pattern", default=UNSET, help="only hunks in files matching this glob")

    def index_args(p):
        p.add_argument("--repo", default=UNSET, help="absolute path of the repo (default: claude-hooks)")
        p.add_argument("--since", default=UNSET, help="only commits after this date or ref")
        p.add_argument("--max-commits", type=int, default=UNSET, help="stop after this many commits (0 = all)")

    @registry.verb("diff_rag", "query", mode="read",
                   desc="which commit changed something: semantic search over a repo's git diff history",
                   args=query_args)
    def query(ns):
        return call("diff_rag", "query", **given(ns, ("query", "repo", "k")))

    @registry.verb("diff_rag", "smart_search", mode="read",
                   desc="search git diff history filtered by author or file pattern",
                   args=smart_args)
    def smart_search(ns):
        return call("diff_rag", "smart_search", **given(ns, ("query", "repo", "k", "author", "file_pattern")))

    @registry.verb("diff_rag", "index_commits", mode="write",
                   desc="build or update a repo's git diff search index from its commits",
                   args=index_args)
    def index_commits(ns):
        return call("diff_rag", "index_commits", **given(ns, ("repo", "since", "max_commits")))
