"""Tests for the Pidgin and Yoruba caption layer."""
import copy
import unittest

from agents import languages
from agents.factcheck import FactChecker
from agents.pipeline import run
from agents.writers import LocalWriter
from engine.moments import detect_all
from engine.player_focus import player_cards
from personalize.feed import build_feed
from personalize.profile import ViewerProfile
from synth_match import Match

LANGS = ("pcm", "yo")
MODES = ("analyst", "casual")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = Match(23)
        m.run()
        cls.events, cls.teams = m.events, m.teams
        cls.overlays = detect_all(cls.events, cls.teams) + player_cards(cls.events, cls.teams, "NBR09")
        cls.checker = FactChecker(cls.events, cls.teams)
        cls.writer = LocalWriter(cls.teams)


class PackTests(Base):
    def test_every_overlay_in_every_language_and_mode_passes_the_checker(self):
        kinds = set()
        for o in self.overlays:
            kinds.add(o["kind"])
            for lang in LANGS:
                for mode in MODES:
                    text = self.writer.write(o, mode, None, lang)
                    self.assertEqual(self.checker.check_text(o, text, lang), [], (o["kind"], lang, mode, text))
        self.assertTrue({"goal", "half_time", "full_time", "state_shift", "player_card"} <= kinds)

    def test_text_differs_by_language(self):
        o = next(x for x in self.overlays if x["kind"] == "goal")
        texts = {l: self.writer.write(o, "casual", None, l) for l in ("en",) + LANGS}
        self.assertEqual(len(set(texts.values())), 3)

    def test_unsupported_language_is_rejected(self):
        with self.assertRaises(ValueError):
            self.writer.write(self.overlays[0], "casual", None, "xx")

    def test_a_mistake_in_another_language_is_caught(self):
        goal = next(x for x in self.overlays if x["kind"] == "goal")
        for lang in LANGS:
            good = self.writer.write(goal, "analyst", None, lang)
            bad_number = good.replace(str(goal["facts"]["score_home"]), "9", 1)
            self.assertTrue(self.checker.check_text(goal, bad_number, lang))
            self.assertTrue(self.checker.check_text(goal, good + languages.fake_claim(lang), lang))

    def test_wrong_situation_phrase_is_caught(self):
        goal = next(x for x in self.overlays if x["facts"].get("situation") == "go_ahead"
                    and x["kind"] == "goal")
        wrong = {"pcm": " Dem don level again.", "yo": " Wọ́n ti dọ́gba padà."}
        for lang in LANGS:
            text = self.writer.write(goal, "analyst", None, lang) + wrong[lang]
            self.assertTrue(any("contradicts" in i for i in self.checker.check_text(goal, text, lang)))

    def test_goal_word_in_a_non_goal_is_caught(self):
        chance = next(x for x in self.overlays if x["kind"] == "big_chance")
        for lang, word in (("pcm", " Na goal!"), ("yo", " Góòlù!")):
            text = self.writer.write(chance, "casual", None, lang) + word
            self.assertTrue(any("not a goal" in i for i in self.checker.check_text(chance, text, lang)))

    def test_tone_marks_compare_in_one_form(self):
        import unicodedata
        goal = next(x for x in self.overlays if x["facts"].get("situation") == "go_ahead")
        text = unicodedata.normalize("NFD", self.writer.write(goal, "casual", None, "yo"))
        wrong = text + unicodedata.normalize("NFD", " Wọ́n ti dọ́gba padà.")
        self.assertTrue(self.checker.check_text(goal, wrong, "yo"))


class PipelineTests(Base):
    def test_faulty_writer_is_corrected_in_each_language(self):
        for lang in LANGS:
            writer = LocalWriter(self.teams, fault_rate=1.0, seed=3)
            results, summary = run(self.overlays, self.events, self.teams, writer, "analyst", lang=lang)
            self.assertGreater(summary["fixed_by_retry"], 0, lang)
            self.assertEqual(summary["held_back"], 0)
            self.assertTrue(all(r["verified"] for r in results))
            self.assertTrue(all(r["language"] == lang for r in results))

    def test_failed_translation_falls_back_to_checked_english(self):
        class Bad:
            name = "bad"

            def write(self, o, mode="casual", feedback=None, lang="en"):
                return "Nonsense 999"
        results, summary = run(self.overlays, self.events, self.teams, Bad(), "casual", lang="yo")
        fell = [r for r in results if r.get("fallback")]
        self.assertTrue(fell)
        self.assertTrue(all(r["text_language"] == "en" and r["verified"] for r in fell))

    def test_english_is_unchanged(self):
        results, _ = run(self.overlays, self.events, self.teams, self.writer, "casual")
        self.assertTrue(all(r["language"] == "en" and r["text_language"] == "en" for r in results))


class FeedTests(Base):
    def test_profile_language_flows_into_the_feed(self):
        for lang in LANGS:
            feed = build_feed(self.events, self.teams,
                              ViewerProfile(language=lang, favorite_player="EVU11", density="full"),
                              self.writer)
            self.assertTrue(all(o["verified"] and o["text_language"] == lang for o in feed["overlays"]))
            self.assertEqual(feed["profile"]["language"], lang)

    def test_facts_do_not_change_with_language(self):
        en = build_feed(self.events, self.teams, ViewerProfile(density="full"), self.writer)["overlays"]
        for lang in LANGS:
            other = build_feed(self.events, self.teams, ViewerProfile(language=lang, density="full"),
                               self.writer)["overlays"]
            self.assertEqual([o["facts"] for o in en], [o["facts"] for o in other])


if __name__ == "__main__":
    unittest.main()
