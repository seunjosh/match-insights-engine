"""Language packs: Nigerian Pidgin (pcm) and Yoruba (yo) captions.

English lives in LocalWriter. For the other languages the numbers, names and
scoreline are filled in by code from the verified facts; only the wording comes
from the pack. That is why a pack is easy to review and correct: every phrase
is one plain string in PACKS below, with {placeholders} for the facts.

*** The Pidgin and Yoruba wording was drafted by an AI and has NOT been reviewed
by a native speaker. Run `python -m tools.language_review` to print every
phrase next to a real example, fix anything that reads wrong, and re-run the tests. ***

The fact-checker also needs to know, per language, which words mean "goal" and
which phrases mean "level", "in front" and so on (`GOAL_WORDS`, `SITUATION_PHRASES`).
Keep those in step with the wording in the pack.
"""
from __future__ import annotations

import re
import unicodedata

LANGUAGES = ("en", "pcm", "yo")
LANGUAGE_NAMES = {"en": "English", "pcm": "Nigerian Pidgin", "yo": "Yoruba"}


def nfc(s: str) -> str:
    """Tone marks can be stored in two ways; compare them in one form."""
    return unicodedata.normalize("NFC", s)


PACKS = {
    "pcm": {
        "verbs": {"saved": "keeper save am", "blocked": "dem block am", "off_target": "e no hit target"},
        "label": {"half_time": "Half time", "full_time": "Full time"},
        "goal": {
            "analyst": "{who} ({code}) don score: {score}.{detail} {situation}",
            "casual": "GOAL! {who} score for {team}, and e be {score}. {situation}",
            "detail": " Di shot get xG of {xg} ({pct}% chance), e fly {speed} km/h.",
            "situation": {
                "analyst": {
                    "equaliser": "Dem don level again.",
                    "go_ahead": "{team} don go front.",
                    "extends_lead": "{team} now lead by {diff}.",
                    "pulls_one_back": "{team} don reduce di gap to {diff}.",
                },
                "casual": {
                    "equaliser": "Everybody level again!",
                    "go_ahead": "{team} don go front!",
                    "extends_lead": "{team} dey pull clear, {diff} ahead.",
                    "pulls_one_back": "{team} don come back inside di game.",
                },
            },
            "low_xg": " Na only {pct}% chance e be on paper.",
            "brace": " Na two for {who}.",
            "hat_trick": " Hat-trick!",
        },
        "big_chance": {
            "analyst": "{who} ({code}): xG {xg}, {pct}% chance, e shoot am {speed} km/h from {dist} m. Di shot: {verb}.",
            "casual": "E near well for {team}! {who} get real chance, but {verb}.",
        },
        "fast_shot": {
            "analyst": "{who} ({code}) shoot di hardest shot so far: {speed} km/h.",
            "casual": "{who} blast am well well, {speed} km/h!",
        },
        "yellow_card": {
            "analyst": "{who} ({code}) collect yellow card. {team} get {n} card for di match.",
            "casual": "Referee show {who} yellow card for {team}.",
        },
        "red_card": {
            "analyst": "{who} ({code}) don commot with red card. {team} go play with one man less.",
            "casual": "Red card! {who} don go, and {team} don remain one man short.",
        },
        "difficult_pass": {
            "analyst": "{who} ({code}) complete {dist} m pass go {recv}, difficulty rating na {diff}/10.",
            "casual": "Fine ball from {who} to {recv}, {dist} m pass wey difficulty na {diff}/10.",
        },
        "summary": {
            "analyst": "{label}: {score}. Possession {ph}-{pa}, shots {sh}-{sa}, xG {xh}-{xa}.{despite}",
            "despite": " {team} {won} even though dem get lower xG ({a} against {b}).",
            "won": {"full_time": "win am", "half_time": "dey lead"},
            "casual": "{label}: {score}.{lead}",
            "lead": " {team} {verb}.",
            "lead_verb": {"full_time": "don win am", "half_time": "dey lead for half time"},
            "level": {"full_time": " E end level.", "half_time": " Everybody level for half time."},
        },
        "player_card": {
            "analyst": "{who} ({code}) so far: {passes} pass{acc}, {shots} shot, xG {xg}{goals}, {tackles} tackle wey e win, {pressures} pressure action.",
            "acc": " ({a}% complete)",
            "goals": ", {g} goal",
            "casual": "Your player {who} so far: {passes} pass, {shots} shot{incl} and {tackles} tackle wey e win.",
            "incl": " ({g} goal inside)",
        },
        "state_shift": {
            "chaos_analyst": "Chaos index {ci}: ball dey change hand {tpm} times for minute and {acc}% pass complete for last {mins} minutes.",
            "control_analyst": "Control: ball dey change hand {tpm} times for minute, {acc}% pass complete for last {mins} minutes, chaos index {ci}.",
            "chaos_casual": "Di game don wild. Di ball dey change hand {tpm} times for minute.",
            "calm_casual": "Things don calm down. Di passing clean and di ball dey stay put.",
        },
        "pressing": {
            "analyst": "{team} dey press high: {n} pressure for {mins} minutes.",
            "casual": "{team} dey sweat dia opponent, dey close dem down again and again.",
        },
        "dominance": {
            "analyst": "{team} get {pct}% of di passes for last {mins} minutes.",
            "casual": "{team} dey control di game with di ball.",
        },
        "fake_claim": " Na di 137th shot on target dis season.",
    },
    "yo": {
        "verbs": {"saved": "aṣọle gbà á", "blocked": "wọ́n dí i lọ́nà",
                  "off_target": "kò kọlu ibi àfojúsùn"},
        "label": {"half_time": "Ìsinmi àárín eré", "full_time": "Ìparí eré"},
        "goal": {
            "analyst": "{who} ({code}) gba góòlù wọlé: {score}.{detail} {situation}",
            "casual": "GÓÒLÙ! {who} gba góòlù wọlé fún {team}, ó sì jẹ́ {score}. {situation}",
            "detail": " Ìgbá bọ́ọ̀lù náà ní xG {xg} ({pct}% àǹfààní), ó yára {speed} km/h.",
            "situation": {
                "analyst": {
                    "equaliser": "Wọ́n ti dọ́gba padà.",
                    "go_ahead": "{team} ti wà níwájú.",
                    "extends_lead": "{team} ń ṣáájú pẹ̀lú {diff}.",
                    "pulls_one_back": "{team} ti dín ìyàtọ̀ kù sí {diff}.",
                },
                "casual": {
                    "equaliser": "Gbogbo wọn ti dọ́gba padà!",
                    "go_ahead": "{team} ti wà níwájú!",
                    "extends_lead": "{team} ń lọ jìnnà, wọ́n ju àwọn alátakò lọ ní {diff}!",
                    "pulls_one_back": "{team} ti padà wọ inú eré náà.",
                },
            },
            "low_xg": " Àǹfààní {pct}% péré ni lórí ìwé.",
            "brace": " Èyí jẹ́ méjì fún {who}.",
            "hat_trick": " Góòlù mẹ́ta nínú eré kan!",
        },
        "big_chance": {
            "analyst": "{who} ({code}): xG {xg}, {pct}% àǹfààní, ó gba bọ́ọ̀lù tó yára {speed} km/h láti {dist} m. Ìgbá náà: {verb}.",
            "casual": "Ó fẹ́rẹ̀ wọlé fún {team}! {who} ní àǹfààní gidi, ṣùgbọ́n {verb}.",
        },
        "fast_shot": {
            "analyst": "{who} ({code}) gba bọ́ọ̀lù tó lágbára jù títí di àkókò yìí: {speed} km/h.",
            "casual": "{who} gba bọ́ọ̀lù líle, {speed} km/h!",
        },
        "yellow_card": {
            "analyst": "{who} ({code}) gba kaadi ofeefee. {team} ní kaadi {n} nínú eré náà.",
            "casual": "Rẹfiri fi kaadi ofeefee han {who} ti {team}.",
        },
        "red_card": {
            "analyst": "{who} ({code}) gba kaadi pupa, a ti lé e jáde. {team} yóò ṣeré pẹ̀lú ẹni kan tó dín.",
            "casual": "Káàdì pupa! {who} ti jáde, {team} sì ti dín ẹnì kan.",
        },
        "difficult_pass": {
            "analyst": "{who} ({code}) fi bọ́ọ̀lù ránṣẹ́ sí {recv} ní ìwọ̀n {dist} m, ìdíwọ̀n ìṣòro rẹ̀ jẹ́ {diff}/10.",
            "casual": "Bọ́ọ̀lù tó dára láti ọwọ́ {who} sí {recv}, {dist} m, ìṣòro rẹ̀ jẹ́ {diff}/10.",
        },
        "summary": {
            "analyst": "{label}: {score}. Ìdìmú bọ́ọ̀lù {ph}-{pa}, ìgbá {sh}-{sa}, xG {xh}-{xa}.{despite}",
            "despite": " {team} {won} bó tilẹ̀ jẹ́ pé xG wọn kéré ({a} sí {b}).",
            "won": {"full_time": "borí", "half_time": "ń ṣáájú"},
            "casual": "{label}: {score}.{lead}",
            "lead": " {team} {verb}.",
            "lead_verb": {"full_time": "ti borí", "half_time": "ń ṣáájú ní ìsinmi"},
            "level": {"full_time": " Eré náà parí ní ìdọ́gba.", "half_time": " Ó dọ́gba ní ìsinmi."},
        },
        "player_card": {
            "analyst": "{who} ({code}) títí di báyìí: pàsì {passes}{acc}, ìgbá {shots}, xG {xg}{goals}, ìgbà {tackles} tó gba bọ́ọ̀lù, titẹ {pressures}.",
            "acc": " ({a}% ṣàṣeyọrí)",
            "goals": ", góòlù {g}",
            "casual": "Olùṣeré rẹ {who} títí di báyìí: pàsì {passes}, ìgbá {shots}{incl} àti ìgbà {tackles} tó gba bọ́ọ̀lù.",
            "incl": " (góòlù {g} wà níbẹ̀)",
        },
        "state_shift": {
            "chaos_analyst": "Chaos index {ci}: bọ́ọ̀lù yí ọwọ́ {tpm} ní ìṣẹ́jú kan, pàsì {acc}% tó yẹ ní ìṣẹ́jú {mins} tó kọjá.",
            "control_analyst": "Ìṣàkóso: bọ́ọ̀lù yí ọwọ́ {tpm} ní ìṣẹ́jú kan, pàsì {acc}% tó yẹ ní ìṣẹ́jú {mins} tó kọjá, chaos index {ci}.",
            "chaos_casual": "Eré náà ti dàrú. Bọ́ọ̀lù ń yí ọwọ́ {tpm} ní ìṣẹ́jú kan.",
            "calm_casual": "Eré náà ti rọlẹ̀. Pàsì ń lọ dáadáa, bọ́ọ̀lù sì dúró sí ibi kan.",
        },
        "pressing": {
            "analyst": "{team} ń fi titẹ gíga: {n} ìgbà ní ìṣẹ́jú {mins}.",
            "casual": "{team} ń dí àwọn alátakò lọ́nà léraléra.",
        },
        "dominance": {
            "analyst": "{team} ní {pct}% pàsì ní ìṣẹ́jú {mins} tó kọjá.",
            "casual": "{team} ń darí eré pẹ̀lú bọ́ọ̀lù.",
        },
        "fake_claim": " Ìgbá kẹ́ 137 tó dé ibi àfojúsùn ní àkókò yìí nìyí.",
    },
}

