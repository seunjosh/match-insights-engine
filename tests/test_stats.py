"""Tests for the clock and stats engine. Run: python -m unittest discover -s tests -t ."""
import unittest

from engine.clock import MatchClock
from engine.stats import SIDES, StatsEngine
from synth_match import Match


def make_match(seed: int):
    match = Match(seed)
    match.run()
    return match


class ClockTests(unittest.TestCase):
    def test_elapsed_never_goes_backwards(self):
        for seed in (1, 2, 3):
            clock = MatchClock()
            last = -1
            for ev in make_match(seed).events:
                now = clock.elapsed(ev)
                self.assertGreaterEqual(now, last)
                last = now


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.match = make_match(5)
        self.engine = StatsEngine()
        self.snapshots = []
        for ev in self.match.events:
            self.engine.ingest(ev)
            self.snapshots.append(self.engine.snapshot())
        self.final = self.snapshots[-1]

    def count(self, kind, side, **match):
        return sum(
            1 for e in self.match.events
            if e["type"] == kind and e["team"] == side
            and all(e.get(k) == v for k, v in match.items())
        )

    def test_score_matches_the_match(self):
        for side in SIDES:
            self.assertEqual(self.final["score"][side], self.match.score[side])

    def test_totals_match_raw_events(self):
        for side in SIDES:
            t = self.final["totals"][side]
            self.assertEqual(t["passes"], self.count("pass", side))
            self.assertEqual(t["passes_complete"], self.count("pass", side, outcome="complete"))
            self.assertEqual(t["shots"], self.count("shot", side))

    def test_turnovers_count_the_team_that_lost_the_ball(self):
        for side in SIDES:
            expected = sum(
                1 for e in self.match.events
                if e["type"] == "possession_change" and e["from_team"] == side
            )
            self.assertEqual(self.final["totals"][side]["turnovers"], expected)

    def test_window_is_a_subset_of_totals(self):
        for snap in self.snapshots[::25]:
            for side in SIDES:
                self.assertLessEqual(
                    snap["window"]["teams"][side]["passes"], snap["totals"][side]["passes"])

    def test_possession_adds_to_100(self):
        for snap in self.snapshots[::25]:
            self.assertAlmostEqual(sum(snap["possession_pct"].values()), 100.0, delta=0.2)

    def test_chaos_index_in_range_and_label_valid(self):
        for snap in self.snapshots:
            w = snap["window"]
            self.assertGreaterEqual(w["chaos_index"], 0.0)
            self.assertLessEqual(w["chaos_index"], 1.0)
            self.assertIn(w["state"], ("control", "balanced", "chaos"))


if __name__ == "__main__":
    unittest.main()
