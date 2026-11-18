"""MCP server exposing Valorant statistics scraped from tracker.gg.

Personal use only. All data belongs to Tracker Network (tracker.gg).
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

import analysis
from cache import SQLiteCache
from config import get_settings
from models import MatchDetails, MatchEntry, MatchPage, MatchPlayer, PlayerProfile, StatsBundle
from scraper import (
    MatchNotFoundError,
    RiotId,
    TrackerError,
    TrackerScraper,
    TransientError,
    extract_match_id,
    normalize_playlist,
)
from scraper.utils import match_page_url, profile_page_url

settings = get_settings()
log = logging.getLogger("valorant_trn")

# Both are lazy: nothing touches the disk or starts a browser until a tool needs it.
cache = SQLiteCache(settings.cache_path)
scraper = TrackerScraper(settings)

# Part of every cache key. Bump it when the cached shapes change.
CACHE_VERSION = 1
MATCHES_PER_PAGE = 20
ALL_ACTS = {"all", "all acts", "career", "lifetime", "overall"}
SECTION_TTLS = {
    "season_stats": settings.cache_ttl_overview,
    "agents": settings.cache_ttl_agents,
    "maps": settings.cache_ttl_maps,
}
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
# What a teammate or opponent line carries in the match history. The full
# scoreboard stays available through get_match_details.
SCOREBOARD_KEYS = (
    "riot_id",
    "agent",
    "rank",
    "kills",
    "deaths",
    "assists",
    "kd",
    "acs",
    "adr",
    "hs_pct",
    "kast",
)


@asynccontextmanager
async def lifespan(_: MCPServer) -> AsyncIterator[None]:
    await cache.purge_expired()
    try:
        yield
    finally:
        await scraper.close()
        await cache.close()


mcp = MCPServer(
    "valorant-trn-stats",
    instructions=(
        "Personal-only Valorant statistics MCP powered by Tracker.gg scraping. Use the tools "
        "to fetch structured data, then reason over it for advanced questions (teammate "
        "analysis, map performance comparisons, etc.). Riot IDs look like Name#TAG. Results "
        "are cached, and tracker.gg is scraped slowly on purpose: the first load of a match "
        "scoreboard takes a few seconds, so ask for the smallest limit that answers the "
        "question. Percentages are on a 0-100 scale. Data belongs to Tracker Network."
    ),
    log_level=settings.log_level,
    lifespan=lifespan,
)

RiotIdArg = Annotated[
    str, Field(description='Riot ID in the form "Name#TAG", for example "Player#NA1".')
]
PlaylistArg = Annotated[
    str,
    Field(
        description="Game mode: competitive, unrated, swiftplay, spikerush, deathmatch, "
        "team-deathmatch or premier."
    ),
]
SeasonArg = Annotated[
    str,
    Field(
        description='"current" for the act tracker.gg shows by default, "all" for every act '
        'combined, or an act from the "seasons" list of get_player_overview, for example '
        '"E26: A5".'
    ),
]
RefreshArg = Annotated[
    bool, Field(description="Ignore the cache and scrape tracker.gg again. Use sparingly.")
]


@dataclass
class Loaded:
    value: Any
    fetched_at: float
    cached: bool
    warning: str | None = None


class Provenance:
    """Collects how fresh the pieces of one tool response are."""

    def __init__(self) -> None:
        self._oldest: float | None = None
        self._all_cached = True
        self.warnings: list[str] = []

    def add(self, loaded: Loaded) -> None:
        if self._oldest is None or loaded.fetched_at < self._oldest:
            self._oldest = loaded.fetched_at
        self._all_cached = self._all_cached and loaded.cached
        if loaded.warning and loaded.warning not in self.warnings:
            self.warnings.append(loaded.warning)

    def as_dict(self) -> dict[str, Any]:
        info: dict[str, Any] = {"source": "tracker.gg", "cached": self._all_cached}
        if self._oldest is not None:
            info["fetched_at"] = datetime.fromtimestamp(self._oldest, UTC).isoformat(
                timespec="seconds"
            )
        if self.warnings:
            info["warnings"] = self.warnings
        return info


@contextmanager
def tool_errors() -> Iterator[None]:
    """Report failures as ToolError; the SDK hides the message of anything else."""
    try:
        yield
    except ToolError:
        raise
    except TrackerError as exc:
        raise ToolError(str(exc)) from exc
    except Exception as exc:
        log.exception("unexpected failure in a tool")
        raise ToolError(f"Unexpected error: {type(exc).__name__}: {exc}") from exc


async def load(
    tool: str,
    riot_id: str,
    params: dict[str, Any],
    ttl: float,
    fetch: Callable[[], Awaitable[Any]],
    *,
    force: bool = False,
) -> Loaded:
    """Return the cached value, or scrape and store it.

    When tracker.gg cannot be reached an expired entry is served instead, with
    a warning, so a temporary block does not take the tools down.
    """
    key = {**params, "v": CACHE_VERSION}
    if not force:
        hit = await cache.get(tool, riot_id, key)
        if hit is not None:
            return Loaded(hit.value, hit.created_at, cached=True)
    try:
        value = await fetch()
    except TransientError as exc:
        stale = await cache.get(tool, riot_id, key, allow_stale=True)
        if stale is None:
            raise
        log.warning("serving stale %s data: %s", tool, exc)
        warning = f"Tracker.gg could not be reached, showing data cached earlier. ({exc})"
        return Loaded(stale.value, stale.created_at, cached=True, warning=warning)
    await cache.set(tool, value, ttl, riot_id, key)
    return Loaded(value, time.time(), cached=False)


def compact(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def scope(playlist: str, season_id: str | None) -> dict[str, Any]:
    return {"playlist": playlist, "season": season_id or "all"}


def section_ttl(section: str, season_id: str | None) -> float:
    ttl = SECTION_TTLS[section]
    # All-act totals move slowly and are the heaviest thing to download.
    return ttl if season_id else max(ttl, settings.cache_ttl_career)


def dump_section(bundle: StatsBundle, section: str) -> Any:
    if section == "season_stats":
        return bundle.season_stats.dump() if bundle.season_stats else None
    return [row.dump() for row in getattr(bundle, section)]


async def store_sections(
    rid: RiotId, playlist: str, season_id: str | None, bundle: StatsBundle, sections: Iterable[str]
) -> None:
    key = {**scope(playlist, season_id), "v": CACHE_VERSION}
    for section in sections:
        ttl = section_ttl(section, season_id)
        await cache.set(section, dump_section(bundle, section), ttl, rid.key, key)


async def load_profile(rid: RiotId, origin: Provenance, *, force: bool = False) -> PlayerProfile:
    async def fetch() -> dict[str, Any]:
        profile = await scraper.fetch_profile(rid)
        # The profile response already holds the default act's stats and agents.
        # Store them so the other tools do not have to scrape for the same thing.
        await store_sections(
            rid,
            profile.default_playlist,
            profile.default_season,
            profile.stats,
            ("season_stats", "agents"),
        )
        return profile.dump()

    loaded = await load("profile", rid.key, {}, settings.cache_ttl_overview, fetch, force=force)
    origin.add(loaded)
    return PlayerProfile.model_validate(loaded.value)


async def load_section(
    rid: RiotId,
    section: str,
    playlist: str,
    season_id: str | None,
    origin: Provenance,
    *,
    force: bool = False,
) -> Any:
    """One of season_stats, agents or maps for a playlist and act (None means all acts)."""

    async def fetch() -> Any:
        bundle = await scraper.fetch_stats(rid, playlist, season_id)
        # One response feeds all three sections, so keep the other two as well.
        others = [name for name in SECTION_TTLS if name != section]
        await store_sections(rid, playlist, season_id, bundle, others)
        return dump_section(bundle, section)

    ttl = section_ttl(section, season_id)
    loaded = await load(section, rid.key, scope(playlist, season_id), ttl, fetch, force=force)
    origin.add(loaded)
    return loaded.value


def squash(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").casefold())


def resolve_season(profile: PlayerProfile, season: str) -> str | None:
    """Map a season argument onto a tracker.gg act ID. None stands for all acts."""
    wanted = (season or "current").strip().casefold()
    if wanted in ALL_ACTS:
        return None
    if wanted in ("current", "default", "latest"):
        if profile.default_season:
            return profile.default_season
        return profile.seasons[0].id if profile.seasons else None
    for act in profile.seasons:
        if wanted == act.id.casefold() or squash(wanted) in (
            squash(act.name),
            squash(act.short_name),
        ):
            return act.id
    known = ", ".join(act.short_name or act.name or act.id for act in profile.seasons[:8])
    raise ToolError(f"Unknown season '{season}'. Use 'current', 'all' or one of: {known}.")


def season_label(profile: PlayerProfile, season_id: str | None) -> str:
    if season_id is None:
        return "All Acts"
    act = next((act for act in profile.seasons if act.id == season_id), None)
    return (act.short_name or act.name or season_id) if act else season_id


async def load_match_entries(
    rid: RiotId, playlist: str, limit: int, origin: Provenance, *, force: bool = False
) -> list[MatchEntry]:
    """The player's most recent matches, newest first, without scoreboards."""
    entries: dict[str, MatchEntry] = {}
    page: int | None = 0
    pages_left = limit // MATCHES_PER_PAGE + 2
    while page is not None and len(entries) < limit and pages_left > 0:
        pages_left -= 1

        async def fetch(page: int = page) -> dict[str, Any]:
            return (await scraper.fetch_match_page(rid, playlist, page)).dump()

        params = {"playlist": playlist, "page": page}
        loaded = await load(
            "match_list", rid.key, params, settings.cache_ttl_matches, fetch, force=force
        )
        origin.add(loaded)
        # History pages shift whenever a new match is played. Once one page has
        # been scraped the later ones must be too, or matches would be skipped.
        force = force or not loaded.cached
        result = MatchPage.model_validate(loaded.value)
        for entry in result.matches:
            entries.setdefault(entry.match_id, entry)
        if loaded.warning or not result.matches:
            break
        page = result.next_page
    return list(entries.values())[:limit]


