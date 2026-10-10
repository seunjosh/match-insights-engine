"""Moment detector: decides what is worth putting on screen.

It watches the event stream and the stats engine and emits "overlays":
small, timed, machine-readable insights. Each overlay carries

  - the numbers it is based on (`facts`), and
  - the ids of the events behind it (`source_event_ids`),

so a fact-checker can later verify every claim against the raw data.
The text here is plain template text built from those facts. The AI agents
rewrite it for a viewer's mode and language, but never change the facts.

Usage:
    python -m engine.moments --events data/match_001_events.jsonl
"""
from __future__ import annotations

import argparse
import json
import os

from .replayer import load_events
from .stats import SIDES, StatsEngine

# Seconds an overlay stays on screen, by priority (5 = most important).
DISPLAY_SECONDS = {5: 10, 4: 8, 3: 7, 2: 5, 1: 4}

BIG_CHANCE_XG = 0.20        # a shot at least this likely to score is a "big chance"
FAST_SHOT_KMH = 100.0       # minimum speed for a "fastest shot" overlay
DIFFICULT_PASS = 9.5        # completed passes rated at least this hard get an overlay
PRESSING_MIN = 14           # pressure actions by one team in the window
DOMINANCE_PCT = 70.0        # one team's share of passes in the window
EVAL_EVERY = 30             # seconds between checks of the rolling-window rules
WINDOW_READY = 300          # rolling-window rules wait until a full window exists
MIN_GAP_LOW = 45            # low-priority overlays keep this gap after any overlay
MAX_SOURCES = 15            # cap on source ids for window-based overlays
COOLDOWN = {"state_shift": 600, "pressing": 720, "dominance": 900, "fast_shot": 600,
            "difficult_pass": 900}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


