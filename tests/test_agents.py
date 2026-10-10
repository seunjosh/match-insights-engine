"""Tests for the writers, fact-checker and pipeline. Run: python -m unittest discover -s tests -t ."""
import copy
import unittest

from agents.factcheck import FactChecker
from agents.pipeline import run
from agents.writers import LocalWriter, OpenAICompatibleWriter
from engine.moments import detect_all
from synth_match import Match

SEEDS = (2, 9, 23)   # includes goal-heavy matches; seed 5 is a 0-0 and has no goals


def build(seed):
    match = Match(seed)
    match.run()
    return match, detect_all(match.events, match.teams), FactChecker(match.events, match.teams)


class GroundingTests(unittest.TestCase):
    def setUp(self):
        self.cases = [build(s) for s in SEEDS]

    def test_detector_facts_match_the_raw_events(self):
        for _, overlays, checker in self.cases:
            for o in overlays:
                self.assertEqual(checker.check_facts(o), [], o["id"])

    def test_detector_template_text_passes(self):
        for _, overlays, checker in self.cases:
            for o in overlays:
                self.assertEqual(checker.check_text(o, o["text"]), [], o["id"])

    def test_both_writer_modes_pass_the_checker(self):
        for match, overlays, checker in self.cases:
            writer = LocalWriter(match.teams)
            for o in overlays:
                for mode in ("analyst", "casual"):
                    self.assertEqual(checker.check_text(o, writer.write(o, mode)), [],
                                     f'{o["id"]} {mode}')

    def test_tampered_facts_are_caught(self):
        match, overlays, checker = self.cases[1]
        goal = next(o for o in overlays if o["kind"] == "goal")
        window = next(o for o in overlays if o["kind"] == "state_shift")
        for o, key, bump in ((goal, "score_home", 1), (window, "turnovers_per_min", 1.0)):
            bad = copy.deepcopy(o)
            bad["facts"][key] += bump
            self.assertTrue(checker.check_facts(bad), key)

    def test_sources_from_the_future_are_rejected(self):
        match, overlays, checker = self.cases[0]
        bad = copy.deepcopy(overlays[0])
        bad["source_event_ids"] = bad["source_event_ids"] + [bad["last_event_id"] + 1]
        self.assertTrue(any("after the overlay" in i for i in checker.check_facts(bad)))

    def test_wrong_trigger_event_is_rejected(self):
        match, overlays, checker = self.cases[1]
        goal = copy.deepcopy(next(o for o in overlays if o["kind"] == "goal"))
        other = next(e for e in match.events if e["type"] == "pass")
        goal["last_event_id"] = other["event_id"]
        self.assertTrue(checker.check_facts(goal))