async def load_match(match_id: str) -> MatchDetails:
    async def fetch() -> dict[str, Any]:
        return (await scraper.fetch_match(match_id)).dump()

    loaded = await load("match", "", {"id": match_id}, settings.cache_ttl_match_details, fetch)
    return MatchDetails.model_validate(loaded.value)


async def load_scoreboards(
    entries: list[MatchEntry], origin: Provenance, ctx: Context
) -> dict[str, MatchDetails]:
    """Scoreboards for the given matches, served from cache where possible."""
    boards: dict[str, MatchDetails] = {}
    for done, entry in enumerate(entries, 1):
        try:
            boards[entry.match_id] = await load_match(entry.match_id)
        except MatchNotFoundError:
            pass
        except TransientError as exc:
            # Do not keep knocking when tracker.gg is refusing requests.
            origin.warnings.append(
                f"Scoreboards were loaded for {len(boards)} of {len(entries)} matches only: {exc}"
            )
            break
        with contextlib.suppress(Exception):
            await ctx.report_progress(done, len(entries), f"Loaded match {done}/{len(entries)}")
    return boards


def player_row(row: MatchPlayer, party_id: str | None = None) -> dict[str, Any]:
    full = row.dump()
    data = {key: full[key] for key in SCOREBOARD_KEYS if key in full}
    if party_id is not None:
        data["in_party"] = row.party_id == party_id
    return data


