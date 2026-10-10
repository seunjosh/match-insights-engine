"""Continuous match clock.

The generator labels second-half events from minute 45 even when the first
half ran into stoppage time, so raw `match_second` values can go backwards at
half-time. MatchClock converts them to one steadily increasing "elapsed"
number of seconds, which the rolling windows and the replayer rely on.
"""
from __future__ import annotations

HALF_SECONDS = 45 * 60


class MatchClock:
    def __init__(self) -> None:
        self._max_first_half = 0
        self._first_half_len: int | None = None

    def elapsed(self, event: dict) -> int:
        """Seconds of match time elapsed when `event` happened."""
        ms = int(event["match_second"])
        if event["half"] == 1:
            self._max_first_half = max(self._max_first_half, ms)
            return ms
        if self._first_half_len is None:
            self._first_half_len = max(self._max_first_half, HALF_SECONDS)
        return self._first_half_len + max(0, ms - HALF_SECONDS)
