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


class Shots(Model):
    head: int | None = None
    body: int | None = None
    leg: int | None = None


class SplitStats(Model):
    """One slice of a player's rounds: a side (attack, defense) or a kind of buy."""

    rounds: int | None = None
    rounds_won: int | None = None
    round_win_rate: float | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    kd: float | None = None
    acs: float | None = None
    adr: float | None = None
    damage_delta_per_round: float | None = None
    hs_pct: float | None = None
    kast: float | None = None
    first_kills: int | None = None
    first_deaths: int | None = None
    entry_success_rate: float | None = None
    rounds_survived: int | None = None
    deaths_traded: int | None = None
    trade_kills: int | None = None


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
    first_kills: int | None = None
    first_deaths: int | None = None
    aces: int | None = None
    clutches: int | None = None
    mvps: int | None = None
    rounds: int | None = None
    round_win_rate: float | None = None
    hours_played: float | None = None

    # The rest of tracker.gg's stat sheet. Tools return it when asked for detail.
    disconnects: int | None = None
    avg_match_minutes: float | None = None
    rounds_won: int | None = None
    rounds_lost: int | None = None
    performance_score: float | None = None
    damage: int | None = None
    damage_received: int | None = None
    # First kills as a share of the rounds the player opened, either way.
    entry_success_rate: float | None = None
    last_deaths: int | None = None
    rounds_survived: int | None = None
    # Deaths a teammate avenged, and kills that avenged a teammate.
    deaths_traded: int | None = None
    trade_kills: int | None = None
    clutches_lost: int | None = None
    clutches_by_size: dict[str, int] | None = None
    clutches_lost_by_size: dict[str, int] | None = None
    # Rounds with three or more kills, then rounds with exactly two, three and four.
    multi_kills: int | None = None
    double_kills: int | None = None
    triple_kills: int | None = None
    quadra_kills: int | None = None
    most_kills_in_match: int | None = None
    plants: int | None = None
    defuses: int | None = None
    econ_rating: float | None = None
    # Keyed by ability slot: c, q, e and x.
    ability_casts: dict[str, int] | None = None
    shots_dealt: Shots | None = None
    shots_received: Shots | None = None
    flawless_rounds: int | None = None
    thrifty_rounds: int | None = None
    team_aces: int | None = None
    suicides: int | None = None
    attack: SplitStats | None = None
    defense: SplitStats | None = None


class SeasonStats(StatLine):
    rank: Rank | None = None
    peak_rank: Rank | None = None
    # Tracker.gg's own rating of the act, out of 1000.
    tracker_score: int | None = None
    # How the player compares with everyone tracked, keyed like the stat fields.
    percentiles: dict[str, float] | None = None


class TopEntry(Model):
    """An agent on one map, or a map for one agent."""

    name: str
    matches: int | None = None
    win_rate: float | None = None
    wins: int | None = None
    losses: int | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    kd: float | None = None
    acs: float | None = None
    adr: float | None = None
    hs_pct: float | None = None
    kast: float | None = None


class Ability(Model):
    name: str | None = None
    casts: int | None = None


class AgentStats(StatLine):
    _lead = ("agent", "role")

    agent: str
    role: str | None = None
    # Share of the player's matches in this scope that were played on the agent.
    pick_rate: float | None = None
    # Keyed by ability slot (c, q, e, x); replaces ability_casts on agent rows.
    abilities: dict[str, Ability] | None = None
    top_maps: list[TopEntry] | None = None


class MapStats(StatLine):
    _lead = ("map",)

    map: str
    top_agents: list[TopEntry] | None = None


class RoleStats(StatLine):
    _lead = ("role",)

    role: str


class WeaponStats(Model):
    _lead = ("weapon", "category")

    weapon: str
    category: str | None = None
    # Matches and rounds in which the weapon was used.
    matches: int | None = None
    rounds: int | None = None
    kills: int | None = None
    # Times the player was killed by this weapon.
    deaths: int | None = None
    kd: float | None = None
    alt_fire_kills: int | None = None
    hs_pct: float | None = None
    damage: int | None = None
    damage_received: int | None = None
    shots_dealt: Shots | None = None
    avg_kill_distance_m: float | None = None
    longest_kill_m: float | None = None