def match_view(
    rid: RiotId, entry: MatchEntry, board: MatchDetails | None, include_opponents: bool
) -> dict[str, Any]:
    """One match from the player's point of view, with teammates when the scoreboard is known."""
    view = entry.dump()
    view.pop("combat_score", None)
    view["url"] = match_page_url(entry.match_id)
    if entry.rounds_won is not None and entry.rounds_lost is not None:
        view["score"] = f"{entry.rounds_won}-{entry.rounds_lost}"
    me = analysis.find_player(board, str(rid)) if board else None
    if board is None or me is None:
        view["scoreboard_available"] = False
        return view

    view.update(
        compact(
            {
                "duration_minutes": board.duration_minutes,
                "first_kills": me.first_kills,
                "first_deaths": me.first_deaths,
                "plants": me.plants,
                "defuses": me.defuses,
            }
        )
    )
    allies = [row for row in board.players if row.team == me.team and row is not me]
    view["party_size"] = 1 + sum(
        me.party_id is not None and row.party_id == me.party_id for row in allies
    )
    view["teammates"] = [player_row(row, me.party_id) for row in allies]
    if include_opponents:
        view["opponents"] = [player_row(row) for row in board.players if row.team != me.team]
    return view


@mcp.tool(annotations=READ_ONLY)
async def get_player_overview(
    riot_id: RiotIdArg,
    playlist: PlaylistArg = "competitive",
    season: SeasonArg = "current",
    include_career: Annotated[
        bool, Field(description="Also return all-act totals under 'career'.")
    ] = True,
    force_refresh: RefreshArg = False,
) -> dict[str, Any]:
    """Headline stats for a player: rank, peak rank and overall performance.

    Returns rank (tier, plus rr and leaderboard_rank for Immortal and above,
    the only ranks tracker.gg has a rating for), peak_rank, and a stats block
    with matches, wins, losses, win_rate, kd, kda, acs, adr, hs_pct, kast,
    kills, deaths, assists, first_bloods, aces, clutches and hours_played for
    the chosen act. "percentiles" compares the player with everyone tracked,
    and "career" holds the same stat block across all acts. "seasons" (newest
    first) and "playlists" list what the season and playlist arguments accept.
    """
    with tool_errors():
        rid = RiotId.parse(riot_id)
        mode = normalize_playlist(playlist)
        origin = Provenance()
        profile = await load_profile(rid, origin, force=force_refresh)
        season_id = resolve_season(profile, season)
        # A forced profile scrape has already refreshed the default act's stats.
        is_default = mode == profile.default_playlist and season_id == profile.default_season
        stats = await load_section(
            rid, "season_stats", mode, season_id, origin, force=force_refresh and not is_default
        )
        stats = dict(stats or {})

        career = None
        if include_career and season_id is not None:
            try:
                career = await load_section(rid, "season_stats", mode, None, origin)
            except TransientError as exc:
                origin.warnings.append(f"Career totals are unavailable right now: {exc}")
        if career:
            hidden = ("rank", "peak_rank", "percentiles")
            career = {k: v for k, v in career.items() if k not in hidden}

        rank = stats.pop("rank", None)
        peak_rank = stats.pop("peak_rank", None) or (
            profile.peak_rank.dump() if profile.peak_rank else None
        )
        percentiles = stats.pop("percentiles", None)
        return compact(
            {
                "riot_id": profile.riot_id or str(rid),
                "profile_url": profile_page_url(rid),
                "account_level": profile.account_level,
                "region": profile.region,
                "playlist": mode,
                "season": season_label(profile, season_id),
                "rank": rank,
                "peak_rank": peak_rank,
                "stats": stats or None,
                "percentiles": percentiles,
                "career": career or None,
                "note": None if stats else f"No {mode} games recorded for this act.",
                "seasons": [act.short_name or act.name or act.id for act in profile.seasons],
                "playlists": profile.playlists,
                **origin.as_dict(),
            }
        )


