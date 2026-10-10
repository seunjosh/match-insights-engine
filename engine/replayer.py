"""Replayer: streams recorded match events as if the match were live.

Usage:
    python -m engine.replayer --events data/match_001_events.jsonl            # instant
    python -m engine.replayer --events data/match_001_events.jsonl --speed 60 # 60x real time

`speed` is match-seconds per real second. 1 = real time, 60 = a minute of
match per real second, 0 = no delay at all.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from typing import AsyncIterator

from .clock import MatchClock
from .stats import StatsEngine


def load_events(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


async def replay(events: list[dict], speed: float = 0.0) -> AsyncIterator[dict]:
    """Yield events one by one, pausing so they arrive at `speed` x real time."""
    clock = MatchClock()
    previous = 0
    for ev in events:
        now = clock.elapsed(ev)
        if speed > 0 and now > previous:
            await asyncio.sleep((now - previous) / speed)
        previous = max(previous, now)
        yield ev


def describe(ev: dict) -> str | None:
    """One-line text for events worth showing live, or None to skip."""
    kind = ev["type"]
    who = f'{ev["player"]} ({ev["team_code"]})' if ev.get("player") else ev["team_code"]
    if kind == "goal":
        return f'GOAL! {who}  {ev["score_home"]}-{ev["score_away"]}'
    if kind == "shot" and ev["outcome"] in ("saved", "blocked") and ev["xg"] >= 0.2:
        return f'Big chance: {who}, xG {ev["xg"]}, {ev["outcome"]}'
    if kind == "yellow_card":
        return f"Yellow card: {who}"
    if kind == "red_card":
        return f"RED CARD: {who}"
    if kind == "half_end":
        return "Half time"
    if kind == "full_time":
        return "Full time"
    return None


def status_line(snap: dict, codes: dict) -> str:
    w = snap["window"]
    acc = {s: snap["totals"][s]["pass_accuracy"] for s in ("home", "away")}
    return (
        f'  {snap["minute"]:>2}\' | {codes["home"]} {snap["score"]["home"]}-{snap["score"]["away"]} {codes["away"]}'
        f' | possession {snap["possession_pct"]["home"]:.0f}-{snap["possession_pct"]["away"]:.0f}'
        f' | pass acc {acc["home"]}/{acc["away"]}'
        f' | last {w["seconds"] // 60} min: {w["state"].upper()} (chaos {w["chaos_index"]},'
        f' {w["turnovers_per_min"]} turnovers/min, tempo {w["tempo_per_min"]}/min)'
    )


async def run(path: str, speed: float, every_minutes: int) -> None:
    events = load_events(path)
    codes = {"home": events[0]["team_code"], "away": next(e["team_code"] for e in events if e["team"] == "away")}
    engine = StatsEngine()
    next_print = every_minutes * 60
    async for ev in replay(events, speed):
        elapsed = engine.ingest(ev)
        line = describe(ev)
        if line:
            print(f'{ev["minute"]:>2}\':{ev["second"]:02d}  {line}')
        if elapsed >= next_print:
            print(status_line(engine.snapshot(), codes))
            next_print += every_minutes * 60
    print(status_line(engine.snapshot(), codes))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", default="data/match_001_events.jsonl")
    ap.add_argument("--speed", type=float, default=0.0, help="match-seconds per real second (0 = instant)")
    ap.add_argument("--every", type=int, default=10, help="print a stats line every N match minutes")
    args = ap.parse_args()
    asyncio.run(run(args.events, args.speed, args.every))


if __name__ == "__main__":
    main()
