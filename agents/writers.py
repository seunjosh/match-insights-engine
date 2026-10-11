"""Writers: turn an overlay's verified facts into an on-screen caption.

Two writers share one interface, `write(overlay, mode, feedback) -> str`:

  LocalWriter              template-based stand-in. Needs no account or network.
                           It can also inject deliberate mistakes on a first
                           attempt (`fault_rate`) so the fact-checker's catch
                           and the retry loop can be tested and demonstrated.

  OpenAICompatibleWriter   asks a chat model over an OpenAI-style API (GitHub
                           Models, Azure OpenAI, or anything compatible). It
                           is configured from environment variables and is
                           told to use only the supplied facts.

`mode` is "analyst" (numbers up front) or "casual" (plain language).
`feedback` is the list of problems the fact-checker found in the last draft.
"""
from __future__ import annotations

import json
import os
import random
import re
import urllib.request

from . import languages

SIDES = ("home", "away")
MODES = ("analyst", "casual")
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _other(side: str) -> str:
    return "away" if side == "home" else "home"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _article(n: int) -> str:
    """'an' before numbers spoken with a leading vowel sound (8, 11, 18, 80-89)."""
    return "an" if n in (8, 11, 18) or 80 <= n <= 89 else "a"


class LocalWriter:
    name = "local-template"

    def __init__(self, teams: dict, fault_rate: float = 0.0, seed: int = 0) -> None:
        self.teams = teams
        self.names = {s: teams[s]["name"] for s in SIDES}
        self.codes = {s: teams[s]["code"] for s in SIDES}
        self.fault_rate = fault_rate
        self.seed = seed

    # ---- public ---------------------------------------------------------
    def write(self, o: dict, mode: str = "casual", feedback: list | None = None,
              lang: str = "en") -> str:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        if lang == "en":
            build = getattr(self, "_" + o["kind"], None)
            text = build(o, mode) if build else o["text"]
        else:
            text = languages.render(self, o, mode, lang)
        if feedback is None and self.fault_rate > 0:
            rng = random.Random(f'{self.seed}-{o["id"]}')
            if rng.random() < self.fault_rate:
                text = self.corrupt(text, o, rng.choice(self._faults_for(o, lang)), lang)
        return text

    # ---- helpers --------------------------------------------------------
    def _team(self, o):
        return self.names[o["team"]]

    def _code(self, o):
        return self.codes[o["team"]]

    def _who(self, o):
        return o["player"]["name"]

    def _scoreline(self, sh, sa):
        return f'{self.codes["home"]} {sh}-{sa} {self.codes["away"]}'

    # ---- captions by kind -----------------------------------------------
    def _goal(self, o, mode):
        f = o["facts"]
        team, who = self._team(o), f["scorer"]
        sh, sa = f["score_home"], f["score_away"]
        diff = abs(sh - sa)
        pct = round(f["xg"] * 100) if f.get("xg") is not None else None
        if mode == "analyst":
            situation = {
                "equaliser": "The sides are level again.",
                "go_ahead": f"{team} edge in front.",
                "extends_lead": f"{team} now lead by {diff}.",
                "pulls_one_back": f"{team} cut the deficit to {diff}.",
            }[f["situation"]]
            detail = ""
            if pct is not None:
                detail = f' The shot carried an xG of {f["xg"]} ({pct}% chance) at {f["shot_speed_kmh"]:.0f} km/h.'
            return f'{who} ({self._code(o)}) scores: {self._scoreline(sh, sa)}.{detail} {situation}'
        situation = {
            "equaliser": "We are all square again!",
            "go_ahead": f"{team} are in front!",
            "extends_lead": f"{team} are pulling clear, {diff} ahead.",
            "pulls_one_back": f"{team} are back in the game.",
        }[f["situation"]]
        text = f"GOAL! {who} scores for {team}, and it is {self._scoreline(sh, sa)}. {situation}"
        if pct is not None and f["xg"] < 0.15:
            text += f" It was only {_article(pct)} {pct}% chance on paper."
        if f["goals_by_scorer"] == 2:
            text += f" That is two for {who}."
        elif f["goals_by_scorer"] == 3:
            text += " Hat-trick!"
        return text

    @staticmethod
    def _verb(outcome):
        return {"saved": "was saved", "blocked": "was blocked",
                "off_target": "missed the target"}[outcome]

    def _big_chance(self, o, mode):
        f, who = o["facts"], self._who(o)
        verb = self._verb(f["outcome"])
        if mode == "analyst":
            pct = round(f["xg"] * 100)
            return (f'{who} ({self._code(o)}): xG {f["xg"]}, {_article(pct)} {pct}% chance, '
                    f'struck at {f["shot_speed_kmh"]:.0f} km/h from {f["distance_to_goal_m"]:.0f} m. '
                    f"The shot {verb}.")
        return f"So close for {self._team(o)}! {who} had a real chance, and the shot {verb}."

    def _fast_shot(self, o, mode):
        f, who = o["facts"], self._who(o)
        if mode == "analyst":
            return f'{who} ({self._code(o)}) hits the hardest shot so far: {f["shot_speed_kmh"]:.0f} km/h.'
        return f'{who} really thumps that one, {f["shot_speed_kmh"]:.0f} km/h!'

    def _yellow_card(self, o, mode):
        who = self._who(o)
        if mode == "analyst":
            return (f'{who} ({self._code(o)}) is booked. {self._team(o)} have '
                    f'{_plural(o["facts"]["team_cards"], "card")} in the match.')
        return f"{who} goes into the book for {self._team(o)}."

    def _red_card(self, o, mode):
        who = self._who(o)
        if mode == "analyst":
            return f"{who} ({self._code(o)}) is sent off. {self._team(o)} must play on a player short."
        return f"Red card! {who} is gone, and {self._team(o)} are a player short."

    def _difficult_pass(self, o, mode):
        f, who = o["facts"], self._who(o)
        if mode == "analyst":
            return (f'{who} ({self._code(o)}) completes a {f["pass_distance_m"]:.0f} m pass to '
                    f'{f["receiver"]}, rated {f["pass_difficulty"]:g}/10 for difficulty.')
        return (f'Lovely ball from {who} to {f["receiver"]}, a {f["pass_distance_m"]:.0f} m pass '
                f'rated {f["pass_difficulty"]:g}/10 for difficulty.')

    def _summary(self, o, mode):
        f = o["facts"]
        final = o["kind"] == "full_time"
        label = "Full time" if final else "Half time"
        sh, sa = f["score_home"], f["score_away"]
        lead = "home" if sh > sa else "away" if sa > sh else None
        if mode == "analyst":
            p, s, x = f["possession_pct"], f["shots"], f["xg"]
            text = (f"{label}: {self._scoreline(sh, sa)}. Possession {p['home']:.0f}-{p['away']:.0f}, "
                    f"shots {s['home']}-{s['away']}, xG {x['home']}-{x['away']}.")
            if lead and x[lead] < x[_other(lead)]:
                text += (f" {self.names[lead]} {'won' if final else 'lead'} despite lower xG "
                         f"({x[lead]} against {x[_other(lead)]}).")
            return text
        text = f"{label}: {self._scoreline(sh, sa)}."
        if lead:
            text += f" {self.names[lead]} {'win it' if final else 'lead at the break'}."
        else:
            text += " It ends level." if final else " All square at the break."
        return text

    _half_time = _summary
    _full_time = _summary

    def _player_card(self, o, mode):
        f, who = o["facts"], self._who(o)
        passes = f'{f["passes"]} {"pass" if f["passes"] == 1 else "passes"}'
        shots = f'{f["shots"]} {"shot" if f["shots"] == 1 else "shots"}'
        tackles = f'{f["tackles_won"]} {"tackle" if f["tackles_won"] == 1 else "tackles"} won'
        pressures = f'{f["pressures"]} pressure {"action" if f["pressures"] == 1 else "actions"}'
        if mode == "analyst":
            if f["pass_accuracy"] is not None:
                passes += f' ({f["pass_accuracy"]}% completed)'
            text = f'{who} ({self._code(o)}) so far: {passes}, {shots}, xG {f["xg"]}'
            if f["goals"]:
                text += f', {f["goals"]} {"goal" if f["goals"] == 1 else "goals"}'
            return text + f', {tackles}, {pressures}.'
        if f["goals"]:
            shots += f' (including {f["goals"]} {"goal" if f["goals"] == 1 else "goals"})'
        return f'Your player {who} so far: {passes}, {shots} and {tackles}.'

    def _state_shift(self, o, mode):
        f = o["facts"]
        tpm, mins = f["turnovers_per_min"], f["window_seconds"] // 60
        if mode == "analyst":
            if f["state"] == "chaos":
                return (f'Chaos index {f["chaos_index"]}: {tpm} turnovers a minute and '
                        f'{f["window_pass_accuracy"]}% pass completion over the last {mins} minutes.')
            return (f'Control: {tpm} turnovers a minute, {f["window_pass_accuracy"]}% pass '
                    f'completion over the last {mins} minutes, chaos index {f["chaos_index"]}.')
        if f["state"] == "chaos":
            return f"The game has gone wild. The ball keeps changing hands, {tpm} times a minute."
        return "Things have calmed down. The passing is tidy and the ball is staying put."

    def _pressing(self, o, mode):
        f, team = o["facts"], self._team(o)
        if mode == "analyst":
            return (f'{team} are pressing high: {f["pressures_in_window"]} pressure actions '
                    f'in {f["window_seconds"] // 60} minutes.')
        return f"{team} are in their opponents' faces, closing them down again and again."

    def _dominance(self, o, mode):
        f, team = o["facts"], self._team(o)
        if mode == "analyst":
            return (f'{team} have {f["pass_share_window"]:.0f}% of the passes over the last '
                    f'{f["window_seconds"] // 60} minutes.')
        return f"{team} are running the show with the ball."

    # ---- deliberate mistakes (testing and demos only) --------------------
    @staticmethod
    def _faults_for(o, lang="en"):
        faults = ["number", "entity", "claim"]
        if lang == "en":   # the situation and outcome faults edit English phrases
            if o["kind"] == "goal":
                faults.append("situation")
            if o["kind"] == "big_chance":
                faults.append("outcome")
        return faults

    def corrupt(self, text: str, o: dict, fault: str, lang: str = "en") -> str:
        """Return `text` with one deliberate mistake. Falls back to an invented stat."""
        out = text if (lang != "en" and fault == "claim") else getattr(self, "_fault_" + fault)(text, o)
        if out == text:
            out = text + (self._fault_claim("", o) if lang == "en" else languages.fake_claim(lang))
        return out

    @staticmethod
    def _fault_number(text, o):
        matches = list(NUMBER.finditer(text))
        if not matches:
            return text
        m = matches[-1]
        s = m.group(0)
        bumped = (f"{float(s) + 1:.{len(s.split('.')[1])}f}" if "." in s else str(int(s) + 1))
        return text[:m.start()] + bumped + text[m.end():]

    def _fault_entity(self, text, o):
        player = (o.get("player") or {}).get("name")
        if player and player in text:
            other = self.teams[_other(o["team"])]["players"][1]["name"]
            return text.replace(player, other, 1)
        if o["kind"] in ("pressing", "dominance") and o["team"]:
            return text.replace(self.names[o["team"]], self.names[_other(o["team"])])
        return text

    @staticmethod
    def _fault_claim(text, o):
        return text + " That is the 137th shot on target this season."

    @staticmethod
    def _fault_situation(text, o):
        if o["facts"]["situation"] != "equaliser":
            return text + " The sides are level again."
        return text + " They take the lead."

    @staticmethod
    def _fault_outcome(text, o):
        return re.sub(r"was saved|was blocked|missed the target", "went in for a goal", text)


