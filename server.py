"""MCP server exposing Valorant statistics scraped from tracker.gg.

Personal use only. All data belongs to Tracker Network (tracker.gg).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import json
import logging
import re
import time
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, NamedTuple, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

import analysis
from cache import SQLiteCache
from config import get_settings
from models import (
    Aggregate,
    GameAct,
    GameData,
    MatchDetails,
    MatchEntry,
    MatchPage,
    MatchPlayer,
    PlayerProfile,
    PremierTeam,
    Round,
    StatsBundle,
)
from scraper import (
    RiotId,
    TrackerError,
    TrackerScraper,
    TransientError,
    extract_match_id,
    normalize_playlist,
)
from scraper import replay as replays
from scraper.utils import act_number, match_page_url, profile_page_url, same_player

settings = get_settings()
log = logging.getLogger("valorant_trn")
Found = TypeVar("Found")

# Both are lazy: nothing touches the disk or starts a browser until a tool needs it.
cache = SQLiteCache(settings.cache_path)
tracker = TrackerScraper(settings)

# Part of every cache key. Bump it when the cached shapes change.
CACHE_VERSION = 4
MATCHES_PER_PAGE = 20
# Agents, maps, weapons and acts change with a game patch at most. A copy older
# than a day is still fetched again before a name is reported as unknown.
GAME_DATA_TTL = 7 * 86400
GAME_DATA_RECHECK = 86400
REGIONS = ("na", "eu", "ap", "kr", "br", "latam")
# Our stat name -> the key tracker.gg keeps a day-by-day history under.
HISTORY_STATS = {
    "rank": "competitiveTier",
    "kd": "kDRatio",
    "kda": "kDARatio",
    "acs": "scorePerRound",
    "adr": "damagePerRound",
    "damage_delta_per_round": "damageDeltaPerRound",
    "hs_pct": "headshotsPercentage",
    "kast": "kAST",
    "win_rate": "matchesWinPct",
    "round_win_rate": "roundsWinPct",
    "matches": "matchesPlayed",
    "kills": "kills",
    "deaths": "deaths",
    "assists": "assists",
    "first_kills": "firstBloods",
    "first_deaths": "firstDeaths",
    "clutches": "clutches",
    "aces": "aces",
    "plants": "plants",
    "defuses": "defuses",
    "econ_rating": "econRating",
}
ALL_ACTS = {"all", "all acts", "career", "lifetime", "overall"}
SECTION_TTLS = {
    "season_stats": settings.cache_ttl_overview,
    "agents": settings.cache_ttl_agents,
    "roles": settings.cache_ttl_agents,
    "weapons": settings.cache_ttl_agents,
    "maps": settings.cache_ttl_maps,
}
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
# For tools that only look at files on this computer.
LOCAL = ToolAnnotations(read_only_hint=True, open_world_hint=False)
# The headline numbers of a stat row, and the fields that label one. The rest
# of tracker.gg's stat sheet is returned with detailed=True.
CORE_STATS = frozenset(
    {
        "matches",
        "wins",
        "losses",
        "ties",
        "win_rate",
        "kills",
        "deaths",
        "assists",
        "kd",
        "kda",
        "acs",
        "adr",
        "damage_delta_per_round",
        "hs_pct",
        "kast",
        "first_kills",
        "first_deaths",
        "aces",
        "clutches",
        "mvps",
        "rounds",
        "round_win_rate",
        "hours_played",
        "tracker_score",
    }
)
ROW_LABELS = frozenset({"agent", "role", "map", "pick_rate", "top_maps", "top_agents"})
TOP_ENTRY_KEYS = ("name", "matches", "win_rate")
# How many agents or maps a detailed call returns when none are named, and how
# many matches: a full stat sheet is long, and a table of them swamps the reader.
DETAILED_ROWS = 5
# Below this many matches a comparison says that a player's numbers are thin.
FEW_MATCHES = 5
DETAILED_MATCHES = 8
PREMIER_MATCHES = 20
# Rows are left off the end of a list once an answer passes this many characters
# of JSON, roughly 18,000 tokens. MCP clients reject or cut off answers not far
# above that.
ANSWER_BUDGET = 48_000
# Section -> the field that names a row in it.
ROW_NAMES = {"agents": "agent", "maps": "map", "weapons": "weapon"}
# What a teammate or opponent line carries in the match history by default.
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
    "first_kills",
    "first_deaths",
)
# The large parts of a scoreboard row and of a history row, kept for detailed=True.
SPLIT_KEYS = ("attack", "defense", "buys", "weapon_kills", "duels", "performance_parts")
# What a kill in the round log carries unless detail is asked for.
KILL_KEYS = ("time", "killer", "victim", "weapon")
HISTORY_DETAIL = ("tracker_score", "last_deaths", "suicides", "shots_dealt")


@asynccontextmanager
async def lifespan(_: MCPServer) -> AsyncIterator[None]:
    await cache.purge_expired()
    try:
        yield
    finally:
        await tracker.close()
        await cache.close()


mcp = MCPServer(
    "valorant-trn-stats",
    instructions=(
        "Personal-only Valorant statistics MCP powered by Tracker.gg scraping. Use the tools "
        "to fetch structured data, then reason over it for advanced questions (teammate "
        "analysis, map performance comparisons, etc.). Riot IDs look like Name#TAG. Results "
        "are cached, and tracker.gg is scraped slowly on purpose: the first load of a match "
        "scoreboard takes a few seconds, so ask for the smallest limit that answers the "
        "question. Percentages are on a 0-100 scale. Data belongs to Tracker Network.\n\n"
        "Most tools return the headline numbers by default and the full stat sheet with "
        "detailed=true. Fields tracker.gg has no value for are left out. Stat names are the "
        "same in every tool: acs is combat score per "
        "round, adr damage per round, kast the share of rounds with a kill, assist, survival "
        "or trade. first_kills and first_deaths count rounds in which the player got the "
        "first kill or was the first of all ten to die, team_first_deaths rounds in which "
        "they were the first of their own team to die, and entry_success_rate is first kills "
        "as a share of the rounds they opened either way. deaths_traded are deaths a teammate "
        "avenged and trade_kills kills that avenged a teammate. multi_kills are rounds with "
        "three or more kills, and double_kills, triple_kills and quadra_kills rounds with "
        "exactly two, three and four. aces are rounds with five kills on a scoreboard and "
        "tracker.gg's own ace count on profile rows. clutches_by_size is keyed 1v1 to 1v5. "
        "econ_rating "
        "is damage per 1000 credits spent, tracker_score tracker.gg's rating out of 1000, "
        "and ability_casts is keyed by ability slot (c, q, e, x). attack and defense blocks "
        "split a player's numbers by side, and buys by tracker.gg's buy type (pistol, eco, "
        "semi, full). get_match_rounds tells one match round by round, kill by kill, and "
        "get_round_stats sums up how rounds go over many matches. get_top_teammates and "
        "get_daily_stats read tracker.gg's own totals, which cost one request and reach "
        "back months, and get_stat_history follows one stat day by day for about a month. "
        "avg_placement is the average position among the "
        "ten players of a match by tracker.gg's performance score, 1 being best. "
        "compare_players ranks players by a weighted score and shows how each stat counted."
        "\n\n"
        'Every answer is {"data": ...}, and answers built on tracker.gg data also carry '
        '"meta". meta.source is "live" when something was scraped for this answer and '
        '"cache" when all of it came from the cache, '
        "meta.cached_at and meta.age_seconds say when the data was scraped, and "
        "meta.ttl_remaining_seconds how long until it is due for a refresh. When "
        "meta.is_stale is true the scrape failed and older data was served instead: the "
        "answer then starts with a warning, and you must tell the user that the numbers may "
        "be outdated and how old they are."
        "\n\n"
        "list_local_replays, analyze_replay and get_utility_effectiveness are placeholders "
        "for replay files on this computer. Reading replays is not built yet, and replays "
        "of other players cannot be fetched at all."
    ),
    log_level=settings.log_level,
    lifespan=lifespan,
)


def envelope(answer: dict[str, Any]) -> CallToolResult:
    """A tool's answer as it goes out: {"data": ..., "meta": ...} in compact JSON.

    Left to the SDK the text is indented, and about a third of it is whitespace.
    meta says how fresh the data is. Answers that have nothing to do with
    tracker.gg come without it.
    """
    meta = answer.get("meta")
    data: dict[str, Any] = {"data": {k: v for k, v in answer.items() if k != "meta"}}
    if meta is not None:
        data["meta"] = meta
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    content = [TextContent(type="text", text=text)]
    if meta and meta["is_stale"]:
        # Said in words first, so that a stale answer cannot pass for a fresh one.
        content.insert(0, TextContent(type="text", text=meta["warnings"][0]))
    return CallToolResult(content=content, structured_content=data)


Handler = Callable[..., Awaitable[dict[str, Any]]]


def tool(handler: Handler | None = None, *, annotations: ToolAnnotations = READ_ONLY) -> Any:
    """Register a read-only tool whose answer goes out through envelope()."""

    def register(handler: Handler) -> Callable[..., Awaitable[CallToolResult]]:
        @functools.wraps(handler)
        async def answer(*args: Any, **kwargs: Any) -> CallToolResult:
            return envelope(await handler(*args, **kwargs))

        return mcp.tool(annotations=annotations)(answer)

    return register if handler is None else register(handler)


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
MapArg = Annotated[str | None, Field(description='Only matches on this map, for example "Split".')]
AgentArg = Annotated[
    str | None,
    Field(description='Only matches the player played on this agent, for example "Jett".'),
]
RegionArg = Annotated[str, Field(description="Region: na, eu, ap, kr, br or latam.")]
ActArg = Annotated[str, Field(description='"current", or an act such as "E26: A5".')]
RiotIdsArg = Annotated[
    list[str],
    Field(
        min_length=2, max_length=10, description="Two to ten Riot IDs to rank against each other."
    ),
]
WeightsArg = Annotated[
    dict[str, float] | None,
    Field(
        description='How much each stat counts, for example {"acs": 0.4, "kd": 0.3, "kast": 0.2, '
        '"adr": 0.1}, which is also what is used when this is left out. Any numbers that are '
        "not negative; they are scaled to add up to 1. Stats that can be weighed: "
        + ", ".join(analysis.COMPARABLE)
        + "."
    ),
]
DetailedArg = Annotated[
    bool,
    Field(
        description="Return the full stat sheet instead of the headline numbers. The answer "
        "gets several times longer, so only ask when the question needs it."
    ),
]


# Not a dataclass: "mcp run" imports this file without registering the module,
# which dataclasses cannot cope with when annotations are strings.
class Loaded(NamedTuple):
    value: Any
    fetched_at: float
    cached: bool
    warning: str | None = None
    expires_at: float | None = None
    # Served although a fresh copy was wanted, because the scrape for it failed.
    # warning then holds what went wrong.
    stale: bool = False


def ago(seconds: float) -> str:
    """An age in words, for example "18 days ago"."""
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = int(seconds // size)
            return f"{count} {unit}{'' if count == 1 else 's'} ago"
    return "less than a minute ago"


class Provenance:
    """Collects how fresh the pieces of one tool response are."""

    def __init__(self) -> None:
        self._pieces = 0
        self._scraped = 0
        # Two of each: over the pieces whose age matters, and over all of them.
        self._oldest: list[float | None] = [None, None]
        self._expires: list[float | None] = [None, None]
        self._stale: list[tuple[float, str]] = []
        self.warnings: list[str] = []

    def add(self, loaded: Loaded, *, undated: bool = False) -> None:
        """Record one piece. undated is for data that never changes, whose age says nothing."""
        self._pieces += 1
        self._scraped += not loaded.cached
        # A stale piece is past its lifetime, so its age matters whatever it is.
        dated = loaded.stale or not undated
        for index in range(0 if dated else 1, 2):
            oldest, expires = self._oldest[index], self._expires[index]
            if oldest is None or loaded.fetched_at < oldest:
                self._oldest[index] = loaded.fetched_at
            if loaded.expires_at is not None and (expires is None or loaded.expires_at < expires):
                self._expires[index] = loaded.expires_at
        if loaded.stale:
            self._stale.append((loaded.fetched_at, loaded.warning or "the scrape failed."))
        elif loaded.warning and loaded.warning not in self.warnings:
            self.warnings.append(loaded.warning)

    def as_dict(self) -> dict[str, Any]:
        """The "meta" block of a tool answer."""
        now = time.time()
        everything = self._oldest[0] is None
        oldest = self._oldest[1] if everything else self._oldest[0]
        expires = self._expires[1] if everything else self._expires[0]
        from_cache = self._pieces > 0 and not self._scraped
        reason = "scrape_failed" if self._stale else "within_ttl" if from_cache else None
        info: dict[str, Any] = {
            "provider": "tracker.gg",
            "source": "cache" if from_cache else "live",
            "cached_at": None,
            "age_seconds": None,
            "is_stale": bool(self._stale),
            "stale_reason": reason,
            "ttl_remaining_seconds": None if expires is None else max(0, int(expires - now)),
        }
        if oldest is not None:
            info["cached_at"] = datetime.fromtimestamp(oldest, UTC).isoformat(timespec="seconds")
            info["age_seconds"] = max(0, int(now - oldest))
        warnings = list(self.warnings)
        if self._stale:
            scraped, failure = min(self._stale)
            # "Part" only when the rest of the answer was scraped just now.
            part = "Part of this data is" if self._scraped else "This data is"
            warnings.insert(
                0,
                f"\u26a0\ufe0f {part} from the cache and may be outdated (scraped "
                f"{ago(now - scraped)}). A fresh copy could not be fetched: {failure}",
            )
        if warnings:
            info["warnings"] = warnings
        return {"meta": info}

    def include(self, other: Provenance) -> None:
        """Take over the pieces another one has collected."""
        self._pieces += other._pieces
        self._scraped += other._scraped
        for index in range(2):
            for ours, theirs in ((self._oldest, other._oldest), (self._expires, other._expires)):
                known = [value for value in (ours[index], theirs[index]) if value is not None]
                ours[index] = min(known, default=None)
        self._stale += other._stale
        self.warnings += [text for text in other.warnings if text not in self.warnings]

    @property
    def stale(self) -> bool:
        return bool(self._stale)


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


# One lock per thing being scraped, so overlapping tool calls scrape it once.
# An entry disappears as soon as nobody holds or waits for its lock.
_in_flight: weakref.WeakValueDictionary[tuple[str, str, str], asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


async def load(
    tool: str,
    riot_id: str,
    params: dict[str, Any],
    ttl: float,
    fetch: Callable[[], Awaitable[Any]],
    *,
    force: bool = False,
    not_before: float | None = None,
    allow_stale: bool = True,
    flight: str | None = None,
) -> Loaded:
    """Return the cached value, or scrape and store it.

    Calls that need the same scrape wait for one another instead of repeating
    it. flight names that scrape when one response fills several cache
    entries. An entry stored before not_before counts as a miss. When
    tracker.gg cannot be reached an expired entry is served instead, with a
    warning, so a temporary block does not take the tools down.
    """
    key = {**params, "v": CACHE_VERSION}

    async def cached(newer_than: float | None) -> Loaded | None:
        hit = await cache.get(tool, riot_id, key)
        if hit is None or (newer_than is not None and hit.created_at < newer_than):
            return None
        return Loaded(hit.value, hit.created_at, cached=True, expires_at=hit.expires_at)

    if not force and (found := await cached(not_before)):
        return found
    asked_at = time.time()
    lock_key = (flight or tool, riot_id, json.dumps(key, sort_keys=True))
    lock = _in_flight.get(lock_key) or _in_flight.setdefault(lock_key, asyncio.Lock())
    async with lock:
        # Whoever held the lock may just have scraped exactly this.
        if found := await cached(asked_at if force else not_before):
            return found
        try:
            value = await fetch()
        except TransientError as exc:
            stale = await cache.get(tool, riot_id, key, allow_stale=True) if allow_stale else None
            if stale is None:
                raise
            log.warning("serving stale %s data: %s", tool, exc)
            return Loaded(
                stale.value,
                stale.created_at,
                cached=True,
                warning=str(exc),
                expires_at=stale.expires_at,
                stale=True,
            )
        await cache.set(tool, value, ttl, riot_id, key)
        now = time.time()
        return Loaded(value, now, cached=False, expires_at=now + ttl)


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
        profile = await tracker.fetch_profile(rid)
        # The profile response already holds the default act's stats and agents.
        # Store them so the other tools do not have to scrape for the same thing.
        if profile.default_season:
            await store_sections(
                rid,
                profile.default_playlist,
                profile.default_season,
                profile.stats,
                ("season_stats", "agents", "roles"),
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
    """One section of SECTION_TTLS for a playlist and act (None means all acts)."""

    async def fetch() -> Any:
        bundle = await tracker.fetch_stats(rid, playlist, season_id)
        # One response feeds every section, so keep the others as well.
        others = [name for name in SECTION_TTLS if name != section]
        await store_sections(rid, playlist, season_id, bundle, others)
        return dump_section(bundle, section)

    ttl = section_ttl(section, season_id)
    loaded = await load(
        section, rid.key, scope(playlist, season_id), ttl, fetch, force=force, flight="stats"
    )
    origin.add(loaded)
    return loaded.value


def squash(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").casefold())


def stat_view(row: dict[str, Any], detailed: bool) -> dict[str, Any]:
    """A stat row as the tools return it: the whole sheet, or the headline numbers."""
    if detailed:
        return row
    view = {key: value for key, value in row.items() if key in CORE_STATS or key in ROW_LABELS}
    for key in ("top_maps", "top_agents"):
        if key in view:
            view[key] = [
                {name: entry[name] for name in TOP_ENTRY_KEYS if name in entry}
                for entry in view[key]
            ]
    return view


def fit(rows: list[dict[str, Any]], budget: int = ANSWER_BUDGET) -> list[dict[str, Any]]:
    """The leading rows that fit in one answer. The first row is always kept."""
    used = 0
    for count, row in enumerate(rows):
        used += len(json.dumps(row, separators=(",", ":")))
        if used > budget and count:
            return rows[:count]
    return rows


def side_headlines(row: dict[str, Any]) -> dict[str, Any]:
    """Round win rate and K/D per side, as flat keys for a row without the side blocks."""
    flat = {}
    for side in ("attack", "defense"):
        split = row.get(side) or {}
        flat[f"{side}_round_win_rate"] = split.get("round_win_rate")
        flat[f"{side}_kd"] = split.get("kd")
    return compact(flat)


def resolve_season(profile: PlayerProfile, season: str) -> str | None:
    """Map a season argument onto a tracker.gg act ID. None stands for all acts."""
    wanted = (season or "current").strip().casefold()
    if wanted in ALL_ACTS:
        return None
    if wanted in ("current", "default", "latest"):
        if profile.default_season:
            return profile.default_season
        return profile.seasons[0].id if profile.seasons else None
    # Tracker.gg writes one act as "E26: A6", "V26: A6" or "V26: ACT VI" depending
    # on the page, so compare the numbers as well as the spelling.
    name, number = squash(wanted), act_number(wanted)
    for act in profile.seasons:
        labels = (act.name, act.short_name)
        if (
            wanted == act.id.casefold()
            or (name and name in map(squash, labels))
            or (number and number in map(act_number, labels))
        ):
            return act.id
    known = ", ".join(act.short_name or act.name or act.id for act in profile.seasons)
    raise ToolError(f"Unknown season '{season}'. Use 'current', 'all' or one of: {known}.")


def season_label(profile: PlayerProfile, season_id: str | None) -> str:
    if season_id is None:
        return "All Acts"
    act = next((act for act in profile.seasons if act.id == season_id), None)
    return (act.short_name or act.name or season_id) if act else season_id


async def load_match_entries(
    rid: RiotId,
    playlist: str,
    limit: int,
    origin: Provenance,
    *,
    force: bool = False,
    filters: dict[str, str] | None = None,
) -> list[MatchEntry]:
    """The player's most recent matches, newest first, without scoreboards.

    filters narrows them on tracker.gg's side: season_id, map_id and agent_id.
    """
    filters = filters or {}
    entries: dict[str, MatchEntry] = {}
    page: int | None = 0
    previous: float | None = None
    pages_left = limit // MATCHES_PER_PAGE + 2
    while page is not None and len(entries) < limit and pages_left > 0:
        pages_left -= 1

        async def fetch(page: int = page) -> dict[str, Any]:
            return (await tracker.fetch_match_page(rid, playlist, page, **filters)).dump()

        try:
            # History pages shift whenever a new match is played, so a page is only
            # used if it was stored no earlier than the one before it. Otherwise
            # the matches that moved across the boundary would be skipped.
            loaded = await load(
                "match_list",
                rid.key,
                {"playlist": playlist, "page": page, **filters},
                settings.cache_ttl_matches,
                fetch,
                force=force and page == 0,
                not_before=previous,
                allow_stale=page == 0,
            )
        except TransientError as exc:
            if not entries:
                raise
            origin.warnings.append(
                f"Only the {len(entries)} most recent matches could be listed: {exc}"
            )
            break
        origin.add(loaded)
        previous = loaded.fetched_at
        result = MatchPage.model_validate(loaded.value)
        for entry in result.matches:
            entries.setdefault(entry.match_id, entry)
        if loaded.warning or not result.matches:
            break
        page = result.next_page
    return list(entries.values())[:limit]


async def load_game_data(
    origin: Provenance | None = None, *, newer_than: float | None = None, undated: bool = False
) -> GameData:
    async def fetch() -> dict[str, Any]:
        return (await tracker.fetch_game_data()).dump()

    loaded = await load("game_data", "", {}, GAME_DATA_TTL, fetch, not_before=newer_than)
    game = GameData.model_validate(loaded.value)
    now = datetime.now(UTC).isoformat()
    current = next((act for act in game.acts if act.starts and act.starts <= now), None)
    if newer_than is None and current and current.ends and current.ends < now:
        # The act these lists call current is over, so they predate the one being played.
        return await load_game_data(origin, newer_than=time.time() - 3600, undated=undated)
    if origin:
        origin.add(loaded, undated=undated)
    return game


async def look_up(find: Callable[[GameData], Found], origin: Provenance | None = None) -> Found:
    """Find something in the reference lists, fetching them again once if it is not there.

    An agent, map or act may have come out since the lists were stored. The
    lists only name things here, so their age is left out of the answer's, but
    a copy that could not be refreshed still marks the answer as stale.
    """
    try:
        return find(await load_game_data(origin, undated=True))
    except ToolError:
        recent = time.time() - GAME_DATA_RECHECK
        return find(await load_game_data(origin, newer_than=recent, undated=True))


async def load_aggregate(rid: RiotId, playlist: str, origin: Provenance) -> Aggregate:
    async def fetch() -> dict[str, Any]:
        return (await tracker.fetch_aggregate(rid, playlist)).dump()

    params = {"playlist": playlist}
    loaded = await load("aggregate", rid.key, params, settings.cache_ttl_matches, fetch)
    origin.add(loaded)
    return Aggregate.model_validate(loaded.value)


def named(rows: list[Any], name: str, kind: str) -> Any:
    """The agent or map called name in tracker.gg's reference list."""
    found = next((row for row in rows if squash(row.name) == squash(name) and row.uuid), None)
    if found is None:
        known = ", ".join(row.name for row in rows if row.uuid)
        raise ToolError(f"Unknown {kind} '{name}'. Tracker.gg knows: {known}.")
    return found


