"""Tests for the editor agent."""
import copy
import unittest

from agents.editor import KEY_PRIORITY, MAX_DELAY, edit


def ov(i, t, priority=2, secs=7, verified=True):
    return {"id": f"ov{i:03d}", "kind": "k", "priority": priority, "verified": verified,
            "display_seconds": secs, "at": {"elapsed_seconds": t}}


class EditorTests(unittest.TestCase):
    def test_free_screen_airs_at_the_moment(self):
        aired, log, c = edit([ov(1, 100), ov(2, 200)])
        self.assertEqual([o["air_at_seconds"] for o in aired], [100, 200])
        self.assertEqual(c["delayed"], 0)

    def test_busy_screen_delays_but_never_airs_early(self):
        aired, _, c = edit([ov(1, 100), ov(2, 103)])
        self.assertEqual(aired[1]["air_at_seconds"], 107)
        self.assertGreaterEqual(aired[1]["air_at_seconds"], 103)
        self.assertEqual(c["delayed"], 1)

    def test_stale_overlay_is_dropped(self):
        aired, log, c = edit([ov(1, 100, secs=40), ov(2, 101)])
        self.assertEqual(len(aired), 1)
        self.assertEqual(c["dropped"], 1)
        self.assertGreater(40 - 1, MAX_DELAY)

    def test_key_moment_cuts_in_and_shortens_the_one_on_screen(self):
        aired, _, c = edit([ov(1, 100), ov(2, 103, priority=KEY_PRIORITY)])
        self.assertEqual(aired[1]["air_at_seconds"], 103)
        self.assertEqual(aired[0]["display_seconds"], 3)
        self.assertTrue(aired[0]["editor"]["cut_short"])
        self.assertEqual(c["cut_short"], 1)

    def test_unverified_overlays_are_never_aired(self):
        aired, log, c = edit([ov(1, 100, verified=False), ov(2, 200)])
        self.assertEqual([o["id"] for o in aired], ["ov002"])
        self.assertEqual(c["rejected"], 1)

    def test_every_overlay_has_a_logged_decision_and_input_is_untouched(self):
        items = [ov(1, 100), ov(2, 102), ov(3, 103, priority=5), ov(4, 104, verified=False)]
        before = copy.deepcopy(items)
        aired, log, c = edit(items)
        self.assertEqual(items, before)
        self.assertEqual(len(log), len(items))
        self.assertEqual(sum(c[k] for k in ("aired", "dropped", "rejected")), len(items))

    def test_aired_overlays_never_overlap_except_when_cut(self):
        items = [ov(i, t, priority=p) for i, (t, p) in enumerate(
            [(0, 2), (2, 3), (4, 2), (5, 5), (9, 2), (10, 2), (30, 2)], 1)]
        aired, _, _ = edit(items)
        for a, b in zip(aired, aired[1:]):
            self.assertLessEqual(a["air_at_seconds"] + a["display_seconds"], b["air_at_seconds"])


if __name__ == "__main__":
    unittest.main()
