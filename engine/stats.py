"""Stats engine: turns a stream of match events into football statistics.

Everything here is plain, deterministic code. The AI agents later in the
pipeline only *explain* these numbers, they never invent them.

Two views are kept up to date as events arrive:
  - totals: the whole match so far
  - window: only the last `window_seconds` of match time (default 5 minutes)

The window view feeds the control-vs-chaos score.
"""
from __future__ import annotations

from collections import deque

from .clock import MatchClock

SIDES = ("home", "away")

# Control-vs-chaos calibration (see chaos_index). Turnovers per minute and the
# share of passes that go astray are each scaled to 0-1 between these bounds.
TURNOVER_RATE_BOUNDS = (0.8, 2.8)
PASS_MISS_BOUNDS = (0.08, 0.30)
CONTROL_BELOW = 0.30
CHAOS_ABOVE = 0.55


def _norm(value: float, lo: float, hi: float) -> float:
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _new_tally() -> dict:
    return {
        "passes": 0, "passes_complete": 0, "difficulty_sum": 0.0,
        "shots": 0, "shots_on_target": 0, "goals": 0, "xg": 0.0,
        "max_shot_kmh": 0.0, "turnovers": 0, "pressures": 0,
        "tackles_won": 0, "fouls": 0, "cards": 0, "corners": 0,
    }


def _add(tally: dict, ev: dict) -> None:
    """Fold one event into the tally of the team it belongs to."""
    kind = ev["type"]
    if kind == "pass":
        tally["passes"] += 1
        tally["difficulty_sum"] += ev.get("pass_difficulty", 0.0)
        if ev.get("outcome") == "complete":
            tally["passes_complete"] += 1
    elif kind == "shot":
        tally["shots"] += 1
        tally["xg"] += ev.get("xg", 0.0)
        tally["max_shot_kmh"] = max(tally["max_shot_kmh"], ev.get("shot_speed_kmh", 0.0))
        if ev.get("outcome") in ("saved", "goal"):
            tally["shots_on_target"] += 1
    elif kind == "goal":
        tally["goals"] += 1
    elif kind == "pressure":
        tally["pressures"] += 1
    elif kind == "tackle" and ev.get("outcome") == "won":
        tally["tackles_won"] += 1
    elif kind == "foul":
        tally["fouls"] += 1
    elif kind in ("yellow_card", "red_card"):
        tally["cards"] += 1
    elif kind == "corner":
        tally["corners"] += 1


def _tally_events(events) -> dict:
    tallies = {s: _new_tally() for s in SIDES}
    for ev in events:
        if ev["type"] == "possession_change":
            # The team that LOST the ball is the one recorded in from_team.
            lost_by = ev.get("from_team")
            if lost_by in tallies:
                tallies[lost_by]["turnovers"] += 1
        elif ev["team"] in tallies:
            _add(tallies[ev["team"]], ev)
    return tallies


def _view(tally: dict) -> dict:
    """Add derived numbers (accuracy, average difficulty) to a raw tally."""
    passes = tally["passes"]
    out = dict(tally)
    out["xg"] = round(tally["xg"], 2)
    out["pass_accuracy"] = round(100 * tally["passes_complete"] / passes, 1) if passes else None
    out["avg_pass_difficulty"] = round(tally["difficulty_sum"] / passes, 1) if passes else None
    del out["difficulty_sum"]
    return out


def _pass_share(tallies: dict) -> dict:
    """Possession proxy: each team's share of all passes attempted."""
    total = sum(t["passes"] for t in tallies.values())
    if not total:
        return {s: 50.0 for s in SIDES}
    return {s: round(100 * tallies[s]["passes"] / total, 1) for s in SIDES}


class StatsEngine:
    def __init__(self, window_seconds: int = 300) -> None:
        self.window_seconds = window_seconds
        self.clock = MatchClock()
        self.elapsed = 0
        self.minute = 0
        self.last_event_id = 0
        self._totals = {s: _new_tally() for s in SIDES}
        self._window: deque = deque()  # (elapsed, event)

    def ingest(self, ev: dict) -> int:
        """Feed one event. Returns the elapsed match seconds for it."""
        self.elapsed = self.clock.elapsed(ev)
        self.minute = ev["minute"]
        self.last_event_id = ev["event_id"]

        if ev["type"] == "possession_change":
            lost_by = ev.get("from_team")
            if lost_by in self._totals:
                self._totals[lost_by]["turnovers"] += 1
        elif ev["team"] in self._totals:
            _add(self._totals[ev["team"]], ev)

        self._window.append((self.elapsed, ev))
        self._evict()
        return self.elapsed

    def _evict(self) -> None:
        cutoff = self.elapsed - self.window_seconds
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()

    def chaos_index(self, window: dict, span_minutes: float) -> float:
        """0 = calm control, 1 = chaos.

        Half comes from how often the ball changes hands, half from how many
        passes go astray, both measured over the rolling window.
        """
        turnovers = sum(window[s]["turnovers"] for s in SIDES)
        passes = sum(window[s]["passes"] for s in SIDES)
        complete = sum(window[s]["passes_complete"] for s in SIDES)
        turnover_rate = turnovers / span_minutes if span_minutes else 0.0
        miss_rate = 1 - complete / passes if passes else 0.0
        return round(
            0.5 * _norm(turnover_rate, *TURNOVER_RATE_BOUNDS)
            + 0.5 * _norm(miss_rate, *PASS_MISS_BOUNDS), 2)

    @staticmethod
    def label(chaos: float) -> str:
        if chaos < CONTROL_BELOW:
            return "control"
        if chaos > CHAOS_ABOVE:
            return "chaos"
        return "balanced"

    def snapshot(self) -> dict:
        totals = {s: _view(self._totals[s]) for s in SIDES}
        window_tallies = _tally_events(ev for _, ev in self._window)
        window = {s: _view(window_tallies[s]) for s in SIDES}

        span_minutes = max(min(self.window_seconds, self.elapsed), 60) / 60
        chaos = self.chaos_index(window, span_minutes)
        share = _pass_share(window_tallies)
        dominant = next((s for s in SIDES if share[s] >= 55), None)
        events_in_window = len(self._window)

        return {
            "elapsed_seconds": self.elapsed,
            "minute": self.minute,
            "last_event_id": self.last_event_id,
            "score": {s: totals[s]["goals"] for s in SIDES},
            "possession_pct": _pass_share({s: self._totals[s] for s in SIDES}),
            "totals": totals,
            "window": {
                "seconds": self.window_seconds,
                "teams": window,
                "possession_pct": share,
                "turnovers_per_min": round(
                    sum(window[s]["turnovers"] for s in SIDES) / span_minutes, 1),
                "tempo_per_min": round(events_in_window / span_minutes, 1),
                "chaos_index": chaos,
                "state": self.label(chaos),
                "dominant_team": dominant,
            },
        }