def find_act(game: GameData, season: str) -> GameAct:
    """An act from the reference list, by name, or the one being played for "current"."""
    wanted = (season or "current").strip().casefold()
    if wanted in ("current", "default", "latest"):
        now = datetime.now(UTC).isoformat()
        started = [act for act in game.acts if act.starts and act.starts <= now]
        if started:
            return started[0]
    number = act_number(wanted)
    for act in game.acts:
        if wanted == act.id.casefold() or (number and number == act_number(act.name)):
            return act
    known = ", ".join(act.name for act in game.acts[:8])
    raise ToolError(f"Unknown act '{season}'. Use 'current' or one of: {known} and older.")


async def match_filters(
    origin: Provenance, map_name: str | None, agent: str | None, season: str | None = None
) -> tuple[dict[str, str], dict[str, str]]:
    """Tracker.gg's IDs for the filters asked for, and the proper names to report back."""
    filters: dict[str, str] = {}
    labels: dict[str, str] = {}
    if map_name:
        found = await look_up(lambda game: named(game.maps, map_name, "map"), origin)
        filters["map_id"], labels["map_filter"] = found.uuid, found.name
    if agent:
        found = await look_up(lambda game: named(game.agents, agent, "agent"), origin)
        filters["agent_id"], labels["agent_filter"] = found.uuid, found.name
    if season and season.strip().casefold() not in ALL_ACTS:
        act = await look_up(lambda game: find_act(game, season), origin)
        filters["season_id"], labels["season_filter"] = act.id, act.name
    return filters, labels


