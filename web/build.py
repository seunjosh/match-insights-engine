"""Build the broadcast-style match screen: one self-contained HTML file.

Usage:
    python -m web.build                       # writes web/screen.html
    python -m web.build --fault 0             # no deliberate writer mistakes
    python -m web.build --writer llm          # captions from the model (needs LLM_* variables)

It replays the match through the whole pipeline once per viewer setup
(language x style x club x followed player) and embeds the results, so the
page works offline and can be opened by double-clicking it.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os

from agents.writers import LocalWriter, OpenAICompatibleWriter
from engine.clock import MatchClock
from engine.replayer import load_events
from engine.stats import StatsEngine
from personalize.feed import build_feed
from personalize.profile import ViewerProfile

HERE = os.path.dirname(os.path.abspath(__file__))

# Short labels for the screen itself (the captions come from the pipeline).
# Pidgin and Yoruba labels are AI drafts that still need a native speaker's review.
UI_LABELS = {
    "en": {"goal": "Goal", "big_chance": "Big chance", "fast_shot": "Hard shot",
           "yellow_card": "Yellow card", "red_card": "Red card", "difficult_pass": "Tough pass",
           "half_time": "Half time", "full_time": "Full time", "state_shift": "Control or chaos",
           "pressing": "Pressing", "dominance": "On top", "player_card": "Your player"},
    "pcm": {"goal": "GOAL", "big_chance": "E near well", "fast_shot": "Hard shot",
            "yellow_card": "Yellow card", "red_card": "Red card", "difficult_pass": "Tough pass",
            "half_time": "Half time", "full_time": "Full time", "state_shift": "Control or chaos",
            "pressing": "Pressing", "dominance": "Dem dey run am", "player_card": "Your player"},
    "yo": {"goal": "Góòlù", "big_chance": "Àǹfààní ńlá", "fast_shot": "Bọ́ọ̀lù líle",
           "yellow_card": "Kaadi ofeefee", "red_card": "Kaadi pupa", "difficult_pass": "Pàsì tó le",
           "half_time": "Ìsinmi àárín eré", "full_time": "Ìparí eré", "state_shift": "Ìṣàkóso / Chaos",
           "pressing": "Titẹ", "dominance": "Ìṣàkóso", "player_card": "Olùṣeré rẹ"},
}


def clock_label(half: int, minute: int) -> str:
    if half == 1 and minute > 45:
        return f"45+{minute - 45}'"
    if half == 2 and minute > 90:
        return f"90+{minute - 90}'"
    return f"{minute}'"


def timeline(events: list[dict], step: int = 5) -> dict:
    """Score, clock and chaos index every `step` seconds of match time."""
    clock, engine = MatchClock(), StatsEngine()
    stamped = [(clock.elapsed(e), e) for e in events]
    end = stamped[-1][0]
    t, i = 0, 0
    out = {"step": step, "clock": [], "home": [], "away": [], "chaos": [], "state": []}
    last = {"clock": "0'", "home": 0, "away": 0, "chaos": 0.0, "state": "control"}
    while t <= end:
        while i < len(stamped) and stamped[i][0] <= t:
            ev = stamped[i][1]
            engine.ingest(ev)
            snap = engine.snapshot()
            last = {"clock": clock_label(ev["half"], ev["minute"]), "home": snap["score"]["home"],
                    "away": snap["score"]["away"], "chaos": snap["window"]["chaos_index"],
                    "state": snap["window"]["state"]}
            i += 1
        for k, v in last.items():
            out[k].append(v)
        t += step
    out["end"] = end
    return out


def pitch_events(events: list[dict]) -> list[dict]:
    clock, out = MatchClock(), []
    for e in events:
        if e["type"] in ("shot", "yellow_card", "red_card"):
            out.append({"t": clock.elapsed(e), "type": e["type"], "team": e["team"], "x": e["x"],
                        "y": e["y"], "outcome": e.get("outcome"), "xg": e.get("xg"),
                        "player": e.get("player"), "label": clock_label(e["half"], e["minute"])})
    return out


def featured_players(events: list[dict], teams: dict) -> dict:
    """The most dangerous player on each side (highest total xG), for the 'follow a player' choice."""
    best = {}
    for side in ("home", "away"):
        tally = {}
        for e in events:
            if e["type"] == "shot" and e["team"] == side:
                tally[e["player_id"]] = tally.get(e["player_id"], 0) + e["xg"]
        pid = max(tally, key=tally.get)
        name = next(p["name"] for p in teams[side]["players"] if p["id"] == pid)
        best[side] = {"id": pid, "name": name}
    return best


def slim(o: dict) -> dict:
    drafts = [{"attempt": c["attempt"], "text": c["text"], "issues": c["issues"]}
              for c in o["check_log"] if c["stage"] == "text" and not c["ok"]]
    return {"id": o["id"], "kind": o["kind"], "priority": o["priority"],
            "air": o["air_at_seconds"], "secs": o["display_seconds"], "team": o["team"],
            "label": clock_label(o["at"]["half"], o["at"]["minute"]), "text": o["text"],
            "why": o["why_shown"], "lang": o["text_language"], "attempts": o["attempts"],
            "fallback": bool(o.get("fallback")), "rejected": drafts,
            "editor": o["editor"]["reason"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", default="data/match_001_events.jsonl")
    ap.add_argument("--fault", type=float, default=0.35,
                    help="local writer only: chance of a deliberate mistake, to show the checker working")
    ap.add_argument("--writer", choices=("local", "llm"), default="local")
    ap.add_argument("--out", default=os.path.join(HERE, "screen.html"))
    args = ap.parse_args()

    events = load_events(args.events)
    with open(args.events.replace("_events.jsonl", "_meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    teams = meta["teams"]
    codes = {s: teams[s]["code"] for s in ("home", "away")}
    stars = featured_players(events, teams)
    players = [None, stars["home"]["id"], stars["away"]["id"]]

    feeds = {}
    for lang, mode, team, player in itertools.product(
            ("en", "pcm", "yo"), ("casual", "analyst"), (None, codes["home"], codes["away"]), players):
        writer = (OpenAICompatibleWriter.from_env(teams) if args.writer == "llm"
                  else LocalWriter(teams, args.fault, seed=7))
        profile = ViewerProfile(mode=mode, favorite_team=team, favorite_player=player,
                                density="normal", language=lang)
        feed = build_feed(events, teams, profile, writer)
        feeds[f"{lang}|{mode}|{team or '-'}|{player or '-'}"] = {
            "overlays": [slim(o) for o in feed["overlays"]], "summary": feed["summary"]}

    data = {
        "teams": {s: {"name": teams[s]["name"], "code": teams[s]["code"]} for s in ("home", "away")},
        "stars": stars, "timeline": timeline(events), "events": pitch_events(events),
        "feeds": feeds, "labels": UI_LABELS, "writer": writer.name, "fault": args.fault,
        "total_events": len(events),
    }
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        html = f.read()
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html.replace("__DATA__", blob))
    print(f"{len(feeds)} personalised feeds -> {args.out} ({os.path.getsize(args.out) // 1024} KB)")


if __name__ == "__main__":
    main()
