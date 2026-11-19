"""Riot ID parsing, playlist and act names, match IDs and URL building."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from scraper import utils
from scraper.exceptions import InvalidRiotIdError, TrackerError
from scraper.utils import RiotId

ME = RiotId("Brim Stone", "TST")
MATCH_ID = "0a1b2c3d-1111-4222-8333-abcdefabcdef"


def query_of(url: str) -> dict[str, str]:
    pairs = parse_qs(urlsplit(url).query, keep_blank_values=True, strict_parsing=True)
    assert all(len(values) == 1 for values in pairs.values())
    return {name: values[0] for name, values in pairs.items()}


def path_of(url: str) -> str:
    return url.split("?", 1)[0]


@pytest.mark.parametrize(
    "raw",
    [
        "Brim Stone#TST",
        "  Brim Stone#TST \n",
        "Brim   Stone # TST",
        "Brim Stone＃TST",
        "Brim%20Stone%23TST",
        "https://tracker.gg/valorant/profile/riot/Brim%20Stone%23TST/overview",
        "tracker.gg/valorant/profile/riot/Brim%20Stone%23TST/matches?playlist=competitive",
        "https://TRACKER.GG/valorant/PROFILE/RIOT/Brim%20Stone%23TST",
    ],
)
def test_riot_id_is_read_from_every_accepted_spelling(raw):
    assert RiotId.parse(raw) == ME


def test_riot_id_parts_and_forms():
    riot_id = RiotId.parse("Jett Lag#0001")
    assert (riot_id.name, riot_id.tag) == ("Jett Lag", "0001")
    assert str(riot_id) == "Jett Lag#0001"
    assert riot_id.encoded == "Jett%20Lag%230001"
    assert RiotId.parse(riot_id.encoded) == riot_id


def test_riot_id_key_ignores_case_but_parsing_keeps_it():
    shouted = RiotId.parse("BRIM STONE#tst")
    assert str(shouted) == "BRIM STONE#tst"
    assert shouted != ME
    assert shouted.key == ME.key == "brim stone#tst"


@pytest.mark.parametrize("name", ["Vyp", "Sixteen Chars Ok"])
@pytest.mark.parametrize("tag", ["TST", "12345"])
def test_riot_id_length_limits_are_inclusive(name, tag):
    assert RiotId.parse(f"{name}#{tag}") == RiotId(name, tag)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "Brim Stone",
        "#TST",
        "Brim Stone#",
        "   #TST",
        "Vy#TST",
        "Seventeen Chars No#TST",
        "Brim Stone#TS",
        "Brim Stone#TOOBIG",
        "Brim Stone#T-T",
        "Brim Stone#T T",
        "Brim#Stone#TST",
        "https://tracker.gg/valorant/profile/riot/Brim%20Stone/overview",
    ],
)
def test_bad_riot_id_is_rejected(raw):
    with pytest.raises(InvalidRiotIdError) as caught:
        RiotId.parse(raw)
    assert isinstance(caught.value, TrackerError)
    assert isinstance(caught.value, ValueError)
    assert raw in str(caught.value)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("Brim Stone#TST", "brim stone#tst", True),
        ("Brim Stone#TST", "Brim Stone#TST", True),
        ("Brim Stone#TST", "Brim Stone#TS7", False),
        ("Brim Stone#TST", "Jett Lag#0001", False),
        ("Brim Stone#TST", None, False),
        (None, "Brim Stone#TST", False),
        (None, None, False),
        ("", "", False),
    ],
)
def test_same_player(a, b, expected):
    assert utils.same_player(a, b) is expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (None, "competitive"),
        ("", "competitive"),
        ("competitive", "competitive"),
        ("Ranked", "competitive"),
        (" comp ", "competitive"),
        ("Unrated", "unrated"),
        ("normal", "unrated"),
        ("unranked", "unrated"),
        ("DM", "deathmatch"),
        ("tdm", "team-deathmatch"),
        ("Team Deathmatch", "team-deathmatch"),
        ("team_deathmatch", "team-deathmatch"),
        ("Spike Rush", "spikerush"),
        ("spike-rush", "spikerush"),
        ("Swift  Play", "swiftplay"),
        ("swiftplay", "swiftplay"),
        ("Snowball Fight", "snowball"),
        ("Premier", "premier"),
    ],
)
def test_playlist_names_are_normalised(given, expected):
    assert utils.normalize_playlist(given) == expected


@pytest.mark.parametrize("given", ["   ", "ranked!", "comp/unrated", "-ranked", "a&b=c", "?"])
def test_playlist_that_cannot_be_a_key_is_rejected(given):
    with pytest.raises(InvalidRiotIdError):
        utils.normalize_playlist(given)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("E9: A2", (9, 2)),
        ("e9: a2", (9, 2)),
        ("V26: A6", (26, 6)),
        ("V26: ACT VI", (26, 6)),
        ("Season 26 Act 6", (26, 6)),
        ("Episode 9 // Act 3", (9, 3)),
        ("EP 5 - Act II", (5, 2)),
        ("E1: A IX", (1, 9)),
        ("E12: A10", (12, 10)),
        ("Episode 9", None),
        ("Act 3", None),
        ("E9: A XX", None),
        ("current", None),
        ("", None),
        (None, None),
    ],
)
def test_act_number(label, expected):
    assert utils.act_number(label) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("V26: ACT VI", "E26: A6"),
        ("Season 26 Act 6", "E26: A6"),
        ("E9: A2", "E9: A2"),
        ("Closed Beta", "Closed Beta"),
        (None, None),
    ],
)
def test_act_label(label, expected):
    assert utils.act_label(label) == expected


@pytest.mark.parametrize(
    "given",
    [
        MATCH_ID,
        MATCH_ID.upper(),
        f"  {MATCH_ID}\n",
        f"https://tracker.gg/valorant/match/{MATCH_ID}",
        f"https://tracker.gg/valorant/match/{MATCH_ID.upper()}?handle=Brim%20Stone%23TST",
    ],
)
def test_match_id_is_pulled_out_in_lower_case(given):
    assert utils.extract_match_id(given) == MATCH_ID


@pytest.mark.parametrize(
    "given",
    ["", "not a match", "0a1b2c3d-1111-4222-8333", MATCH_ID.replace("a", "g"), MATCH_ID[:-1]],
)
def test_text_without_a_match_id_is_rejected(given):
    with pytest.raises(InvalidRiotIdError):
        utils.extract_match_id(given)


def test_page_urls():
    assert (
        utils.profile_page_url(ME)
        == "https://tracker.gg/valorant/profile/riot/Brim%20Stone%23TST/overview"
    )
    assert utils.match_page_url(MATCH_ID) == f"https://tracker.gg/valorant/match/{MATCH_ID}"


def test_match_url_round_trips_through_extract_match_id():
    assert utils.extract_match_id(utils.match_page_url(MATCH_ID)) == MATCH_ID
    assert utils.extract_match_id(utils.match_url(MATCH_ID)) == MATCH_ID


def test_profile_page_url_parses_back_to_the_same_riot_id():
    assert RiotId.parse(utils.profile_page_url(ME)) == ME
    assert RiotId.parse(utils.profile_url(ME)) == ME


def test_api_urls_for_a_profile_and_a_match():
    profile = "https://api.tracker.gg/api/v2/valorant/standard/profile/riot/Brim%20Stone%23TST"
    assert utils.profile_url(ME) == profile
    assert (
        utils.match_url(MATCH_ID)
        == f"https://api.tracker.gg/api/v2/valorant/standard/matches/{MATCH_ID}"
    )


def test_segments_url_for_one_act():
    url = utils.segments_url(ME, "competitive", "act-7")
    assert path_of(url) == f"{utils.profile_url(ME)}/segments/season"
    assert query_of(url) == {"playlist": "competitive", "seasonId": "act-7", "source": "web"}


def test_segments_url_for_all_acts_has_no_season():
    url = utils.segments_url(ME, "unrated", None)
    assert path_of(url) == f"{utils.profile_url(ME)}/segments/playlist"
    assert query_of(url) == {"playlist": "unrated", "source": "web"}


def test_matches_url_has_only_the_filters_given():
    url = utils.matches_url(ME, "competitive")
    assert path_of(url) == (
        "https://api.tracker.gg/api/v2/valorant/standard/matches/riot/Brim%20Stone%23TST"
    )
    assert query_of(url) == {"platform": "pc", "type": "competitive"}
    assert query_of(utils.matches_url(ME, "unrated", page=0)) == {
        "platform": "pc",
        "type": "unrated",
    }
    assert query_of(utils.matches_url(ME, "competitive", map_id="map-1")) == {
        "platform": "pc",
        "type": "competitive",
        "map": "map-1",
    }


def test_matches_url_with_every_filter_and_a_page():
    url = utils.matches_url(
        ME, "competitive", page=2, season_id="act-7", map_id="map-1", agent_id="agent-9"
    )
    assert query_of(url) == {
        "platform": "pc",
        "type": "competitive",
        "season": "act-7",
        "map": "map-1",
        "agent": "agent-9",
        "next": "2",
    }


class FixedZone:
    """Stands in for datetime in a time zone that is offset from UTC."""

    def __init__(self, offset: timedelta) -> None:
        self.offset = offset

    def now(self) -> FixedZone:
        return self

    def astimezone(self) -> datetime:
        return datetime(2020, 1, 1, 12, tzinfo=timezone(self.offset))


@pytest.mark.parametrize(
    ("offset", "minutes"),
    [
        (timedelta(0), 0),
        (timedelta(hours=2), -120),
        (timedelta(hours=-5), 300),
        (timedelta(hours=5, minutes=30), -330),
    ],
)
def test_local_offset_is_minutes_behind_utc(monkeypatch, offset, minutes):
    monkeypatch.setattr(utils, "datetime", FixedZone(offset))
    assert utils.local_offset_minutes() == minutes


def test_aggregate_and_history_urls_carry_the_local_offset(monkeypatch):
    monkeypatch.setattr(utils, "local_offset_minutes", lambda: 300)
    aggregate = utils.aggregate_url(ME, "competitive")
    assert path_of(aggregate) == f"{utils.profile_url(ME)}/aggregated"
    assert query_of(aggregate) == {"localOffset": "300", "playlist": "competitive"}

    history = utils.stat_history_url(ME, "kDRatio", "unrated")
    assert path_of(history) == f"{utils.profile_url(ME)}/stats/overview/kDRatio"
    assert query_of(history) == {"localOffset": "300", "playlist": "unrated"}


def test_stat_name_is_escaped_in_the_history_url(monkeypatch):
    monkeypatch.setattr(utils, "local_offset_minutes", lambda: 0)
    url = utils.stat_history_url(ME, "odd/stat name", "competitive")
    assert path_of(url).endswith("/stats/overview/odd%2Fstat%20name")


def test_distribution_url():
    url = utils.distribution_url("eu", "act-7")
    assert path_of(url) == "https://api.tracker.gg/api/v1/valorant/insights/distribution"
    assert query_of(url) == {"type": "ranked", "platform": "pc", "region": "eu", "act": "act-7"}


def test_leaderboard_url():
    url = utils.leaderboard_url("na", "act-7", 100, 50)
    assert path_of(url) == "https://api.tracker.gg/api/v1/valorant/standard/leaderboards"
    assert query_of(url) == {
        "type": "ranked",
        "platform": "all",
        "board": "default",
        "region": "na",
        "act": "act-7",
        "skip": "100",
        "take": "50",
    }


def test_insights_premier_and_game_data_urls():
    base = "https://api.tracker.gg/api/v1/valorant"
    assert utils.insights_url("agents") == f"{base}/insights/agents?playlist=competitive"
    assert utils.premier_url("roster 1/2") == f"{base}/premier/roster/roster%201%2F2/detailed"
    game_data = utils.game_data_url()
    assert path_of(game_data) == f"{base}/db/batch"
    assert set(query_of(game_data)["types"].split(",")) == {
        "playlists",
        "seasons",
        "weapons",
        "maps",
        "agents",
    }


def test_search_url_escapes_the_query():
    url = utils.search_url("Brim Stone#TST & co")
    assert path_of(url) == "https://api.tracker.gg/api/v2/valorant/standard/search"
    assert "#" not in url
    assert query_of(url) == {
        "platform": "riot",
        "query": "Brim Stone#TST & co",
        "autocomplete": "true",
    }
