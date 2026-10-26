"""Argument handling, help and dispatch for `mac <area> <verb>`."""
import argparse
import sys

from mac.contract import (
    EXIT_OK, EXIT_USAGE, Failure, apply_limit, dump, error_object,
)
from mac.registry import Registry, load_groups

HELP_FLAGS = ("-h", "--help")


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Failure("usage", message, EXIT_USAGE)


def _positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}")
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def build_parser(verb):
    parser = _Parser(prog=f"mac {verb.area} {verb.name}", description=verb.desc)
    parser.add_argument("--limit", type=_positive_int, default=None,
                        help="max items for list results (default 100)")
    parser.add_argument("--json", action="store_true",
                        help="accepted for compatibility; output is always JSON")
    if verb.configure:
        verb.configure(parser)
    return parser


def usage_line(verb):
    text = build_parser(verb).format_usage().removeprefix("usage:")
    return " ".join(text.split())


def describe(registry, area=None):
    areas = [area] if area else registry.areas()
    return [
        {"area": v.area, "verb": v.name, "mode": v.mode, "desc": v.desc, "usage": usage_line(v)}
        for a in areas for v in registry.verbs(a)
    ]


def help_text(registry, area=None):
    if area is None:
        lines = ["usage: mac <area> <verb> [options]", "", "areas:"]
        lines += [f"  {a}  ({len(registry.verbs(a))} verbs)" for a in registry.areas()]
        lines += ["", "mac <area> --help lists verbs; mac --help --json lists everything."]
        return "\n".join(lines)
    lines = [f"mac {area} verbs:"]
    for v in registry.verbs(area):
        lines.append(f"  {v.name} [{v.mode}]  {v.desc}")
        lines.append(f"      {usage_line(v)}")
    return "\n".join(lines)


def default_registry():
    registry = Registry()
    load_groups(registry)
    return registry


def _run(args, registry, out, err):
    as_json = "--json" in args
    if not args or args[0] in HELP_FLAGS:
        print(dump(describe(registry)) if as_json else help_text(registry), file=out)
        return EXIT_OK

    area = args[0]
    if area not in registry.areas():
        raise Failure("unknown_area", f"unknown area {area!r}; run `mac --help`", EXIT_USAGE)
    rest = args[1:]
    if not rest or rest[0] in HELP_FLAGS or rest == ["--json"]:
        print(dump(describe(registry, area)) if as_json else help_text(registry, area), file=out)
        return EXIT_OK

    verb = registry.get(area, rest[0])
    if verb is None:
        raise Failure("unknown_verb", f"unknown verb {rest[0]!r} in {area!r}; run `mac {area} --help`",
                      EXIT_USAGE)
    ns = build_parser(verb).parse_args(rest[1:])
    try:
        result = verb.handler(ns)
    except Failure:
        raise
    except Exception as exc:
        raise Failure("internal", f"{type(exc).__name__}: {exc}")
    data, cut = apply_limit(result, ns.limit)
    print(dump(data), file=out)
    if cut:
        print(dump({"truncated": cut}), file=err)
    return EXIT_OK


def main(argv, registry=None, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    try:
        return _run(list(argv), registry or default_registry(), out, err)
    except Failure as failure:
        print(dump(error_object(failure.code, failure.message)), file=err)
        return failure.status
    except SystemExit as stop:  # argparse -h
        return stop.code or EXIT_OK
