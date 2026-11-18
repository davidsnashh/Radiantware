"""Turn tracker.gg responses (JSON, or JSON wrapped in HTML) into models."""

from __future__ import annotations

import html
import json
import math
import re
from collections import Counter
from collections.abc import Iterator
from typing import Any

from models import (
    Ability,
    AgentStats,
    Kill,
    MapStats,
    MatchDetails,
    MatchEntry,
    MatchPage,
    MatchPlayer,
    MatchTeam,
    PlayerProfile,
    Rank,
    RoleStats,
    Round,
    RoundPlayer,
    SearchResult,
    Season,
    SeasonStats,
    Shots,
    SpikeEvent,
    SplitStats,
    StatsBundle,
    TopEntry,
    WeaponStats,
)

from .utils import act_label

_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.DOTALL | re.IGNORECASE)
_TIER_ICON_RE = re.compile(r"/(\d+)\.png")

_CHALLENGE_MARKERS = (
    "just a moment...",
    "_cf_chl_opt",
    "challenge-error-text",
    "attention required!",
    "you have been blocked",
)
_RATE_LIMIT_MARKERS = ("error 1015", "you are being rate limited")

# Our stat name -> tracker.gg stat key, for the stats that carry a percentile.
_PERCENTILE_KEYS = {
    "wins": "matchesWon",
    "win_rate": "matchesWinPct",
    "round_win_rate": "roundsWinPct",
    "kills": "kills",
    "kd": "kDRatio",
    "acs": "scorePerRound",
    "adr": "damagePerRound",
    "damage_delta_per_round": "damageDeltaPerRound",
    "hs_pct": "headshotsPercentage",
    "kast": "kAST",
}

_TOP_ENTRIES = 3
# Ability slot -> the name tracker.gg's stat keys and agent metadata use for it.
_ABILITY_SLOTS = {"c": "grenade", "q": "ability1", "e": "ability2", "x": "ultimate"}
_SIDES = {"attacker": "attack", "defender": "defense"}
_SIDE_TOTALS = ("rounds", "won", "score", "damage", "dealt", "received")
_BODY_PARTS = ("head", "body", "leg")
# After a surrender tracker.gg lists the rounds that were never played under this result.
_SURRENDERED = "Surrendered"
_SPIKE = "Bomb"
_BUY_ORDER = ("pistol", "eco", "semi", "full")
# Tracker.gg names a player's buy by the credits spent in the round. The limits
# are not published; these reproduce its own per-player counts.
_ECO_MAX_SPEND = 1000
_FULL_MIN_SPEND = 3900
# Two positions further apart than this are not one fight: one of them is not on the map.
_MAX_FIGHT_METRES = 150
# Distances come in Unreal units, which are centimetres.
_UNITS_PER_METRE = 100


def extract_json(text: str) -> Any:
    """Decode a JSON body, including one a browser wrapped in its <pre> viewer."""
    body = text.strip()
    if body.startswith("<"):
        found = _PRE_RE.search(body)
        if not found:
            raise ValueError("response is HTML without an embedded JSON document")
        body = html.unescape(found.group(1)).strip()
    return json.loads(body)


def is_cloudflare_challenge(body: str) -> bool:
    head = body[:20_000].casefold()
    return head.lstrip().startswith("<") and any(marker in head for marker in _CHALLENGE_MARKERS)


def is_rate_limit_page(body: str) -> bool:
    head = body[:20_000].casefold()
    return head.lstrip().startswith("<") and any(marker in head for marker in _RATE_LIMIT_MARKERS)


