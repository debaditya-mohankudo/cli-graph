"""Area groups: graph/groups.json is valid, and find_cli uses it to reach
neighbouring areas and to favour a group a query names."""
import copy
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from find_cli import expand, rank
from graph import groups

from test_find_cli import TOY, TOY_EDGES

AREAS = ["contacts", "imessage", "mail", "astrology"]
SPEC = {"groups": {"communication": ["contacts", "imessage", "mail"]},
        "ungrouped": ["astrology"]}


def with_groups(graph, area_to_group):
    g = copy.deepcopy(graph)
    for area, group in area_to_group.items():
        g["nodes"].append({"id": f"group:{group}", "kind": "group", "name": group})
        g["edges"].append({"from": f"domain:{area}", "to": f"group:{group}", "type": "in_group"})
    return g


GROUPED = with_groups(TOY, {"contacts": "communication", "imessage": "communication"})


class ValidateTest(unittest.TestCase):
    def test_committed_groups_cover_every_area_once(self):
        graph = json.loads((REPO / "graph" / "cli_graph.json").read_text())
        graph_areas = sorted({n["area"] for n in graph["nodes"] if n["kind"] == "command"})
        self.assertEqual(groups.validate(groups.load(), graph_areas), [])

    def test_a_valid_spec_passes(self):
        self.assertEqual(groups.validate(SPEC, AREAS), [])

    def test_an_area_left_out_fails(self):
        self.assertEqual(groups.validate(SPEC, AREAS + ["vault"]),
                         ["area 'vault' is in no group and not in ungrouped"])

    def test_an_area_in_two_places_fails(self):
        spec = copy.deepcopy(SPEC)
        spec["ungrouped"].append("mail")
        self.assertEqual(len(groups.validate(spec, AREAS)), 1)

    def test_an_unknown_area_fails(self):
        spec = copy.deepcopy(SPEC)
        spec["groups"]["communication"].append("fax")
        self.assertEqual(groups.validate(spec, AREAS), ["group 'communication': 'fax' is not a CLI area"])

    def test_a_one_area_group_and_a_bad_name_fail(self):
        spec = {"groups": {"Comms": ["contacts"], "messaging": ["imessage", "mail"]},
                "ungrouped": ["astrology"]}
        self.assertEqual(len(groups.validate(spec, AREAS)), 2)

    def test_command_groups_skips_ungrouped_areas(self):
        got = groups.command_groups(GROUPED)
        self.assertEqual(got["mac contacts search"], "communication")
        self.assertNotIn("mac vault read", got)


class GroupExpandTest(unittest.TestCase):
    def test_group_neighbours_come_from_other_areas_and_need_a_score(self):
        scores = {"mac imessage send": 1.0, "mac imessage read": 0.5}
        out = expand.expand(["mac contacts search"], GROUPED, [], scores=scores, siblings=0)
        self.assertEqual(out, [
            {"id": "mac imessage send", "via": "in_group", "dir": "group",
             "from": "mac contacts search", "hop": 2},
            {"id": "mac imessage read", "via": "in_group", "dir": "group",
             "from": "mac contacts search", "hop": 2}])

    def test_zero_scores_and_ungrouped_seeds_add_nothing(self):
        self.assertEqual(expand.expand(["mac contacts search"], GROUPED, [], siblings=0), [])
        out = expand.expand(["mac vault read"], GROUPED, [], scores={"mac imessage send": 1.0},
                            siblings=0)
        self.assertEqual(out, [])

    def test_group_siblings_are_capped(self):
        scores = {"mac imessage send": 1.0, "mac imessage read": 0.5}
        out = expand.expand(["mac contacts search"], GROUPED, [], scores=scores, siblings=0,
                            group_siblings=1)
        self.assertEqual([n["id"] for n in out], ["mac imessage send"])


class GroupBoostTest(unittest.TestCase):
    def test_naming_a_group_boosts_only_matching_commands_in_it(self):
        docs = rank.documents(GROUPED)
        cg = groups.command_groups(GROUPED)
        plain = rank.scores("read", docs, cg)
        named = rank.scores("read communication", docs, cg)
        self.assertGreater(named["mac imessage read"], plain["mac imessage read"])
        self.assertEqual(named["mac vault read"], plain["mac vault read"])
        self.assertEqual(named["mac contacts get"], 0.0)

    def test_plural_group_word_also_boosts(self):
        docs = rank.documents(GROUPED)
        cg = groups.command_groups(GROUPED)
        self.assertGreater(rank.scores("read communications", docs, cg)["mac imessage read"],
                           rank.scores("read", docs, cg)["mac imessage read"])


if __name__ == "__main__":
    unittest.main()
