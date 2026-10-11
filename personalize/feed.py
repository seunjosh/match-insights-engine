"""Personalised feed: the same match, told for one viewer.

Steps: detect moments, add player-focus cards if the viewer follows a player,
choose what this viewer sees, then write and fact-check every caption in the
viewer's mode.

Usage:
    python -m personalize.feed --events data/match_001_events.jsonl --mode analyst --density full
    python -m personalize.feed --events data/match_001_events.jsonl --mode casual --team EVU --density light
    python -m personalize.feed --events data/match_001_events.jsonl --team NBR --player NBR09 --focus passing
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from agents.editor import edit
from agents.pipeline import run
from agents.writers import LocalWriter, OpenAICompatibleWriter
from engine.moments import detect_all
from engine.player_focus import find_player, player_cards
from engine.replayer import load_events

from .profile import DENSITY, FOCUS, LANGUAGES, MODES, ViewerProfile
from .select import select_overlays


def build_feed(events: list[dict], teams: dict, profile: ViewerProfile, writer) -> dict:
    overlays = detect_all(events, teams)
    if profile.favorite_player:
        overlays += player_cards(events, teams, profile.favorite_player)
        overlays.sort(key=lambda o: (o["at"]["elapsed_seconds"], o["id"]))
    chosen = select_overlays(overlays, profile, teams)
    results, summary = run(chosen, events, teams, writer, profile.mode, lang=profile.language)
    aired, editor_log, counts = edit(results)
    summary["available"] = len(overlays)
    summary["chosen"] = len(results)
    summary["shown"] = len(aired)
    summary["editor"] = counts
    return {"profile": asdict(profile), "summary": summary, "overlays": aired,
            "editor_log": editor_log}


def _resolve_player(teams: dict, text: str) -> str:
    side, player = find_player(teams, text)
    if player:
        return player["id"]
    for s in ("home", "away"):
        for p in teams[s]["players"]:
            if p["name"].lower() == text.lower():
                return p["id"]
    options = ", ".join(f'{p["id"]} ({p["name"]})' for s in ("home", "away")
                        for p in teams[s]["players"][1:])
    raise SystemExit(f"Unknown player {text!r}. Choose one of: {options}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", default="data/match_001_events.jsonl")
    ap.add_argument("--mode", choices=MODES, default="casual")
    ap.add_argument("--team", help="favourite club code, for example NBR")
    ap.add_argument("--player", help="favourite player id (for example NBR09) or full name")
    ap.add_argument("--focus", choices=[f for f in FOCUS if f])
    ap.add_argument("--density", choices=DENSITY, default="normal")
    ap.add_argument("--lang", choices=LANGUAGES, default="en",
                    help="en, pcm (Nigerian Pidgin) or yo (Yoruba)")
    ap.add_argument("--writer", choices=("local", "llm"), default="local")
    ap.add_argument("--fault", type=float, default=0.0)
    ap.add_argument("--out")
    args = ap.parse_args()

    events = load_events(args.events)
    with open(args.events.replace("_events.jsonl", "_meta.json"), encoding="utf-8") as f:
        teams = json.load(f)["teams"]
    codes = [teams[s]["code"] for s in ("home", "away")]
    if args.team and args.team not in codes:
        raise SystemExit(f"Unknown club {args.team!r}. Choose one of: {', '.join(codes)}")

    profile = ViewerProfile(
        name="cli", mode=args.mode, favorite_team=args.team,
        favorite_player=_resolve_player(teams, args.player) if args.player else None,
        focus=args.focus, density=args.density, language=args.lang)
    writer = (OpenAICompatibleWriter.from_env(teams) if args.writer == "llm"
              else LocalWriter(teams, args.fault))
    feed = build_feed(events, teams, profile, writer)

    for o in feed["overlays"]:
        at = o["at"]
        mark = "OK  " if o["verified"] else "HELD"
        print(f'{at["minute"]:>2}\':{at["second"]:02d} {mark} {o["headline"]:<12} {o["text"]}')
        print(f'        why shown: {", ".join(o["why_shown"])}')

    out = args.out or args.events.replace("_events.jsonl", f"_feed_{args.mode}_{args.density}{'' if args.lang == 'en' else '_' + args.lang}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=2)
    s = feed["summary"]
    print(f'\nshowing {s["shown"]} of {s["available"]} overlays -> {out}')


if __name__ == "__main__":
    main()
