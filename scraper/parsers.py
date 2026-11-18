"""Turn tracker.gg responses (JSON, or JSON wrapped in HTML) into models."""

from __future__ import annotations

import html
import json
import re
from typing import Any

from models import (
    AgentStats,
    MapStats,
    MatchDetails,
    MatchEntry,
    MatchPage,
    MatchPlayer,
    MatchTeam,
    PlayerProfile,
    Rank,
    SearchResult,
    Season,
    SeasonStats,
    StatsBundle,
    TopEntry,
)

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
    "win_rate": "matchesWinPct",
    "kd": "kDRatio",
    "acs": "scorePerRound",
    "adr": "damagePerRound",
    "damage_delta_per_round": "damageDeltaPerRound",
    "hs_pct": "headshotsPercentage",
    "kast": "kAST",
}

_TOP_ENTRIES = 3


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


def _number(stats: dict[str, Any], key: str) -> float | None:
    stat = stats.get(key)
    value = stat.get("value") if isinstance(stat, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _float(stats: dict[str, Any], key: str, digits: int = 2) -> float | None:
    value = _number(stats, key)
    return None if value is None else round(value, digits)


def _int(stats: dict[str, Any], key: str) -> int | None:
    value = _number(stats, key)
    return None if value is None else round(value)


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
        act=meta.get("actName"),
    )


def _tier_name(stat: Any) -> str | None:
    rank = _rank(stat)
    return rank.tier if rank else None


def _stat_line(stats: dict[str, Any]) -> dict[str, Any]:
    seconds = _number(stats, "timePlayed")
    return {
        "matches": _int(stats, "matchesPlayed"),
        "wins": _int(stats, "matchesWon"),
        "losses": _int(stats, "matchesLost"),
        "ties": _int(stats, "matchesTied"),
        "win_rate": _float(stats, "matchesWinPct", 1),
        "kills": _int(stats, "kills"),
        "deaths": _int(stats, "deaths"),
        "assists": _int(stats, "assists"),
        "kd": _float(stats, "kDRatio"),
        "kda": _float(stats, "kDARatio"),
        "acs": _float(stats, "scorePerRound", 1),
        "adr": _float(stats, "damagePerRound", 1),
        "damage_delta_per_round": _float(stats, "damageDeltaPerRound", 1),
        "hs_pct": _float(stats, "headshotsPercentage", 1),
        "kast": _float(stats, "kAST", 1),
        "first_bloods": _int(stats, "firstBloods"),
        "first_deaths": _int(stats, "firstDeaths"),
        "aces": _int(stats, "aces"),
        "clutches": _int(stats, "clutches"),
        "mvps": _int(stats, "mVPs"),
        "rounds_played": _int(stats, "roundsPlayed"),
        "round_win_rate": _float(stats, "roundsWinPct", 1),
        "hours_played": None if seconds is None else round(seconds / 3600, 1),
    }


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
        win_rate=_float(stats, "matchesWinPct", 1),
    )


def _most_played(entries: list[TopEntry]) -> list[TopEntry] | None:
    ranked = sorted(entries, key=lambda entry: entry.matches or 0, reverse=True)
    return ranked[:_TOP_ENTRIES] or None