class FaultTests(unittest.TestCase):
    """The checker must reject captions that a writer got wrong."""

    def setUp(self):
        self.cases = [build(s) for s in SEEDS]

    def corrupted(self, fault):
        for match, overlays, checker in self.cases:
            writer = LocalWriter(match.teams)
            for o in overlays:
                if fault not in writer._faults_for(o):
                    continue
                for mode in ("analyst", "casual"):
                    clean = writer.write(o, mode)
                    bad = getattr(writer, "_fault_" + fault)(clean, o)
                    if bad != clean:
                        yield checker, o, bad

    def assert_all_rejected(self, fault):
        count = 0
        for checker, o, bad in self.corrupted(fault):
            count += 1
            self.assertTrue(checker.check_text(o, bad), f"{fault} not caught: {bad}")
        self.assertGreater(count, 10)

    def test_invented_statistic_is_caught(self):
        self.assert_all_rejected("claim")

    def test_wrong_player_or_team_is_caught(self):
        self.assert_all_rejected("entity")

    def test_wrong_goal_situation_is_caught(self):
        self.assert_all_rejected("situation")

    def test_goal_claimed_on_a_missed_chance_is_caught(self):
        self.assert_all_rejected("outcome")

    def test_nearly_all_altered_numbers_are_caught(self):
        total = caught = 0
        for checker, o, bad in self.corrupted("number"):
            total += 1
            caught += bool(checker.check_text(o, bad))
        self.assertGreater(total, 50)
        self.assertGreaterEqual(caught / total, 0.9)

    def test_wrong_scoreline_is_caught(self):
        match, overlays, checker = self.cases[1]
        o = next(x for x in overlays if x["kind"] == "goal")
        codes = match.teams
        bad = (f'{o["facts"]["scorer"]} scores for {codes["home"]["name"]}: '
               f'{codes["home"]["code"]} {o["facts"]["score_home"] + 1}-{o["facts"]["score_away"]} '
               f'{codes["away"]["code"]}.')
        self.assertTrue(checker.check_text(o, bad))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.match, self.overlays, self.checker = build(23)

    def test_clean_writer_is_accepted_first_try(self):
        results, summary = run(self.overlays, self.match.events, self.match.teams,
                               LocalWriter(self.match.teams), "analyst")
        self.assertTrue(all(r["verified"] for r in results))
        self.assertEqual(summary["first_try"], summary["total"])

    def test_faulty_writer_is_corrected_by_the_retry_loop(self):
        writer = LocalWriter(self.match.teams, fault_rate=1.0, seed=3)
        results, summary = run(self.overlays, self.match.events, self.match.teams, writer, "casual")
        self.assertTrue(all(r["verified"] for r in results))
        self.assertGreater(summary["fixed_by_retry"], 0)
        for r in results:
            self.assertEqual(self.checker.check_text(r, r["text"]), [])
            if r["attempts"] > 1:
                self.assertFalse(r["check_log"][0]["ok"])
                self.assertTrue(r["check_log"][-1]["ok"])

    def test_stubborn_writer_falls_back_to_the_checked_template(self):
        class Stubborn:
            name = "stubborn"

            def write(self, o, mode, feedback=None):
                return o["text"] + " That is the 137th shot on target this season."

        results, summary = run(self.overlays, self.match.events, self.match.teams, Stubborn())
        self.assertEqual(summary["fallback"], summary["total"])
        for r, o in zip(results, self.overlays):
            self.assertTrue(r["verified"])
            self.assertEqual(r["text"], o["text"])

    def test_overlay_with_wrong_facts_is_held_back(self):
        bad = copy.deepcopy(self.overlays)
        goal = next(o for o in bad if o["kind"] == "goal")
        goal["facts"]["goals_by_scorer"] += 1
        results, summary = run(bad, self.match.events, self.match.teams,
                               LocalWriter(self.match.teams))
        self.assertEqual(summary["held_back"], 1)
        held = next(r for r in results if r["id"] == goal["id"])
        self.assertFalse(held["verified"])
        self.assertEqual(held["attempts"], 0)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            LocalWriter(self.match.teams).write(self.overlays[0], "poetic")


class GrammarTests(unittest.TestCase):
    def test_article_before_percentages(self):
        from agents.writers import _article
        for n in (8, 11, 18, 80, 85):
            self.assertEqual(_article(n), "an", n)
        for n in (7, 12, 28, 60):
            self.assertEqual(_article(n), "a", n)

    def test_low_xg_goal_caption_uses_the_right_article(self):
        match, overlays, checker = build(23)
        writer = LocalWriter(match.teams)
        goal = next(o for o in overlays if o["kind"] == "goal" and o["facts"]["xg"] < 0.09)
        self.assertIn("an 8% chance", writer.write(goal, "casual"))


class ModelWriterTests(unittest.TestCase):
    def setUp(self):
        self.match, self.overlays, _ = build(23)
        self.goal = next(o for o in self.overlays if o["kind"] == "goal")

    def make(self, reply="  \"Great goal.\"  ", **kw):
        calls = []

        def post(url, headers, body):
            calls.append((url, headers, body))
            return {"choices": [{"message": {"content": reply}}]}

        writer = OpenAICompatibleWriter("https://example.test/v1/", "KEY", "some-model",
                                        post=post, teams=self.match.teams, **kw)
        return writer, calls

    def test_request_contains_facts_rules_and_feedback(self):
        writer, calls = self.make()
        text = writer.write(self.goal, "analyst", feedback=["the number 9 is not supported"])
        url, headers, body = calls[0]
        self.assertEqual(text, "Great goal.")
        self.assertEqual(url, "https://example.test/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer KEY")
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        self.assertIn("ONLY the facts", system)
        self.assertIn("analyst", system)
        self.assertIn(self.goal["facts"]["scorer"], user)
        self.assertIn("the number 9 is not supported", user)

    def test_azure_style_auth_and_version(self):
        writer, calls = self.make(auth="api-key", api_version="2024-06-01")
        writer.write(self.goal, "casual")
        url, headers, _ = calls[0]
        self.assertEqual(headers["api-key"], "KEY")
        self.assertNotIn("Authorization", headers)
        self.assertTrue(url.endswith("/chat/completions?api-version=2024-06-01"))


if __name__ == "__main__":
    unittest.main()