@mcp.tool(annotations=READ_ONLY)
async def get_player_agents(
    riot_id: RiotIdArg,
    playlist: PlaylistArg = "competitive",
    season: SeasonArg = "current",
    force_refresh: RefreshArg = False,
) -> dict[str, Any]:
    """Per-agent performance for a player, most played first.

    Each entry has agent, role, matches, wins, losses, win_rate, kd, kda, acs,
    adr, hs_pct, kast, kills, deaths, assists, hours_played and top_maps (the
    maps the agent was played on most). Use season="all" for lifetime numbers.
    """
    with tool_errors():
        return await _stat_rows(riot_id, "agents", playlist, season, force_refresh)


@mcp.tool(annotations=READ_ONLY)
async def get_player_maps(
    riot_id: RiotIdArg,
    playlist: PlaylistArg = "competitive",
    season: SeasonArg = "current",
    force_refresh: RefreshArg = False,
) -> dict[str, Any]:
    """Per-map performance for a player, most played first.

    Each entry has map, matches, wins, losses, win_rate, kd, acs, adr, hs_pct,
    kast, attack_round_win_rate, defense_round_win_rate, attack_kd, defense_kd
    and top_agents (the agents played most on that map). Use season="all" for
    lifetime numbers.
    """
    with tool_errors():
        return await _stat_rows(riot_id, "maps", playlist, season, force_refresh)


