"""parse_profile: who the player is, plus the stats of the default act."""

from sample_payloads import ACT_ID, BRIM, ROSTER_ID, sample_profile, stat_segments

from models import Rank
from scraper.parsers import parse_profile, parse_stats_bundle


def test_profile_carries_identity_and_defaults():
    profile = parse_profile(sample_profile())
    assert profile.riot_id == BRIM
    assert profile.account_level == 120
    assert profile.region == "eu"
    assert profile.privacy == "public"
    assert profile.default_playlist == "competitive"
    assert profile.default_season == ACT_ID
    assert profile.premier_roster_id == ROSTER_ID


def test_profile_lists_the_seasons_and_playlists_that_have_an_id():
    profile = parse_profile(sample_profile())
    assert [(season.id, season.name, season.short_name) for season in profile.seasons] == [
        (ACT_ID, "V26: ACT 5", "E26: A5"),
        ("older-act", "V26: ACT 4", "E26: A4"),
    ]
    assert profile.playlists == ["competitive", "unrated"]


def test_profile_peak_rank_is_the_competitive_one():
    profile = parse_profile(sample_profile())
    assert profile.peak_rank == Rank(
        tier="Radiant", tier_id=27, rr=450, leaderboard_rank=212, act="E25: A3"
    )


def test_profile_without_a_competitive_peak_has_no_peak_rank():
    data = sample_profile()
    data["segments"] = [
        segment
        for segment in data["segments"]
        if segment["attributes"].get("playlist") != "competitive"
    ]
    assert parse_profile(data).peak_rank is None


def test_profile_stats_are_those_of_its_segments():
    profile = parse_profile(sample_profile())
    assert profile.stats == parse_stats_bundle(stat_segments())
    assert profile.stats.season_stats.kills == 300
    assert [row.agent for row in profile.stats.agents] == ["Jett", "Sage"]


def test_profile_falls_back_to_the_handle_for_the_riot_id():
    data = sample_profile()
    del data["platformInfo"]["platformUserIdentifier"]
    assert parse_profile(data).riot_id == "Brim Stone"


def test_profile_drops_fields_of_an_unexpected_type():
    data = sample_profile()
    data["metadata"]["accountLevel"] = "120"
    data["metadata"]["premierRosterId"] = 42
    profile = parse_profile(data)
    assert profile.account_level is None
    assert profile.premier_roster_id is None


def test_empty_profile_still_parses():
    profile = parse_profile({})
    assert profile.riot_id == ""
    assert profile.default_playlist == "competitive"
    assert profile.seasons == []
    assert profile.peak_rank is None
    assert profile.stats.season_stats is None
    assert profile.stats.agents == []
