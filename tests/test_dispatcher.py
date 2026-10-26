import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mac.cli import describe, main, usage_line
from mac.contract import DEFAULT_LIMIT, Failure, apply_limit, error_object
from mac.registry import Registry, load_groups


def make_registry():
    registry = Registry()

    @registry.verb("demo", "items", mode="read", desc="list n items",
                   args=lambda p: p.add_argument("--n", type=int, default=3))
    def items(ns):
        return list(range(ns.n))

    @registry.verb("demo", "echo", mode="write", desc="echo a word",
                   args=lambda p: p.add_argument("word"))
    def echo(ns):
        return {"word": ns.word}

    @registry.verb("demo", "denied", mode="read", desc="always fails")
    def denied(ns):
        raise Failure("denied", "not allowed", 3)

    @registry.verb("demo", "boom", mode="read", desc="raises unexpectedly")
    def boom(ns):
        raise KeyError("x")

    return registry


def run(*argv, registry=None):
    out, err = io.StringIO(), io.StringIO()
    status = main(list(argv), registry or make_registry(), out, err)
    return status, out.getvalue(), err.getvalue()


class ApplyLimitTest(unittest.TestCase):
    def test_short_list_untouched(self):
        self.assertEqual(apply_limit([1, 2], 5), ([1, 2], None))

    def test_long_list_cut_and_reported(self):
        self.assertEqual(apply_limit([1, 2, 3], 2), ([1, 2], {"shown": 2, "total": 3}))

    def test_default_limit_applies_when_unset(self):
        data, cut = apply_limit(list(range(DEFAULT_LIMIT + 1)), None)
        self.assertEqual(len(data), DEFAULT_LIMIT)
        self.assertEqual(cut["total"], DEFAULT_LIMIT + 1)

    def test_non_list_never_cut(self):
        self.assertEqual(apply_limit({"a": 1}, 1), ({"a": 1}, None))


class RegistryTest(unittest.TestCase):
    def test_bad_mode_rejected(self):
        with self.assertRaises(ValueError):
            Registry().verb("a", "b", mode="rw", desc="x")

    def test_duplicate_rejected(self):
        registry = Registry()
        registry.verb("a", "b", mode="read", desc="x")(lambda ns: 1)
        with self.assertRaises(ValueError):
            registry.verb("a", "b", mode="read", desc="x")(lambda ns: 1)

    def test_areas_and_verbs_sorted(self):
        registry = make_registry()
        self.assertEqual(registry.areas(), ["demo"])
        self.assertEqual([v.name for v in registry.verbs("demo")], ["boom", "denied", "echo", "items"])


class DescribeTest(unittest.TestCase):
    def test_usage_line_derives_from_parser(self):
        verb = make_registry().get("demo", "echo")
        self.assertIn("mac demo echo", usage_line(verb))
        self.assertIn("word", usage_line(verb))
        self.assertNotIn("\n", usage_line(verb))

    def test_describe_exposes_mode(self):
        modes = {d["verb"]: d["mode"] for d in describe(make_registry())}
        self.assertEqual(modes["echo"], "write")
        self.assertEqual(modes["items"], "read")


class DispatchTest(unittest.TestCase):
    def test_success_prints_json_exit_zero(self):
        status, out, err = run("demo", "echo", "hi")
        self.assertEqual((status, json.loads(out), err), (0, {"word": "hi"}, ""))

    def test_json_flag_is_accepted_noop(self):
        status, out, _ = run("demo", "echo", "hi", "--json")
        self.assertEqual((status, json.loads(out)), (0, {"word": "hi"}))

    def test_limit_truncates_and_notes_on_stderr(self):
        status, out, err = run("demo", "items", "--n", "5", "--limit", "2")
        self.assertEqual((status, json.loads(out)), (0, [0, 1]))
        self.assertEqual(json.loads(err), {"truncated": {"shown": 2, "total": 5}})

    def test_bad_limit_is_usage_error(self):
        status, out, err = run("demo", "items", "--limit", "0")
        self.assertEqual((status, out), (2, ""))
        self.assertEqual(json.loads(err)["error"]["code"], "usage")

    def test_failure_object_and_status(self):
        status, out, err = run("demo", "denied")
        self.assertEqual((status, out), (3, ""))
        self.assertEqual(json.loads(err), error_object("denied", "not allowed"))

    def test_unexpected_exception_is_internal_error(self):
        status, _, err = run("demo", "boom")
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "internal")

    def test_unknown_area_and_verb(self):
        for argv, code in ((("nope",), "unknown_area"), (("demo", "nope"), "unknown_verb")):
            status, _, err = run(*argv)
            self.assertEqual(status, 2)
            self.assertEqual(json.loads(err)["error"]["code"], code)

    def test_missing_argument_is_usage_error(self):
        status, _, err = run("demo", "echo")
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(err)["error"]["code"], "usage")


class HelpTest(unittest.TestCase):
    def test_top_help_lists_areas(self):
        status, out, _ = run("--help")
        self.assertEqual(status, 0)
        self.assertIn("demo", out)

    def test_area_help_lists_verbs_with_mode_and_usage(self):
        status, out, _ = run("demo", "--help")
        self.assertEqual(status, 0)
        self.assertIn("echo [write]", out)
        self.assertIn("mac demo items", out)

    def test_help_json_is_machine_readable(self):
        status, out, _ = run("--help", "--json")
        entries = json.loads(out)
        self.assertEqual(status, 0)
        self.assertEqual({e["verb"] for e in entries}, {"boom", "denied", "echo", "items"})
        self.assertTrue(all({"area", "verb", "mode", "desc", "usage"} <= e.keys() for e in entries))

    def test_area_help_json_scoped_to_area(self):
        _, out, _ = run("demo", "--json")
        self.assertTrue(all(e["area"] == "demo" for e in json.loads(out)))

    def test_verb_help_exits_zero(self):
        with contextlib.redirect_stdout(io.StringIO()):
            status = main(["demo", "echo", "-h"], make_registry(), io.StringIO(), io.StringIO())
        self.assertEqual(status, 0)


@contextlib.contextmanager
def group_package(name, modules):
    """Importable temp package whose modules are given as {file name: source}."""
    with tempfile.TemporaryDirectory() as tmp:
        pkg = Path(tmp) / name
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        for file, source in modules.items():
            (pkg / file).write_text(source)
        sys.path.insert(0, tmp)
        try:
            yield name
        finally:
            sys.path.remove(tmp)
            for loaded in [m for m in sys.modules if m.startswith(name)]:
                del sys.modules[loaded]


class GroupDiscoveryTest(unittest.TestCase):
    def test_new_group_needs_only_its_own_module(self):
        modules = {
            "extra.py": "def register(registry):\n"
                        "    registry.verb('extra', 'hello', mode='read', desc='hi')(lambda ns: 'hello')\n",
            "_private.py": "raise RuntimeError('must not be imported')\n",
        }
        registry = Registry()
        with group_package("fake_groups", modules) as package:
            load_groups(registry, package=package)
        self.assertIsNotNone(registry.get("extra", "hello"))

    def test_group_without_register_fails_loudly(self):
        with group_package("bad_groups", {"broken.py": "X = 1\n"}) as package:
            with self.assertRaises(RuntimeError):
                load_groups(Registry(), package=package)


if __name__ == "__main__":
    unittest.main()