async def _stat_rows(
    riot_id: str, section: str, playlist: str, season: str, force: bool
) -> dict[str, Any]:
    rid = RiotId.parse(riot_id)
    mode = normalize_playlist(playlist)
    origin = Provenance()
    profile = await load_profile(rid, origin)
    season_id = resolve_season(profile, season)
    rows = await load_section(rid, section, mode, season_id, origin, force=force)
    return compact(
        {
            "riot_id": profile.riot_id or str(rid),
            "playlist": mode,
            "season": season_label(profile, season_id),
            section: rows or [],
            "note": None if rows else f"No {mode} games recorded for this scope.",
            **origin.as_dict(),
        }
    )


@mcp.tool(annotations=READ_ONLY)
async def get_recent_matches(
    riot_id: RiotIdArg,
    ctx: Context,
    limit: Annotated[
        int, Field(ge=1, le=50, description="How many matches to return, newest first.")
    ] = 20,
    playlist: PlaylistArg = "competitive",
    include_opponents: Annotated[
        bool, Field(description="Also list the five enemy players of every match.")
    ] = False,
    force_refresh: RefreshArg = False,
) -> dict[str, Any]:
    """Recent match history with the player's own line and every teammate's line.

    Each match has match_id, url, played_at, map, mode, result (victory or
    defeat), score, agent, kills, deaths, assists, kd, acs, adr, hs_pct, kast,
    damage, party_size and teammates. Every teammate entry has riot_id, agent,
    rank, kills, deaths, assists, kd, acs, adr, hs_pct, kast and in_party
    (true when they queued together with the player). Group by teammate
    riot_id and filter by map to compare teammates, or call
    get_teammate_stats, which does that aggregation.

    Scoreboards are scraped one match at a time on first use and cached for
    weeks afterwards, so a cold call takes a few seconds per match.
    """
    with tool_errors():
        rid = RiotId.parse(riot_id)
        mode = normalize_playlist(playlist)
        origin = Provenance()
        entries = await load_match_entries(rid, mode, limit, origin, force=force_refresh)
        boards = await load_scoreboards(entries, origin, ctx)
        matches = [
            match_view(rid, entry, boards.get(entry.match_id), include_opponents)
            for entry in entries
        ]
        return {
            "riot_id": str(rid),
            "playlist": mode,
            "count": len(matches),
            "matches": matches,
            **origin.as_dict(),
        }


