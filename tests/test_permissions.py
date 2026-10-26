"""Permission rules for `mac` follow the graph and the hand-reviewed ask set (task:0aa96180)."""
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))  # `tools` alone is local-mac's package

import gen_permissions as gp  # noqa: E402

GRAPH = json.loads(gp.GRAPH.read_text())
COMMANDS = gp.commands(GRAPH)


def graph_with(*extra):
    g = json.loads(json.dumps(GRAPH))
    for area, verb in extra:
        g["nodes"].append({"kind": "command", "id": f"mac {area} {verb}", "area": area, "verb": verb})
    return g


class RulesTest(unittest.TestCase):
    def test_every_command_gets_exactly_one_decision(self):
        allow, ask = gp.rules(GRAPH)
        for area, verb in COMMANDS:
            asked = f"Bash(mac {area} {verb} *)" in ask
            allowed = f"Bash(mac {area} {verb} *)" in allow
            self.assertTrue(asked != allowed, f"mac {area} {verb}: ask={asked} allow={allowed}")

    def test_the_user_ask_set_prompts(self):
        _, ask = gp.rules(GRAPH)
        for cmd in ("imessage send", "mail compose", "mail delete", "mail move", "calendar delete_event",
                    "notes delete", "reminders delete", "vault delete", "vault move",
                    "safari close_all_tabs", "system process_kill", "system sleep_now",
                    "connector execute_action", "vpn disconnect"):
            self.assertIn(f"Bash(mac {cmd} *)", ask)

    def test_reads_and_non_destructive_writes_are_allowed(self):
        allow, _ = gp.rules(GRAPH)
        for cmd in ("mail read", "vault write", "vault append", "wyckoff db_init_state",
                    "calendar add_event", "reminders create"):
            self.assertIn(f"Bash(mac {cmd} *)", allow)

    def test_an_ask_verb_prompts_under_every_launcher_form(self):
        _, ask = gp.rules(GRAPH)
        for launcher in ("mac", "~/bin/mac", str(Path.home() / "bin" / "mac"), str(REPO / "bin" / "mac")):
            self.assertIn(f"Bash({launcher} imessage send *)", ask)

    def test_a_new_verb_is_allowed(self):
        allow, _ = gp.rules(graph_with(("mail", "brand_new")))
        self.assertIn("Bash(mac mail brand_new *)", allow)

    def test_an_ask_entry_the_graph_lacks_is_an_error(self):
        g = json.loads(json.dumps(GRAPH))
        g["nodes"] = [n for n in g["nodes"] if n.get("id") != "mac imessage send"]
        with self.assertRaises(SystemExit) as e:
            gp.rules(g)
        self.assertIn("imessage send", str(e.exception))


class ApplyTest(unittest.TestCase):
    SETTINGS = {"permissions": {
        "allow": ["Bash(git status)", "Bash(mac mail gone_verb *)", "Bash(mac --help)", "mcp__taskfw__tasks__get"],
        "ask": ["Bash(~/bin/mac imessage removed *)"],
        "defaultMode": "auto"},
        "hooks": {"x": 1}}

    def test_other_rules_and_keys_are_kept_in_place(self):
        out = gp.apply(self.SETTINGS, GRAPH)
        self.assertEqual(out["permissions"]["allow"][:3], ["Bash(git status)", "Bash(mac --help)",
                                                          "mcp__taskfw__tasks__get"])
        self.assertEqual(out["permissions"]["defaultMode"], "auto")
        self.assertEqual(out["hooks"], {"x": 1})

    def test_rules_for_removed_verbs_are_dropped(self):
        out = gp.apply(self.SETTINGS, GRAPH)
        flat = out["permissions"]["allow"] + out["permissions"]["ask"]
        self.assertNotIn("Bash(mac mail gone_verb *)", flat)
        self.assertNotIn("Bash(~/bin/mac imessage removed *)", flat)

    def test_apply_is_idempotent_and_does_not_mutate_its_input(self):
        before = json.dumps(self.SETTINGS)
        once = gp.apply(self.SETTINGS, GRAPH)
        self.assertEqual(gp.apply(once, GRAPH), once)
        self.assertEqual(json.dumps(self.SETTINGS), before)


@unittest.skipUnless(gp.SETTINGS.exists(), "no ~/.claude/settings.json on this machine")
class LiveSettingsTest(unittest.TestCase):
    def test_settings_json_rules_are_current(self):
        self.assertEqual(gp.main(["--check"]), 0,
                         "mac permission rules in ~/.claude/settings.json are stale; "
                         "run `uv run python tools/gen_permissions.py`")


if __name__ == "__main__":
    unittest.main()