async def load_match(match_id: str) -> Loaded:
    async def fetch() -> dict[str, Any]:
        return (await tracker.fetch_match(match_id)).dump()

    return await load("match", "", {"id": match_id}, settings.cache_ttl_match_details, fetch)


async def load_scoreboards(
    entries: list[MatchEntry], origin: Provenance, ctx: Context
) -> dict[str, MatchDetails]:
    """Scoreboards for the given matches, served from cache where possible."""
    boards: dict[str, MatchDetails] = {}
    unavailable = 0
    for done, entry in enumerate(entries, 1):
        try:
            loaded = await load_match(entry.match_id)
        except TransientError as exc:
            # Do not keep knocking when tracker.gg is refusing requests.
            origin.warnings.append(
                f"Scoreboards were loaded for {len(boards)} of {len(entries)} matches only: {exc}"
            )
            break
        except TrackerError:
            # Tracker.gg has no scoreboard for this match. The others are still worth having.
            unavailable += 1
        else:
            origin.add(loaded, undated=True)
            boards[entry.match_id] = MatchDetails.model_validate(loaded.value)
        with contextlib.suppress(Exception):
            await ctx.report_progress(done, len(entries), f"Loaded match {done}/{len(entries)}")
    if unavailable:
        origin.warnings.append(f"Tracker.gg has no scoreboard for {unavailable} of the matches.")
    return boards


def player_row(
    row: MatchPlayer, party_id: str | None = None, *, detailed: bool = False
) -> dict[str, Any]:
    """A scoreboard line: the core numbers, or with detailed everything but the splits."""
    full = row.dump()
    if detailed:
        data = {k: v for k, v in full.items() if k not in ("team", "party_id", *SPLIT_KEYS)}
    else:
        data = {key: full[key] for key in SCOREBOARD_KEYS if key in full}
    if party_id is not None:
        data["in_party"] = row.party_id == party_id
    return data