# Words that mean "goal" or "scored" in each language. A caption for a moment
# that is not a goal must not use them.
GOAL_WORDS = {
    "en": re.compile(r"\bgoals?\b|\bscor(?:es|ed)\b|\bequali[sz]er\b", re.I),
    "pcm": re.compile(r"\bgoals?\b|\bscor(?:e|es|ed)\b|\bequali[sz]er\b", re.I),
    "yo": re.compile(nfc(r"góòlù|gòlù|goolu|\bgól\b"), re.I),
}

# Phrases that say how a goal changed the match, and the situation they mean.
_SIT = {
    "pcm": {
        "level": "equaliser", "go front": "go_ahead", "lead by": "extends_lead",
        "pull clear": "extends_lead", "reduce di gap": "pulls_one_back",
        "come back inside": "pulls_one_back",
    },
    "yo": {
        "dọ́gba": "equaliser", "níwájú": "go_ahead", "ń ṣáájú": "extends_lead",
        "lọ jìnnà": "extends_lead", "dín ìyàtọ̀": "pulls_one_back",
        "padà wọ inú eré": "pulls_one_back",
    },
}
SITUATION_PHRASES = {lang: {nfc(k): v for k, v in d.items()} for lang, d in _SIT.items()}


# ----------------------------------------------------------------------------
# Rendering. `w` is a LocalWriter (it supplies names, codes and the scoreline).
# ----------------------------------------------------------------------------
def _f(x, spec=""):
    return format(x, spec)


