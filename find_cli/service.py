"""What the find_cli server and `mac cli find` share (task:d430f68b).

    Finder().answer(task, limit, hops, area)  ->  find()'s result, or
                                                  {"error": {code, message}}

Both entry points call this, so for the same input they return the same
result. The graph and edges are re-read when either file's mtime or size
changes, so a regenerated graph or an edited edges.json shows in the next
call. A file that fails to parse (half-written by graph.generate, say) keeps
the last good pair; only a first load with no good pair is an error. Usage
counts are read on every call. find() stays pure: reloading lives here.
"""
from graph.generate import GRAPH
from graph.validate_edges import EDGES
from mac.contract import error_object

from . import DEFAULT_LIMIT, find, load
from . import usage as _usage


def _stamp(*paths):
    return tuple((s.st_mtime_ns, s.st_size) for s in (p.stat() for p in paths))


class Finder:
    def __init__(self, graph_path=GRAPH, edges_path=EDGES):
        self.paths = (graph_path, edges_path)
        self.stamp = None
        self.pair = None

    def current(self):
        """(graph, edges): the last pair that parsed, refreshed if the files changed."""
        try:
            stamp = _stamp(*self.paths)
            if stamp != self.stamp:
                self.pair = load(*self.paths)
                self.stamp = stamp
        except (OSError, ValueError, KeyError):
            if self.pair is None:
                raise
        return self.pair

    def answer(self, task, limit=DEFAULT_LIMIT, hops=2, area=""):
        try:
            graph, edges = self.current()
            return find(task, graph, edges, limit=limit, hops=hops,
                        usage=_usage.load(), area=area or None)
        except Exception as exc:
            return error_object("internal", f"{type(exc).__name__}: {exc}")
