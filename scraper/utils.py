"""Riot ID parsing, playlist names and tracker.gg URL building."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, unquote, urlencode

from .exceptions import InvalidRiotIdError

SITE_BASE = "https://tracker.gg/valorant"
API_BASE = "https://api.tracker.gg/api/v2/valorant/standard"
# Rank distribution, leaderboards, insights, Premier and the reference lists live here.
DATA_BASE = "https://api.tracker.gg/api/v1/valorant"

_PROFILE_URL_RE = re.compile(r"/profile/riot/([^/?#]+)", re.IGNORECASE)
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_MATCH_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
_PLAYLIST_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_ACT_RE = re.compile(
    r"(?:season|episode|ep|[ev])\s*(\d+)\D+?(?:act|a)\s*(\d+|[ivx]+)\b", re.IGNORECASE
)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9}

_PLAYLIST_ALIASES = {
    "ranked": "competitive",
    "comp": "competitive",
    "normal": "unrated",
    "unranked": "unrated",
    "dm": "deathmatch",
    "tdm": "team-deathmatch",
    "spike-rush": "spikerush",
    "swift-play": "swiftplay",
    "snowball-fight": "snowball",
}


@dataclass(frozen=True, slots=True)
class RiotId:
    name: str
    tag: str

    @classmethod
    def parse(cls, raw: str) -> RiotId:
        """Accept "Name#TAG" with stray whitespace, a URL-encoded ID or a profile URL."""
        text = (raw or "").strip()
        url_match = _PROFILE_URL_RE.search(text)
        if url_match:
            text = url_match.group(1)
        if _PERCENT_ESCAPE_RE.search(text):
            text = unquote(text)
        # Full-width "＃" is what some IMEs produce.
        name, sep, tag = text.replace("＃", "#").rpartition("#")
        name, tag = " ".join(name.split()), tag.strip()
        if not sep or not name or not tag:
            raise InvalidRiotIdError(
                f"'{raw}' is not a Riot ID. Expected the form Name#TAG, for example Player#NA1."
            )
        if not 3 <= len(name) <= 16 or "#" in name:
            raise InvalidRiotIdError(f"'{raw}': the name part of a Riot ID is 3 to 16 characters.")
        if not 3 <= len(tag) <= 5 or not tag.isalnum():
            raise InvalidRiotIdError(
                f"'{raw}': the tagline of a Riot ID is 3 to 5 letters or digits."
            )
        return cls(name, tag)

    def __str__(self) -> str:
        return f"{self.name}#{self.tag}"

    @property
    def key(self) -> str:
        """Case-insensitive form used for cache keys and comparisons."""
        return str(self).casefold()

    @property
    def encoded(self) -> str:
        return quote(str(self), safe="")


def same_player(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and a.casefold() == b.casefold()


def normalize_playlist(value: str | None) -> str:
    """Map user-facing names ("ranked", "Spike Rush") onto tracker.gg playlist keys."""
    key = re.sub(r"[\s_]+", "-", (value or "competitive").strip().casefold())
    key = _PLAYLIST_ALIASES.get(key, key)
    if not _PLAYLIST_RE.fullmatch(key):
        raise InvalidRiotIdError(
            f"'{value}' is not a playlist. Try competitive, unrated, swiftplay, spikerush, "
            "deathmatch, team-deathmatch or premier."
        )
    return key


def act_number(label: str | None) -> tuple[int, int] | None:
    """Read (episode, act) from "E26: A6", "V26: ACT VI", "Season 26 Act 6" and the like."""
    found = _ACT_RE.search(label or "")
    if not found:
        return None
    act = found.group(2).casefold()
    if not act.isdigit() and act not in _ROMAN:
        return None
    return int(found.group(1)), _ROMAN.get(act) or int(act)


def act_label(label: str | None) -> str | None:
    """Rewrite any spelling of an act the way profiles list it, for example "E26: A6"."""
    number = act_number(label)
    return f"E{number[0]}: A{number[1]}" if number else label


def extract_match_id(value: str) -> str:
    """Pull the match UUID out of a bare ID or a tracker.gg match URL."""
    found = _MATCH_ID_RE.search(value or "")
    if not found:
        raise InvalidRiotIdError(
            f"'{value}' does not contain a match ID. Pass the UUID or a tracker.gg match URL."
        )
    return found.group(0).lower()


def profile_page_url(riot_id: RiotId) -> str:
    return f"{SITE_BASE}/profile/riot/{riot_id.encoded}/overview"


def match_page_url(match_id: str) -> str:
    return f"{SITE_BASE}/match/{match_id}"


def profile_url(riot_id: RiotId) -> str:
    return f"{API_BASE}/profile/riot/{riot_id.encoded}"


def segments_url(riot_id: RiotId, playlist: str, season_id: str | None) -> str:
    """All stat segments for one act, or for every act when season_id is None."""
    if season_id:
        query = {"playlist": playlist, "seasonId": season_id, "source": "web"}
        return f"{profile_url(riot_id)}/segments/season?{urlencode(query)}"
    return f"{profile_url(riot_id)}/segments/playlist?{urlencode({'playlist': playlist, 'source': 'web'})}"


def matches_url(
    riot_id: RiotId,
    playlist: str,
    page: int = 0,
    season_id: str | None = None,
    map_id: str | None = None,
    agent_id: str | None = None,
) -> str:
    """A page of the match history. The filters take tracker.gg's IDs, not names."""
    query: dict[str, str | int] = {"platform": "pc", "type": playlist}
    for name, value in (("season", season_id), ("map", map_id), ("agent", agent_id)):
        if value:
            query[name] = value
    if page:
        query["next"] = page
    return f"{API_BASE}/matches/riot/{riot_id.encoded}?{urlencode(query)}"