class StatsBundle(Model):
    """Everything one segments request returns for a playlist and act."""

    season_stats: SeasonStats | None = None
    agents: list[AgentStats] = []
    maps: list[MapStats] = []
    roles: list[RoleStats] = []
    weapons: list[WeaponStats] = []


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
    # Position among all ten players by tracker.gg's performance score.
    performance_rank: int | None = None
    tracker_score: int | None = None
    # The history alone has these two; scoreboards do not.
    last_deaths: int | None = None
    suicides: int | None = None
    shots_dealt: Shots | None = None


class MatchPage(Model):
    matches: list[MatchEntry] = []
    next_page: int | None = None


class MatchPlayer(Model):
    riot_id: str
    team: str | None = None
    party_id: str | None = None
    agent: str | None = None
    rank: str | None = None
    account_level: int | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    kd: float | None = None
    acs: float | None = None
    adr: float | None = None
    hs_pct: float | None = None
    kast: float | None = None
    damage: int | None = None
    damage_received: int | None = None
    damage_delta_per_round: float | None = None
    combat_score: int | None = None
    # Hits on the other team and hits taken from it, by body part.
    shots_dealt: Shots | None = None
    shots_received: Shots | None = None
    # Rounds in which the player got the first kill, or was the first of all ten to die.
    first_kills: int | None = None
    first_deaths: int | None = None
    # Rounds in which the player was the first of their own team to die.
    team_first_deaths: int | None = None
    entry_success_rate: float | None = None
    rounds_survived: int | None = None
    deaths_traded: int | None = None
    trade_kills: int | None = None
    clutches: int | None = None
    clutches_lost: int | None = None
    clutches_by_size: dict[str, int] | None = None
    clutches_lost_by_size: dict[str, int] | None = None
    multi_kills: int | None = None
    double_kills: int | None = None
    triple_kills: int | None = None
    quadra_kills: int | None = None
    aces: int | None = None
    plants: int | None = None
    defuses: int | None = None
    econ_rating: float | None = None
    avg_loadout_value: int | None = None
    credits_spent: int | None = None
    ability_casts: dict[str, int] | None = None
    # Tracker.gg's rating of the match out of 1000, and the separate number
    # that performance_rank orders the ten players by.
    tracker_score: int | None = None
    performance_score: float | None = None
    performance_rank: int | None = None
    # Tracker.gg's labels for the match, such as "Top Frag" or "Trader".
    tags: list[str] | None = None
    attack: SplitStats | None = None
    defense: SplitStats | None = None
    # Keyed by tracker.gg's buy types: pistol, eco, semi and full.
    buys: dict[str, SplitStats] | None = None
    weapon_kills: dict[str, int] | None = None


class MatchTeam(Model):
    team: str
    won: bool | None = None
    rounds_won: int | None = None
    rounds_lost: int | None = None
    # True for a team that gave the match up.
    surrendered: bool | None = None
    started_on: str | None = None
    # Rounds won by how they ended, and spike plants by site.
    round_wins: dict[str, int] | None = None
    plants_by_site: dict[str, int] | None = None


class SpikeEvent(Model):
    by: str | None = None
    site: str | None = None
    # Seconds into the round.
    time: float | None = None


class Kill(Model):
    # Seconds into the round.
    time: float | None = None
    killer: str | None = None
    victim: str | None = None
    weapon: str | None = None
    assists: list[str] | None = None
    distance_m: float | None = None
    # Where each of them stood on the minimap, as [x, y] from 0 at the top left to 1.
    killer_at: list[float] | None = None
    victim_at: list[float] | None = None


class RoundPlayer(Model):
    """One player's round."""

    riot_id: str
    # Tracker.gg's buy type: pistol, eco, semi or full.
    buy: str | None = None
    # Set when the player was not in the game for the round.
    away: bool | None = None
    loadout_value: int | None = None
    spent: int | None = None
    remaining: int | None = None
    score: int | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    damage: int | None = None


class Round(Model):
    round: int
    winner: str | None = None
    ending: str | None = None
    # The team on attack.
    attackers: str | None = None
    plant: SpikeEvent | None = None
    defuse: SpikeEvent | None = None
    kills: list[Kill] | None = None
    players: list[RoundPlayer] | None = None


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
    round_log: list[Round] | None = None


class SearchResult(Model):
    riot_id: str
    status: str | None = None
