"""tools/cutover.py: removing and restoring the migrated servers' allow rules (task:8cd14cfe)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import cutover  # noqa: E402

SETTINGS = {
    "permissions": {
        "allow": [
            "Bash(git status)",
            "mcp__local-mac__calendar__list_events",
            "mcp__claude-hooks__memory__add",
            "mcp__wyckoff-analyzer__update_run",
            "Bash(mac calendar list_events *)",
            "mcp__astrology__chart",
            "mcp__sysml-mcp__parse",
            "mcp__local-mac-extra__x",
        ],
        "ask": ["Bash(mac mail compose *)"],
    },
    "other": {"kept": True},
}


class CutoverRulesTest(unittest.TestCase):
    def test_strip_removes_only_migrated_server_rules(self):
        out, removed = cutover.strip_rules(SETTINGS)
        self.assertEqual(removed, ["mcp__local-mac__calendar__list_events",
                                   "mcp__wyckoff-analyzer__update_run",
                                   "mcp__astrology__chart", "mcp__sysml-mcp__parse"])
        self.assertEqual(out["permissions"]["allow"], [
            "Bash(git status)", "mcp__claude-hooks__memory__add",
            "Bash(mac calendar list_events *)", "mcp__local-mac-extra__x"])
        self.assertEqual(out["permissions"]["ask"], SETTINGS["permissions"]["ask"])
        self.assertEqual(out["other"], SETTINGS["other"])

    def test_claude_hooks_cutover_strips_only_claude_hooks_rules(self):
        servers = cutover.CUTOVERS["299daf58"]
        out, removed = cutover.strip_rules(SETTINGS, servers)
        self.assertEqual(removed, ["mcp__claude-hooks__memory__add"])
        self.assertIn("mcp__astrology__chart", out["permissions"]["allow"])
        self.assertNotIn("mcp__claude-hooks__memory__add", out["permissions"]["allow"])

    def test_each_cutover_has_its_own_backup(self):
        paths = {cutover.backup_path(c) for c in cutover.CUTOVERS}
        self.assertEqual(len(paths), len(cutover.CUTOVERS))
        self.assertEqual(cutover.backup_path("9839b040").name, "cutover-9839b040-backup.json")

    def test_strip_does_not_mutate_input(self):
        before = cutover.render(SETTINGS)
        cutover.strip_rules(SETTINGS)
        self.assertEqual(cutover.render(SETTINGS), before)

    def test_restore_brings_every_rule_back_once(self):
        out, removed = cutover.strip_rules(SETTINGS)
        back = cutover.restore_rules(out, removed)
        self.assertEqual(sorted(back["permissions"]["allow"]), sorted(SETTINGS["permissions"]["allow"]))
        again = cutover.restore_rules(back, removed)
        self.assertEqual(again, back)

    def test_strip_is_a_no_op_after_cutover(self):
        out, _ = cutover.strip_rules(SETTINGS)
        self.assertEqual(cutover.strip_rules(out), (out, []))


if __name__ == "__main__":
    unittest.main()
