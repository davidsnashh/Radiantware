"""Normalised shapes for everything scraped from tracker.gg.

Percentages are on a 0-100 scale. ACS is average combat score (score per
round) and ADR is average damage per round.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Keys moved to the front of dump(), so rows read label first.
    _lead: ClassVar[tuple[str, ...]] = ()

    def dump(self) -> dict[str, Any]:
        """JSON-ready dict without the fields tracker.gg did not provide."""
        data = self.model_dump(mode="json", exclude_none=True)
        lead = {key: data.pop(key) for key in self._lead if key in data}
        return {**lead, **data}


class Rank(Model):
    tier: str | None = None
    tier_id: int | None = None
    # Tracker.gg only knows the rank rating of Immortal and Radiant players.
    rr: int | None = None
    leaderboard_rank: int | None = None
    act: str | None = None


class StatLine(Model):
    matches: int | None = None
    wins: int | None = None
    losses: int | None = None
    ties: int | None = None
    win_rate: float | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    kd: float | None = None
    kda: float | None = None
    acs: float | None = None
    adr: float | None = None
    damage_delta_per_round: float | None = None
    hs_pct: float | None = None
    kast: float | None = None
    first_bloods: int | None = None
    first_deaths: int | None = None
    aces: int | None = None
    clutches: int | None = None
    mvps: int | None = None
    rounds_played: int | None = None
    round_win_rate: float | None = None
    hours_played: float | None = None


class SeasonStats(StatLine):
    rank: Rank | None = None
    peak_rank: Rank | None = None
    # How the player compares with everyone tracked, keyed like the stat fields.
    percentiles: dict[str, float] | None = None


class TopEntry(Model):
    name: str
    matches: int | None = None
    win_rate: float | None = None


class AgentStats(StatLine):
    _lead = ("agent", "role")

    agent: str
    role: str | None = None
    top_maps: list[TopEntry] | None = None


class MapStats(StatLine):
    _lead = ("map",)

    map: str
    attack_round_win_rate: float | None = None
    defense_round_win_rate: float | None = None
    attack_kd: float | None = None
    defense_kd: float | None = None
    top_agents: list[TopEntry] | None = None


class StatsBundle(Model):
    """Everything one segments request returns for a playlist and act."""

    season_stats: SeasonStats | None = None
    agents: list[AgentStats] = []
    maps: list[MapStats] = []


class Season(Model):
    id: str
    name: str | None = None
    short_name: str | None = None


class PlayerProfile(Model):
    riot_id: str
    account_level: int | None = None
    region: str | None = None
    privacy: str | None = None
    default_playlist: str = "competitive"
    default_season: str | None = None
    seasons: list[Season] = []
    playlists: list[str] = []
    peak_rank: Rank | None = None
    # Stats for the default playlist and act; tracker.gg leaves maps out here.
    stats: StatsBundle = StatsBundle()


class MatchEntry(Model):
    """One row of a player's match history, with only that player's numbers."""

    match_id: str
    played_at: str | None = None
    map: str | None = None
    mode: str | None = None
    season: str | None = None
    result: str | None = None
    rounds_won: int | None = None
    rounds_lost: int | None = None
    agent: str | None = None
    rank: str | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    kd: float | None = None
    acs: float | None = None
    adr: float | None = None
    hs_pct: float | None = None
    kast: float | None = None
    damage: int | None = None
    combat_score: int | None = None
    placement: int | None = None


class MatchPage(Model):
    matches: list[MatchEntry] = []
    next_page: int | None = None


class MatchPlayer(Model):
    riot_id: str
    team: str | None = None
    party_id: str | None = None
    agent: str | None = None
    rank: str | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    kd: float | None = None
    acs: float | None = None
    adr: float | None = None
    hs_pct: float | None = None
    kast: float | None = None
    damage: int | None = None
    combat_score: int | None = None
    first_kills: int | None = None
    first_deaths: int | None = None
    plants: int | None = None
    defuses: int | None = None
    placement: int | None = None


class MatchTeam(Model):
    team: str
    won: bool | None = None
    rounds_won: int | None = None
    rounds_lost: int | None = None


class MatchDetails(Model):
    match_id: str
    played_at: str | None = None
    map: str | None = None
    mode: str | None = None
    playlist: str | None = None
    ranked: bool | None = None
    duration_minutes: float | None = None
    rounds: int | None = None
    teams: list[MatchTeam] = []
    players: list[MatchPlayer] = []


class SearchResult(Model):
    riot_id: str
    status: str | None = None