def _goal(w, o, mode, P):
    f, g = o["facts"], P["goal"]
    team, sh, sa = w._team(o), f["score_home"], f["score_away"]
    diff = abs(sh - sa)
    pct = round(f["xg"] * 100) if f.get("xg") is not None else None
    sit = g["situation"][mode][f["situation"]].format(team=team, diff=diff)
    ctx = dict(who=f["scorer"], code=w._code(o), team=team, score=w._scoreline(sh, sa), situation=sit)
    if mode == "analyst":
        detail = ""
        if pct is not None:
            detail = g["detail"].format(xg=f["xg"], pct=pct, speed=_f(f["shot_speed_kmh"], ".0f"))
        return g["analyst"].format(detail=detail, **ctx)
    text = g["casual"].format(**ctx)
    if pct is not None and f["xg"] < 0.15:
        text += g["low_xg"].format(pct=pct)
    if f["goals_by_scorer"] == 2:
        text += g["brace"].format(who=f["scorer"])
    elif f["goals_by_scorer"] == 3:
        text += g["hat_trick"]
    return text


def _big_chance(w, o, mode, P):
    f = o["facts"]
    return P["big_chance"][mode].format(
        who=w._who(o), code=w._code(o), team=w._team(o), xg=f["xg"], pct=round(f["xg"] * 100),
        speed=_f(f["shot_speed_kmh"], ".0f"), dist=_f(f["distance_to_goal_m"], ".0f"),
        verb=P["verbs"][f["outcome"]])