class OpenAICompatibleWriter:
    """Chat-model writer for any OpenAI-style `/chat/completions` endpoint.

    Environment variables (see `from_env`):
      LLM_BASE_URL     e.g. the GitHub Models or Azure OpenAI endpoint (see their docs)
      LLM_API_KEY      your key or token
      LLM_MODEL        model or deployment name
      LLM_AUTH         "bearer" (default) or "api-key" (Azure OpenAI)
      LLM_API_VERSION  optional, appended as ?api-version=... (Azure OpenAI)

    This class has been tested only with a stubbed network call.
    """

    RULES = (
        "You write one short on-screen caption (under 40 words) for a live football match overlay. "
        "Use ONLY the facts supplied. Never add numbers, names, players, teams or events that are "
        "not in the facts. Use full player names exactly as given. Do not call a moment a goal "
        "unless the kind is goal. Return the caption text only."
    )
    MODE_HINTS = {
        "analyst": "Audience: a data-hungry analyst. Lead with the numbers and be precise.",
        "casual": "Audience: a casual fan. Use plain, warm language and avoid statistics jargon.",
    }

    def __init__(self, base_url, api_key, model, auth="bearer", api_version=None,
                 post=None, teams=None):
        self.base_url = base_url.rstrip("/")
        self.api_key, self.model, self.auth = api_key, model, auth
        self.api_version = api_version
        self.post = post or self._http_post
        self.names = {s: teams[s]["name"] for s in SIDES} if teams else {}
        self.name = f"llm:{model}"

    @classmethod
    def from_env(cls, teams):
        env = os.environ
        missing = [k for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL") if not env.get(k)]
        if missing:
            raise SystemExit("Set these environment variables to use the model writer: "
                             + ", ".join(missing))
        return cls(env["LLM_BASE_URL"], env["LLM_API_KEY"], env["LLM_MODEL"],
                   env.get("LLM_AUTH", "bearer"), env.get("LLM_API_VERSION"), teams=teams)

    def build_messages(self, o, mode, feedback, lang="en"):
        payload = {
            "kind": o["kind"], "headline": o["headline"], "base_text": o["text"],
            "team": self.names.get(o["team"]) if o.get("team") else None,
            "player": (o.get("player") or {}).get("name"),
            "facts": o["facts"],
        }
        user = json.dumps(payload)
        if feedback:
            user += ("\nYour previous draft was rejected for these reasons, fix them: "
                     + "; ".join(feedback))
        system = self.RULES + " " + self.MODE_HINTS[mode]
        if lang != "en":
            system += (f" Write the caption in {languages.LANGUAGE_NAMES[lang]}. Keep every number, "
                       "player name, team name and the scoreline exactly as in the facts, using digits.")
        return [{"role": "system", "content": system},
                {"role": "user", "content": user}]

    def write(self, o, mode="casual", feedback=None, lang="en"):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        url = self.base_url + "/chat/completions"
        if self.api_version:
            url += f"?api-version={self.api_version}"
        headers = {"Content-Type": "application/json"}
        headers["api-key" if self.auth == "api-key" else "Authorization"] = (
            self.api_key if self.auth == "api-key" else f"Bearer {self.api_key}")
        body = {"model": self.model, "temperature": 0.4,
                "messages": self.build_messages(o, mode, feedback, lang)}
        data = self.post(url, headers, body)
        return data["choices"][0]["message"]["content"].strip().strip('"')

    @staticmethod
    def _http_post(url, headers, body):
        req = urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
