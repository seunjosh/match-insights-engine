# Match Insights Engine (working title)

A live "second screen" for football: synthetic match events stream in, plain code computes the stats, AI agents explain why moments matter, a fact-checker verifies every claim against the data, and the result is shown as broadcast-style overlays, personalised by mode, club, player and language (including Nigerian Pidgin, Yoruba, Hausa and Igbo).

> Status: day 1. Working: synthetic match generator, replayer, stats engine (with control-vs-chaos score), moment detector with overlay JSON, tests. Planned: AI agents (explainer, fact-checker, editor, localiser), personalisation, translation, UI.

## Replay a match live

```bash
python -m engine.replayer --events data/match_001_events.jsonl --every 10   # instant
python -m engine.replayer --events data/match_001_events.jsonl --speed 60   # 60x real time
python -m unittest discover -s tests -t .                                  # run tests
```

The stats engine keeps whole-match totals and a rolling 5-minute window. The **chaos index** (0 to 1) blends how often the ball changes hands with how many passes go astray in that window: below 0.30 is *control*, above 0.55 is *chaos*, in between is *balanced*.

## Detect moments (overlays)

```bash
python -m engine.moments --events data/match_001_events.jsonl
```

This prints a timeline of everything worth showing on screen and writes `data/match_001_overlays.json`. A match produces about 30 overlays, roughly one every three minutes: goals, big chances, cards, control/chaos shifts, pressing spells, spells of dominance, tough passes, the fastest shot, half time and full time.

### Overlay format

Each overlay is timed and machine-readable, so a broadcast renderer can place it on a live feed:

```json
{
  "id": "ov012",
  "kind": "state_shift",
  "priority": 3,
  "at": {"elapsed_seconds": 1721, "minute": 28, "second": 41, "half": 1},
  "display_seconds": 7,
  "headline": "Chaos",
  "text": "The match has turned frantic. The ball changed hands 2.4 times a minute ...",
  "team": null,
  "player": null,
  "facts": {"state": "chaos", "chaos_index": 0.58, "turnovers_per_min": 2.4},
  "source_event_ids": [1043, 1051, 1066],
  "last_event_id": 1068,
  "verified": null
}
```

- `facts` holds the numbers behind the text. The AI agents may reword the text but must not change these.
- `source_event_ids` lists the raw events the overlay is based on. A source id never comes from after `last_event_id`, so an overlay cannot use information from the future.
- `verified` stays `null` until the fact-checker agent has checked the claims against the data.

## Data is synthetic

All clubs and players are fictional. No real match data is used.

## Generate a match

```bash
python synth_match.py --seed 7 --out data/match_001
```

This writes:

- `data/match_001_events.jsonl`: one JSON event per line, in time order
- `data/match_001_meta.json`: teams, lineups and the final score

Pitch coordinates: `x` runs 0-100 from the home goal to the away goal, `y` runs 0-100 across the width.

## Event types

| Type | Meaning |
|---|---|
| `pass` | A pass. Has `outcome`, `pass_distance_m`, `pass_difficulty` (1-10) and `ball_speed_ms` |
| `shot` | A shot at goal. Has `outcome` (goal, saved, blocked, off_target), `xg` and `shot_speed_kmh` |
| `goal`, `save` | Result events that follow a shot |
| `tackle` | A challenge for the ball, `won` or `lost` |
| `pressure` | A defender closing down the ball carrier, with `pressure_level` |
| `possession_change` | The ball changes team, with a `cause` |
| `foul`, `yellow_card`, `red_card`, `free_kick` | Rule events |
| `corner`, `goal_kick`, `kickoff` | Restarts |
| `half_end`, `full_time` | Match markers |

## Football terms used

- **xG (expected goals):** the chance a shot becomes a goal, from 0 to 1. A shot with xG 0.30 scores about 3 times in 10.
- **Pressing / pressure:** defenders closing the ball carrier down quickly to win the ball back.
- **Possession:** which team currently has the ball.
- **Control vs chaos:** our label for calm spells (few turnovers, accurate passing) versus frantic ones (many turnovers, loose passing).

## Planned pipeline

1. Replayer streams events in real time (or faster for demos)
2. Stats engine: possession, pass accuracy, turnovers, tempo
3. Explainer agent: turns shifts in the numbers into reasons
4. Fact-checker agent: rejects any claim the data does not support
5. Personaliser and translator: mode, favourite club or player, language
6. Overlay JSON feeding a broadcast-style web page
