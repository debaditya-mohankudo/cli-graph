"""`mac code_rag` — semantic and symbol search over a repo's code index, wrapping claude-hooks' code_rag__* handlers.

The index lives in the repo (`.code_embeddings.*`, `.code_graph.json`); a repo
with no index answers with an 'index not found' text, as the MCP tool did.
"""
import argparse

from mac.groups._backend import given
from mac.groups._hooks import call

UNSET = argparse.SUPPRESS


def register(registry):
    def search_args(p):
        p.add_argument("query")
        p.add_argument("--repo", default=UNSET, help="absolute path of the repo (default: claude-hooks)")
        p.add_argument("--k", type=int, default=UNSET, help="number of results (default 5)")

    @registry.verb("code_rag", "query", mode="read",
                   desc="semantic search over a repo's code: find functions and files by what they do",
                   args=search_args)
    def query(ns):
        return call("code_rag", "query", **given(ns, ("query", "repo", "k")))

    @registry.verb("code_rag", "smart_search", mode="read",
                   desc="find a symbol or concept in a repo's code: name lookup first, semantic rerank after",
                   args=search_args)
    def smart_search(ns):
        return call("code_rag", "smart_search", **given(ns, ("query", "repo", "k")))

    def index_args(p):
        p.add_argument("files", nargs="+", help="repo-relative file paths")
        p.add_argument("--repo", default=UNSET, help="absolute path of the repo (default: claude-hooks)")

    @registry.verb("code_rag", "index_files", mode="write",
                   desc="re-index specific files of a repo into its code search index",
                   args=index_args)
    def index_files(ns):
        return call("code_rag", "index_files", **given(ns, ("files", "repo")))
