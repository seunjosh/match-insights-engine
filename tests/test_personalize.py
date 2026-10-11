"""Tests for player focus, viewer profiles and personalised feeds."""
import copy
import unittest

from agents.factcheck import FactChecker
from agents.writers import LocalWriter
from engine.moments import detect_all
from engine.player_focus import CARD_TIMES, find_player, player_cards
from personalize.feed import build_feed
from personalize.profile import ViewerProfile
from personalize.select import QUOTA, select_overlays
from synth_match import Match

SEED = 23   # a 4-3 match: plenty of goals for both sides


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.match = Match(SEED)
        cls.match.run()
        cls.events, cls.teams = cls.match.events, cls.match.teams
        cls.overlays = detect_all(cls.events, cls.teams)
        cls.checker = FactChecker(cls.events, cls.teams)
        cls.codes = {s: cls.teams[s]["code"] for s in ("home", "away")}

    def feed(self, **kw):
        return build_feed(self.events, self.teams, ViewerProfile(**kw), LocalWriter(self.teams))


class PlayerFocusTests(Base):
    def test_cards_are_grounded_in_the_raw_events_for_every_outfield_player(self):
        count = 0
        for side in ("home", "away"):
            for p in self.teams[side]["players"][1:]:
                for card in player_cards(self.events, self.teams, p["id"]):
                    count += 1
                    self.assertEqual(self.checker.check_facts(card), [], (p["id"], card["id"]))
                    self.assertEqual(self.checker.check_text(card, card["text"]), [])
        self.assertGreater(count, 50)

    def test_cards_come_at_set_times_and_in_order(self):
        cards = player_cards(self.events, self.teams, "NBR09")
        times = [c["at"]["elapsed_seconds"] for c in cards]
        self.assertEqual(times, sorted(times))
        self.assertLessEqual(len(cards), len(CARD_TIMES) + 2)
        self.assertTrue(all(c["player"]["id"] == "NBR09" for c in cards))

    def test_stats_only_ever_grow(self):
        cards = player_cards(self.events, self.teams, "NBR09")
        for key in ("passes", "shots", "tackles_won", "pressures", "goals"):
            values = [c["facts"][key] for c in cards]
            self.assertEqual(values, sorted(values), key)

    def test_tampered_card_is_caught(self):
        card = copy.deepcopy(player_cards(self.events, self.teams, "NBR09")[-1])
        card["facts"]["passes"] += 1
        self.assertTrue(self.checker.check_facts(card))

    def test_both_writer_modes_pass_the_checker(self):
        writer = LocalWriter(self.teams)
        for card in player_cards(self.events, self.teams, "EVU11"):
            for mode in ("analyst", "casual"):
                self.assertEqual(self.checker.check_text(card, writer.write(card, mode)), [])

    def test_unknown_player_is_rejected(self):
        with self.assertRaises(ValueError):
            player_cards(self.events, self.teams, "XXX99")
        self.assertEqual(find_player(self.teams, "xxx99"), (None, None))


class ProfileTests(unittest.TestCase):
    def test_bad_settings_are_rejected(self):
        for bad in ({"mode": "poetic"}, {"density": "huge"}, {"focus": "dancing"}, {"language": "xx"}):
            with self.assertRaises(ValueError):
                ViewerProfile(**bad)

    def test_defaults_are_valid(self):
        self.assertEqual(ViewerProfile().mode, "casual")


