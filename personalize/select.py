"""Choose which overlays one viewer sees, and say why.

Every overlay gets a relevance score for the viewer. Key moments (goals, red
cards, half time, full time) are always shown. Everything else competes for
the places allowed by the viewer's density setting. Each overlay that is
shown carries `why_shown`, the reasons behind its score, so the
personalisation is explainable as well as the football.
"""
from __future__ import annotations

from .profile import ViewerProfile

MUST_SHOW_PRIORITY = 4
QUOTA = {"light": 12, "normal": 22, "full": None}   # None = show everything

FOCUS_KINDS = {
    "passing": {"difficult_pass", "dominance", "state_shift"},
    "shooting": {"big_chance", "fast_shot", "goal"},
    "pressing": {"pressing", "state_shift"},
    "discipline": {"yellow_card", "red_card"},
}
MODE_BOOST = {
    "analyst": {"state_shift", "dominance", "pressing", "difficult_pass", "fast_shot"},
    "casual": {"big_chance", "yellow_card"},
}


def score_overlay(o: dict, profile: ViewerProfile, teams: dict) -> tuple[float, list[str]]:
    """Return (relevance score, reasons). A score of 10 or more means always shown."""
    if o["priority"] >= MUST_SHOW_PRIORITY:
        return 10.0, ["key moment"]

    score, reasons = float(o["priority"]), []

    if profile.favorite_team and o["team"]:
        fav_side = next((s for s in ("home", "away") if teams[s]["code"] == profile.favorite_team), None)
        if o["team"] == fav_side:
            score += 1.5
            reasons.append("your club")
        elif fav_side:
            score -= 1.0

    if profile.favorite_player:
        player = o.get("player")
        fav_name = next((p["name"] for s in ("home", "away") for p in teams[s]["players"]
                         if p["id"] == profile.favorite_player), None)
        if player and player["id"] == profile.favorite_player:
            score += 3.0
            reasons.append("your player")
        elif fav_name and o["facts"].get("receiver") == fav_name:
            score += 2.0
            reasons.append("your player received the pass")

    if profile.focus and o["kind"] in FOCUS_KINDS[profile.focus]:
        score += 1.5
        reasons.append(f"your focus: {profile.focus}")

    if o["kind"] in MODE_BOOST[profile.mode]:
        score += 0.5
        reasons.append(f"suits {profile.mode} viewing")

    return score, reasons


def select_overlays(overlays: list[dict], profile: ViewerProfile, teams: dict) -> list[dict]:
    """Return copies of the chosen overlays in time order, with relevance and why_shown."""
    scored = []
    for o in overlays:
        score, reasons = score_overlay(o, profile, teams)
        scored.append((score, reasons, o))

    quota = QUOTA[profile.density]
    must = [x for x in scored if x[0] >= 10.0]
    rest = sorted((x for x in scored if x[0] < 10.0),
                  key=lambda x: (-x[0], x[2]["at"]["elapsed_seconds"]))
    chosen = must + (rest if quota is None else rest[: max(0, quota - len(must))])
    chosen.sort(key=lambda x: (x[2]["at"]["elapsed_seconds"], x[2]["id"]))

    out = []
    for score, reasons, o in chosen:
        item = dict(o)
        item["relevance"] = round(score, 1)
        item["why_shown"] = reasons or ["match highlight"]
        out.append(item)
    return out