def _fast_shot(w, o, mode, P):
    return P["fast_shot"][mode].format(who=w._who(o), code=w._code(o),
                                       speed=_f(o["facts"]["shot_speed_kmh"], ".0f"))


def _card(kind):
    def build(w, o, mode, P):
        return P[kind][mode].format(who=w._who(o), code=w._code(o), team=w._team(o),
                                    n=o["facts"].get("team_cards", ""))
    return build


def _difficult_pass(w, o, mode, P):
    f = o["facts"]
    return P["difficult_pass"][mode].format(
        who=w._who(o), code=w._code(o), recv=f["receiver"],
        dist=_f(f["pass_distance_m"], ".0f"), diff=_f(f["pass_difficulty"], "g"))


def _summary(w, o, mode, P):
    f, S = o["facts"], P["summary"]
    kind = o["kind"]
    label = P["label"][kind]
    sh, sa = f["score_home"], f["score_away"]
    lead = "home" if sh > sa else "away" if sa > sh else None
    score = w._scoreline(sh, sa)
    if mode == "analyst":
        p, s, x = f["possession_pct"], f["shots"], f["xg"]
        despite = ""
        if lead:
            opp = "away" if lead == "home" else "home"
            if x[lead] < x[opp]:
                despite = S["despite"].format(team=w.names[lead], won=S["won"][kind],
                                              a=x[lead], b=x[opp])
        return S["analyst"].format(
            label=label, score=score, ph=_f(p["home"], ".0f"), pa=_f(p["away"], ".0f"),
            sh=s["home"], sa=s["away"], xh=x["home"], xa=x["away"], despite=despite)
    tail = (S["lead"].format(team=w.names[lead], verb=S["lead_verb"][kind]) if lead
            else S["level"][kind])
    return S["casual"].format(label=label, score=score, lead=tail)


def _player_card(w, o, mode, P):
    f, C = o["facts"], P["player_card"]
    acc = C["acc"].format(a=f["pass_accuracy"]) if f["pass_accuracy"] is not None else ""
    goals = C["goals"].format(g=f["goals"]) if f["goals"] else ""
    if mode == "analyst":
        return C["analyst"].format(who=w._who(o), code=w._code(o), passes=f["passes"], acc=acc,
                                   shots=f["shots"], xg=f["xg"], goals=goals,
                                   tackles=f["tackles_won"], pressures=f["pressures"])
    incl = C["incl"].format(g=f["goals"]) if f["goals"] else ""
    return C["casual"].format(who=w._who(o), passes=f["passes"], shots=f["shots"], incl=incl,
                              tackles=f["tackles_won"])


def _state_shift(w, o, mode, P):
    f, S = o["facts"], P["state_shift"]
    chaos = f["state"] == "chaos"
    key = ("chaos" if chaos else "control") + "_analyst" if mode == "analyst" else \
          ("chaos_casual" if chaos else "calm_casual")
    return S[key].format(ci=f["chaos_index"], tpm=f["turnovers_per_min"],
                         acc=f["window_pass_accuracy"], mins=f["window_seconds"] // 60)


def _pressing(w, o, mode, P):
    f = o["facts"]
    return P["pressing"][mode].format(team=w._team(o), n=f["pressures_in_window"],
                                      mins=f["window_seconds"] // 60)


def _dominance(w, o, mode, P):
    f = o["facts"]
    return P["dominance"][mode].format(team=w._team(o), pct=_f(f["pass_share_window"], ".0f"),
                                       mins=f["window_seconds"] // 60)


BUILDERS = {
    "goal": _goal, "big_chance": _big_chance, "fast_shot": _fast_shot,
    "yellow_card": _card("yellow_card"), "red_card": _card("red_card"),
    "difficult_pass": _difficult_pass, "half_time": _summary, "full_time": _summary,
    "player_card": _player_card, "state_shift": _state_shift, "pressing": _pressing,
    "dominance": _dominance,
}


def render(w, o: dict, mode: str, lang: str) -> str:
    """Caption for overlay `o` in `lang` ("pcm" or "yo"), filled from the verified facts."""
    if lang not in PACKS:
        raise ValueError(f"language must be one of {tuple(PACKS)} here, got {lang!r}")
    build = BUILDERS.get(o["kind"])
    return nfc(build(w, o, mode, PACKS[lang])) if build else o["text"]


def fake_claim(lang: str) -> str:
    return PACKS[lang]["fake_claim"]
