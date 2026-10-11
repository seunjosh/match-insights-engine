"""Print a review sheet of every Pidgin and Yoruba phrase next to a real example.

Usage:
    python -m tools.language_review > data/language_review.md

Fix any wording that reads wrong in agents/languages.py (PACKS), then run the
tests again. Keep the phrases in SITUATION_PHRASES in step with the wording.
"""
from agents import languages
from agents.writers import LocalWriter
from engine.moments import detect_all
from engine.player_focus import player_cards
from synth_match import Match

KINDS = ["goal", "big_chance", "fast_shot", "yellow_card", "red_card", "difficult_pass",
         "half_time", "full_time", "state_shift", "pressing", "dominance", "player_card"]


def main() -> None:
    overlays, teams = [], None
    for seed in (23, 2, 9, 11, 14):
        m = Match(seed)
        m.run()
        teams = teams or m.teams
        found = detect_all(m.events, m.teams) + player_cards(m.events, m.teams, "NBR09")
        for o in found:
            overlays.append((m.teams, o))
    print("# Language review sheet\n")
    print("Mark each line OK or write the corrected wording. Numbers and names are filled in by code.\n")
    for kind in KINDS:
        picks = [(t, o) for t, o in overlays if o["kind"] == kind][:2]
        if kind == "state_shift":
            picks = ([(t, o) for t, o in overlays if o["kind"] == kind and o["facts"]["state"] == "chaos"][:1]
                     + [(t, o) for t, o in overlays if o["kind"] == kind and o["facts"]["state"] != "chaos"][:1])
        if kind == "goal":
            seen, picks = set(), []
            for t, o in overlays:
                s = o["facts"]["situation"] if o["kind"] == "goal" else None
                if s and s not in seen:
                    seen.add(s)
                    picks.append((t, o))
        print(f"## {kind}\n")
        for t, o in picks:
            w = LocalWriter(t)
            print(f"- facts: `{o['facts'].get('situation', o['facts'].get('state', ''))}`")
            for mode in ("analyst", "casual"):
                for lang in ("en", "pcm", "yo"):
                    print(f"  - {mode} / {lang}: {w.write(o, mode, None, lang)}")
            print()
    print("## Phrases the fact-checker looks for\n")
    for lang, d in languages.SITUATION_PHRASES.items():
        print(f"- {lang}: " + "; ".join(f'"{k}" = {v}' for k, v in d.items()))


if __name__ == "__main__":
    main()
