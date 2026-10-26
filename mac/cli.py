"""Argument handling, help and dispatch for `mac <area> <verb>`."""
import argparse
import json
import re
import sys
from datetime import date, datetime

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


def _json_of(pytype, label):
    def parse(text):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise argparse.ArgumentTypeError(f"not valid JSON: {exc}")
        if not isinstance(value, pytype):
            raise argparse.ArgumentTypeError(f"must be a JSON {label}")
        return value
    return parse


# argparse types for a dict or list parameter passed as a JSON string.
json_object = _json_of(dict, "object")
json_list = _json_of(list, "array")


_YMD = re.compile(r"\d{4}-\d{2}-\d{2}")


def iso_date(text):
    """argparse type for local-mac's IsoDate: YYYY-MM-DD and a real calendar day."""
    if not _YMD.fullmatch(text):  # date.fromisoformat also takes 20261027 and 2026-W44-2
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a valid YYYY-MM-DD date: {text!r} ({exc})")
    return text


def iso_datetime(text):
    """argparse type for local-mac's IsoDateTime: a YYYY-MM-DD date or an ISO-8601 date-time.

    Date and time must be joined with 'T': the handlers read a value without
    one as a bare date. tests/test_arg_types.py holds this and iso_date to the
    same verdicts as local-mac's tools/arg_types.py.
    """
    if len(text) == 10:
        return iso_date(text)
    if text[10:11] == " ":
        raise argparse.ArgumentTypeError(
            f"join date and time with 'T', e.g. 2026-10-27T15:00:00: {text!r}")
    if text[10:11] != "T":
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date or ISO-8601 date-time: {text!r}")
    iso_date(text[:10])
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a valid ISO-8601 date-time: {text!r} ({exc})")
    return text


# A date `format` (local-mac's IsoDate / IsoDateTime annotation, or a proxied
# server's JSON schema) -> the argparse type above that checks it. Read by
# tools/gen_groups.py and tools/gen_mcp_groups.py.
FORMAT_TYPES = {"date": "iso_date", "date-or-datetime": "iso_datetime"}


def int_or_str(text):
    """argparse type for an integer-or-string parameter: digits become an int."""
    return int(text) if text.lstrip("-").isdigit() else text


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
