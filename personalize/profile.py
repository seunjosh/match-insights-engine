"""Viewer profile: what one viewer wants from the match."""
from __future__ import annotations

from dataclasses import dataclass

MODES = ("analyst", "casual")
FOCUS = (None, "passing", "shooting", "pressing", "discipline")
DENSITY = ("light", "normal", "full")
LANGUAGES = ("en", "pcm", "yo")   # English, Nigerian Pidgin, Yoruba


@dataclass(frozen=True)
class ViewerProfile:
    name: str = "viewer"
    mode: str = "casual"                 # "analyst": numbers up front, "casual": plain language
    favorite_team: str | None = None     # club code, for example "NBR"
    favorite_player: str | None = None   # player id, for example "NBR09"; turns on player focus
    focus: str | None = None             # a single thing the viewer cares about
    density: str = "normal"              # how many overlays: "light", "normal" or "full"
    language: str = "en"

    def __post_init__(self) -> None:
        for field, value, allowed in (("mode", self.mode, MODES), ("focus", self.focus, FOCUS),
                                      ("density", self.density, DENSITY),
                                      ("language", self.language, LANGUAGES)):
            if value not in allowed:
                raise ValueError(f"{field} must be one of {allowed}, got {value!r}")