def match_view(
    rid: RiotId,
    entry: MatchEntry,
    board: MatchDetails | None,
    include_opponents: bool,
    detailed: bool = False,
) -> dict[str, Any]:
    """One match from the player's point of view, with teammates when the scoreboard is known."""
    view = entry.dump()
    if not detailed:
        for key in ("combat_score", *HISTORY_DETAIL):
            view.pop(key, None)
    view["url"] = match_page_url(entry.match_id)
    if entry.rounds_won is not None and entry.rounds_lost is not None:
        view["score"] = f"{entry.rounds_won}-{entry.rounds_lost}"
    me = analysis.find_player(board, str(rid), entry) if board else None
    if board is None or me is None:
        view["scoreboard_available"] = False
        return view

    if board.duration_minutes is not None:
        view["duration_minutes"] = board.duration_minutes
    if detailed:
        mine = player_row(me, detailed=True)
        view.update({key: value for key, value in mine.items() if key != "riot_id"})
    else:
        view.update(
            compact(
                {
                    "first_kills": me.first_kills,
                    "first_deaths": me.first_deaths,
                    "plants": me.plants,
                    "defuses": me.defuses,
                }
            )
        )

    def is_ally(row: MatchPlayer) -> bool:
        # Free-for-all modes have no teams, so everybody else is an opponent.
        return me.team is not None and row.team == me.team

    others = [row for row in board.players if row is not me]
    allies = [row for row in others if is_ally(row)]
    view["party_size"] = 1 + sum(
        me.party_id is not None and row.party_id == me.party_id for row in allies
    )
    view["teammates"] = [player_row(row, me.party_id, detailed=detailed) for row in allies]
    if include_opponents:
        view["opponents"] = [
            player_row(row, detailed=detailed) for row in others if not is_ally(row)
        ]
    return view


def round_view(
    entry: Round,
    score: dict[str, int],
    team_of: dict[str, str | None],
    focus: str | None,
    detailed: bool,
) -> dict[str, Any]:
    """One round of the log: the result, both teams' economy and the kills in order."""
    data = entry.dump()
    kills = data.pop("kills", [])
    lines = data.pop("players", [])
    by_team: dict[str, list[dict[str, Any]]] = {}
    for line, row in zip(lines, entry.players or [], strict=True):
        team = team_of.get(row.riot_id)
        if team:
            by_team.setdefault(team, []).append(line)
    economy = {}
    for team in by_team:
        rows = [row for row in entry.players or [] if team_of.get(row.riot_id) == team]
        economy[team] = compact(
            {
                "buy": analysis.team_buy(rows),
                "loadout_value": sum(row.loadout_value or 0 for row in rows),
                "spent": sum(row.spent or 0 for row in rows),
            }
        )
    if not detailed:
        kills = [{key: kill[key] for key in KILL_KEYS if key in kill} for kill in kills]
        for event in ("plant", "defuse"):
            data.get(event, {}).pop("at", None)
    view = {**data, "score": score, "economy": economy or None, "kills": kills}
    if focus:
        mine = next((line for line in lines if same_player(line["riot_id"], focus)), None)
        view["player"] = mine and {key: value for key, value in mine.items() if key != "riot_id"}
    if detailed:
        view["players"] = by_team or None
    return compact(view)