def parse_stats_bundle(segments: list[dict[str, Any]]) -> StatsBundle:
    """Split a segment list into the overall stat line, agents and maps."""
    overall: SeasonStats | None = None
    agents: list[AgentStats] = []
    maps: dict[str, MapStats] = {}
    maps_by_agent: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    agents_by_map: dict[str, list[TopEntry]] = {}

    for segment in segments or []:
        kind = segment.get("type")
        attrs = segment.get("attributes") or {}
        meta = segment.get("metadata") or {}
        stats = segment.get("stats") or {}
        name = meta.get("name") or "Unknown"
        if kind in ("season", "playlist") and overall is None:
            overall = SeasonStats(
                **_stat_line(stats),
                rank=_rank(stats.get("rank")),
                peak_rank=_rank(stats.get("peakRank")),
                percentiles=_percentiles(stats),
            )
        elif kind == "agent":
            agents.append(AgentStats(agent=name, role=meta.get("role"), **_stat_line(stats)))
        elif kind == "map":
            maps[attrs.get("key") or name] = MapStats(
                map=name,
                attack_round_win_rate=_float(stats, "attackRoundsWinPct", 1),
                defense_round_win_rate=_float(stats, "defenseRoundsWinPct", 1),
                attack_kd=_float(stats, "attackKDRatio"),
                defense_kd=_float(stats, "defenseKDRatio"),
                **_stat_line(stats),
            )
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

    def by_matches(row: AgentStats | MapStats) -> int:
        return row.matches or 0

    return StatsBundle(
        season_stats=overall,
        agents=sorted(agents, key=by_matches, reverse=True),
        maps=sorted(maps.values(), key=by_matches, reverse=True),
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
                season=meta.get("seasonName"),
                result=meta.get("result") or segment_meta.get("result"),
                rounds_won=_int(stats, "roundsWon"),
                rounds_lost=_int(stats, "roundsLost"),
                agent=segment_meta.get("agentName"),
                rank=_tier_name(stats.get("rank")),
                kills=_int(stats, "kills"),
                deaths=_int(stats, "deaths"),
                assists=_int(stats, "assists"),
                kd=_float(stats, "kdRatio"),
                acs=_float(stats, "scorePerRound", 1),
                adr=_float(stats, "damagePerRound", 1),
                hs_pct=_float(stats, "headshotsPercentage", 1),
                kast=_float(stats, "kAST", 1),
                damage=_int(stats, "damage"),
                combat_score=_int(stats, "score"),
                placement=_int(stats, "placement"),
            )
        )
    next_page = (data.get("metadata") or {}).get("next")
    return MatchPage(matches=entries, next_page=next_page if isinstance(next_page, int) else None)


def _match_player(segment: dict[str, Any]) -> MatchPlayer:
    attrs = segment.get("attributes") or {}
    meta = segment.get("metadata") or {}
    stats = segment.get("stats") or {}
    handle = (meta.get("platformInfo") or {}).get("platformUserHandle")
    party = meta.get("partyId")
    return MatchPlayer(
        riot_id=attrs.get("platformUserIdentifier") or handle or "Unknown",
        team=meta.get("teamId"),
        party_id=None if party is None else str(party),
        agent=meta.get("agentName"),
        rank=_tier_name(stats.get("rank")),
        kills=_int(stats, "kills"),
        deaths=_int(stats, "deaths"),
        assists=_int(stats, "assists"),
        kd=_float(stats, "kdRatio"),
        acs=_float(stats, "scorePerRound", 1),
        adr=_float(stats, "damagePerRound", 1),
        hs_pct=_float(stats, "hsAccuracy", 1),
        kast=_float(stats, "kast", 1),
        damage=_int(stats, "damage"),
        combat_score=_int(stats, "score"),
        first_kills=_int(stats, "firstKills"),
        first_deaths=_int(stats, "firstDeaths"),
        plants=_int(stats, "plants"),
        defuses=_int(stats, "defuses"),
        placement=_int(stats, "placement"),
    )


def parse_match(data: dict[str, Any]) -> MatchDetails:
    """Keep the scoreboard and drop the per-round segments, which are most of the payload."""
    attrs = data.get("attributes") or {}
    meta = data.get("metadata") or {}
    teams: list[MatchTeam] = []
    players: list[MatchPlayer] = []
    for segment in data.get("segments") or []:
        kind = segment.get("type")
        if kind == "team-summary":
            team_attrs = segment.get("attributes") or {}
            team_meta = segment.get("metadata") or {}
            stats = segment.get("stats") or {}
            teams.append(
                MatchTeam(
                    team=team_attrs.get("teamId") or team_meta.get("name") or "Unknown",
                    won=team_meta.get("hasWon"),
                    rounds_won=_int(stats, "roundsWon"),
                    rounds_lost=_int(stats, "roundsLost"),
                )
            )
        elif kind == "player-summary":
            players.append(_match_player(segment))

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
        teams=teams,
        players=players,
    )


def parse_search(data: Any) -> list[SearchResult]:
    return [
        SearchResult(riot_id=item["platformUserIdentifier"], status=item.get("status"))
        for item in data or []
        if isinstance(item, dict) and item.get("platformUserIdentifier")
    ]
