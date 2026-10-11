"""Fact-checker: verifies overlays against the raw match events.

It works in two stages and never trusts the detector or the writer:

1. Facts: every number in an overlay's `facts` is recomputed from the raw
   events with separate code (not the stats engine) and compared.
2. Text: every number, player, team and claim in a caption must be backed by
   those verified facts. Unsupported numbers, names that do not belong to the
   moment, and claims that contradict the facts (a "goal" in a missed chance,
   "level" in a go-ahead goal) are rejected with a reason the writer can use
   to try again.

Known limits: it checks numbers, names and the claim phrases listed below. It
cannot judge style, and a model that writes only a surname (several players
share surnames) cannot be checked for swaps, so writers must use full names.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from engine.clock import MatchClock
from . import languages
from engine.stats import CHAOS_ABOVE, CONTROL_BELOW, PASS_MISS_BOUNDS, SIDES, TURNOVER_RATE_BOUNDS

NUMBER = re.compile(r"\d+(?:\.\d+)?")
TOLERANCE = 0.051
MAX_WORDS = 60
GOAL_WORDS = re.compile(r"\bgoals?\b|\bscor(?:es|ed)\b|\bequali[sz]er\b", re.I)
GOAL_KINDS = {"goal", "half_time", "full_time"}
GOAL_WORD_KINDS = GOAL_KINDS | {"player_card"}   # kinds whose text may mention goals
BOTH_TEAM_KINDS = {"half_time", "full_time", "state_shift"}
# Phrases that assert how a goal changed the match, and the situation they mean.
SITUATION_PHRASES = {
    "level": "equaliser", "all square": "equaliser",
    "take the lead": "go_ahead", "in front": "go_ahead", "now lead": "extends_lead",
    "lead by": "extends_lead", "extend": "extends_lead", "pulling clear": "extends_lead",
    "pull one back": "pulls_one_back", "back in the game": "pulls_one_back",
    "cut the deficit": "pulls_one_back",
}


def _norm(value: float, lo: float, hi: float) -> float:
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _numbers(value):
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _numbers(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _numbers(v)


def _forms(v) -> set:
    forms = {str(v), f"{v:g}", f"{v:.0f}", f"{v:.1f}", f"{v:.2f}"}
    if float(v).is_integer():
        forms.add(str(int(v)))
    return forms


@dataclass
class CheckResult:
    issues: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


class FactChecker:
    def __init__(self, events: list[dict], teams: dict) -> None:
        self.events = events
        self.pos = {e["event_id"]: i for i, e in enumerate(events)}
        clock = MatchClock()
        self.elapsed = {e["event_id"]: clock.elapsed(e) for e in events}
        self.teams = teams
        self.names = {s: teams[s]["name"] for s in SIDES}
        self.codes = {s: teams[s]["code"] for s in SIDES}
        self.players = {p["name"] for s in SIDES for p in teams[s]["players"]}

    # ------------------------------------------------------------------ facts
    def check_facts(self, o: dict) -> list[str]:
        """Recompute the overlay's facts from raw events. Empty list = verified."""
        last = o["last_event_id"]
        if last not in self.pos:
            return ["the triggering event does not exist in the match data"]
        issues = []
        if o["at"]["elapsed_seconds"] != self.elapsed[last]:
            issues.append("the overlay time does not match its triggering event")
        for sid in o["source_event_ids"]:
            if sid not in self.pos:
                issues.append(f"source event {sid} does not exist")
            elif sid > last:
                issues.append(f"source event {sid} happened after the overlay")
        if issues:
            return issues
        rule = getattr(self, "_facts_" + o["kind"], None)
        if rule is None:
            return [f'no verification rule for overlay kind "{o["kind"]}"']
        return rule(o, self.events[self.pos[last]])

    def _cmp(self, expected: dict, facts: dict, prefix: str = "") -> list[str]:
        issues = []
        for key, want in expected.items():
            got = facts.get(key, "<missing>")
            name = prefix + key
            if isinstance(want, dict):
                if isinstance(got, dict):
                    issues += self._cmp(want, got, name + ".")
                else:
                    issues.append(f"fact {name} is missing")
            elif (isinstance(want, (int, float)) and not isinstance(want, bool)
                  and isinstance(got, (int, float))):
                if abs(got - want) > TOLERANCE:
                    issues.append(f"fact {name} is {got} but the match data gives {want}")
            elif got != want:
                issues.append(f"fact {name} is {got!r} but the match data gives {want!r}")
        return issues

    def _upto(self, ev):
        return self.events[: self.pos[ev["event_id"]] + 1]

    def _window(self, o):
        last = o["last_event_id"]
        t = self.elapsed[last]
        seconds = o["facts"].get("window_seconds", 300)
        win = [e for e in self.events[: self.pos[last] + 1]
               if t - seconds <= self.elapsed[e["event_id"]] <= t]
        return t, seconds, win

    def _sources_within(self, o, win, kind, side=None):
        ids = {e["event_id"] for e in win if e["type"] == kind and (side is None or e["team"] == side)}
        bad = [s for s in o["source_event_ids"] if s not in ids]
        return [f"source events {bad} are not {kind} events in the window"] if bad else []

    def _facts_goal(self, o, ev):
        if ev["type"] != "goal":
            return ["the triggering event is not a goal"]
        upto = self._upto(ev)
        goals = [e for e in upto if e["type"] == "goal"]
        side = ev["team"]
        opp = "away" if side == "home" else "home"
        counted = {s: sum(1 for g in goals if g["team"] == s) for s in SIDES}
        issues = []
        if (ev["score_home"], ev["score_away"]) != (counted["home"], counted["away"]):
            issues.append("the goal event's scoreline disagrees with the goals counted")
        prev = goals[-2] if len(goals) > 1 else None
        before = {"home": prev["score_home"], "away": prev["score_away"]} if prev else {"home": 0, "away": 0}
        mine, theirs = counted[side], counted[opp]
        if mine == theirs:
            situation = "equaliser"
        elif mine > theirs and before[side] <= before[opp]:
            situation = "go_ahead"
        elif mine > theirs:
            situation = "extends_lead"
        else:
            situation = "pulls_one_back"
        shots = [e for e in upto if e["type"] == "shot" and e["team"] == side
                 and e["event_id"] < ev["event_id"]]
        shot = shots[-1] if shots else None
        expected = {
            "scorer_id": ev["player_id"], "scorer": ev["player"], "team": side,
            "score_home": counted["home"], "score_away": counted["away"],
            "situation": situation,
            "goals_by_scorer": sum(1 for g in goals if g["player_id"] == ev["player_id"]),
            "xg": shot["xg"] if shot else None,
            "shot_speed_kmh": shot["shot_speed_kmh"] if shot else None,
        }
        if ev["event_id"] not in o["source_event_ids"]:
            issues.append("the goal event is not among the sources")
        return issues + self._cmp(expected, o["facts"])

    def _facts_big_chance(self, o, ev):
        if ev["type"] != "shot" or ev["outcome"] == "goal":
            return ["the triggering event is not a missed or saved shot"]
        expected = {k: ev[k] for k in ("xg", "outcome", "shot_speed_kmh", "distance_to_goal_m")}
        return self._cmp(expected, o["facts"])

    def _facts_fast_shot(self, o, ev):
        if ev["type"] != "shot":
            return ["the triggering event is not a shot"]
        earlier = [e["shot_speed_kmh"] for e in self._upto(ev)[:-1] if e["type"] == "shot"]
        issues = []
        if earlier and ev["shot_speed_kmh"] < max(earlier):
            issues.append("an earlier shot was faster, so this is not the fastest so far")
        expected = {"shot_speed_kmh": ev["shot_speed_kmh"], "outcome": ev["outcome"]}
        return issues + self._cmp(expected, o["facts"])

    def _facts_card(self, o, ev, kind):
        if ev["type"] != kind:
            return [f"the triggering event is not a {kind}"]
        cards = sum(1 for e in self._upto(ev) if e["type"] in ("yellow_card", "red_card")
                    and e["team"] == ev["team"])
        return self._cmp({"team_cards": cards}, o["facts"])

    def _facts_yellow_card(self, o, ev):
        return self._facts_card(o, ev, "yellow_card")

    def _facts_red_card(self, o, ev):
        return self._facts_card(o, ev, "red_card")

    def _facts_difficult_pass(self, o, ev):
        if ev["type"] != "pass" or ev["outcome"] != "complete":
            return ["the triggering event is not a completed pass"]
        expected = {"pass_distance_m": ev["pass_distance_m"], "pass_difficulty": ev["pass_difficulty"],
                    "ball_speed_ms": ev["ball_speed_ms"], "receiver": ev["receiver"]}
        return self._cmp(expected, o["facts"])

    def _facts_summary(self, o, ev, kind):
        if ev["type"] != ("full_time" if kind == "full_time" else "half_end"):
            return ["the triggering event is not a match-period marker"]
        upto = self._upto(ev)
        goals = {s: sum(1 for e in upto if e["type"] == "goal" and e["team"] == s) for s in SIDES}
        shots = {s: sum(1 for e in upto if e["type"] == "shot" and e["team"] == s) for s in SIDES}
        xg = {s: round(sum(e["xg"] for e in upto if e["type"] == "shot" and e["team"] == s), 2) for s in SIDES}
        passes = {s: sum(1 for e in upto if e["type"] == "pass" and e["team"] == s) for s in SIDES}
        total = sum(passes.values())
        poss = {s: round(100 * passes[s] / total, 1) if total else 50.0 for s in SIDES}
        expected = {"score_home": goals["home"], "score_away": goals["away"],
                    "possession_pct": poss, "shots": shots, "xg": xg}
        return self._cmp(expected, o["facts"])

    def _facts_half_time(self, o, ev):
        return self._facts_summary(o, ev, "half_time")

    def _facts_full_time(self, o, ev):
        return self._facts_summary(o, ev, "full_time")

    def _facts_player_card(self, o, ev):
        pid = o["player"]["id"]
        mine = [e for e in self._upto(ev) if e.get("player_id") == pid]
        passes = [e for e in mine if e["type"] == "pass"]
        done = sum(e["outcome"] == "complete" for e in passes)
        shots = [e for e in mine if e["type"] == "shot"]
        expected = {
            "passes": len(passes), "passes_complete": done,
            "pass_accuracy": round(100 * done / len(passes), 1) if passes else None,
            "shots": len(shots),
            "shots_on_target": sum(e["outcome"] in ("saved", "goal") for e in shots),
            "goals": sum(1 for e in mine if e["type"] == "goal"),
            "xg": round(sum(e["xg"] for e in shots), 2),
            "tackles_won": sum(1 for e in mine if e["type"] == "tackle" and e["outcome"] == "won"),
            "pressures": sum(1 for e in mine if e["type"] == "pressure"),
        }
        foreign = [s for s in o["source_event_ids"] if self.events[self.pos[s]].get("player_id") != pid]
        issues = [f"source events {foreign} do not involve {pid}"] if foreign else []
        return issues + self._cmp(expected, o["facts"])

    def _window_numbers(self, win, t, seconds):
        span = max(min(seconds, t), 60) / 60
        turnovers = sum(1 for e in win if e["type"] == "possession_change")
        passes = {s: 0 for s in SIDES}
        complete = {s: 0 for s in SIDES}
        for e in win:
            if e["type"] == "pass":
                passes[e["team"]] += 1
                complete[e["team"]] += e["outcome"] == "complete"
        return span, turnovers, passes, complete

    def _facts_state_shift(self, o, ev):
        t, seconds, win = self._window(o)
        span, turnovers, passes, complete = self._window_numbers(win, t, seconds)
        total = sum(passes.values())
        done = sum(complete.values())
        miss = 1 - done / total if total else 0.0
        chaos = round(0.5 * _norm(turnovers / span, *TURNOVER_RATE_BOUNDS)
                      + 0.5 * _norm(miss, *PASS_MISS_BOUNDS), 2)
        state = "control" if chaos < CONTROL_BELOW else "chaos" if chaos > CHAOS_ABOVE else "balanced"
        share = {s: round(100 * passes[s] / total, 1) if total else 50.0 for s in SIDES}
        expected = {"state": state, "chaos_index": chaos,
                    "turnovers_per_min": round(turnovers / span, 1),
                    "window_pass_accuracy": round(100 * done / total, 1) if total else None,
                    "possession_pct_window": share}
        return (self._cmp(expected, o["facts"])
                + self._sources_within(o, win, "possession_change"))

    def _facts_pressing(self, o, ev):
        t, seconds, win = self._window(o)
        side = o["team"]
        n = sum(1 for e in win if e["type"] == "pressure" and e["team"] == side)
        return (self._cmp({"pressures_in_window": n}, o["facts"])
                + self._sources_within(o, win, "pressure", side))

    def _facts_dominance(self, o, ev):
        t, seconds, win = self._window(o)
        _, _, passes, _ = self._window_numbers(win, t, seconds)
        total = sum(passes.values())
        share = round(100 * passes[o["team"]] / total, 1) if total else 50.0
        return (self._cmp({"pass_share_window": share}, o["facts"])
                + self._sources_within(o, win, "pass", o["team"]))

    # ------------------------------------------------------------------- text
    def _allowed_numbers(self, o) -> set:
        facts = o["facts"]
        allowed = set()
        values = list(_numbers(facts)) + [o["at"]["minute"]]
        if "window_seconds" in facts:
            values.append(facts["window_seconds"] / 60)
        if facts.get("xg") is not None and o["kind"] in ("goal", "big_chance"):
            values.append(round(facts["xg"] * 100))
        if "score_home" in facts:
            values.append(abs(facts["score_home"] - facts["score_away"]))
        for v in values:
            allowed |= _forms(v)
        if o["kind"] == "difficult_pass":
            allowed.add("10")   # the "/10" of the difficulty scale
        return allowed

    def _allowed_team_tokens(self, o) -> set:
        sides = SIDES if o["kind"] in BOTH_TEAM_KINDS else ((o["team"],) if o["team"] else ())
        tokens = {self.names[s] for s in sides} | {self.codes[s] for s in sides}
        if o["kind"] == "goal":
            tokens |= set(self.codes.values())   # the scoreline shows both codes
        return tokens

    def check_text(self, o: dict, text: str, lang: str = "en") -> list[str]:
        """Issues with a caption for overlay `o` written in `lang`. Empty list = acceptable."""
        issues = []
        facts = o["facts"]
        if lang != "en":
            text = languages.nfc(text)

        allowed = self._allowed_numbers(o)
        for num in dict.fromkeys(NUMBER.findall(text)):
            if num not in allowed:
                issues.append(f"the number {num} is not supported by the facts")

        if o["kind"] in GOAL_KINDS:
            pattern = rf'\b{re.escape(self.codes["home"])} (\d+)-(\d+) {re.escape(self.codes["away"])}\b'
            m = re.search(pattern, text)
            if m and (int(m.group(1)), int(m.group(2))) != (facts["score_home"], facts["score_away"]):
                issues.append(f'the scoreline {m.group(1)}-{m.group(2)} does not match the facts '
                              f'({facts["score_home"]}-{facts["score_away"]})')

        player = (o.get("player") or {}).get("name")
        allowed_players = {player, facts.get("receiver"), facts.get("scorer")} - {None}
        for name in sorted(self.players):
            if name in text and name not in allowed_players:
                issues.append(f"{name} is mentioned but is not part of this moment")
        if player and player not in text:
            issues.append(f"the caption does not name {player}")

        allowed_teams = self._allowed_team_tokens(o)
        mentioned = [t for s in SIDES for t in (self.names[s], self.codes[s])
                     if re.search(rf"\b{re.escape(t)}\b", text)]
        for token in mentioned:
            if token not in allowed_teams:
                issues.append(f"{token} is mentioned but is not part of this moment")
        if not player and o["team"] and not (allowed_teams & set(mentioned)):
            issues.append(f'the caption does not name {self.names[o["team"]]}')

        if o["kind"] not in GOAL_WORD_KINDS and languages.GOAL_WORDS[lang].search(text):
            issues.append("the caption talks about a goal, but this moment is not a goal")

        if o["kind"] == "goal":
            lowered = text.lower()
            phrases = SITUATION_PHRASES if lang == "en" else languages.SITUATION_PHRASES[lang]
            for phrase, situation in phrases.items():
                if phrase in lowered and situation != facts["situation"]:
                    issues.append(f'"{phrase}" contradicts the facts (situation: {facts["situation"]})')

        if len(text.split()) > MAX_WORDS:
            issues.append(f"the caption is too long (over {MAX_WORDS} words)")
        return issues

    def check(self, o: dict, text: str | None = None) -> CheckResult:
        """Full check: facts first, then the caption text."""
        issues = self.check_facts(o)
        if not issues:
            issues = self.check_text(o, o["text"] if text is None else text)
        return CheckResult(issues)
