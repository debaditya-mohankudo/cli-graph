"""Hand-written search tags per command (task:802cfc3e).

    {"about": "...", "tags": {"<command id>": ["word", ...], ...}}

A tag is a word a task uses for a command whose description lacks it ("text"
for imessage send). find_cli.rank.documents() adds a command's tags to its
BM25 document beside the alias verbs, so closing a wording gap needs neither a
reworded desc nor a fake alias edge. cli_graph.json is not touched.

Tags rank; they never certify. confidence() reads documents without them
(lesson find-cli-boosts-must-not-feed-confidence), so a tag-only hit shows
low confidence.

Rules, each checked by validate():
  - every key is a command node of the committed graph;
  - a command has at least one tag; tags are non-empty lowercase
    alphanumeric words, unique within the command.

    uv run python -m graph.tags     # exit 1 and name each problem
"""
import json
import re
import sys
from pathlib import Path

from graph.generate import GRAPH
from graph.validate_edges import command_ids

TAGS = Path(__file__).resolve().parent / "tags.json"
WORD = re.compile(r"[a-z0-9]+")


def load(path=TAGS):
    """{command id: [tag, ...]} from a tags file; {} when the file is missing."""
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text())["tags"]


def validate(tags, graph):
    """Problems with tags against this graph; [] when valid."""
    commands = command_ids(graph)
    problems = []
    for cid in tags:
        words = tags[cid]
        if cid not in commands:
            problems.append(f"tags {cid!r}: not a command in the graph")
        if not isinstance(words, list) or not words:
            problems.append(f"tags {cid!r}: needs a non-empty list of words")
            continue
        for w in words:
            if not isinstance(w, str) or not WORD.fullmatch(w):
                problems.append(f"tags {cid!r}: {w!r} is not a lowercase alphanumeric word")
        if len(set(words)) != len(words):
            problems.append(f"tags {cid!r}: duplicate word")
    return problems


def main():
    problems = validate(load(), json.loads(GRAPH.read_text()))
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
