"""Editor agent: decides what actually goes on air, and when.

The detector and the writers can produce overlays that land on top of each
other (a card two seconds after a goal). A real producer would not air both.
The editor walks the feed in time order and applies a few plain rules:

  1. An overlay that failed the fact-check is never aired.
  2. Key moments (priority 4 or 5: goals, red cards, half and full time) air
     immediately and cut short whatever is on screen.
  3. Anything else waits until the screen is free, but never longer than
     MAX_DELAY seconds. If it would be stale by then it is dropped.
  4. An overlay is never aired earlier than the moment it describes, so a
     caption cannot use information from the future.

Every decision, with its reason, goes into the editor log so a producer can
see (and in a real product, override) what was done.
"""
from __future__ import annotations

MAX_DELAY = 15          # seconds a non-key overlay may wait for a free screen
KEY_PRIORITY = 4


def edit(results: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Return (aired overlays, editor log, counts). Input overlays are not modified."""
    order = sorted(results, key=lambda o: (o["at"]["elapsed_seconds"], -o["priority"], o["id"]))
    aired, log = [], []
    counts = {"aired": 0, "delayed": 0, "cut_short": 0, "dropped": 0, "rejected": 0}
    current = None          # the overlay currently on screen
    free_at = 0

    for o in order:
        at = o["at"]["elapsed_seconds"]
        entry = {"id": o["id"], "kind": o["kind"], "priority": o["priority"], "moment": at}
        if not o.get("verified"):
            entry.update(decision="rejected", reason="failed the fact-check")
            counts["rejected"] += 1
            log.append(entry)
            continue

        start = at
        reason = "screen was free"
        if free_at > at:
            if o["priority"] >= KEY_PRIORITY:
                reason = "key moment: aired at once"
                # captions that were queued for after this moment are no longer worth airing
                while aired and aired[-1]["air_at_seconds"] > at:
                    gone = aired.pop()
                    counts["aired"] -= 1
                    counts["delayed"] -= gone["editor"]["delay_seconds"] > 0
                    counts["dropped"] += 1
                    for e in log:
                        if e["id"] == gone["id"]:
                            e.update(decision="dropped",
                                     reason="a key moment took the screen first")
                            e.pop("air_at", None)
                if aired and aired[-1]["air_at_seconds"] + aired[-1]["display_seconds"] > at:
                    prev = aired[-1]
                    prev["display_seconds"] = max(1, at - prev["air_at_seconds"])
                    prev["editor"]["cut_short"] = True
                    counts["cut_short"] += 1
            else:
                start = free_at
                if start - at > MAX_DELAY:
                    entry.update(decision="dropped",
                                 reason=f"screen busy for {start - at}s, caption would be stale")
                    counts["dropped"] += 1
                    log.append(entry)
                    continue
                reason = f"waited {start - at}s for the screen"
                counts["delayed"] += 1

        item = dict(o)
        item["air_at_seconds"] = start
        item["editor"] = {"decision": "aired", "reason": reason, "delay_seconds": start - at}
        aired.append(item)
        current, free_at = item, start + item["display_seconds"]
        counts["aired"] += 1
        entry.update(decision="aired", reason=reason, air_at=start)
        log.append(entry)
    return aired, log, counts