@tool
async def get_player_overview(
    riot_id: RiotIdArg,
    playlist: PlaylistArg = "competitive",
    season: SeasonArg = "current",
    include_career: Annotated[
        bool, Field(description="Also return all-act totals under 'career'.")
    ] = True,
    detailed: DetailedArg = False,
    force_refresh: RefreshArg = False,
) -> dict[str, Any]:
    """Headline stats for a player: rank, peak rank and overall performance.

    Returns rank (tier, plus rr and leaderboard_rank for Immortal and above,
    the only ranks tracker.gg has a rating for), peak_rank, and a stats block
    with matches, wins, losses, win_rate, kd, kda, acs, adr, hs_pct, kast,
    kills, deaths, assists, first_kills, first_deaths, aces, clutches,
    tracker_score and hours_played for the chosen act. "percentiles" compares
    the player with everyone tracked, and "career" holds the stat block across
    all acts, without the few numbers tracker.gg only has per act (mvps,
    tracker_score, and in the full sheet trade_kills and thrifty_rounds).
    "seasons" (newest first) and "playlists" list what the season and playlist
    arguments accept.

    detailed=true turns both stat blocks into the full sheet: attack and
    defense blocks, clutches won and lost by size, multi-kills, trades, rounds
    survived, last deaths, entry success, plants and defuses, econ rating,
    ability casts, shots dealt and received by body part, flawless and thrifty
    rounds, team aces, total damage and more.
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
        rank = stats.pop("rank", None)
        peak_rank = stats.pop("peak_rank", None) or (
            profile.peak_rank.dump() if profile.peak_rank else None
        )
        percentiles = stats.pop("percentiles", None)

        career = None
        if include_career and season_id is not None:
            try:
                career = await load_section(rid, "season_stats", mode, None, origin)
            except TransientError as exc:
                origin.warnings.append(f"Career totals are unavailable right now: {exc}")
        if career:
            hidden = ("rank", "peak_rank", "percentiles")
            career = {k: v for k, v in career.items() if k not in hidden}

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
                "stats": stat_view(stats, detailed) or None,
                "percentiles": percentiles,
                "career": stat_view(career or {}, detailed) or None,
                "note": None if stats else f"No {mode} games recorded for this act.",
                "seasons": [act.short_name or act.name or act.id for act in profile.seasons],
                "playlists": profile.playlists,
                **origin.as_dict(),
            }
        )


@tool
async def get_player_agents(
    riot_id: RiotIdArg,
    playlist: PlaylistArg = "competitive",
    season: SeasonArg = "current",
    agents: Annotated[
        list[str] | None, Field(description='Only these agents, for example ["Jett", "Omen"].')
    ] = None,
    detailed: DetailedArg = False,
    force_refresh: RefreshArg = False,
) -> dict[str, Any]:
    """Per-agent performance for a player, most played first, plus totals per role.

    Each agent has agent, role, pick_rate, matches, wins, losses, win_rate,
    kd, kda, acs, adr, hs_pct, kast, kills, deaths, assists, first_kills,
    first_deaths, aces, clutches, hours_played and top_maps (the maps the
    agent was played on most). "roles" has the main numbers per role
    (duelist, initiator, controller, sentinel). Use season="all" for lifetime
    numbers.

    detailed=true returns the full stat sheet per agent, as described for
    get_player_overview, with "abilities" (the name and casts of each
    ability) in place of ability_casts, and with kd, acs, adr, hs_pct, kast,
    kills, deaths and assists on every top_maps entry. Detailed rows are
    long, so name the agents you want. Without names only the five most
    played are returned and "not_shown" lists the rest.
    """
    with tool_errors():
        return await _stat_rows(
            riot_id, "agents", playlist, season, force_refresh, agents, detailed
        )


@tool
async def get_player_maps(
    riot_id: RiotIdArg,
    playlist: PlaylistArg = "competitive",
    season: SeasonArg = "current",
    maps: Annotated[
        list[str] | None, Field(description='Only these maps, for example ["Split", "Ascent"].')
    ] = None,
    detailed: DetailedArg = False,
    force_refresh: RefreshArg = False,
) -> dict[str, Any]:
    """Per-map performance for a player, most played first.

    Each entry has map, matches, wins, losses, win_rate, kd, kda, acs, adr,
    hs_pct, kast, kills, deaths, assists, first_kills, first_deaths, aces,
    clutches, attack_round_win_rate, defense_round_win_rate, attack_kd,
    defense_kd and top_agents (the agents played most on that map). Use
    season="all" for lifetime numbers.

    detailed=true returns the full stat sheet per map, as described for
    get_player_overview, with attack and defense blocks in place of the four
    flat side numbers, and with kd, acs, adr, hs_pct, kast, kills, deaths and
    assists on every top_agents entry. Detailed rows are long, so name the
    maps you want. Without names only the five most played are returned and
    "not_shown" lists the rest.
    """
    with tool_errors():
        return await _stat_rows(riot_id, "maps", playlist, season, force_refresh, maps, detailed)


@tool
async def get_player_weapons(
    riot_id: RiotIdArg,
    playlist: PlaylistArg = "competitive",
    season: SeasonArg = "current",
    force_refresh: RefreshArg = False,
) -> dict[str, Any]:
    """Per-weapon performance for a player, most kills first.

    Each entry has weapon, category, matches and rounds (in which it was
    used), kills, deaths (times the player was killed by that weapon), kd,
    alt_fire_kills, hs_pct, damage, damage_received (taken from that weapon,
    which tracker.gg only has per act), shots_dealt (head, body, leg),
    avg_kill_distance_m and longest_kill_m. Abilities that deal weapon-like
    damage are listed too. Use season="all" for lifetime numbers.
    """
    with tool_errors():
        return await _stat_rows(riot_id, "weapons", playlist, season, force_refresh)


async def _stat_rows(
    riot_id: str,
    section: str,
    playlist: str,
    season: str,
    force: bool,
    only: list[str] | None = None,
    detailed: bool = False,
) -> dict[str, Any]:
    rid = RiotId.parse(riot_id)
    mode = normalize_playlist(playlist)
    origin = Provenance()
    profile = await load_profile(rid, origin)
    season_id = resolve_season(profile, season)
    rows = await load_section(rid, section, mode, season_id, origin, force=force) or []
    label = ROW_NAMES[section]
    notes = [] if rows else [f"No {mode} games recorded for this scope."]
    not_shown = None
    if only:
        wanted = {squash(name) for name in only}
        known = {squash(row.get(label)) for row in rows}
        missing = [name for name in only if squash(name) not in known]
        if missing and rows:
            notes.append(f"Nothing recorded for {', '.join(missing)} in this scope.")
        rows = [row for row in rows if squash(row.get(label)) in wanted]
    elif detailed and len(rows) > DETAILED_ROWS:
        not_shown = [row.get(label) for row in rows[DETAILED_ROWS:]]
        rows = rows[:DETAILED_ROWS]
        notes.append(
            f"Detailed rows are limited to the {DETAILED_ROWS} most played. "
            "Name the others to see them."
        )

    def view(row: dict[str, Any]) -> dict[str, Any]:
        if section == "weapons":
            return row
        shown = stat_view(row, detailed)
        if section == "maps" and not detailed:
            top_agents = shown.pop("top_agents", None)
            shown = compact({**shown, **side_headlines(row), "top_agents": top_agents})
        return shown

    shown = fit([view(row) for row in rows])
    if len(shown) < len(rows):
        not_shown = [row.get(label) for row in rows[len(shown) :]] + (not_shown or [])
        notes.append(f"Only {len(shown)} rows fit in one answer. Name fewer at a time.")
    result: dict[str, Any] = {
        "riot_id": profile.riot_id or str(rid),
        "playlist": mode,
        "season": season_label(profile, season_id),
        section: shown,
    }
    if section == "agents":
        roles = await load_section(rid, "roles", mode, season_id, origin)
        result["roles"] = [stat_view(row, False) for row in roles or []]
    return compact(
        {**result, "not_shown": not_shown, "note": " ".join(notes) or None, **origin.as_dict()}
    )


@tool
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
    detailed: DetailedArg = False,
    skip: Annotated[
        int,
        Field(ge=0, le=200, description="Leave out this many of the newest matches, to page back."),
    ] = 0,
    map_name: MapArg = None,
    agent: AgentArg = None,
    season: Annotated[
        str | None,
        Field(description='Only matches of this act, for example "E26: A5", or "current".'),
    ] = None,
    force_refresh: RefreshArg = False,
) -> dict[str, Any]:
    """Recent match history with the player's own line and every teammate's line.

    Each match has match_id, url, played_at, map, mode, result (victory or
    defeat), score, agent, kills, deaths, assists, kd, acs, adr, hs_pct, kast,
    damage, first_kills, first_deaths, plants, defuses, performance_rank (the
    player's position among all ten players by tracker.gg's performance
    score), party_size and teammates. Every teammate entry has riot_id, agent,
    rank, kills, deaths, assists, kd, acs, adr, hs_pct, kast, first_kills,
    first_deaths and in_party (true when they queued together with the
    player). Group by teammate riot_id and filter by map to compare
    teammates, or call get_teammate_stats, which does that aggregation.

    detailed=true gives the player and every teammate the whole scoreboard
    line listed under get_match_details (clutches, multi-kills, trades,
    economy, ability casts and so on). That is long, so a detailed call
    returns at most eight matches. Use get_teammate_stats for totals.

    map_name, agent and season narrow the history on tracker.gg's side, so
    limit then counts matches on that map, on that agent or in that act.

    An answer holds only so much: when the matches asked for do not fit, the
    oldest are left off and "note" says which skip value continues from there.

    Scoreboards are scraped one match at a time on first use and cached for
    weeks afterwards, so a cold call takes a few seconds per match.
    """
    with tool_errors():
        rid = RiotId.parse(riot_id)
        mode = normalize_playlist(playlist)
        origin = Provenance()
        wanted = min(limit, DETAILED_MATCHES) if detailed else limit
        filters, labels = await match_filters(origin, map_name, agent, season)
        entries = await load_match_entries(
            rid, mode, skip + wanted, origin, force=force_refresh, filters=filters
        )
        entries = entries[skip:]
        boards = await load_scoreboards(entries, origin, ctx)
        views = [
            match_view(rid, entry, boards.get(entry.match_id), include_opponents, detailed)
            for entry in entries
        ]
        matches = fit(views)
        note = None
        if len(matches) < len(views) or (wanted < limit and len(views) == wanted):
            note = (
                f"{len(matches)} matches fit in this answer. "
                f"Call again with skip={skip + len(matches)} for older ones."
            )
        return compact(
            {
                "riot_id": str(rid),
                "playlist": mode,
                **labels,
                "count": len(matches),
                "matches": matches,
                "note": note,
                **origin.as_dict(),
            }
        )


@tool
async def get_match_details(
    match_id_or_url: Annotated[
        str, Field(description="A match ID (UUID) or a tracker.gg match URL.")
    ],
    detailed: DetailedArg = False,
) -> dict[str, Any]:
    """Full scoreboard of one match: both teams and all ten players.

    Returns map, mode, played_at, duration_minutes, rounds and a list of teams
    with won, rounds_won, rounds_lost, surrendered (set on a team that gave
    up), started_on (attack or defense), round_wins (rounds won by how they
    ended), plants_by_site and players.
    Each player has riot_id, agent, rank, account_level, party_id (players
    sharing one queued together), kills, deaths, assists, kd, acs, adr,
    hs_pct, kast, damage, damage_received, damage_delta_per_round,
    combat_score, shots_dealt and shots_received (hits by body part: head,
    body, leg), first_kills, first_deaths, team_first_deaths,
    entry_success_rate, rounds_survived, deaths_traded, trade_kills, clutches,
    clutches_lost, clutches_by_size, clutches_lost_by_size, multi_kills,
    double_kills, triple_kills, quadra_kills, aces, plants, defuses,
    econ_rating, avg_loadout_value, credits_spent, ability_casts,
    tracker_score, performance_score, performance_grade (pass, merit or
    distinction), performance_rank (position among all ten players by
    performance_score, which is not the order by combat score) and tags
    (tracker.gg's labels for the match, such as "Top Frag").

    detailed=true adds to every player attack and defense blocks, buys (their
    rounds by buy type), weapon_kills, duels (per opponent: kills, deaths,
    damage_dealt and damage_taken) and performance_parts (what the
    performance score is made of), and to the match a round_log with the
    winner, the ending and the plant site of every round. The kills of each
    round are in get_match_rounds.

    A free-for-all such as deathmatch has no teams, so its players are listed
    under "players" instead, and modes without rounds have no side, buy or
    round numbers.
    """
    with tool_errors():
        match_id = extract_match_id(match_id_or_url)
        origin = Provenance()
        loaded = await load_match(match_id)
        origin.add(loaded)
        board = MatchDetails.model_validate(loaded.value)
        result = board.dump()
        result.pop("round_log", None)
        round_log = [
            compact(
                {
                    "round": entry.round,
                    "winner": entry.winner,
                    "ending": entry.ending,
                    "plant_site": entry.plant.site if entry.plant else None,
                }
            )
            for entry in board.round_log or []
        ]
        hidden = () if detailed else SPLIT_KEYS
        players = [
            {k: v for k, v in row.items() if k not in hidden} for row in result.pop("players", [])
        ]
        result["url"] = match_page_url(match_id)
        if board.teams:
            for team in result["teams"]:
                team["players"] = [
                    {k: v for k, v in row.items() if k != "team"}
                    for row in players
                    if row.get("team") == team["team"]
                ]
        else:
            result.pop("teams", None)
            result["players"] = players
        if detailed and round_log:
            result["round_log"] = round_log
        return {**result, **origin.as_dict()}


@tool
async def get_match_rounds(
    match_id_or_url: Annotated[
        str, Field(description="A match ID (UUID) or a tracker.gg match URL.")
    ],
    rounds: Annotated[
        list[int] | None, Field(description="Only these round numbers, for example [1, 13].")
    ] = None,
    riot_id: Annotated[
        str | None, Field(description="Also show this player's own line in every round.")
    ] = None,
    detailed: DetailedArg = False,
) -> dict[str, Any]:
    """Round-by-round account of one match: how each round went and the kills in order.

    Every round has round, winner, ending (Elimination, Defuse, Detonate or
    Time), attackers (the team on attack), score (rounds each team has won
    after it), plant and defuse (by, site, and time in seconds into the
    round), detonated_at when the spike went off, economy (per team: buy, the
    buy type most of its players were on,
    with loadout_value and spent added up) and kills in the order they
    happened. A kill has time (seconds into the round), killer, victim and
    weapon. A kill whose killer is the victim is a suicide or the spike, and
    one within a team is a team kill. Neither counts as a kill on the
    scoreboard or in a player's line, while the death does, except a death to
    the spike. "teams" lists each team's players, and marks a team that
    surrendered.

    With riot_id every round also has "player", that player's line: buy
    (pistol, eco, semi or full, by credits spent), loadout_value, spent,
    remaining, score, kills, deaths, assists and damage, or "away" for a
    round they were not in the game for.

    detailed=true adds to every kill the assists, distance_m, alt_fire when
    the weapon's alternate fire made it, and the minimap positions killer_at
    and victim_at ([x, y], each from 0 at the top left to 1), to a plant or
    defuse its position "at", and to every round "players" with the line of
    all ten by team. That
    is long, so name the rounds you want. Rounds that do not fit are left off
    and "note" says which.
    """
    with tool_errors():
        match_id = extract_match_id(match_id_or_url)
        focus = str(RiotId.parse(riot_id)) if riot_id else None
        origin = Provenance()
        loaded = await load_match(match_id)
        origin.add(loaded)
        board = MatchDetails.model_validate(loaded.value)
        if not board.round_log:
            raise ToolError("Tracker.gg has no round-by-round data for this match.")
        team_of = {row.riot_id: row.team for row in board.players}
        if focus and not any(same_player(name, focus) for name in team_of):
            raise ToolError(f"{focus} did not play in this match.")

        score: dict[str, int] = {team.team: 0 for team in board.teams}
        views = []
        for entry in board.round_log:
            if entry.winner:
                score[entry.winner] = score.get(entry.winner, 0) + 1
            if not rounds or entry.round in rounds:
                views.append(round_view(entry, dict(score), team_of, focus, detailed))
        shown = fit(views)
        note = None
        if len(shown) < len(views):
            left = ", ".join(str(view["round"]) for view in views[len(shown) :])
            note = f"Did not fit in this answer: round {left}. Ask for them with rounds."
        elif not views:
            played = board.round_log
            note = f"No such round. This match has rounds {played[0].round} to {played[-1].round}."
        return compact(
            {
                "match_id": board.match_id,
                "url": match_page_url(match_id),
                "map": board.map,
                "mode": board.mode,
                "played_at": board.played_at,
                "teams": [
                    compact(
                        {
                            "team": team.team,
                            "won": team.won,
                            "rounds_won": team.rounds_won,
                            "surrendered": team.surrendered,
                            "started_on": team.started_on,
                            "players": [
                                name for name, side in team_of.items() if side == team.team
                            ],
                        }
                    )
                    for team in board.teams
                ],
                "rounds": shown,
                "note": note,
                **origin.as_dict(),
            }
        )


@tool
async def get_round_stats(
    riot_id: RiotIdArg,
    ctx: Context,
    map_name: MapArg = None,
    agent: AgentArg = None,
    limit_matches: Annotated[
        int, Field(ge=1, le=100, description="How many recent matches to analyse.")
    ] = 30,
    playlist: PlaylistArg = "competitive",
) -> dict[str, Any]:
    """How rounds go for the player's team over their recent matches.

    With map_name or agent the matches analysed are the most recent ones on
    that map or agent, not the ones among the last few that happen to match.

    Built from the round-by-round data of every analysed match. Each block
    counts rounds, the ones the player's team won, and win_rate:

    - rounds overall, and attack and defense. Each side also has spike_planted
      and spike_not_planted (on attack: after the team planted, on defense:
      after the enemy planted, so that one is the retake rate) and by_site
    - pistol_rounds (the first round of each half), after_pistol_win and
      after_pistol_loss (the round that follows)
    - opening.first_kill and opening.first_death: rounds in which the team got
      the first kill, or lost the first player
    - economy: rounds by both teams' buy, as "<own buy> vs <enemy buy>", where
      a team's buy is the type most of its players were on (pistol, eco, semi
      or full)
    - endings: how the rounds the team won and lost ended
    - you: the player's own opening duels (first_kill and first_death, with
      how the round then went), avg_kill_time and avg_death_time (seconds
      into the round), avg_kill_distance_m and avg_death_distance_m, and
      killed_by (the weapons that killed them most). These cover fights with
      the enemy only, not a suicide, the spike or a team kill

    A cold call scrapes one scoreboard per match at a few seconds each. Later
    calls reuse the cache.
    """
    with tool_errors():
        rid = RiotId.parse(riot_id)
        mode = normalize_playlist(playlist)
        origin = Provenance()
        filters, labels = await match_filters(origin, map_name, agent)
        entries = await load_match_entries(rid, mode, limit_matches, origin, filters=filters)
        boards = await load_scoreboards(entries, origin, ctx)
        ordered = [boards[entry.match_id] for entry in entries if entry.match_id in boards]
        history = {entry.match_id: entry for entry in entries}
        summary = analysis.round_stats(str(rid), ordered, history)
        return {"riot_id": str(rid), "playlist": mode, **labels, **summary, **origin.as_dict()}


@tool
async def get_teammate_stats(
    riot_id: RiotIdArg,
    ctx: Context,
    map_name: MapArg = None,
    agent: AgentArg = None,
    limit_matches: Annotated[
        int, Field(ge=1, le=100, description="How many recent matches to analyse.")
    ] = 30,
    playlist: PlaylistArg = "competitive",
    top: Annotated[int, Field(ge=1, le=25, description="How many teammates to return.")] = 10,
    detailed: DetailedArg = False,
) -> dict[str, Any]:
    """Most played teammates over the player's recent matches, with their stats.

    Teammates are ordered by games played together across all analysed
    matches, and "rank" is that position, so the first five entries are the
    five most played teammates. Each has games_together, games_in_party,
    account_level, wins, losses, win_rate, kills, deaths, assists, kd, acs,
    adr, hs_pct, kast, damage_delta_per_round, rounds, agents, by_map (games,
    win_rate, kd and acs per map), your_record_with and your_record_without
    (the player's own results with and without that teammate), and these
    totals, most with a rate next to them:

    - first_kills, first_deaths and team_first_deaths, with first_kill_rate,
      first_death_rate and team_first_death_rate (percent of the rounds
      played together), and entry_success_rate
    - rounds_survived with survival_rate
    - deaths_traded with deaths_traded_rate (percent of their deaths that a
      teammate avenged), and trade_kills
    - clutches and clutches_lost with clutch_win_rate and clutches_by_size
    - multi_kills, double_kills, triple_kills, quadra_kills and aces
    - plants, defuses, econ_rating, avg_loadout_value, tracker_score and
      ability_casts

    Compare teammates by the rates and averages rather than the totals, since
    they played different numbers of games. "Which of my five most played
    teammates dies first the most" is the highest first_death_rate among rank
    1 to 5.

    "rank" orders teammates by games together in the matches analysed here.
    "most_played_rank" is their place in tracker.gg's own list of the player's
    most played teammates over the last months (see get_top_teammates), when
    they are on it.

    With map_name or agent the matches analysed are the most recent ones on
    that map or agent, so every number is for that map. "Which of my five
    most played teammates has the lowest KD on Split" is answered by calling
    this with map_name="Split" and comparing kd among the teammates whose
    most_played_rank is 1 to 5.

    detailed=true adds attack and defense blocks, buys (by buy type),
    weapon_kills and tags to every teammate and to your_stats. That is long,
    so ask for few teammates: the ones that do not fit in one answer are left
    off and "note" says so.

    Fields with no data are left out, for example the rates of a teammate who
    never opened a round, or your_record_without for one who was in every
    match.

    A cold call scrapes one scoreboard per match at a few seconds each. Later
    calls reuse the cache.
    """
    with tool_errors():
        rid = RiotId.parse(riot_id)
        mode = normalize_playlist(playlist)
        origin = Provenance()
        filters, labels = await match_filters(origin, map_name, agent)
        entries = await load_match_entries(rid, mode, limit_matches, origin, filters=filters)
        boards = await load_scoreboards(entries, origin, ctx)
        ordered = [boards[entry.match_id] for entry in entries if entry.match_id in boards]
        history = {entry.match_id: entry for entry in entries}
        most_played = None
        try:
            totals = await load_aggregate(rid, mode, origin)
            most_played = [row.riot_id for row in totals.teammates]
        except TrackerError as exc:
            origin.warnings.append(f"Tracker.gg's most-played list is unavailable: {exc}")
        summary = analysis.teammate_stats(str(rid), ordered, top, history, detailed, most_played)
        rows = summary["teammates"]
        rest = len(json.dumps({key: value for key, value in summary.items() if key != "teammates"}))
        summary["teammates"] = fit(rows, ANSWER_BUDGET - rest)
        if len(summary["teammates"]) < len(rows):
            summary["note"] = (
                f"Only the first {len(summary['teammates'])} of {len(rows)} teammates fit in "
                "one answer. Ask for fewer, or without detailed."
            )
        return {"riot_id": str(rid), "playlist": mode, **labels, **summary, **origin.as_dict()}


@tool
async def compare_players(
    riot_ids: RiotIdsArg,
    weights: WeightsArg = None,
    playlist: PlaylistArg = "competitive",
    season: SeasonArg = "current",
    force_refresh: RefreshArg = False,
) -> dict[str, Any]:
    """Rank players against each other by a weighted score, and show the working.

    Uses each player's stats for the act, the same numbers get_player_overview
    returns. For every weighted stat the best value among the players is worth
    100 points and the others get their value as a percentage of it. A player's
    score is the sum of weight times points.

    "ranking" lists the players best first. Each has a breakdown per stat
    (value, points, weight, contribution) that adds up to the score, and
    ahead_of_next: by how much they lead the next player, and how much of that
    lead comes from each stat. "weights" are the weights as used, and
    default_weights says whether they were the defaults.

    A stat that one of the players has no value for is left out for everyone
    and named under left_out. Players without games in the chosen act are
    listed under not_ranked. A player whose numbers could not be refreshed has
    "stale": true in the ranking. A cold call costs one or two requests per
    player.
    """
    with tool_errors():
        mode = normalize_playlist(playlist)
        rids = list({rid.key: rid for rid in map(RiotId.parse, riot_ids)}.values())
        if len(rids) < 2:
            raise ToolError("Give at least two different Riot IDs to compare.")
        origin = Provenance()
        players: list[tuple[str, dict[str, Any]]] = []
        acts: dict[str, str] = {}
        outdated: list[str] = []
        not_ranked: list[str] = []
        for rid in rids:
            # Kept apart per player, so that the answer can say whose numbers are old.
            own = Provenance()
            profile = await load_profile(rid, own, force=force_refresh)
            name = profile.riot_id or str(rid)
            if name in acts or name in not_ranked:
                name = str(rid)
            try:
                season_id = resolve_season(profile, season)
            except ToolError as exc:
                raise ToolError(f"{name}: {exc}") from exc
            is_default = mode == profile.default_playlist and season_id == profile.default_season
            stats = await load_section(
                rid, "season_stats", mode, season_id, own, force=force_refresh and not is_default
            )
            origin.include(own)
            if not stats or not stats.get("matches"):
                not_ranked.append(name)
                continue
            players.append((name, stats))
            acts[name] = season_label(profile, season_id)
            if own.stale:
                outdated.append(name)
        if len(players) < 2:
            raise ToolError(
                f"Fewer than two of these players have {mode} games in that act, so there "
                "is nothing to compare."
            )
        try:
            result = analysis.compare_players(players, weights)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

        notes = []
        same_act = len(set(acts.values())) == 1
        for row in result["ranking"]:
            if not same_act:
                row["season"] = acts[row["riot_id"]]
            if row["riot_id"] in outdated:
                row["stale"] = True
        if not same_act:
            notes.append(
                'The numbers are from different acts, because "current" is the act '
                "tracker.gg shows for each player."
            )
        if outdated:
            notes.append(
                f"A fresh copy could not be fetched for {', '.join(outdated)}, so their "
                "numbers may be outdated."
            )
        few = [
            f"{row['riot_id']} ({row['matches']})"
            for row in result["ranking"]
            if row["matches"] < FEW_MATCHES
        ]
        if few:
            notes.append(f"Played few matches, so their numbers say less: {', '.join(few)}.")
        return compact(
            {
                "playlist": mode,
                "season": next(iter(acts.values())) if same_act else None,
                **result,
                "not_ranked": not_ranked or None,
                "note": " ".join(notes) or None,
                **origin.as_dict(),
            }
        )


def region_key(region: str) -> str:
    key = squash(region)
    if key not in REGIONS:
        raise ToolError(f"Unknown region '{region}'. Use one of: {', '.join(REGIONS)}.")
    return key


@tool
async def get_top_teammates(
    riot_id: RiotIdArg,
    playlist: PlaylistArg = "competitive",
) -> dict[str, Any]:
    """The player's most played teammates and party sizes, as tracker.gg counts them.

    Tracker.gg keeps its own totals over the player's last few months in a
    playlist, and "period" says which days and how many matches that is.
    "teammates" is its list of the up to twenty most played, most played
    first: rank, riot_id, matches, wins, losses and win_rate together,
    last_played, and the teammate's own kd and avg_placement in those
    matches. "parties" has the player's own matches, wins, losses, win_rate,
    kd and avg_placement by party size, 1 being solo queue.

    This costs one request and covers far more matches than
    get_teammate_stats, which reads scoreboards one by one but knows every
    stat. Use this one to find out who the most played teammates are.
    """
    with tool_errors():
        rid = RiotId.parse(riot_id)
        mode = normalize_playlist(playlist)
        origin = Provenance()
        totals = await load_aggregate(rid, mode, origin)
        period = None
        if totals.days:
            period = {
                "from": totals.days[0].date,
                "to": totals.days[-1].date,
                "matches": sum(day.matches or 0 for day in totals.days),
            }
        return compact(
            {
                "riot_id": str(rid),
                "playlist": mode,
                "period": period,
                "teammates": [
                    {"rank": rank, **row.dump()} for rank, row in enumerate(totals.teammates, 1)
                ],
                "parties": [row.dump() for row in totals.parties],
                "note": None if totals.days else f"No recent {mode} matches on tracker.gg.",
                **origin.as_dict(),
            }
        )


@tool
async def get_daily_stats(
    riot_id: RiotIdArg,
    playlist: PlaylistArg = "competitive",
    days: Annotated[
        int, Field(ge=1, le=120, description="How many of the latest days played to return.")
    ] = 30,
) -> dict[str, Any]:
    """Day-by-day numbers for the player, newest first.

    One entry per day on which the player played: date, matches, wins,
    losses, win_rate, kills, deaths, kd, adr, avg_placement,
    performance_score and minutes_played. Tracker.gg keeps the last few
    months. A day runs by this computer's time zone.
    """
    with tool_errors():
        rid = RiotId.parse(riot_id)
        mode = normalize_playlist(playlist)
        origin = Provenance()
        totals = await load_aggregate(rid, mode, origin)
        latest = [day.dump() for day in reversed(totals.days)][:days]
        return compact(
            {
                "riot_id": str(rid),
                "playlist": mode,
                "days_played": len(totals.days),
                "days": latest,
                "note": None if latest else f"No recent {mode} matches on tracker.gg.",
                **origin.as_dict(),
            }
        )


@tool
async def get_stat_history(
    riot_id: RiotIdArg,
    stat: Annotated[
        str,
        Field(
            description="rank, kd, kda, acs, adr, damage_delta_per_round, hs_pct, kast, "
            "win_rate, round_win_rate, matches, kills, deaths, assists, first_kills, "
            "first_deaths, clutches, aces, plants, defuses or econ_rating."
        ),
    ] = "kd",
    playlist: PlaylistArg = "competitive",
) -> dict[str, Any]:
    """How one stat moved day by day, and the best matches for it.

    "history" has a point per day played over about the last month, oldest
    first: date and value. With stat="rank" a point has tier, rr and
    leaderboard_rank instead, over about the last three months, which
    tracker.gg only keeps for Immortal and Radiant players. "best_matches"
    lists the ten matches with the highest value of the stat that tracker.gg
    knows of, from any act: value (the stat in that match), match_id, url,
    played_at, map, agent, result and the player's other numbers in it.

    These days are UTC days, so an evening match can fall on the next date
    here and on its own date in get_daily_stats.
    """
    with tool_errors():
        rid = RiotId.parse(riot_id)
        mode = normalize_playlist(playlist)
        name = re.sub(r"[\s-]+", "_", stat.strip().casefold())
        key = HISTORY_STATS.get(name, stat.strip())

        async def fetch() -> dict[str, Any]:
            return (await tracker.fetch_stat_history(rid, key, mode)).dump()

        params = {"playlist": mode, "stat": key}
        loaded = await load("stat_history", rid.key, params, settings.cache_ttl_overview, fetch)
        origin = Provenance()
        origin.add(loaded)
        best = []
        for entry in loaded.value.get("best_matches", []):
            hidden = ("combat_score", *HISTORY_DETAIL)
            row = {key: value for key, value in entry.items() if key not in hidden}
            best.append({**row, "url": match_page_url(entry["match_id"])})
        points = loaded.value.get("points", [])
        return compact(
            {
                "riot_id": str(rid),
                "playlist": mode,
                "stat": name if name in HISTORY_STATS else loaded.value.get("stat"),
                "history": points,
                "best_matches": best,
                "note": None
                if points
                else "Tracker.gg has no history of this stat for the player.",
                **origin.as_dict(),
            }
        )


@tool
async def get_rank_distribution(
    region: RegionArg = "na",
    season: ActArg = "current",
) -> dict[str, Any]:
    """How the ranked players of a region are spread over the ranks in one act.

    Every tier has share (the percent of ranked players in it), players, and
    top_percent (the percent of players in that tier or a higher one), lowest
    tier first.
    """
    with tool_errors():
        where = region_key(region)
        origin = Provenance()
        act = await look_up(lambda game: find_act(game, season), origin)

        async def fetch() -> list[dict[str, Any]]:
            return [row.dump() for row in await tracker.fetch_distribution(where, act.id)]

        params = {"region": where, "act": act.id}
        loaded = await load("distribution", "", params, settings.cache_ttl_career, fetch)
        origin.add(loaded)
        tiers, above = [], 0.0
        for row in reversed(loaded.value):
            above += row.get("share") or 0
            tiers.append({**row, "top_percent": round(min(above, 100), 2)})
        return compact(
            {
                "region": where,
                "season": act.name,
                "players": sum(row.get("players") or 0 for row in loaded.value) or None,
                "tiers": tiers[::-1],
                "note": None if tiers else "Tracker.gg has no rank distribution for this act.",
                **origin.as_dict(),
            }
        )


@tool
async def get_leaderboard(
    region: RegionArg = "na",
    season: ActArg = "current",
    start_rank: Annotated[int, Field(ge=1, le=20000, description="The first rank to list.")] = 1,
    limit: Annotated[int, Field(ge=1, le=100, description="How many players to list.")] = 50,
) -> dict[str, Any]:
    """The ranked leaderboard of a region for one act, best first.

    Rows have rank, riot_id, rr (rank rating), tier and wins.
    """
    with tool_errors():
        where = region_key(region)
        origin = Provenance()
        act = await look_up(lambda game: find_act(game, season), origin)
        skip = start_rank - 1

        async def fetch() -> dict[str, Any]:
            return (await tracker.fetch_leaderboard(where, act.id, skip, limit)).dump()

        params = {"region": where, "act": act.id, "skip": skip, "take": limit}
        loaded = await load("leaderboard", "", params, settings.cache_ttl_search, fetch)
        origin.add(loaded)
        rows = loaded.value.get("rows", [])
        return compact(
            {
                "region": where,
                "season": act.name,
                "title": loaded.value.get("title"),
                "updated_at": loaded.value.get("updated_at"),
                "count": len(rows),
                "players": rows,
                **origin.as_dict(),
            }
        )


@tool
async def get_meta_insights() -> dict[str, Any]:
    """How agents and maps are doing across all the competitive matches tracker.gg tracks.

    "agents" has for each agent its role, tier (tracker.gg's tier list, S at
    the top), pick_rate (its share of all picks), win_rate, kd,
    kills_per_match, deaths_per_match, assists_per_match and
    damage_delta_per_round, most picked first. "maps" has play_rate,
    attackers_kd and defenders_kd for the maps in the pool. Tracker.gg has
    one set of these numbers: they cannot be narrowed to a rank, a region or
    a map.
    """
    with tool_errors():
        origin = Provenance()

        async def agents() -> list[dict[str, Any]]:
            return [row.dump() for row in await tracker.fetch_agent_insights()]

        async def maps() -> list[dict[str, Any]]:
            return [row.dump() for row in await tracker.fetch_map_insights()]

        result = {}
        for kind, fetch in (("agents", agents), ("maps", maps)):
            loaded = await load("insights", "", {"kind": kind}, settings.cache_ttl_career, fetch)
            origin.add(loaded)
            result[kind] = loaded.value
        return {**result, **origin.as_dict()}


@tool
async def get_premier_team(
    riot_id: Annotated[
        str | None, Field(description="Riot ID of a player on the team, as Name#TAG.")
    ] = None,
    roster_id: Annotated[
        str | None, Field(description="The team's roster ID, instead of a player.")
    ] = None,
    detailed: DetailedArg = False,
) -> dict[str, Any]:
    """A Premier team: its standing, players, past stages and recent matches.

    Returns name, region, zone, division, league_score, rank, wins and losses,
    "stats" (the team's all-time numbers on tracker.gg, the full stat sheet
    with detailed=true), "players" (riot_id, roster_role for those on the
    roster now, the agents they played for the team, matches, wins, losses,
    round_win_rate, acs, damage_delta_per_round, hs_pct, kast, tracker_score,
    rank and peak_rank), "stages" (division, score, wins, losses, rounds and
    playoff placement per stage) and "recent_matches" (the last twenty:
    opponent, map, rounds_won, rounds_lost, won and league points). A
    match_id from there works with get_match_details and get_match_rounds.
    """
    with tool_errors():
        origin = Provenance()
        owner = None
        if not roster_id:
            if not riot_id:
                raise ToolError("Give the Riot ID of a player on the team, or a roster ID.")
            rid = RiotId.parse(riot_id)
            owner = str(rid)
            roster_id = (await load_profile(rid, origin)).premier_roster_id
            if not roster_id:
                note = f"{rid} is not on a Premier team that tracker.gg knows of."
                return {"riot_id": owner, "note": note, **origin.as_dict()}
        roster = roster_id.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", roster):
            raise ToolError(f"'{roster_id}' is not a roster ID.")

        async def fetch() -> dict[str, Any]:
            return (await tracker.fetch_premier(roster)).dump()

        loaded = await load("premier", "", {"id": roster}, settings.cache_ttl_overview, fetch)
        origin.add(loaded)
        team = PremierTeam.model_validate(loaded.value).dump()
        matches = team.pop("matches", [])
        return compact(
            {
                **team,
                "stats": stat_view(team.get("stats") or {}, detailed) or None,
                "matches_played": len(matches),
                "recent_matches": matches[:PREMIER_MATCHES],
                **origin.as_dict(),
            }
        )


@tool
async def get_game_data(
    kind: Annotated[
        Literal["agents", "maps", "weapons", "acts", "playlists"],
        Field(description="Which list to return."),
    ],
) -> dict[str, Any]:
    """Tracker.gg's reference lists for the game.

    agents have name, role and the names of their abilities by slot (c, q, e,
    x). maps have name. weapons have name, category and cost. acts have name,
    starts and ends, newest first. playlists maps the playlist keys the other
    tools accept to their names.
    """
    with tool_errors():
        origin = Provenance()
        rows = (await load_game_data(origin)).dump().get(kind) or []
        if isinstance(rows, list):
            # Tracker.gg's own IDs are of no use to a reader.
            rows = [{k: v for k, v in row.items() if k not in ("uuid", "id")} for row in rows]
        return {"kind": kind, "count": len(rows), kind: rows, **origin.as_dict()}


@tool
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
            return [result.dump() for result in await tracker.search(text)]

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


ReplayPathArg = Annotated[
    str,
    Field(description="Path of a replay file on this computer, as list_local_replays gives it."),
]


@tool(annotations=LOCAL)
async def list_local_replays() -> dict[str, Any]:
    """Replay files on this computer, newest first.

    Looks in the folder set as TRN_REPLAY_DIR, or else in the game's own replay
    folder, which only exists on Windows. Each file comes with its name, path,
    size and the time it was last changed.

    Replays are local only. A replay exists on the computer of a player who
    was in the match and downloaded it in the game, and other players' replays
    cannot be fetched from anywhere. Reading what is inside a replay is not
    built yet, so analysis_available is false.
    """
    with tool_errors():
        folder = settings.replay_dir or replays.default_folder()
        files = replays.find_replays(folder)
        note = None
        if folder is None:
            note = (
                "No replay folder is known on this computer. The game only runs on Windows, "
                "where it keeps replays in %LOCALAPPDATA%\\VALORANT\\Saved\\Demos. To use "
                "replay files here, set TRN_REPLAY_DIR to the folder they are in."
            )
        elif not folder.exists():
            note = f"The replay folder {folder} does not exist."
        elif not folder.is_dir():
            note = f"{folder} is not a folder, so it holds no replays."
        elif not files:
            note = (
                f"There are no replay files in {folder}. A replay appears there once it has "
                "been downloaded in the game."
            )
        return compact(
            {
                "folder": str(folder) if folder else None,
                "count": len(files),
                "replays": [file.describe() for file in files],
                "analysis_available": False,
                "note": note,
                "limitations": [replays.LOCAL_ONLY, replays.UNDOCUMENTED],
            }
        )


@tool(annotations=LOCAL)
async def analyze_replay(
    path: ReplayPathArg,
    questions: Annotated[
        list[str] | None,
        Field(description="What you want to know about the match, in plain words."),
    ] = None,
) -> dict[str, Any]:
    """Not built yet: answer questions about one match from its replay file.

    Checks that the file exists and returns status "not_implemented" with what
    is planned (round state, line of sight, utility) and which tools answer
    similar questions today. No part of the replay is read.

    Replays are local only: the file has to be on this computer already, and
    other players' replays cannot be fetched.
    """
    with tool_errors():
        answer = replays.not_built(
            "Replay analysis",
            replays.open_replay(path),
            replays.PLANNED,
            "get_match_rounds tells a match round by round, kill by kill, from tracker.gg's "
            "data, and get_round_stats sums up how rounds go over many matches.",
        )
        return {**answer, "questions": questions or []}


@tool(annotations=LOCAL)
async def get_utility_effectiveness(path: ReplayPathArg) -> dict[str, Any]:
    """Not built yet: what a player's abilities achieved in one match.

    Meant to answer questions such as "how many of my flashes blinded an
    enemy?" and "how many stuns led to a kill?" from a replay file. For now it
    checks that the file exists and returns status "not_implemented" with what
    is planned. No part of the replay is read.

    Replays are local only: the file has to be on this computer already, and
    other players' replays cannot be fetched.
    """
    with tool_errors():
        return replays.not_built(
            "Utility analysis",
            replays.open_replay(path),
            (replays.UTILITY,),
            "ability_casts in get_match_details and get_player_agents counts how often each "
            "ability was used. Tracker.gg does not know what an ability hit.",
        )


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
