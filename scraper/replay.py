"""Local replay files: what can be done with them today, and the plan for the rest.

A replay only exists on the computer of someone who played in the match and
downloaded it in the game. There is nowhere to fetch another player's replays
from, so everything here works on files that are already on this machine.

Reading what is inside a replay is not built yet, because the format is not
documented. This module finds and names the files, and lays out the pieces a
reader will plug into:

    ReplayParser      turns a file into a Replay: the match as a list of events
    ReplayAnalyzer    answers one kind of question from a Replay

PLANNED lists the analyzers that are meant to follow.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .exceptions import TrackerError

# Guides name both endings for the game's replay files.
REPLAY_SUFFIXES = (".vrf", ".dem")
LOCAL_ONLY = (
    "Replays are local only. A replay exists on the computer of a player who was in the "
    "match and downloaded it in the game, and nowhere else. Other players' replays cannot "
    "be fetched."
)
UNDOCUMENTED = "The replay format is not documented, so nothing inside a replay can be read yet."


class ReplayError(TrackerError):
    """A replay file cannot be found or used."""


class ReplayNotSupportedError(ReplayError):
    """Reading replays is not built yet."""


@dataclass(frozen=True, slots=True)
class ReplayFile:
    path: Path
    size_bytes: int
    modified_at: float

    def describe(self) -> dict[str, Any]:
        changed = datetime.fromtimestamp(self.modified_at, UTC)
        return {
            "file": self.path.name,
            "path": str(self.path),
            "size_mb": round(self.size_bytes / 1_000_000, 1),
            "modified_at": changed.isoformat(timespec="seconds"),
        }


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    """One thing that happened in a match: a shot, an ability, a death, a plant."""

    round: int
    # Seconds into the round.
    time: float
    kind: str
    player: str | None = None
    target: str | None = None
    position: tuple[float, float, float] | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Replay:
    """A replay once it has been read: who played, and everything that happened in order."""

    file: ReplayFile
    map: str | None
    players: tuple[str, ...]
    events: tuple[ReplayEvent, ...]


class ReplayParser(Protocol):
    def parse(self, file: ReplayFile) -> Replay:
        """Read a replay file. Raises ReplayNotSupportedError for one it cannot read."""
        ...


class ReplayAnalyzer(Protocol):
    name: str

    def analyze(self, replay: Replay) -> dict[str, Any]:
        """Answer this analyzer's questions about one replay."""
        ...


@dataclass(frozen=True, slots=True)
class Planned:
    """An analyzer that is meant to exist, and what it has to be given."""

    name: str
    needs: str
    answers: tuple[str, ...]

    def describe(self) -> dict[str, Any]:
        return {"analysis": self.name, "will_answer": list(self.answers), "needs": self.needs}


ROUND_STATE = Planned(
    "round_state",
    "where every player was, with health and equipment, at each moment of a round",
    (
        "Who was alive and where at any moment of a round",
        "How a round was won or lost: the trades, the retake, the time left",
    ),
)
LINE_OF_SIGHT = Planned(
    "line_of_sight",
    "player positions and view directions, and the shape of the map",
    (
        "Who could see whom, and when",
        "Which angles a player held, and which ones they were killed from",
    ),
)
UTILITY = Planned(
    "utility",
    "every ability use, with who it hit and for how long",
    (
        "How many flashes blinded an enemy, and how many blinded a teammate",
        "How many stuns, slows and reveals were followed by a kill",
        "How long smokes and walls covered what they were meant to cover",
    ),
)
PLANNED = (ROUND_STATE, LINE_OF_SIGHT, UTILITY)


class NoParser:
    """Stands in until a reader for the format exists."""

    def parse(self, file: ReplayFile) -> Replay:
        raise ReplayNotSupportedError(
            f"{file.path.name} cannot be read. {UNDOCUMENTED} get_match_rounds has the "
            "round-by-round data tracker.gg keeps for a match."
        )


parser: ReplayParser = NoParser()


def default_folder() -> Path | None:
    """Where the game keeps replays, on the one system it runs on."""
    local = os.environ.get("LOCALAPPDATA")
    if sys.platform != "win32" or not local:
        return None
    return Path(local) / "VALORANT" / "Saved" / "Demos"


def _replay_file(path: Path) -> ReplayFile | None:
    try:
        info = path.stat()
        usable = path.is_file()
    except (OSError, ValueError):
        # ValueError is what a path with a null character in it gives.
        return None
    return ReplayFile(path, info.st_size, info.st_mtime) if usable else None


def find_replays(folder: Path | None) -> list[ReplayFile]:
    """The replay files in a folder, newest first."""
    if folder is None or not folder.is_dir():
        return []
    try:
        inside = list(folder.iterdir())
    except OSError as exc:
        raise ReplayError(f"The replay folder {folder} cannot be read: {exc}") from exc
    candidates = (path for path in inside if path.suffix.lower() in REPLAY_SUFFIXES)
    found = [replay for path in candidates if (replay := _replay_file(path))]
    return sorted(found, key=lambda replay: replay.modified_at, reverse=True)


def open_replay(path: str) -> ReplayFile:
    """Check that a path names a replay file on this computer."""
    shown = path if len(path) <= 200 else f"{path[:200]}..."
    endings = " or ".join(REPLAY_SUFFIXES)
    try:
        # resolve() so that the answer names the file in full, whatever was typed.
        chosen = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ReplayError(f"'{shown}' is not a path that can be used: {exc}") from exc
    if chosen.suffix.lower() not in REPLAY_SUFFIXES:
        raise ReplayError(
            f"'{shown}' is not a replay file. Replay files end in {endings}. {LOCAL_ONLY}"
        )
    found = _replay_file(chosen)
    if found is None:
        raise ReplayError(
            f"There is no replay file at '{shown}'. {LOCAL_ONLY} list_local_replays shows the "
            "ones on this computer."
        )
    return found


def not_built(
    feature: str, replay: ReplayFile, planned: Sequence[Planned], meanwhile: str
) -> dict[str, Any]:
    """What a replay tool answers for as long as replays cannot be read."""
    return {
        "status": "not_implemented",
        "message": f"{feature} is not built yet. {UNDOCUMENTED}",
        "replay": replay.describe(),
        "planned": [plan.describe() for plan in planned],
        "meanwhile": meanwhile,
        "limitations": [LOCAL_ONLY, UNDOCUMENTED],
    }
