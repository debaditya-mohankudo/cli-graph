"""`mac git` keeps its promises against a real temporary repo and a real bare remote (task:fcc92c98)."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mac.cli import default_registry, main  # noqa: E402

TASK = "task:fcc92c98"


def git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=True).stdout


def mac(*argv):
    out, err = io.StringIO(), io.StringIO()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        status = main(list(argv), default_registry(), out, err)
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return status, out.getvalue(), err.getvalue()


class GitVerbsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.remote, self.repo = base / "remote.git", base / "repo"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        git(self.repo, "remote", "add", "origin", str(self.remote))
        (self.repo / "a.txt").write_text("a\n")
        (self.repo / "b.txt").write_text("b\n")
        git(self.repo, "add", "a.txt", "b.txt")
        git(self.repo, "commit", "-q", "-m", f"{TASK} seed")
        git(self.repo, "push", "-q", "-u", "origin", "main")

    def tearDown(self):
        self._tmp.cleanup()

    def run_ok(self, *argv):
        status, out, err = mac(*argv, "--repo", str(self.repo))
        self.assertEqual(status, 0, err)
        return json.loads(out)

    def test_status_reports_branch_and_changed_files(self):
        (self.repo / "a.txt").write_text("changed\n")
        (self.repo / "new.txt").write_text("n\n")
        s = self.run_ok("git", "status")
        self.assertEqual((s["branch"], s["upstream"], s["ahead"]), ("main", "origin/main", 0))
        self.assertEqual({(f["status"], f["path"]) for f in s["files"]}, {(" M", "a.txt"), ("??", "new.txt")})

    def test_diff_shows_patch_and_staged_split(self):
        (self.repo / "a.txt").write_text("changed\n")
        self.assertIn("+changed", self.run_ok("git", "diff")["diff"])
        self.assertEqual(self.run_ok("git", "diff", "--staged")["diff"], "")
        self.run_ok("git", "add", "a.txt")
        self.assertIn("+changed", self.run_ok("git", "diff", "--staged")["diff"])

    def test_log_lists_recent_commits(self):
        rows = self.run_ok("git", "log", "-n", "5")
        self.assertEqual([r["subject"] for r in rows], [f"{TASK} seed"])

    def test_add_stages_only_the_named_paths(self):
        (self.repo / "a.txt").write_text("1\n")
        (self.repo / "b.txt").write_text("2\n")
        self.assertEqual(self.run_ok("git", "add", "a.txt")["staged"], ["a.txt"])

    def test_add_has_no_stage_everything_form(self):
        status, _, err = mac("git", "add", "--repo", str(self.repo))
        self.assertEqual(status, 2, err)

    def test_commit_takes_only_what_is_staged(self):
        (self.repo / "a.txt").write_text("1\n")
        (self.repo / "b.txt").write_text("2\n")
        self.run_ok("git", "add", "a.txt")
        done = self.run_ok("git", "commit", "-m", f"{TASK} stage a only")
        self.assertEqual(done["files"], ["a.txt"])
        self.assertEqual(git(self.repo, "status", "--short").strip(), "M b.txt")

    def test_commit_with_paths_leaves_other_staged_changes_alone(self):
        (self.repo / "a.txt").write_text("1\n")
        (self.repo / "b.txt").write_text("2\n")
        git(self.repo, "add", "a.txt", "b.txt")
        done = self.run_ok("git", "commit", "-m", f"{TASK} just b", "b.txt")
        self.assertEqual(done["files"], ["b.txt"])
        self.assertEqual(git(self.repo, "diff", "--cached", "--name-only").split(), ["a.txt"])

    def test_commit_without_task_ref_is_refused_and_commits_nothing(self):
        (self.repo / "a.txt").write_text("1\n")
        self.run_ok("git", "add", "a.txt")
        status, _, err = mac("git", "commit", "-m", "no reference here", "--repo", str(self.repo))
        self.assertEqual(status, 1)
        self.assertIn("task:<id>", json.loads(err)["error"]["message"])
        self.assertEqual(len(git(self.repo, "log", "--oneline").splitlines()), 1)

    def test_commit_with_nothing_staged_fails(self):
        status, _, err = mac("git", "commit", "-m", f"{TASK} empty", "--repo", str(self.repo))
        self.assertEqual(status, 1)
        self.assertIn("nothing staged", json.loads(err)["error"]["message"])

    def test_push_reports_branch_and_commit_count(self):
        for i in (1, 2):
            (self.repo / "a.txt").write_text(f"{i}\n")
            self.run_ok("git", "add", "a.txt")
            self.run_ok("git", "commit", "-m", f"{TASK} change {i}")
        self.assertEqual(self.run_ok("git", "status")["ahead"], 2)
        pushed = self.run_ok("git", "push")
        self.assertEqual((pushed["branch"], pushed["commits"]), ("main", 2))
        self.assertEqual(self.run_ok("git", "status")["ahead"], 0)

    def test_failed_push_exits_nonzero_with_the_reason(self):
        status, _, err = mac("git", "push", "nowhere", "main", "--repo", str(self.repo))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(err)["error"]["code"], "tool_error")

    def test_not_a_repo_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as d:
            status, _, err = mac("git", "status", "--repo", d)
        self.assertEqual(status, 1)
        self.assertIn("not a git repository", json.loads(err)["error"]["message"])


if __name__ == "__main__":
    unittest.main()