@mcp.tool(annotations=READ_ONLY)
async def get_match_details(
    match_id_or_url: Annotated[
        str, Field(description="A match ID (UUID) or a tracker.gg match URL.")
    ],
) -> dict[str, Any]:
    """Full scoreboard of one match: both teams and all ten players.

    Returns map, mode, played_at, duration_minutes, rounds and a list of teams
    with won, rounds_won, rounds_lost and players. Each player has riot_id,
    agent, rank, party_id (players sharing one queued together), kills,
    deaths, assists, kd, acs, adr, hs_pct, kast, damage, combat_score,
    first_kills, first_deaths, plants, defuses and placement.
    """
    with tool_errors():
        match_id = extract_match_id(match_id_or_url)
        board = await load_match(match_id)
        result = board.dump()
        players = result.pop("players", [])
        result["url"] = match_page_url(match_id)
        if board.teams:
            for team in result["teams"]:
                team["players"] = [
                    {k: v for k, v in row.items() if k != "team"}
                    for row in players
                    if row.get("team") == team["team"]
                ]
        else:
            result["players"] = players
        result["source"] = "tracker.gg"
        return result


@mcp.tool(annotations=READ_ONLY)
async def get_teammate_stats(
    riot_id: RiotIdArg,
    ctx: Context,
    map_name: Annotated[
        str | None,
        Field(description='Only consider teammates seen on this map, for example "Split".'),
    ] = None,
    limit_matches: Annotated[
        int, Field(ge=1, le=100, description="How many recent matches to analyse.")
    ] = 30,
    playlist: PlaylistArg = "competitive",
    top: Annotated[int, Field(ge=1, le=25, description="How many teammates to return.")] = 10,
) -> dict[str, Any]:
    """Most played teammates over the player's recent matches, with their stats.

    Teammates are ordered by games played together across all analysed
    matches, and "rank" is that position, so the first five entries are the
    five most played teammates. Each has games_together, games_in_party,
    wins, losses, win_rate, kills, deaths, assists, kd, acs, adr, hs_pct,
    kast, agents, by_map (games, win_rate, kd and acs per map),
    your_record_with and your_record_without (the player's own results with
    and without that teammate).

    With map_name, only teammates who shared that map are listed and each gets
    an on_map block with their numbers on it. For example "which of my five
    most played teammates has the lowest KD on Split" is answered by calling
    this with map_name="Split" and comparing on_map.kd among rank 1 to 5.

    A cold call scrapes one scoreboard per match at a few seconds each. Later
    calls reuse the cache.
    """
    with tool_errors():
        rid = RiotId.parse(riot_id)
        mode = normalize_playlist(playlist)
        origin = Provenance()
        entries = await load_match_entries(rid, mode, limit_matches, origin)
        boards = await load_scoreboards(entries, origin, ctx)
        ordered = [boards[entry.match_id] for entry in entries if entry.match_id in boards]
        summary = analysis.teammate_stats(str(rid), ordered, map_name, top)
        return {"riot_id": str(rid), "playlist": mode, **summary, **origin.as_dict()}


@mcp.tool(annotations=READ_ONLY)
async def search_player(
    query: Annotated[
        str, Field(min_length=2, description="Start of a Riot ID, for example a player name.")
    ],
) -> dict[str, Any]:
    """Find Riot IDs known to tracker.gg that match a name.

    Useful when the tagline is unknown. Returns up to 20 results with riot_id
    and a short activity status.
    """
    with tool_errors():
        text = query.strip()

        async def fetch() -> list[dict[str, Any]]:
            return [result.dump() for result in await scraper.search(text)]

        params = {"query": text.casefold()}
        loaded = await load("search", "", params, settings.cache_ttl_search, fetch)
        origin = Provenance()
        origin.add(loaded)
        return {
            "query": text,
            "count": len(loaded.value),
            "results": loaded.value,
            **origin.as_dict(),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Valorant stats MCP server (personal use only)")
    parser.add_argument(
        "--transport", choices=("stdio", "streamable-http"), default=settings.transport
    )
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        mcp.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
