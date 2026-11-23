"""mac cli skills: scan, frontmatter parsing, filters. Synthetic fixtures only."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mac.groups import cli


def skill(root, dirname, body):
    d = Path(root) / dirname
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body)
    return d


class SkillsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        g = self.home / ".claude" / "skills"
        skill(g, "alpha", "---\nname: alpha\ndescription: Does the alpha thing\n---\nbody")
        skill(g, "folded", "---\nname: folded\ndescription: >\n  first line\n  second line\n---\n")
        (g / "nodoc").mkdir()
        low = g / "lower"
        low.mkdir()
        (low / "skill.md").write_text("---\nname: lower\ndescription: lowercase file\n---\n")
        skill(g, "broken", "no frontmatter")
        skill(self.home / "workspace" / "proj" / ".claude", "skills/beta", "---\nname: beta\ndescription: beta tool\n---\n")
        self.target = Path(self.tmp.name) / "elsewhere"
        skill(self.target, "linked", "---\nname: linked\ndescription: via symlink\n---\n")
        os.symlink(self.target / "linked", g / "linked")
        p = mock.patch.object(Path, "home", return_value=self.home)
        p.start()
        self.addCleanup(p.stop)

    def run_verb(self, **kw):
        ns = SimpleNamespace(**{"query": "", "name": "", "scope": "", **kw})
        reg = mock.MagicMock()
        fns = {}
        reg.verb.side_effect = lambda a, n, **k: (lambda f: fns.setdefault(n, f) or f)
        cli.register(reg)
        return fns["skills"](ns)

    def test_lists_global_and_project_skips_dirs_without_skill_md(self):
        names = {(r["name"], r["scope"]) for r in cli.list_skills()}
        self.assertEqual(names, {("alpha", "global"), ("folded", "global"), ("linked", "global"), ("lower", "global"), ("beta", "proj")})

    def test_block_scalar_description_is_one_line(self):
        row = next(r for r in cli.list_skills() if r["name"] == "folded")
        self.assertEqual(row["description"], "first line second line")

    def test_filters(self):
        self.assertEqual([r["name"] for r in self.run_verb(name="beta")["skills"]], ["beta"])
        self.assertEqual({r["scope"] for r in self.run_verb(scope="proj")["skills"]}, {"proj"})
        self.assertEqual(self.run_verb(query="ALPHA thing")["count"], 1)
        self.assertEqual(self.run_verb(query="nomatch")["count"], 0)

    def test_read_only(self):
        before = sorted(str(p) for p in self.home.rglob("*"))
        self.run_verb()
        self.assertEqual(before, sorted(str(p) for p in self.home.rglob("*")))


if __name__ == "__main__":
    unittest.main()