def local_offset_minutes() -> int:
    """Minutes the local clock is behind UTC, the way a browser reports it.

    Tracker.gg uses it to decide where one day ends and the next begins.
    """
    offset = datetime.now().astimezone().utcoffset()
    return -int(offset.total_seconds() // 60) if offset else 0


def aggregate_url(riot_id: RiotId, playlist: str) -> str:
    query = {"localOffset": local_offset_minutes(), "playlist": playlist}
    return f"{profile_url(riot_id)}/aggregated?{urlencode(query)}"


def stat_history_url(riot_id: RiotId, stat: str, playlist: str) -> str:
    query = {"localOffset": local_offset_minutes(), "playlist": playlist}
    return f"{profile_url(riot_id)}/stats/overview/{quote(stat, safe='')}?{urlencode(query)}"


def distribution_url(region: str, act_id: str) -> str:
    query = {"type": "ranked", "platform": "pc", "region": region, "act": act_id}
    return f"{DATA_BASE}/insights/distribution?{urlencode(query)}"


def leaderboard_url(region: str, act_id: str, skip: int, take: int) -> str:
    query = {"type": "ranked", "platform": "all", "board": "default", "region": region}
    return f"{DATA_BASE}/standard/leaderboards?{urlencode({**query, 'act': act_id, 'skip': skip, 'take': take})}"


def insights_url(kind: str) -> str:
    return f"{DATA_BASE}/insights/{kind}?playlist=competitive"


def premier_url(roster_id: str) -> str:
    return f"{DATA_BASE}/premier/roster/{quote(roster_id, safe='')}/detailed"


def game_data_url() -> str:
    return f"{DATA_BASE}/db/batch?types=playlists,seasons,weapons,maps,agents"


def match_url(match_id: str) -> str:
    return f"{API_BASE}/matches/{match_id}"


def search_url(query: str) -> str:
    params = {"platform": "riot", "query": query, "autocomplete": "true"}
    return f"{API_BASE}/search?{urlencode(params)}"
