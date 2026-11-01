"""Domain layer (task:a70134dd): graph/domains.json is valid against the closed
group set, and find_cli uses it to favour the domain a plain-words query means
without changing anything when it is off or no domain word matches."""
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import find_cli
from find_cli import rank
from graph import domains, groups

import test_find_cli

GROUPS = {"communication", "markets"}


class ValidateTest(unittest.TestCase):
    def test_committed_file_is_valid(self):
        self.assertEqual(domains.validate(domains.load(), set(groups.load()["groups"])), [])

    def test_names_a_domain_that_is_not_a_group(self):
        problems = domains.validate({"communication": ["mail"], "markets": ["stock"],
                                     "cooking": ["recipe"]}, GROUPS)
        self.assertEqual(problems, ["domain 'cooking': not a group in graph/groups.json"])

    def test_names_a_group_with_no_vocabulary(self):
        self.assertEqual(domains.validate({"communication": ["mail"]}, GROUPS),
                         ["group 'markets': has no domain vocabulary"])
        self.assertEqual(domains.validate({"communication": ["mail"], "markets": []}, GROUPS),
                         ["domain 'markets': needs at least one word"])

    def test_a_word_belongs_to_one_domain(self):
        problems = domains.validate({"communication": ["share"], "markets": ["share"]}, GROUPS)
        self.assertEqual(problems, ["word 'share': listed under 'communication' and 'markets'"])

    def test_main_exits_zero_on_the_committed_file(self):
        self.assertEqual(domains.main(), 0)


class FindWithDomainsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph, cls.edges = find_cli.load()
        cls.domains = domains.load()

    def test_plain_words_resolve_to_a_domain_and_are_reported(self):
        q = "ping my friend that I am late"
        self.assertNotIn("communication", q)
        r = find_cli.find(q, self.graph, self.edges, domains=self.domains)
        self.assertEqual(r["domains"], ["communication"])
        self.assertEqual(r["seeds"][0]["id"], "mac imessage send")

    def test_off_leaves_no_domains_key_and_same_output(self):
        for q in test_find_cli.FindOnCommittedGraphTest.PHRASES:
            off = find_cli.find(q, self.graph, self.edges)
            self.assertNotIn("domains", off)
            self.assertEqual(json.dumps(off),
                             json.dumps(find_cli.find(q, self.graph, self.edges, domains=None)))

    def test_no_domain_word_falls_back_to_keyword_ranking(self):
        for q in ("list my reminders", "zzzz nonsense", "what time is it"):
            if rank.resolve_domains(q, self.domains):
                continue
            on = find_cli.find(q, self.graph, self.edges, domains=self.domains)
            off = find_cli.find(q, self.graph, self.edges)
            self.assertEqual(on["domains"], [])
            self.assertEqual({k: v for k, v in on.items() if k != "domains"}, off, q)

    def test_a_named_area_is_not_diluted_by_its_domain(self):
        # "reminder" names the reminders area; boosting all of productivity too
        # would let calendar add_event catch up with reminders create.
        q = "add a reminder to rerun after CPI"
        on = rank.seeds(q, self.graph, self.edges, domains=self.domains)
        self.assertEqual(on, rank.seeds(q, self.graph, self.edges))

    def test_confidence_ignores_the_domain_boost(self):
        for q in test_find_cli.FindOnCommittedGraphTest.PHRASES + ["ping my friend that I am late"]:
            on = find_cli.find(q, self.graph, self.edges, domains=self.domains)
            off = find_cli.find(q, self.graph, self.edges)
            self.assertEqual(on["confidence"], off["confidence"], q)

    def test_guard_phrases_keep_their_seeds_with_the_layer_on(self):
        for phrase, want, within in test_find_cli.FindOnCommittedGraphTest.GUARDS:
            got = [c for c, _ in rank.seeds(phrase, self.graph, self.edges,
                                            domains=self.domains)][:within]
            self.assertIn(want, got, phrase)


if __name__ == "__main__":
    unittest.main()