def _number(stats: dict[str, Any], *keys: str) -> float | None:
    """The first of the given stats that holds a number. Endpoints spell some keys differently."""
    for key in keys:
        stat = stats.get(key)
        value = stat.get("value") if isinstance(stat, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _float(stats: dict[str, Any], *keys: str, digits: int = 2) -> float | None:
    value = _number(stats, *keys)
    return None if value is None else round(value, digits)


def _int(stats: dict[str, Any], *keys: str) -> int | None:
    value = _number(stats, *keys)
    return None if value is None else round(value)


def _text(stats: dict[str, Any], key: str) -> str | None:
    stat = stats.get(key)
    value = stat.get("value") if isinstance(stat, dict) else None
    return value if isinstance(value, str) and value else None


def _share(part: float | None, whole: float | None) -> float | None:
    if part is None or not whole:
        return None
    return round(100 * part / whole, 1)


def _entry_rate(first_kills: int | None, first_deaths: int | None) -> float | None:
    # Worked out here: tracker.gg's own "esr" is a fraction on profiles and a
    # percentage on scoreboards.
    if first_kills is None or first_deaths is None:
        return None
    return _share(first_kills, first_kills + first_deaths)


def _clutch_sizes(stats: dict[str, Any], prefix: str) -> dict[str, int] | None:
    """Clutches by the number of opponents left, without the sizes that never happened."""
    sizes = {f"1v{left}": _int(stats, f"{prefix}1v{left}") for left in range(1, 6)}
    return {size: count for size, count in sizes.items() if count} or None


def _ability_casts(stats: dict[str, Any]) -> dict[str, int] | None:
    casts = {slot: _int(stats, f"{key}Casts") for slot, key in _ABILITY_SLOTS.items()}
    return {slot: count for slot, count in casts.items() if count is not None} or None


def _shots(stats: dict[str, Any], prefix: str) -> Shots | None:
    shots = Shots(
        head=_int(stats, f"{prefix}Headshots"),
        body=_int(stats, f"{prefix}Bodyshots"),
        leg=_int(stats, f"{prefix}Legshots"),
    )
    return shots if shots.model_dump(exclude_none=True) else None


def _split(stats: dict[str, Any], prefix: str = "") -> SplitStats | None:
    """Stats of one side ("attack", "defense"), or with no prefix of a whole segment."""

    def keys(*names: str) -> tuple[str, ...]:
        return tuple(prefix + name if prefix else name[0].lower() + name[1:] for name in names)

    first_kills = _int(stats, *keys("FirstKills", "FirstBloods"))
    first_deaths = _int(stats, *keys("FirstDeaths"))
    split = SplitStats(
        rounds=_int(stats, *keys("RoundsPlayed")),
        rounds_won=_int(stats, *keys("RoundsWon")),
        round_win_rate=_float(stats, *keys("RoundsWinPct"), digits=1),
        kills=_int(stats, *keys("Kills")),
        deaths=_int(stats, *keys("Deaths")),
        assists=_int(stats, *keys("Assists")),
        kd=_float(stats, *keys("KdRatio", "KDRatio")),
        acs=_float(stats, *keys("ScorePerRound"), digits=1),
        adr=_float(stats, *keys("DamagePerRound"), digits=1),
        damage_delta_per_round=_float(stats, *keys("DamageDeltaPerRound"), digits=1),
        hs_pct=_float(stats, *keys("HsAccuracy", "HeadshotsPercentage"), digits=1),
        kast=_float(stats, *keys("Kast", "KAST"), digits=1),
        first_kills=first_kills,
        first_deaths=first_deaths,
        entry_success_rate=_entry_rate(first_kills, first_deaths),
        rounds_survived=_int(stats, *keys("Survived")),
        deaths_traded=_int(stats, *keys("Traded")),
        trade_kills=_int(stats, *keys("TradesAvenger")),
    )
    return split if split.model_dump(exclude_none=True) else None


def _rank(stat: Any) -> Rank | None:
    """Read a rank stat.

    The shape varies by endpoint: the tier name sits in metadata.tierName on
    profiles and in value on scoreboards, while a numeric value is the rank
    rating, which tracker.gg only has for Immortal and above.
    """
    if not isinstance(stat, dict):
        return None
    meta = stat.get("metadata") or {}
    value = stat.get("value")
    tier = meta.get("tierName") or (value if isinstance(value, str) else None)
    tier_id = meta.get("tierId")
    if not isinstance(tier_id, int):
        icon = _TIER_ICON_RE.search(meta.get("iconUrl") or "")
        tier_id = int(icon.group(1)) if icon else None
    if not tier and tier_id is None:
        return None
    is_rating = isinstance(value, (int, float)) and not isinstance(value, bool)
    position = stat.get("rank")
    return Rank(
        tier=tier or None,
        tier_id=tier_id,
        rr=round(value) if is_rating else None,
        leaderboard_rank=position if isinstance(position, int) else None,
        act=act_label(meta.get("actName")),
    )


def _tier_name(stat: Any) -> str | None:
    rank = _rank(stat)
    return rank.tier if rank else None


def _stat_line(stats: dict[str, Any]) -> dict[str, Any]:
    seconds = _number(stats, "timePlayed")
    match_seconds = _number(stats, "matchesDuration")
    first_kills = _int(stats, "firstBloods")
    first_deaths = _int(stats, "firstDeaths")
    big_rounds = [_int(stats, f"kills{kills}K") for kills in (3, 4, 5, 6)]
    return {
        "matches": _int(stats, "matchesPlayed"),
        "wins": _int(stats, "matchesWon"),
        "losses": _int(stats, "matchesLost"),
        "ties": _int(stats, "matchesTied"),
        "win_rate": _float(stats, "matchesWinPct", digits=1),
        "kills": _int(stats, "kills"),
        "deaths": _int(stats, "deaths"),
        "assists": _int(stats, "assists"),
        "kd": _float(stats, "kDRatio"),
        "kda": _float(stats, "kDARatio"),
        "acs": _float(stats, "scorePerRound", digits=1),
        "adr": _float(stats, "damagePerRound", digits=1),
        "damage_delta_per_round": _float(stats, "damageDeltaPerRound", digits=1),
        "hs_pct": _float(stats, "headshotsPercentage", digits=1),
        "kast": _float(stats, "kAST", digits=1),
        "first_kills": first_kills,
        "first_deaths": first_deaths,
        "aces": _int(stats, "aces"),
        "clutches": _int(stats, "clutches"),
        "mvps": _int(stats, "mVPs"),
        "rounds": _int(stats, "roundsPlayed"),
        "round_win_rate": _float(stats, "roundsWinPct", digits=1),
        "hours_played": None if seconds is None else round(seconds / 3600, 1),
        "disconnects": _int(stats, "matchesDisconnected"),
        "avg_match_minutes": None if match_seconds is None else round(match_seconds / 60, 1),
        "rounds_won": _int(stats, "roundsWon"),
        "rounds_lost": _int(stats, "roundsLost"),
        "performance_score": _float(stats, "performancePerMatch", digits=1),
        "damage": _int(stats, "damage"),
        "damage_received": _int(stats, "damageReceived"),
        "entry_success_rate": _entry_rate(first_kills, first_deaths),
        "last_deaths": _int(stats, "lastDeaths"),
        "rounds_survived": _int(stats, "survived"),
        "deaths_traded": _int(stats, "traded"),
        "trade_kills": _int(stats, "tradesAvenger"),
        "clutches_lost": _int(stats, "clutchesLost"),
        "clutches_by_size": _clutch_sizes(stats, "clutches"),
        "clutches_lost_by_size": _clutch_sizes(stats, "clutchesLost"),
        "multi_kills": None if big_rounds[0] is None else sum(count or 0 for count in big_rounds),
        "double_kills": _int(stats, "kills2K"),
        "triple_kills": big_rounds[0],
        "quadra_kills": big_rounds[1],
        "most_kills_in_match": _int(stats, "mostKillsInMatch"),
        "plants": _int(stats, "plants"),
        "defuses": _int(stats, "defuses"),
        "econ_rating": _float(stats, "econRatingPerMatch", digits=1),
        "ability_casts": _ability_casts(stats),
        "shots_dealt": _shots(stats, "dealt"),
        "shots_received": _shots(stats, "received"),
        "flawless_rounds": _int(stats, "flawless"),
        "thrifty_rounds": _int(stats, "thrifty"),
        "team_aces": _int(stats, "teamAces"),
        "suicides": _int(stats, "suicides"),
        "attack": _split(stats, "attack"),
        "defense": _split(stats, "defense"),
    }


def _sheet(stats: dict[str, Any], all_acts: bool) -> dict[str, Any]:
    sheet = _stat_line(stats)
    if all_acts:
        # Tracker.gg does not total these across acts: it sends a flat 0 for the
        # first two and the current act's number for trade kills.
        sheet["mvps"] = sheet["thrifty_rounds"] = sheet["trade_kills"] = None
        for side in _SIDES.values():
            if sheet[side]:
                sheet[side].trade_kills = None
    return sheet


def _abilities(meta: dict[str, Any], stats: dict[str, Any]) -> dict[str, Ability] | None:
    names = {str(key).casefold(): info for key, info in (meta.get("abilities") or {}).items()}
    found = {}
    for slot, key in _ABILITY_SLOTS.items():
        info = names.get(key)
        ability = Ability(
            name=info.get("name") if isinstance(info, dict) else None,
            casts=_int(stats, f"{key}Casts"),
        )
        if ability.model_dump(exclude_none=True):
            found[slot] = ability
    return found or None


def _weapon(meta: dict[str, Any], stats: dict[str, Any], all_acts: bool) -> WeaponStats:
    kills = _int(stats, "kills")
    distance = _number(stats, "killDistance")
    longest = _number(stats, "longestKillDistance")
    return WeaponStats(
        weapon=meta.get("name") or "Unknown",
        category=meta.get("category"),
        matches=_int(stats, "matchesPlayed"),
        rounds=_int(stats, "roundsPlayed"),
        kills=kills,
        deaths=_int(stats, "deaths"),
        kd=_float(stats, "kDRatio"),
        alt_fire_kills=_int(stats, "secondaryKills"),
        hs_pct=_float(stats, "headshotsPercentage", digits=1),
        damage=_int(stats, "damage"),
        # Not totalled across acts: tracker.gg sends a flat 0 there.
        damage_received=None if all_acts else _int(stats, "damageReceived"),
        shots_dealt=_shots(stats, "dealt"),
        # Tracker.gg's own average is per match, so divide the total by the kills.
        avg_kill_distance_m=(
            round(distance / kills / _UNITS_PER_METRE, 1) if distance and kills else None
        ),
        longest_kill_m=None if longest is None else round(longest / _UNITS_PER_METRE, 1),
    )


def _percentiles(stats: dict[str, Any]) -> dict[str, float] | None:
    found = {}
    for name, key in _PERCENTILE_KEYS.items():
        stat = stats.get(key)
        value = stat.get("percentile") if isinstance(stat, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            found[name] = float(value)
    return found or None


def _top_entry(name: str, stats: dict[str, Any]) -> TopEntry:
    return TopEntry(
        name=name,
        matches=_int(stats, "matchesPlayed"),
        win_rate=_float(stats, "matchesWinPct", digits=1),
        wins=_int(stats, "matchesWon"),
        losses=_int(stats, "matchesLost"),
        kills=_int(stats, "kills"),
        deaths=_int(stats, "deaths"),
        assists=_int(stats, "assists"),
        kd=_float(stats, "kDRatio"),
        acs=_float(stats, "scorePerRound", digits=1),
        adr=_float(stats, "damagePerRound", digits=1),
        hs_pct=_float(stats, "headshotsPercentage", digits=1),
        kast=_float(stats, "kAST", digits=1),
    )


def _most_played(entries: list[TopEntry]) -> list[TopEntry] | None:
    ranked = sorted(entries, key=lambda entry: entry.matches or 0, reverse=True)
    return ranked[:_TOP_ENTRIES] or None


def parse_stats_bundle(segments: list[dict[str, Any]]) -> StatsBundle:
    """Split a segment list into the overall stat line, agents, maps, roles and weapons."""
    overall: SeasonStats | None = None
    agents: list[AgentStats] = []
    maps: dict[str, MapStats] = {}
    roles: list[RoleStats] = []
    weapons: list[WeaponStats] = []
    maps_by_agent: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    agents_by_map: dict[str, list[TopEntry]] = {}

    for segment in segments or []:
        kind = segment.get("type")
        attrs = segment.get("attributes") or {}
        meta = segment.get("metadata") or {}
        stats = segment.get("stats") or {}
        name = meta.get("name") or "Unknown"
        all_acts = kind == "playlist" or ("seasonId" in attrs and attrs["seasonId"] is None)

        if kind in ("season", "playlist") and overall is None:
            overall = SeasonStats(
                **_sheet(stats, all_acts),
                rank=_rank(stats.get("rank")),
                peak_rank=_rank(stats.get("peakRank")),
                tracker_score=_int(stats, "trnPerformanceScore"),
                percentiles=_percentiles(stats),
            )
        elif kind == "agent":
            # The abilities block carries the casts on agent rows, with names.
            sheet = {**_sheet(stats, all_acts), "ability_casts": None}
            agents.append(
                AgentStats(
                    agent=name,
                    role=meta.get("role"),
                    pick_rate=_float(stats, "pickRate", digits=1),
                    abilities=_abilities(meta, stats),
                    **sheet,
                )
            )
        elif kind == "map":
            maps[attrs.get("key") or name] = MapStats(map=name, **_sheet(stats, all_acts))
        elif kind == "agent-role":
            roles.append(RoleStats(role=name, **_sheet(stats, all_acts)))
        elif kind == "weapon":
            weapons.append(_weapon(meta, stats, all_acts))
        elif kind == "agent-top-map" and attrs.get("mapKey"):
            maps_by_agent.setdefault(name, []).append((attrs["mapKey"], stats))
        elif kind == "map-top-agent" and attrs.get("mapKey"):
            agents_by_map.setdefault(attrs["mapKey"], []).append(_top_entry(name, stats))

    for agent in agents:
        agent.top_maps = _most_played(
            [
                _top_entry(maps[key].map if key in maps else key.replace("-", " ").title(), stats)
                for key, stats in maps_by_agent.get(agent.agent, [])
            ]
        )
    for key, map_stats in maps.items():
        map_stats.top_agents = _most_played(agents_by_map.get(key, []))

    def by_matches(row: AgentStats | MapStats | RoleStats) -> int:
        return row.matches or 0

    return StatsBundle(
        season_stats=overall,
        agents=sorted(agents, key=by_matches, reverse=True),
        maps=sorted(maps.values(), key=by_matches, reverse=True),
        roles=sorted(roles, key=by_matches, reverse=True),
        weapons=sorted(weapons, key=lambda row: row.kills or 0, reverse=True),
    )


def parse_profile(data: dict[str, Any]) -> PlayerProfile:
    info = data.get("platformInfo") or {}
    meta = data.get("metadata") or {}
    segments = data.get("segments") or []

    peak = None
    for segment in segments:
        attrs = segment.get("attributes") or {}
        if segment.get("type") == "peak-rating" and attrs.get("playlist") == "competitive":
            stats = segment.get("stats") or {}
            peak = _rank(stats.get("peakRating") or stats.get("peakRank"))

    level = meta.get("accountLevel")
    return PlayerProfile(
        riot_id=info.get("platformUserIdentifier") or info.get("platformUserHandle") or "",
        account_level=level if isinstance(level, int) else None,
        region=meta.get("activeShard"),
        privacy=meta.get("privacy"),
        default_playlist=meta.get("defaultPlaylist") or "competitive",
        default_season=meta.get("defaultSeason"),
        seasons=[
            Season(id=season["id"], name=season.get("name"), short_name=season.get("shortName"))
            for season in meta.get("seasons") or []
            if season.get("id")
        ],
        playlists=[item["id"] for item in meta.get("playlists") or [] if item.get("id")],
        peak_rank=peak,
        stats=parse_stats_bundle(segments),
    )


def parse_match_page(data: dict[str, Any]) -> MatchPage:
    entries = []
    for item in data.get("matches") or []:
        attrs = item.get("attributes") or {}
        meta = item.get("metadata") or {}
        if not attrs.get("id"):
            continue
        # The history only carries the requesting player's own segment.
        segment = next(iter(item.get("segments") or []), {})
        segment_meta = segment.get("metadata") or {}
        stats = segment.get("stats") or {}
        entries.append(
            MatchEntry(
                match_id=attrs["id"],
                played_at=meta.get("timestamp"),
                map=meta.get("mapName"),
                mode=meta.get("modeName"),
                season=act_label(meta.get("seasonName")),
                result=meta.get("result") or segment_meta.get("result"),
                rounds_won=_int(stats, "roundsWon"),
                rounds_lost=_int(stats, "roundsLost"),
                agent=segment_meta.get("agentName"),
                rank=_tier_name(stats.get("rank")),
                kills=_int(stats, "kills"),
                deaths=_int(stats, "deaths"),
                assists=_int(stats, "assists"),
                kd=_float(stats, "kdRatio"),
                acs=_float(stats, "scorePerRound", digits=1),
                adr=_float(stats, "damagePerRound", digits=1),
                hs_pct=_float(stats, "headshotsPercentage", digits=1),
                kast=_float(stats, "kAST", digits=1),
                damage=_int(stats, "damage"),
                combat_score=_int(stats, "score"),
                performance_rank=_int(stats, "placement"),
                tracker_score=_int(stats, "trnPerformanceScore"),
                last_deaths=_int(stats, "lastDeaths"),
                suicides=_int(stats, "suicides"),
                shots_dealt=_shots(stats, "dealt"),
            )
        )
    next_page = (data.get("metadata") or {}).get("next")
    return MatchPage(matches=entries, next_page=next_page if isinstance(next_page, int) else None)


def _identifier(segment: dict[str, Any], key: str = "platformUserIdentifier") -> str:
    return (segment.get("attributes") or {}).get(key) or ""


def _round_number(segment: dict[str, Any]) -> int:
    number = (segment.get("attributes") or {}).get("round")
    return number if isinstance(number, int) else 0


def _match_player(segment: dict[str, Any]) -> MatchPlayer:
    meta = segment.get("metadata") or {}
    stats = segment.get("stats") or {}
    handle = (meta.get("platformInfo") or {}).get("platformUserHandle")
    party = meta.get("partyId")
    level = meta.get("accountLevel")
    first_kills = _int(stats, "firstKills")
    first_deaths = _int(stats, "firstDeaths")
    head_hits = _int(stats, "headshots")
    tags = [
        tag["name"] for tag in meta.get("tags") or [] if isinstance(tag, dict) and tag.get("name")
    ]
    return MatchPlayer(
        riot_id=_identifier(segment) or handle or "Unknown",
        team=meta.get("teamId"),
        party_id=None if party is None else str(party),
        agent=meta.get("agentName"),
        rank=_tier_name(stats.get("rank")),
        account_level=level if isinstance(level, int) else None,
        kills=_int(stats, "kills"),
        deaths=_int(stats, "deaths"),
        assists=_int(stats, "assists"),
        kd=_float(stats, "kdRatio"),
        acs=_float(stats, "scorePerRound", digits=1),
        adr=_float(stats, "damagePerRound", digits=1),
        hs_pct=_float(stats, "hsAccuracy", digits=1),
        kast=_float(stats, "kast", digits=1),
        damage=_int(stats, "damage"),
        damage_received=_int(stats, "damageReceived"),
        damage_delta_per_round=_float(stats, "damageDeltaPerRound", digits=1),
        combat_score=_int(stats, "score"),
        # The damage rows replace this with the full count when they are there.
        shots_dealt=None if head_hits is None else Shots(head=head_hits),
        first_kills=first_kills,
        first_deaths=first_deaths,
        entry_success_rate=_entry_rate(first_kills, first_deaths),
        rounds_survived=_int(stats, "survived"),
        deaths_traded=_int(stats, "traded"),
        trade_kills=_int(stats, "tradesAvenger"),
        clutches=_int(stats, "clutches"),
        clutches_lost=_int(stats, "clutchesLost"),
        clutches_by_size=_clutch_sizes(stats, "clutches"),
        clutches_lost_by_size=_clutch_sizes(stats, "clutchesLost"),
        multi_kills=_int(stats, "multiKills"),
        double_kills=_int(stats, "doubleKills"),
        triple_kills=_int(stats, "tripleKills"),
        quadra_kills=_int(stats, "quadraKills"),
        aces=_int(stats, "pentaKills"),
        plants=_int(stats, "plants"),
        defuses=_int(stats, "defuses"),
        econ_rating=_float(stats, "econRating", digits=1),
        ability_casts=_ability_casts(stats),
        tracker_score=_int(stats, "trnPerformanceScore"),
        performance_score=_float(stats, "performance", digits=1),
        performance_rank=_int(stats, "placement"),
        tags=tags or None,
        attack=_scoreboard_side(stats, "attack"),
        defense=_scoreboard_side(stats, "defense"),
    )


def _scoreboard_side(stats: dict[str, Any], side: str) -> SplitStats | None:
    split = _split(stats, side)
    if split:
        # Tracker.gg divides a scoreboard's per-round defense numbers by the wrong
        # round count, so these four are rebuilt from the round rows instead.
        split.round_win_rate = split.acs = split.adr = split.damage_delta_per_round = None
    return split


def _match_team(segment: dict[str, Any]) -> MatchTeam:
    attrs = segment.get("attributes") or {}
    meta = segment.get("metadata") or {}
    stats = segment.get("stats") or {}
    return MatchTeam(
        team=attrs.get("teamId") or meta.get("name") or "Unknown",
        won=meta.get("hasWon"),
        rounds_won=_int(stats, "roundsWon"),
        rounds_lost=_int(stats, "roundsLost"),
    )


def _team_damage(
    players: dict[str, MatchPlayer], rows: list[dict[str, Any]]
) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Damage rows between the two teams, as attacker, victim and row.

    Like the scoreboard, this leaves out damage to a teammate or to oneself.
    """
    for row in rows:
        names = _identifier(row), _identifier(row, "opponentPlatformUserIdentifier")
        attacker, victim = players.get(names[0]), players.get(names[1])
        if attacker is not None and victim is not None and attacker.team != victim.team:
            yield names[0], names[1], row


def _add_player_rounds(
    players: dict[str, MatchPlayer],
    teams: dict[str, MatchTeam],
    rounds: list[dict[str, Any]],
    damage_rows: list[dict[str, Any]],
) -> dict[tuple[str, int], str]:
    """Per-side round counts and per-round numbers, and money spent, from the round rows.

    Returns the side every player was on in every round.
    """
    totals: dict[tuple[str, str], dict[str, float]] = {}
    side_in_round: dict[tuple[str, int], str] = {}
    loadouts: dict[str, list[float]] = {}
    spent: dict[str, float] = {}
    shots: dict[tuple[str, str], Counter[str]] = {}
    for segment in sorted(rounds, key=_round_number):
        name = _identifier(segment)
        player = players.get(name)
        if player is None:
            continue
        meta = segment.get("metadata") or {}
        stats = segment.get("stats") or {}
        side = _SIDES.get(meta.get("teamSide"))
        if side:
            side_in_round[name, _round_number(segment)] = side
            total = totals.setdefault((name, side), dict.fromkeys(_SIDE_TOTALS, 0.0))
            total["rounds"] += 1
            total["won"] += meta.get("hasWon") is True
            total["score"] += _number(stats, "score") or 0
            total["damage"] += _number(stats, "damage") or 0
            team = teams.get(player.team or "")
            if team and team.started_on is None:
                team.started_on = side
        value = _number(stats, "loadoutValue")
        if value is not None:
            loadouts.setdefault(name, []).append(value)
        credits = _number(stats, "spentCredits")
        if credits is not None:
            spent[name] = spent.get(name, 0) + credits

    for *names, row in _team_damage(players, damage_rows):
        stats = row.get("stats") or {}
        damage = _number(stats, "damage") or 0
        for name, total in zip(names, ("dealt", "received"), strict=True):
            hits = shots.setdefault((name, total), Counter())
            for part in _BODY_PARTS:
                hits[part] += _int(stats, f"{part}shots") or 0
            side = side_in_round.get((name, _round_number(row)))
            if side:
                totals[name, side][total] += damage

    for name in {name for name, _ in totals}:
        for side in _SIDES.values():
            total = totals.get((name, side))
            if total is None:
                # The match ended before the teams switched sides.
                setattr(players[name], side, None)
                continue
            split = getattr(players[name], side) or SplitStats()
            played = total["rounds"]
            split.rounds = round(played)
            split.rounds_won = round(total["won"])
            split.round_win_rate = _share(total["won"], played)
            split.acs = round(total["score"] / played, 1)
            split.adr = round(total["dealt" if damage_rows else "damage"] / played, 1)
            if damage_rows:
                delta = total["dealt"] - total["received"]
                split.damage_delta_per_round = round(delta / played, 1)
            setattr(players[name], side, split)
    for name, values in loadouts.items():
        players[name].avg_loadout_value = round(sum(values) / len(values))
    for name, credits in spent.items():
        players[name].credits_spent = round(credits)
    for (name, total), hits in shots.items():
        setattr(players[name], f"shots_{total}", Shots(**hits))
    return side_in_round


def _counted_kills(
    players: dict[str, MatchPlayer], segments: list[dict[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    """The kill events the scoreboard counts as kills, each with the killer's name.

    The events also list suicides and kills on a teammate, which it does not.
    """
    kills = []
    for segment in segments:
        name = _identifier(segment)
        killer = players.get(name)
        victim = players.get(_identifier(segment, "opponentPlatformUserIdentifier"))
        if killer is None or killer is victim:
            continue
        if victim is not None and killer.team is not None and killer.team == victim.team:
            continue
        kills.append((name, segment))
    return kills


def _add_weapon_kills(
    players: dict[str, MatchPlayer], kills: list[tuple[str, dict[str, Any]]]
) -> None:
    weapons: dict[str, Counter[str]] = {}
    for name, segment in kills:
        meta = segment.get("metadata") or {}
        weapon = meta.get("weaponName") or (meta.get("finishingDamage") or {}).get("damageType")
        if weapon:
            weapons.setdefault(name, Counter())[str(weapon)] += 1
    for name, counts in weapons.items():
        players[name].weapon_kills = dict(counts.most_common())


def _add_round_kills(
    players: dict[str, MatchPlayer],
    kills: list[tuple[str, dict[str, Any]]],
    side_in_round: dict[tuple[str, int], str],
) -> None:
    """Recount kills per side and multi-kill rounds: tracker.gg's own include team kills."""
    if not kills:
        return
    per_round: Counter[tuple[str, int]] = Counter()
    per_side: Counter[tuple[str, str]] = Counter()
    for name, segment in kills:
        number = _round_number(segment)
        per_round[name, number] += 1
        side = side_in_round.get((name, number))
        if side:
            per_side[name, side] += 1
    for name, player in players.items():
        sizes = Counter(count for (killer, _), count in per_round.items() if killer == name)
        player.double_kills, player.triple_kills, player.quadra_kills = sizes[2], sizes[3], sizes[4]
        player.aces = sum(rounds for size, rounds in sizes.items() if size >= 5)
        player.multi_kills = player.triple_kills + player.quadra_kills + player.aces
        for side in _SIDES.values():
            split = getattr(player, side)
            if split and split.rounds:
                split.kills = per_side[name, side]
                split.kd = round(split.kills / max(split.deaths or 0, 1), 2)


def _add_team_first_deaths(players: dict[str, MatchPlayer], segments: list[dict[str, Any]]) -> None:
    """Count the rounds in which a player was the first of their own team to die."""
    by_round: dict[int, list[dict[str, Any]]] = {}
    for segment in segments:
        by_round.setdefault(_round_number(segment), []).append(segment)
    if not by_round:
        return
    first_down: Counter[str] = Counter()
    for events in by_round.values():
        events.sort(key=lambda event: (event.get("metadata") or {}).get("roundTime") or 0)
        teams_hit: set[str] = set()
        for event in events:
            name = _identifier(event, "opponentPlatformUserIdentifier")
            victim = players.get(name)
            cause = ((event.get("metadata") or {}).get("finishingDamage") or {}).get("damageType")
            if cause == _SPIKE:
                # The spike kills after the round is decided, which is not a death on the scoreboard.
                continue
            if victim is None or victim.team is None or victim.team in teams_hit:
                continue
            teams_hit.add(victim.team)
            first_down[name] += 1
    for name, player in players.items():
        if player.team is not None:
            player.team_first_deaths = first_down[name]


def _add_buys(players: dict[str, MatchPlayer], segments: list[dict[str, Any]]) -> None:
    buys: dict[str, dict[str, SplitStats]] = {}
    for segment in segments:
        name = _identifier(segment)
        kind = (segment.get("attributes") or {}).get("loadout")
        split = _split(segment.get("stats") or {})
        if name in players and kind and split and split.rounds:
            # Buy rows report the share of kills that were headshots under this
            # name, which is a different number from the share of hits.
            split.hs_pct = None
            buys.setdefault(name, {})[str(kind)] = split

    def order(kind: str) -> int:
        return _BUY_ORDER.index(kind) if kind in _BUY_ORDER else len(_BUY_ORDER)

    for name, found in buys.items():
        players[name].buys = {kind: found[kind] for kind in sorted(found, key=order)}


def _seconds(milliseconds: Any) -> float | None:
    is_number = isinstance(milliseconds, (int, float)) and not isinstance(milliseconds, bool)
    return round(milliseconds / 1000, 1) if is_number else None


def _on_minimap(location: Any, details: dict[str, Any]) -> list[float] | None:
    """A game position as minimap [x, y], each from 0 at the top left to 1."""
    try:
        x = location["y"] * details["xMultiplier"] + details["xScalarToAdd"]
        y = location["x"] * details["yMultiplier"] + details["yScalarToAdd"]
    except (KeyError, TypeError):
        return None
    if not (-0.1 <= x <= 1.1 and -0.1 <= y <= 1.1):
        # Some fights are off the map picture, such as a duel inside an ultimate's arena.
        return None
    return [round(x, 3), round(y, 3)]


def _kill(event: dict[str, Any], map_details: dict[str, Any]) -> Kill:
    meta = event.get("metadata") or {}
    killer = _identifier(event) or None
    stood = next(
        (
            spot.get("location")
            for spot in meta.get("playerLocations") or []
            if isinstance(spot, dict) and spot.get("platformUserIdentifier") == killer
        ),
        None,
    )
    fell = meta.get("opponentLocation")
    distance = None
    try:
        apart = math.dist((stood["x"], stood["y"]), (fell["x"], fell["y"])) / _UNITS_PER_METRE
    except (KeyError, TypeError):
        pass
    else:
        distance = round(apart, 1) if apart <= _MAX_FIGHT_METRES else None
    helpers = [
        helper.get("platformUserIdentifier")
        for helper in meta.get("assistants") or []
        if isinstance(helper, dict) and helper.get("platformUserIdentifier")
    ]
    return Kill(
        time=_seconds(meta.get("roundTime")),
        killer=killer,
        victim=_identifier(event, "opponentPlatformUserIdentifier") or None,
        weapon=meta.get("weaponName") or (meta.get("finishingDamage") or {}).get("damageType"),
        assists=helpers or None,
        distance_m=distance,
        killer_at=_on_minimap(stood, map_details),
        victim_at=_on_minimap(fell, map_details),
    )


def _spike_event(event: Any) -> SpikeEvent | None:
    if not isinstance(event, dict):
        return None
    site = event.get("site")
    return SpikeEvent(
        by=event.get("platformUserIdentifier"),
        site=site if isinstance(site, str) else None,
        time=_seconds(event.get("roundTime")),
    )


def _buy_type(spent: int | None, pistol_round: bool) -> str | None:
    if pistol_round:
        return "pistol"
    if spent is None:
        return None
    if spent <= _ECO_MAX_SPEND:
        return "eco"
    return "semi" if spent < _FULL_MIN_SPEND else "full"


def _round_players(
    players: dict[str, MatchPlayer], rows: list[dict[str, Any]]
) -> tuple[dict[int, list[RoundPlayer]], dict[int, str]]:
    """Every player's line per round, and the team that attacked in each round."""
    lines: dict[int, list[RoundPlayer]] = {}
    attackers: dict[int, str] = {}
    for row in rows:
        number = _round_number(row)
        meta = row.get("metadata") or {}
        stats = row.get("stats") or {}
        if _SIDES.get(meta.get("teamSide")) == "attack" and isinstance(meta.get("teamId"), str):
            attackers[number] = meta["teamId"]
        player = players.get(_identifier(row))
        if player is None:
            continue
        lines.setdefault(number, []).append(
            RoundPlayer(
                riot_id=player.riot_id,
                loadout_value=_int(stats, "loadoutValue"),
                spent=_int(stats, "spentCredits"),
                remaining=_int(stats, "remainingCredits"),
                score=_int(stats, "score"),
                kills=_int(stats, "kills"),
                deaths=_int(stats, "deaths"),
                assists=_int(stats, "assists"),
                damage=_int(stats, "damage"),
            )
        )
    # A half opens with a pistol round, and a half starts where the teams swap sides.
    first = min(attackers, default=None)
    swap = next((n for n in sorted(attackers) if attackers[n] != attackers[first]), None)
    for number, round_lines in lines.items():
        for line in round_lines:
            line.buy = _buy_type(line.spent, number in (first, swap))
    return lines, attackers


def _round_log(
    players: dict[str, MatchPlayer],
    teams: dict[str, MatchTeam],
    summaries: list[dict[str, Any]],
    round_rows: list[dict[str, Any]],
    kill_events: list[dict[str, Any]],
    damage_rows: list[dict[str, Any]],
    map_details: dict[str, Any],
) -> list[Round] | None:
    """Every round played: how it ended, each player's round and the kills in order.

    Also notes per team how its rounds were won and where it planted.
    """
    lines, attackers = _round_players(players, round_rows)
    credited = Counter(
        (name, _round_number(event)) for name, event in _counted_kills(players, kill_events)
    )
    dealt: Counter[tuple[str, int]] = Counter()
    for attacker, _, row in _team_damage(players, damage_rows):
        dealt[attacker, _round_number(row)] += _number(row.get("stats") or {}, "damage") or 0
    in_play: dict[int, set[str]] = {}
    for event in kill_events:
        seen = in_play.setdefault(_round_number(event), set())
        seen.update((_identifier(event), _identifier(event, "opponentPlatformUserIdentifier")))
        for spot in (event.get("metadata") or {}).get("playerLocations") or []:
            if isinstance(spot, dict) and spot.get("platformUserIdentifier"):
                seen.add(spot["platformUserIdentifier"])
    for number, round_lines in lines.items():
        for line in round_lines:
            # Tracker.gg's round rows count a kill on a teammate and damage to one,
            # so both are taken from the events between the teams instead.
            if kill_events:
                line.kills = credited[line.riot_id, number]
            if damage_rows:
                line.damage = round(dealt[line.riot_id, number])
            idle = not (line.loadout_value or line.spent or line.score or line.deaths)
            if idle and number in in_play and line.riot_id not in in_play[number]:
                # Tracker.gg leaves such rounds out of its buy types as well.
                line.buy, line.away = None, True

    kills: dict[int, list[Kill]] = {}
    in_order = sorted(kill_events, key=lambda e: (e.get("metadata") or {}).get("roundTime") or 0)
    for event in in_order:
        kills.setdefault(_round_number(event), []).append(_kill(event, map_details))

    rounds: list[Round] = []
    for segment in sorted(summaries, key=_round_number):
        number = _round_number(segment)
        if not number:
            continue
        stats = segment.get("stats") or {}
        meta = segment.get("metadata") or {}
        winner, ending = _text(stats, "winningTeam"), _text(stats, "roundResult")
        if ending == _SURRENDERED:
            for team in teams.values():
                if winner and team.team != winner:
                    team.surrendered = True
            continue
        plant = _spike_event(meta.get("plant"))
        rounds.append(
            Round(
                round=number,
                winner=winner,
                ending=ending,
                attackers=attackers.get(number),
                plant=plant,
                defuse=_spike_event(meta.get("defuse")),
                kills=kills.get(number),
                players=lines.get(number),
            )
        )

        winning = teams.get(winner or "")
        if winning and ending:
            wins = winning.round_wins or {}
            winning.round_wins = {**wins, ending: wins.get(ending, 0) + 1}
        planter = players.get((plant.by if plant else None) or "")
        planting = teams.get((planter.team if planter else None) or "")
        if planting and plant and plant.site:
            sites = planting.plants_by_site or {}
            planting.plants_by_site = {**sites, plant.site: sites.get(plant.site, 0) + 1}
    return rounds or None


def parse_match(data: dict[str, Any]) -> MatchDetails:
    """Keep the scoreboard, what the per-round rows add up to, and a log of every round.

    Most of the payload is positions of all ten players at every kill, which are dropped.
    """
    attrs = data.get("attributes") or {}
    meta = data.get("metadata") or {}
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for segment in data.get("segments") or []:
        by_kind.setdefault(segment.get("type") or "", []).append(segment)

    teams = {team.team: team for team in map(_match_team, by_kind.get("team-summary", []))}
    players: list[MatchPlayer] = []
    by_name: dict[str, MatchPlayer] = {}
    for segment in by_kind.get("player-summary", []):
        player = _match_player(segment)
        players.append(player)
        if _identifier(segment):
            by_name[_identifier(segment)] = player

    unplayed = {
        _round_number(segment)
        for segment in by_kind.get("round-summary", [])
        if _text(segment.get("stats") or {}, "roundResult") == _SURRENDERED
    }

    def played(kind: str) -> list[dict[str, Any]]:
        return [row for row in by_kind.get(kind, []) if _round_number(row) not in unplayed]

    if meta.get("isTeamBased") is False:
        # Tracker.gg lists every player of a free-for-all as a team of their own.
        teams = {}
    kills = _counted_kills(by_name, played("player-round-kills"))
    _add_weapon_kills(by_name, kills)
    _add_buys(by_name, by_kind.get("player-loadout", []))
    round_log = None
    if meta.get("isRoundBased") is not False:
        side_in_round = _add_player_rounds(
            by_name, teams, played("player-round"), played("player-round-damage")
        )
        _add_round_kills(by_name, kills, side_in_round)
        _add_team_first_deaths(by_name, played("player-round-kills"))
        round_log = _round_log(
            by_name,
            teams,
            by_kind.get("round-summary", []),
            played("player-round"),
            played("player-round-kills"),
            played("player-round-damage"),
            meta.get("mapDetails") or {},
        )

    duration_ms = meta.get("duration")
    is_number = isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool)
    rounds = meta.get("rounds")
    players.sort(key=lambda player: (player.team or "", -(player.acs or 0)))
    return MatchDetails(
        match_id=attrs.get("id") or "",
        played_at=meta.get("dateStarted"),
        map=meta.get("mapName"),
        mode=meta.get("modeName"),
        playlist=meta.get("playlist") or meta.get("queueId"),
        ranked=meta.get("isRanked"),
        duration_minutes=round(duration_ms / 60_000, 1) if is_number else None,
        rounds=rounds if isinstance(rounds, int) else None,
        teams=list(teams.values()),
        players=players,
        round_log=round_log,
    )


def parse_search(data: Any) -> list[SearchResult]:
    return [
        SearchResult(riot_id=item["platformUserIdentifier"], status=item.get("status"))
        for item in data or []
        if isinstance(item, dict) and item.get("platformUserIdentifier")
    ]
