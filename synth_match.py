"""Synthetic football match generator.

Simulates one match and writes a stream of events that look like real
football tracking/event data. All teams and players are fictional.

Pitch coordinates: x runs 0-100 from the home team's own goal (0) to the
away team's goal (100); y runs 0-100 across the pitch width.
Home always attacks towards x=100 in this simple model.

Usage:
    python synth_match.py --seed 7 --out data/match_001
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random

FIRST_NAMES = [
    "Adrian", "Bruno", "Callum", "Dario", "Emeka", "Felix", "Gabriel", "Hakim",
    "Ivan", "Jonas", "Kofi", "Luca", "Mateo", "Nnamdi", "Oscar", "Pedro",
    "Quentin", "Rafael", "Sami", "Tobi", "Ugo", "Viktor", "Wale", "Xavi",
    "Yusuf", "Zane", "Ayo", "Declan", "Ethan", "Femi", "Giorgio", "Harvey",
]
LAST_NAMES = [
    "Adebayo", "Brandt", "Carvalho", "Dunmore", "Eze", "Fontaine", "Garrido",
    "Holloway", "Ibrahim", "Jovanovic", "Kessler", "Lindqvist", "Mbeki",
    "Novak", "Okafor", "Pereira", "Quigley", "Rossi", "Sterling-Vale",
    "Takahashi", "Umar", "Vasquez", "Whitlock", "Yilmaz", "Zielinski",
    "Abara", "Bellamy", "Cordero", "Delaney", "Ferreira",
]
# 4-3-3 lineup: position, typical x (own half = low), typical y
FORMATION = [
    ("GK", 5, 50),
    ("LB", 25, 15), ("CB", 22, 38), ("CB", 22, 62), ("RB", 25, 85),
    ("CM", 45, 30), ("CM", 42, 50), ("CM", 45, 70),
    ("LW", 70, 15), ("ST", 78, 50), ("RW", 70, 85),
]
CLUBS = [("Northbridge Rovers", "NBR"), ("Eastvale United", "EVU")]


def build_team(rng: random.Random, name: str, code: str, used: set) -> dict:
    players = []
    for i, (pos, x, y) in enumerate(FORMATION):
        while True:
            full = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if full not in used:
                used.add(full)
                break
        players.append({
            "id": f"{code}{i + 1:02d}",
            "name": full,
            "shirt": i + 1 if i else 1,
            "position": pos,
            "base_x": x,
            "base_y": y,
            "skill": round(rng.uniform(0.9, 1.1), 3),
        })
    return {"name": name, "code": code, "players": players}


def clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


class Match:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        used: set = set()
        self.teams = {
            "home": build_team(self.rng, CLUBS[0][0], CLUBS[0][1], used),
            "away": build_team(self.rng, CLUBS[1][0], CLUBS[1][1], used),
        }
        # Slight random edge so matches differ in who dominates.
        self.strength = {"home": self.rng.uniform(0.95, 1.1), "away": self.rng.uniform(0.9, 1.05)}
        self.events: list[dict] = []
        self.score = {"home": 0, "away": 0}
        self.cards = {"home": 0, "away": 0}
        self.clock = 0.0          # seconds since kickoff of current half
        self.half = 1
        self.possession = "home"
        self.bx = 50.0            # ball x in absolute pitch coordinates
        self.by = 50.0
        self.holder = self.pick_player("home", near=(50, 50))
        # "chaos" level changes in phases to create control vs chaos stretches.
        self.chaos = 0.3
        self.next_phase = 0.0
        self.seq = 0

    # ---- helpers ---------------------------------------------------------
    def other(self, side: str) -> str:
        return "away" if side == "home" else "home"

    def pick_player(self, side: str, near: tuple[float, float] | None = None,
                    exclude: dict | None = None) -> dict:
        players = self.teams[side]["players"]
        cands = [p for p in players if p is not exclude and p["position"] != "GK"]
        if near is None:
            return self.rng.choice(cands)
        # Home attack frame == absolute; away base_x is mirrored.
        def pos_x(p):
            return p["base_x"] if side == "home" else 100 - p["base_x"]
        weights = []
        for p in cands:
            d = math.hypot(pos_x(p) - near[0], p["base_y"] - near[1])
            weights.append(1.0 / (8.0 + d))
        return self.rng.choices(cands, weights=weights, k=1)[0]

    def attack_x(self, side: str) -> float:
        """Ball progress towards the goal the team is attacking (0-100)."""
        return self.bx if side == "home" else 100 - self.bx

    def minute_label(self) -> tuple[int, int]:
        base = 0 if self.half == 1 else 45
        total = int(self.clock)
        return base + total // 60, total % 60

    def emit(self, etype: str, side: str, player: dict | None, **extra) -> dict:
        self.seq += 1
        minute, second = self.minute_label()
        ev = {
            "event_id": self.seq,
            "half": self.half,
            "minute": minute,
            "second": second,
            "match_second": minute * 60 + second,
            "type": etype,
            "team": side,
            "team_code": self.teams[side]["code"],
            "player_id": player["id"] if player else None,
            "player": player["name"] if player else None,
            "x": round(self.bx, 1),
            "y": round(self.by, 1),
        }
        ev.update(extra)
        self.events.append(ev)
        return ev

    # ---- game logic ------------------------------------------------------
    def update_phase(self):
        if self.clock >= self.next_phase:
            # New phase every 4-9 minutes: calm (control) or frantic (chaos).
            self.chaos = self.rng.choice([0.12, 0.2, 0.3, 0.45, 0.6, 0.75])
            self.next_phase = self.clock + self.rng.uniform(240, 540)

    def pressure_on_ball(self) -> float:
        return clamp(self.rng.gauss(0.35 + self.chaos * 0.5, 0.15), 0.0, 1.0)

    def step(self):
        self.update_phase()
        side = self.possession
        opp = self.other(side)
        ax = self.attack_x(side)
        pressure = self.pressure_on_ball()
        holder = self.holder

        # Pressure event: opponent closes the player down.
        if pressure > 0.55 and self.rng.random() < 0.5:
            presser = self.pick_player(opp, near=(self.bx, self.by))
            self.emit("pressure", opp, presser, target_player_id=holder["id"],
                      pressure_level=round(pressure, 2))

        # Chance to shoot grows near goal.
        if ax > 72 and self.rng.random() < (ax - 65) / 300:
            self.shoot(side, holder, pressure)
            return

        # Foul chance rises with chaos.
        if self.rng.random() < 0.012 + 0.02 * self.chaos:
            self.foul(opp, side)
            return

        # Otherwise: pass attempt (or loss of the ball via dribble/tackle).
        if self.rng.random() < 0.10 + 0.12 * pressure:
            self.dribble_or_tackle(side, opp, holder)
            return
        self.make_pass(side, opp, holder, pressure)

    def make_pass(self, side, opp, holder, pressure):
        forward = 1 if side == "home" else -1
        # Mostly forward-ish passes, some back/sideways.
        advance = self.rng.choices([-12, 0, 8, 16, 26], weights=[2, 3, 4, 3, 1])[0]
        tx = clamp(self.bx + forward * advance + self.rng.gauss(0, 4))
        ty = clamp(self.by + self.rng.gauss(0, 14))
        distance_m = math.hypot((tx - self.bx) * 1.05, (ty - self.by) * 0.68)
        # Pass difficulty 1-10: longer, forward, under pressure = harder.
        difficulty = clamp(1 + distance_m / 7 + max(advance, 0) / 12 + pressure * 4, 1, 10)
        base_acc = 1.05 * holder["skill"] * self.strength[side]
        p_ok = clamp(base_acc - difficulty * 0.025 - pressure * 0.08, 0.25, 0.97)
        ok = self.rng.random() < p_ok
        receiver = self.pick_player(side, near=(tx, ty), exclude=holder)
        speed = round(clamp(self.rng.gauss(14 + distance_m / 4, 3), 6, 32), 1)  # m/s
        self.emit(
            "pass", side, holder,
            outcome="complete" if ok else "incomplete",
            end_x=round(tx, 1), end_y=round(ty, 1),
            receiver_id=receiver["id"] if ok else None,
            receiver=receiver["name"] if ok else None,
            pass_distance_m=round(distance_m, 1),
            pass_difficulty=round(difficulty, 1),
            ball_speed_ms=speed,
        )
        self.advance_clock(self.rng.uniform(2.5, 6.5))
        if ok:
            self.bx, self.by, self.holder = tx, ty, receiver
        else:
            self.bx, self.by = tx, ty
            self.change_possession(opp, "interception", cause_player=holder)

    def dribble_or_tackle(self, side, opp, holder):
        tackler = self.pick_player(opp, near=(self.bx, self.by))
        won = self.rng.random() < 0.38 + 0.1 * self.chaos
        if won:
            self.emit("tackle", opp, tackler, outcome="won",
                      against_player_id=holder["id"])
            self.advance_clock(self.rng.uniform(1.5, 4))
            self.change_possession(opp, "tackle", cause_player=holder, new_holder=tackler)
        else:
            self.emit("tackle", opp, tackler, outcome="lost",
                      against_player_id=holder["id"])
            self.advance_clock(self.rng.uniform(1.5, 4))
            forward = 1 if side == "home" else -1
            self.bx = clamp(self.bx + forward * self.rng.uniform(3, 9))

    def foul(self, fouler_side, victim_side):
        fouler = self.pick_player(fouler_side, near=(self.bx, self.by))
        victim = self.holder
        self.emit("foul", fouler_side, fouler, against_player_id=victim["id"])
        r = self.rng.random()
        if r < 0.12:
            self.cards[fouler_side] += 1
            self.emit("yellow_card", fouler_side, fouler)
        elif r < 0.125:
            self.emit("red_card", fouler_side, fouler)
        self.advance_clock(self.rng.uniform(15, 35))
        self.possession = victim_side
        self.holder = victim
        ax = self.attack_x(victim_side)
        if ax > 82:
            self.take_penalty_or_free_kick(victim_side, victim)
        else:
            self.emit("free_kick", victim_side, victim)
            self.advance_clock(self.rng.uniform(3, 8))

    def take_penalty_or_free_kick(self, side, player):
        # Fouls in the box are rare; model as a free kick shot most of the time.
        self.emit("free_kick", side, player)
        self.advance_clock(self.rng.uniform(5, 10))
        self.shoot(side, player, pressure=0.2, set_piece=True)

    def shoot(self, side, shooter, pressure, set_piece=False):
        opp = self.other(side)
        ax = self.attack_x(side)
        dist_to_goal = math.hypot((100 - ax) * 1.05, (self.by - 50) * 0.68)
        xg = clamp(0.45 * math.exp(-dist_to_goal / 14) * (1 - pressure * 0.4), 0.01, 0.6)
        speed_kmh = round(clamp(self.rng.gauss(95 - dist_to_goal * 0.6, 10), 50, 135), 1)
        r = self.rng.random()
        on_target = self.rng.random() < 0.38 + 0.2 * shooter["skill"] - 0.2
        if r < xg * shooter["skill"] * self.strength[side]:
            outcome = "goal"
        elif on_target:
            outcome = "saved"
        elif self.rng.random() < 0.3:
            outcome = "blocked"
        else:
            outcome = "off_target"
        self.emit("shot", side, shooter, outcome=outcome, xg=round(xg, 3),
                  shot_speed_kmh=speed_kmh, distance_to_goal_m=round(dist_to_goal, 1),
                  set_piece=set_piece)
        self.advance_clock(self.rng.uniform(2, 5))
        if outcome == "goal":
            self.score[side] += 1
            self.emit("goal", side, shooter,
                      score_home=self.score["home"], score_away=self.score["away"])
            self.advance_clock(self.rng.uniform(30, 50))
            self.restart_after_goal(opp)
        elif outcome == "saved":
            keeper = self.teams[opp]["players"][0]
            self.emit("save", opp, keeper)
            if self.rng.random() < 0.3:
                self.corner(side)
            else:
                self.goal_kick(opp)
        elif outcome == "blocked":
            self.corner(side) if self.rng.random() < 0.4 else \
                self.change_possession(opp, "block", cause_player=shooter)
        else:
            self.goal_kick(opp)

    def corner(self, side):
        taker = self.pick_player(side, near=(90, 90))
        self.bx = 100.0 if side == "home" else 0.0
        self.by = self.rng.choice([2.0, 98.0])
        self.emit("corner", side, taker)
        self.advance_clock(self.rng.uniform(20, 40))
        self.bx = 90.0 if side == "home" else 10.0
        self.by = 50.0
        self.possession = side
        self.holder = self.pick_player(side, near=(self.bx, self.by))

    def goal_kick(self, side):
        keeper = self.teams[side]["players"][0]
        self.bx = 6.0 if side == "home" else 94.0
        self.by = 50.0
        self.possession = side
        self.emit("goal_kick", side, keeper)
        self.advance_clock(self.rng.uniform(15, 30))
        self.holder = self.pick_player(side, near=(25 if side == "home" else 75, 50))
        self.bx = 25.0 if side == "home" else 75.0

    def restart_after_goal(self, conceding_side):
        self.bx, self.by = 50.0, 50.0
        self.possession = conceding_side
        self.holder = self.pick_player(conceding_side, near=(50, 50))
        self.emit("kickoff", conceding_side, self.holder)

    def change_possession(self, new_side, cause, cause_player=None, new_holder=None):
        old = self.possession
        self.possession = new_side
        self.holder = new_holder or self.pick_player(new_side, near=(self.bx, self.by))
        self.emit("possession_change", new_side, self.holder, cause=cause,
                  from_team=old, from_player_id=cause_player["id"] if cause_player else None)

    def advance_clock(self, secs: float):
        self.clock += secs

    # ---- run -------------------------------------------------------------
    def run(self) -> dict:
        self.emit("kickoff", "home", self.holder)
        for half in (1, 2):
            self.half = half
            self.clock = 0.0
            self.next_phase = 0.0
            if half == 2:
                self.bx, self.by = 50.0, 50.0
                self.possession = "away"
                self.holder = self.pick_player("away", near=(50, 50))
                self.emit("kickoff", "away", self.holder)
            limit = 45 * 60 + self.rng.randint(60, 240)  # stoppage time
            while self.clock < limit:
                self.step()
            self.emit("half_end" if half == 1 else "full_time", "home", None,
                      score_home=self.score["home"], score_away=self.score["away"])
        return self.summary()

    def summary(self) -> dict:
        return {
            "home": self.teams["home"]["name"],
            "away": self.teams["away"]["name"],
            "final_score": f'{self.score["home"]}-{self.score["away"]}',
            "event_count": len(self.events),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/match_001")
    args = ap.parse_args()

    m = Match(args.seed)
    summary = m.run()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out + "_events.jsonl", "w", encoding="utf-8") as f:
        for ev in m.events:
            f.write(json.dumps(ev) + "\n")
    meta = {
        "match_id": os.path.basename(args.out),
        "seed": args.seed,
        "synthetic": True,
        "teams": m.teams,
        "summary": summary,
        "pitch": {"x": "0-100 home goal to away goal", "y": "0-100 across width"},
    }
    with open(args.out + "_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
