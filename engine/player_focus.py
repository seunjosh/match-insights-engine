"""Player focus: follow one player through the match with periodic stat cards.

A card is an overlay of kind "player_card" in the same format as the moment
detector's overlays, so the writer and the fact-checker handle it like any
other. Cards appear at 15, 30, 60 and 75 minutes of match time, at half time
and at full time, and only once the player has been involved a few times.
"""
from __future__ import annotations

from .clock import MatchClock
from .moments import DISPLAY_SECONDS

CARD_TIMES = (900, 1800, 3600, 4500)   # elapsed seconds: 15, 30, 60, 75 minutes
MIN_INVOLVEMENTS = 3
MAX_SOURCES = 15


def find_player(teams: dict, player_id: str):
    """Return (side, player dict) for a player id, or (None, None)."""
    for side in ("home", "away"):
        for p in teams[side]["players"]:
            if p["id"].lower() == player_id.lower():
                return side, p
    return None, None


def _new() -> dict:
    return {"passes": 0, "passes_complete": 0, "shots": 0, "shots_on_target": 0,
            "goals": 0, "xg": 0.0, "tackles_won": 0, "pressures": 0}


def _add(stats: dict, ev: dict) -> None:
    kind = ev["type"]
    if kind == "pass":
        stats["passes"] += 1
        stats["passes_complete"] += ev["outcome"] == "complete"
    elif kind == "shot":
        stats["shots"] += 1
        stats["xg"] += ev["xg"]
        stats["shots_on_target"] += ev["outcome"] in ("saved", "goal")
    elif kind == "goal":
        stats["goals"] += 1
    elif kind == "tackle" and ev["outcome"] == "won":
        stats["tackles_won"] += 1
    elif kind == "pressure":
        stats["pressures"] += 1


def card_text(name: str, code: str, f: dict) -> str:
    parts = [f'{f["passes"]} {"pass" if f["passes"] == 1 else "passes"}']
    if f["pass_accuracy"] is not None:
        parts[0] += f' ({f["pass_accuracy"]}% completed)'
    parts.append(f'{f["shots"]} {"shot" if f["shots"] == 1 else "shots"}')
    if f["goals"]:
        parts.append(f'{f["goals"]} {"goal" if f["goals"] == 1 else "goals"}')
    parts.append(f'{f["tackles_won"]} {"tackle" if f["tackles_won"] == 1 else "tackles"} won')
    parts.append(f'{f["pressures"]} pressure {"action" if f["pressures"] == 1 else "actions"}')
    return f"{name} ({code}) so far: " + ", ".join(parts) + "."


def player_cards(events: list[dict], teams: dict, player_id: str) -> list[dict]:
    side, player = find_player(teams, player_id)
    if player is None:
        raise ValueError(f"unknown player id {player_id!r}")
    code = teams[side]["code"]
    clock = MatchClock()
    stats, involved = _new(), []
    pending = list(CARD_TIMES)
    overlays: list[dict] = []

    for ev in events:
        t = clock.elapsed(ev)
        if ev.get("player_id") == player["id"]:
            _add(stats, ev)
            involved.append(ev["event_id"])

        due = False
        if ev["type"] in ("half_end", "full_time"):
            due = True
        elif pending and t >= pending[0]:
            while pending and t >= pending[0]:
                pending.pop(0)
            due = True
        if not due or len(involved) < MIN_INVOLVEMENTS:
            continue

        passes = stats["passes"]
        facts = {
            "passes": passes, "passes_complete": stats["passes_complete"],
            "pass_accuracy": round(100 * stats["passes_complete"] / passes, 1) if passes else None,
            "shots": stats["shots"], "shots_on_target": stats["shots_on_target"],
            "goals": stats["goals"], "xg": round(stats["xg"], 2),
            "tackles_won": stats["tackles_won"], "pressures": stats["pressures"],
        }
        overlays.append({
            "id": f"pf{len(overlays) + 1:03d}",
            "kind": "player_card",
            "priority": 3,
            "at": {"elapsed_seconds": t, "minute": ev["minute"],
                   "second": ev["second"], "half": ev["half"]},
            "display_seconds": DISPLAY_SECONDS[3],
            "headline": "Player focus",
            "text": card_text(player["name"], code, facts),
            "team": side,
            "player": {"id": player["id"], "name": player["name"]},
            "facts": facts,
            "source_event_ids": involved[-MAX_SOURCES:],
            "last_event_id": ev["event_id"],
            "verified": None,
        })
    return overlays
