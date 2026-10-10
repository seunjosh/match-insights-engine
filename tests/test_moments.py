"""Tests for the moment detector. Run: python -m unittest discover -s tests -t ."""
import json
import unittest

from engine.moments import DISPLAY_SECONDS, MIN_GAP_LOW, detect_all
from synth_match import Match

REQUIRED = {"id", "kind", "priority", "at", "display_seconds", "headline", "text",
            "team", "player", "facts", "source_event_ids", "last_event_id", "verified"}


def overlays_for(seed: int):
    match = Match(seed)
    match.run()
    return match, detect_all(match.events, match.teams)


class MomentTests(unittest.TestCase):
    def setUp(self):
        self.cases = [overlays_for(seed) for seed in (2, 5, 9)]

    def test_every_goal_gets_exactly_one_overlay(self):
        for match, overlays in self.cases:
            goals = [o for o in overlays if o["kind"] == "goal"]
            self.assertEqual(len(goals), sum(match.score.values()))
            for o in goals:
                self.assertIn(o["headline"], ("GOAL", "HAT-TRICK"))

    def test_final_goal_overlay_scoreline_matches_the_match(self):
        for match, overlays in self.cases:
            goals = [o for o in overlays if o["kind"] == "goal"]
            if goals:
                last = goals[-1]["facts"]
                self.assertEqual(last["score_home"], match.score["home"])
                self.assertEqual(last["score_away"], match.score["away"])

    def test_required_fields_and_ranges(self):
        for _, overlays in self.cases:
            ids = set()
            for o in overlays:
                self.assertTrue(REQUIRED <= set(o), o["id"])
                self.assertIn(o["priority"], DISPLAY_SECONDS)
                self.assertEqual(o["display_seconds"], DISPLAY_SECONDS[o["priority"]])
                self.assertTrue(o["text"])
                self.assertTrue(o["source_event_ids"])
                self.assertNotIn(o["id"], ids)
                ids.add(o["id"])

    def test_sources_exist_and_never_come_from_the_future(self):
        for match, overlays in self.cases:
            known = {e["event_id"] for e in match.events}
            for o in overlays:
                for sid in o["source_event_ids"]:
                    self.assertIn(sid, known)
                    self.assertLessEqual(sid, o["last_event_id"])

    def test_overlays_are_in_time_order(self):
        for _, overlays in self.cases:
            times = [o["at"]["elapsed_seconds"] for o in overlays]
            self.assertEqual(times, sorted(times))

    def test_low_priority_overlays_keep_their_distance(self):
        for _, overlays in self.cases:
            for prev, cur in zip(overlays, overlays[1:]):
                if cur["priority"] <= 2:
                    gap = cur["at"]["elapsed_seconds"] - prev["at"]["elapsed_seconds"]
                    self.assertGreaterEqual(gap, MIN_GAP_LOW)

    def test_overlay_volume_is_sensible(self):
        for _, overlays in self.cases:
            self.assertGreater(len(overlays), 10)
            self.assertLess(len(overlays), 60)

    def test_overlays_are_json_serialisable(self):
        for _, overlays in self.cases:
            self.assertEqual(json.loads(json.dumps(overlays)), overlays)

    def test_same_match_gives_same_overlays(self):
        _, first = overlays_for(5)
        _, second = overlays_for(5)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