class SelectionTests(Base):
    def select(self, overlays=None, **kw):
        return select_overlays(overlays or self.overlays, ViewerProfile(**kw), self.teams)

    def test_key_moments_are_always_shown(self):
        key = {o["id"] for o in self.overlays if o["priority"] >= 4}
        for kw in ({"density": "light"}, {"density": "light", "favorite_team": "EVU"},
                   {"density": "light", "mode": "analyst", "focus": "passing"}):
            self.assertTrue(key <= {o["id"] for o in self.select(**kw)}, kw)

    def test_density_controls_how_much_is_shown(self):
        light, normal, full = (len(self.select(density=d)) for d in ("light", "normal", "full"))
        self.assertLess(light, normal)
        self.assertLess(normal, full)
        self.assertEqual(full, len(self.overlays))
        self.assertLessEqual(normal, QUOTA["normal"])

    def about(self, chosen, code):
        side = next(s for s in ("home", "away") if self.codes[s] == code)
        return sum(1 for o in chosen if o["team"] == side and o["priority"] < 4)

    def test_favourite_club_gets_more_of_the_low_priority_overlays(self):
        for fav, other in (("NBR", "EVU"), ("EVU", "NBR")):
            mine = self.about(self.select(density="light", favorite_team=fav), fav)
            plain = self.about(self.select(density="light"), fav)
            self.assertGreaterEqual(mine, plain)
            theirs = self.about(self.select(density="light", favorite_team=fav), other)
            self.assertGreaterEqual(mine, theirs)

    def test_focus_pulls_in_matching_kinds(self):
        def share(chosen, kinds):
            return sum(o["kind"] in kinds for o in chosen)
        shooting = {"big_chance", "fast_shot"}
        self.assertGreaterEqual(share(self.select(density="light", focus="shooting"), shooting),
                                share(self.select(density="light"), shooting))
        passing = {"difficult_pass", "dominance"}
        self.assertGreaterEqual(share(self.select(density="light", focus="passing"), passing),
                                share(self.select(density="light"), passing))

    def test_every_shown_overlay_has_a_reason_and_order_is_chronological(self):
        chosen = self.select(density="normal", favorite_team="NBR", mode="analyst")
        times = [o["at"]["elapsed_seconds"] for o in chosen]
        self.assertEqual(times, sorted(times))
        for o in chosen:
            self.assertTrue(o["why_shown"])
            self.assertIn("relevance", o)

    def test_selection_does_not_change_the_original_overlays(self):
        before = copy.deepcopy(self.overlays)
        self.select(density="light", favorite_team="EVU")
        self.assertEqual(self.overlays, before)


class FeedTests(Base):
    def test_every_overlay_in_a_feed_is_verified(self):
        for kw in ({"mode": "analyst", "density": "full"},
                   {"mode": "casual", "density": "light", "favorite_team": "EVU"},
                   {"mode": "casual", "favorite_team": "NBR", "favorite_player": "NBR09",
                    "focus": "passing"}):
            feed = self.feed(**kw)
            self.assertTrue(all(o["verified"] for o in feed["overlays"]), kw)
            self.assertEqual(feed["summary"]["held_back"], 0)
            self.assertEqual(feed["summary"]["shown"], len(feed["overlays"]))

    def test_following_a_player_adds_their_cards(self):
        plain = self.feed(density="full")
        follow = self.feed(density="full", favorite_player="EVU11")
        self.assertEqual(sum(o["kind"] == "player_card" for o in plain["overlays"]), 0)
        self.assertGreater(sum(o["kind"] == "player_card" for o in follow["overlays"]), 2)

    def test_the_same_match_reads_differently_for_different_viewers(self):
        analyst = self.feed(mode="analyst", density="full")["overlays"]
        casual = self.feed(mode="casual", density="full")["overlays"]
        self.assertEqual([o["id"] for o in analyst], [o["id"] for o in casual])
        differing = sum(a["text"] != c["text"] for a, c in zip(analyst, casual))
        self.assertGreater(differing / len(analyst), 0.9)
        # same facts underneath, whatever the wording
        for a, c in zip(analyst, casual):
            self.assertEqual(a["facts"], c["facts"])

    def test_different_viewers_get_different_selections(self):
        nbr = {o["id"] for o in self.feed(density="light", favorite_team="NBR")["overlays"]}
        evu = {o["id"] for o in self.feed(density="light", favorite_team="EVU")["overlays"]}
        self.assertNotEqual(nbr, evu)

    def test_a_faulty_writer_is_still_corrected_inside_a_feed(self):
        writer = LocalWriter(self.teams, fault_rate=1.0, seed=4)
        feed = build_feed(self.events, self.teams,
                          ViewerProfile(mode="analyst", favorite_player="NBR09"), writer)
        self.assertTrue(all(o["verified"] for o in feed["overlays"]))
        self.assertGreater(feed["summary"]["fixed_by_retry"], 0)


if __name__ == "__main__":
    unittest.main()