class MomentDetector:
    """Call `engine.ingest(ev)` first, then `detector.process(ev)`."""

    def __init__(self, engine: StatsEngine, teams: dict | None = None) -> None:
        self.engine = engine
        self.names: dict = {}
        self.codes: dict = {}
        if teams:
            for side in SIDES:
                self.names[side] = teams[side]["name"]
                self.codes[side] = teams[side]["code"]
        self._n = 0
        self._score = {"home": 0, "away": 0}
        self._last_shot: dict = {}
        self._goals: dict = {}
        self._state = "balanced"
        self._last_eval = 0
        self._last_emit = -10**9
        self._max_shot = 0.0
        self._fired: dict = {}

    # ---- naming helpers --------------------------------------------------
    def _team(self, side: str) -> str:
        return self.names.get(side) or self.codes.get(side, side.title())

    def _code(self, side: str) -> str:
        return self.codes.get(side, side.upper())

    def _scoreline(self) -> str:
        return (f'{self._code("home")} {self._score["home"]}-'
                f'{self._score["away"]} {self._code("away")}')

    @staticmethod
    def _player(ev: dict) -> dict | None:
        return {"id": ev["player_id"], "name": ev["player"]} if ev.get("player") else None

    # ---- cooldowns and emission -----------------------------------------
    def _ready(self, key: str, t: int) -> bool:
        return t - self._fired.get(key, -10**9) >= COOLDOWN[key]

    def _emit(self, kind, priority, headline, text, ev, facts, sources,
              side=None, player=None):
        t = self.engine.elapsed
        if priority <= 2 and t - self._last_emit < MIN_GAP_LOW:
            return None
        self._n += 1
        self._last_emit = t
        return {
            "id": f"ov{self._n:03d}",
            "kind": kind,
            "priority": priority,
            "at": {"elapsed_seconds": t, "minute": ev["minute"],
                   "second": ev["second"], "half": ev["half"]},
            "display_seconds": DISPLAY_SECONDS[priority],
            "headline": headline,
            "text": text,
            "team": side,
            "player": player,
            "facts": facts,
            "source_event_ids": sorted(set(sources)),
            "last_event_id": ev["event_id"],
            "verified": None,   # filled in by the fact-checker agent later
        }

    # ---- main entry ------------------------------------------------------
    def process(self, ev: dict) -> list[dict]:
        t = self.engine.elapsed
        self.codes.setdefault(ev["team"], ev["team_code"])
        out = []
        handler = getattr(self, "_on_" + ev["type"], None)
        if handler:
            overlay = handler(ev, t)
            if overlay:
                out.append(overlay)
        if t - self._last_eval >= EVAL_EVERY:
            self._last_eval = t
            out.extend(self._periodic(ev, t))
        return out

    # ---- single-event rules ---------------------------------------------
    def _on_shot(self, ev, t):
        side = ev["team"]
        self._last_shot[side] = ev
        speed = ev["shot_speed_kmh"]
        is_record = speed > self._max_shot
        self._max_shot = max(self._max_shot, speed)
        if ev["outcome"] == "goal":
            return None   # the goal overlay covers it
        player = self._player(ev)
        if ev["xg"] >= BIG_CHANCE_XG:
            verb = {"saved": "was saved", "blocked": "was blocked",
                    "off_target": "missed the target"}[ev["outcome"]]
            text = (f'{ev["player"]} had a big chance for {self._team(side)}: xG {ev["xg"]}, '
                    f'about a {round(ev["xg"] * 100)}% chance of scoring, and the shot {verb}.')
            facts = {"xg": ev["xg"], "outcome": ev["outcome"],
                     "shot_speed_kmh": speed, "distance_to_goal_m": ev["distance_to_goal_m"]}
            return self._emit("big_chance", 3, "Big chance", text, ev, facts,
                              [ev["event_id"]], side, player)
        if is_record and speed >= FAST_SHOT_KMH and self._ready("fast_shot", t):
            text = (f'Fastest shot of the match so far: {ev["player"]} ({self._code(side)}) '
                    f'at {speed:.0f} km/h.')
            overlay = self._emit("fast_shot", 2, "Fastest shot", text, ev,
                                 {"shot_speed_kmh": speed, "outcome": ev["outcome"]},
                                 [ev["event_id"]], side, player)
            if overlay:
                self._fired["fast_shot"] = t
            return overlay
        return None

    def _on_goal(self, ev, t):
        side = ev["team"]
        opp = "away" if side == "home" else "home"
        before = dict(self._score)
        self._score = {"home": ev["score_home"], "away": ev["score_away"]}
        mine, theirs = self._score[side], self._score[opp]
        if mine == theirs:
            situation, line = "equaliser", f"Level at {mine}-{theirs}."
        elif mine > theirs and before[side] <= before[opp]:
            situation, line = "go_ahead", f"{self._team(side)} take the lead."
        elif mine > theirs:
            situation, line = "extends_lead", f"{self._team(side)} extend their lead."
        else:
            situation, line = "pulls_one_back", f"{self._team(side)} pull one back."

        goals = self._goals.setdefault(ev["player_id"], [])
        goals.append(ev["event_id"])
        count = len(goals)
        extra = ""
        if count == 2:
            extra = f' Second goal of the match for {ev["player"]}.'
        elif count == 3:
            extra = f' Hat-trick for {ev["player"]}!'
        elif count > 3:
            extra = f' That is {count} goals for {ev["player"]}.'

        shot = self._last_shot.get(side)
        sources = ([shot["event_id"]] if shot else []) + [ev["event_id"]]
        facts = {
            "scorer_id": ev["player_id"], "scorer": ev["player"], "team": side,
            "score_home": self._score["home"], "score_away": self._score["away"],
            "situation": situation, "goals_by_scorer": count,
            "xg": shot["xg"] if shot else None,
            "shot_speed_kmh": shot["shot_speed_kmh"] if shot else None,
        }
        text = f'{ev["player"]} scores for {self._team(side)}. {self._scoreline()}. {line}{extra}'
        headline = "HAT-TRICK" if count == 3 else "GOAL"
        return self._emit("goal", 5, headline, text, ev, facts, sources,
                          side, self._player(ev))

    def _card_count(self, side: str) -> int:
        return self.engine.snapshot()["totals"][side]["cards"]

    def _on_yellow_card(self, ev, t):
        side = ev["team"]
        n = self._card_count(side)
        text = (f'{ev["player"]} ({self._code(side)}) is shown a yellow card. '
                f'{self._team(side)} now have {_plural(n, "card")} in the match.')
        return self._emit("yellow_card", 2, "Yellow card", text, ev,
                          {"team_cards": n}, [ev["event_id"]], side, self._player(ev))

    def _on_red_card(self, ev, t):
        side = ev["team"]
        text = f'{ev["player"]} is sent off. {self._team(side)} must play on with ten men.'
        return self._emit("red_card", 5, "RED CARD", text, ev,
                          {"team_cards": self._card_count(side)}, [ev["event_id"]],
                          side, self._player(ev))

    def _on_pass(self, ev, t):
        if (ev["outcome"] != "complete" or ev["pass_difficulty"] < DIFFICULT_PASS
                or not self._ready("difficult_pass", t)):
            return None
        side = ev["team"]
        text = (f'{ev["player"]} completes a {ev["pass_distance_m"]:.0f} m pass to '
                f'{ev["receiver"]}, rated {ev["pass_difficulty"]}/10 for difficulty.')
        facts = {"pass_distance_m": ev["pass_distance_m"],
                 "pass_difficulty": ev["pass_difficulty"],
                 "ball_speed_ms": ev["ball_speed_ms"], "receiver": ev["receiver"]}
        overlay = self._emit("difficult_pass", 2, "Tough pass", text, ev, facts,
                             [ev["event_id"]], side, self._player(ev))
        if overlay:
            self._fired["difficult_pass"] = t
        return overlay

    def _on_half_end(self, ev, t):
        return self._summary(ev, final=False)

    def _on_full_time(self, ev, t):
        return self._summary(ev, final=True)

    def _summary(self, ev, final: bool):
        snap = self.engine.snapshot()
        h, a = snap["score"]["home"], snap["score"]["away"]
        tot, poss = snap["totals"], snap["possession_pct"]
        shots = (tot["home"]["shots"], tot["away"]["shots"])
        xg = (tot["home"]["xg"], tot["away"]["xg"])
        self._score = {"home": h, "away": a}
        label = "Full time" if final else "Half time"
        text = (f'{label}: {self._scoreline()}. Possession {poss["home"]:.0f}-{poss["away"]:.0f}, '
                f'shots {shots[0]}-{shots[1]}, xG {xg[0]}-{xg[1]}.')
        if h != a:
            lead, trail = ("home", "away") if h > a else ("away", "home")
            lead_xg, trail_xg = tot[lead]["xg"], tot[trail]["xg"]
            if lead_xg < trail_xg:
                text += (f' {self._team(lead)} {"won" if final else "lead"} despite '
                         f'lower xG ({lead_xg} against {trail_xg}).')
        facts = {"score_home": h, "score_away": a, "possession_pct": poss,
                 "shots": {"home": shots[0], "away": shots[1]},
                 "xg": {"home": xg[0], "away": xg[1]}}
        return self._emit("full_time" if final else "half_time", 4, label, text, ev,
                          facts, [ev["event_id"]])

    # ---- rolling-window rules -------------------------------------------
    def _periodic(self, ev, t) -> list[dict]:
        snap = self.engine.snapshot()
        w = snap["window"]
        out = []
        if t >= WINDOW_READY:
            state = w["state"]
            if (state in ("chaos", "control") and state != self._state
                    and self._ready("state_shift", t)):
                overlay = self._state_shift(ev, w, state)
                if overlay:
                    self._fired["state_shift"] = t
                    out.append(overlay)
            self._state = state
            for side in SIDES:
                for rule in (self._pressing, self._dominance):
                    overlay = rule(ev, t, w, side)
                    if overlay:
                        out.append(overlay)
        return out

    def _window_ids(self, kind: str, side: str | None = None) -> list[int]:
        ids = [e["event_id"] for e in self.engine.window_events()
               if e["type"] == kind and (side is None or e["team"] == side)]
        return ids[-MAX_SOURCES:]

    def _state_shift(self, ev, w, state):
        teams = w["teams"]
        passes = sum(teams[s]["passes"] for s in SIDES)
        complete = sum(teams[s]["passes_complete"] for s in SIDES)
        acc = round(100 * complete / passes, 1) if passes else None
        mins, tpm = w["seconds"] // 60, w["turnovers_per_min"]
        if state == "chaos":
            headline = "Chaos"
            text = (f"The match has turned frantic. The ball changed hands {tpm} times a minute "
                    f"and only {acc}% of passes found a team-mate over the last {mins} minutes.")
        else:
            headline = "Control"
            text = (f"The game has settled. Just {tpm} turnovers a minute and {acc}% pass "
                    f"completion over the last {mins} minutes.")
            if w["dominant_team"]:
                side = w["dominant_team"]
                text += (f' {self._team(side)} have {w["possession_pct"][side]:.0f}% '
                         f"of the passing.")
        facts = {"state": state, "previous_state": self._state,
                 "chaos_index": w["chaos_index"], "turnovers_per_min": tpm,
                 "window_pass_accuracy": acc, "window_seconds": w["seconds"],
                 "possession_pct_window": w["possession_pct"]}
        return self._emit("state_shift", 3, headline, text, ev, facts,
                          self._window_ids("possession_change"))

    def _pressing(self, ev, t, w, side):
        n = w["teams"][side]["pressures"]
        key = f"pressing_{side}"
        COOLDOWN.setdefault(key, COOLDOWN["pressing"])
        if n < PRESSING_MIN or not self._ready(key, t):
            return None
        text = (f'{self._team(side)} are pressing hard: {n} pressure actions '
                f'in the last {w["seconds"] // 60} minutes.')
        overlay = self._emit("pressing", 3, "Pressing", text, ev,
                             {"pressures_in_window": n, "window_seconds": w["seconds"]},
                             self._window_ids("pressure", side), side)
        if overlay:
            self._fired[key] = t
        return overlay

    def _dominance(self, ev, t, w, side):
        pct = w["possession_pct"][side]
        key = f"dominance_{side}"
        COOLDOWN.setdefault(key, COOLDOWN["dominance"])
        if pct < DOMINANCE_PCT or not self._ready(key, t):
            return None
        text = (f'{self._team(side)} are dominating the ball: {pct:.0f}% of the passes '
                f'in the last {w["seconds"] // 60} minutes.')
        overlay = self._emit("dominance", 2, "On top", text, ev,
                             {"pass_share_window": pct, "window_seconds": w["seconds"]},
                             self._window_ids("pass", side), side)
        if overlay:
            self._fired[key] = t
        return overlay


def detect_all(events: list[dict], teams: dict | None = None,
               window_seconds: int = 300) -> list[dict]:
    """Run the whole match through the engine and detector, return all overlays."""
    engine = StatsEngine(window_seconds)
    detector = MomentDetector(engine, teams)
    overlays: list[dict] = []
    for ev in events:
        engine.ingest(ev)
        overlays.extend(detector.process(ev))
    return overlays


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", default="data/match_001_events.jsonl")
    ap.add_argument("--out", help="where to write overlay JSON (default: next to the events)")
    args = ap.parse_args()

    events = load_events(args.events)
    meta_path = args.events.replace("_events.jsonl", "_meta.json")
    teams = None
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            teams = json.load(f)["teams"]
    overlays = detect_all(events, teams)

    out = args.out or args.events.replace("_events.jsonl", "_overlays.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(overlays, f, indent=2)

    for o in overlays:
        print(f'{o["at"]["minute"]:>2}\':{o["at"]["second"]:02d} [p{o["priority"]}] '
              f'{o["headline"]:<12} {o["text"]}')
    kinds: dict = {}
    for o in overlays:
        kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
    print(f"\n{len(overlays)} overlays -> {out}\n{kinds}")


if __name__ == "__main__":
    main()
