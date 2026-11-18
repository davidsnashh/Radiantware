"""Statistics derived from match scoreboards: who a player queues with and how it goes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from models import MatchDetails, MatchPlayer
from scraper.utils import same_player


def find_player(match: MatchDetails, riot_id: str) -> MatchPlayer | None:
    return next((row for row in match.players if same_player(row.riot_id, riot_id)), None)


def team_won(match: MatchDetails, team: str | None) -> bool | None:
    """True or False for a decided match, None for a draw or an unknown result."""
    own = next((entry for entry in match.teams if entry.team == team), None)
    if own is None or own.won is None:
        return None
    if not own.won and not any(entry.won for entry in match.teams):
        return None
    return own.won


@dataclass
class _Mean:
    total: float = 0.0
    weight: float = 0.0

    def add(self, value: float | None, weight: float) -> None:
        if value is not None:
            self.total += value * weight
            self.weight += weight

    @property
    def value(self) -> float | None:
        return round(self.total / self.weight, 1) if self.weight else None


@dataclass
class _Tally:
    """Running totals for one player across a set of matches."""

    games: int = 0
    wins: int = 0
    losses: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    acs: _Mean = field(default_factory=_Mean)
    adr: _Mean = field(default_factory=_Mean)
    hs_pct: _Mean = field(default_factory=_Mean)
    kast: _Mean = field(default_factory=_Mean)

    def add(self, row: MatchPlayer, rounds: int | None, won: bool | None) -> None:
        self.games += 1
        self.wins += won is True
        self.losses += won is False
        self.kills += row.kills or 0
        self.deaths += row.deaths or 0
        self.assists += row.assists or 0
        # Per-round averages are weighted by match length so long games count for more.
        weight = rounds or 1
        self.acs.add(row.acs, weight)
        self.adr.add(row.adr, weight)
        self.hs_pct.add(row.hs_pct, weight)
        self.kast.add(row.kast, weight)

    @property
    def kd(self) -> float | None:
        return round(self.kills / max(self.deaths, 1), 2) if self.games else None

    @property
    def win_rate(self) -> float | None:
        return round(100 * self.wins / self.games, 1) if self.games else None

    def summary(self) -> dict[str, Any]:
        return {
            "games": self.games,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "kills": self.kills,
            "deaths": self.deaths,
            "assists": self.assists,
            "kd": self.kd,
            "acs": self.acs.value,
            "adr": self.adr.value,
            "hs_pct": self.hs_pct.value,
            "kast": self.kast.value,
        }

    def brief(self) -> dict[str, Any]:
        return {
            "games": self.games,
            "wins": self.wins,
            "win_rate": self.win_rate,
            "kd": self.kd,
            "acs": self.acs.value,
        }


@dataclass
class _Teammate:
    riot_id: str
    overall: _Tally = field(default_factory=_Tally)
    by_map: dict[str, _Tally] = field(default_factory=dict)
    agents: Counter[str] = field(default_factory=Counter)
    party_games: int = 0
    # The analysed player's own line in the matches shared with this teammate.
    player_with: _Tally = field(default_factory=_Tally)


def _same_map(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and a.strip().casefold() == b.strip().casefold()


def teammate_stats(
    riot_id: str,
    matches: Sequence[MatchDetails],
    map_name: str | None = None,
    top: int = 10,
) -> dict[str, Any]:
    """Aggregate the players who shared a team with riot_id across the given matches.

    Teammates are ranked by games played together over all matches. With
    map_name only teammates seen on that map are listed, each with an extra
    "on_map" block, while "rank" still reflects the overall ordering.
    """
    player = _Tally()
    player_on_map = _Tally()
    teammates: dict[str, _Teammate] = {}
    # (teammate keys, the player's row, rounds, result) per analysed match.
    appearances: list[tuple[set[str], MatchPlayer, int | None, bool | None]] = []
    map_label = map_name

    for match in matches:
        me = find_player(match, riot_id)
        if me is None or me.team is None:
            continue
        won = team_won(match, me.team)
        player.add(me, match.rounds, won)
        if _same_map(match.map, map_name):
            player_on_map.add(me, match.rounds, won)
            map_label = match.map

        present: set[str] = set()
        for row in match.players:
            if row.team != me.team or row is me or row.riot_id == "Unknown":
                continue
            key = row.riot_id.casefold()
            present.add(key)
            mate = teammates.setdefault(key, _Teammate(row.riot_id))
            mate.overall.add(row, match.rounds, won)
            mate.player_with.add(me, match.rounds, won)
            mate.by_map.setdefault(match.map or "Unknown", _Tally()).add(row, match.rounds, won)
            if row.agent:
                mate.agents[row.agent] += 1
            if me.party_id is not None and row.party_id == me.party_id:
                mate.party_games += 1
        appearances.append((present, me, match.rounds, won))

    ranked = sorted(
        teammates.items(),
        key=lambda item: (item[1].overall.games, item[1].party_games, item[1].overall.wins),
        reverse=True,
    )

    rows: list[dict[str, Any]] = []
    for rank, (key, mate) in enumerate(ranked, 1):
        on_map = next((t for name, t in mate.by_map.items() if _same_map(name, map_name)), None)
        if map_name and on_map is None:
            continue
        if len(rows) >= top:
            break
        without = _Tally()
        for present, me, rounds, won in appearances:
            if key not in present:
                without.add(me, rounds, won)
        row: dict[str, Any] = {
            "riot_id": mate.riot_id,
            "rank": rank,
            "games_together": mate.overall.games,
            "games_in_party": mate.party_games,
            **{k: v for k, v in mate.overall.summary().items() if k != "games"},
            "agents": dict(mate.agents.most_common()),
            "by_map": {name: tally.brief() for name, tally in sorted(mate.by_map.items())},
            "your_record_with": mate.player_with.brief(),
            "your_record_without": without.brief(),
        }
        if on_map is not None:
            row["on_map"] = on_map.summary()
        rows.append(row)

    result: dict[str, Any] = {
        "matches_analyzed": player.games,
        "your_stats": player.summary(),
        "teammates_seen": len(teammates),
        "teammates": rows,
    }
    if map_name:
        result["map_filter"] = map_label
        result["matches_on_map"] = player_on_map.games
        result["your_stats_on_map"] = player_on_map.summary()
    return result
