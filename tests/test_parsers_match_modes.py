"""parse_match: surrendered matches and modes without teams or rounds."""

import sample_payloads as sp
from sample_payloads import BLUE, BRIM, JETT, RED, SAGE

from models import Duel
from scraper.parsers import parse_match


def by_name(match):
    return {player.riot_id: player for player in match.players}


def test_rounds_that_were_never_played_are_dropped():
    match = parse_match(sp.surrendered_match())
    assert match.rounds == 8
    assert [played.round for played in match.round_log] == [1, 2, 3, 4, 5, 6]
    assert "Surrendered" not in {played.ending for played in match.round_log}


def test_team_that_gave_up_is_flagged():
    teams = {team.team: team for team in parse_match(sp.surrendered_match()).teams}
    assert teams[BLUE].surrendered is True
    assert teams[RED].surrendered is None


def test_match_played_to_the_end_is_not_flagged():
    assert [team.surrendered for team in parse_match(sp.sample_match()).teams] == [None, None]


def test_unplayed_rounds_change_nothing_else():
    played_out = parse_match(sp.sample_match())
    given_up = parse_match(sp.surrendered_match())
    assert given_up.players == played_out.players
    assert given_up.round_log == played_out.round_log
    for before, after in zip(played_out.teams, given_up.teams, strict=True):
        assert after.model_copy(update={"surrendered": None}) == before


def test_unplayed_rounds_are_not_counted_for_a_side_or_a_kill():
    data = sp.surrendered_match()
    stray = [
        segment
        for segment in data["segments"]
        if segment["type"] == "player-round-kills" and segment["attributes"]["round"] == 7
    ]
    assert len(stray) == 1
    match = parse_match(data)
    brim, sage = by_name(match)[BRIM], by_name(match)[SAGE]
    assert (brim.defense.rounds, sage.attack.rounds) == (3, 3)
    assert sage.weapon_kills == {"Phantom": 2, "Sheriff": 1}
    assert sage.duels[BRIM].kills == 1
    assert "Surrendered" not in {key for team in match.teams for key in team.round_wins}


def test_deathmatch_has_no_teams_and_no_round_log():
    match = parse_match(sp.deathmatch())
    assert (match.mode, match.playlist, match.ranked) == ("Deathmatch", "deathmatch", False)
    assert match.teams == []
    assert match.round_log is None
    assert [player.riot_id for player in match.players] == [BRIM, JETT, SAGE]


def test_deathmatch_skips_everything_built_from_rounds():
    for player in parse_match(sp.deathmatch()).players:
        assert (player.attack, player.defense) == (None, None)
        assert player.team_first_deaths is None
        assert (player.credits_spent, player.avg_loadout_value) == (None, None)
        assert (player.double_kills, player.multi_kills, player.aces) == (None, None, None)
        assert player.shots_dealt is None


def test_same_payload_is_read_round_by_round_when_the_mode_has_rounds():
    data = sp.deathmatch()
    data["metadata"]["isRoundBased"] = True
    match = parse_match(data)
    assert [played.round for played in match.round_log] == [1]
    assert by_name(match)[BRIM].double_kills == 1
    assert by_name(match)[BRIM].credits_spent == 0


def test_deathmatch_still_counts_weapon_kills_and_duels():
    players = by_name(parse_match(sp.deathmatch()))
    assert players[BRIM].weapon_kills == {"Vandal": 1, "Sheriff": 1}
    assert players[JETT].weapon_kills == {"Phantom": 1}
    assert players[SAGE].weapon_kills == {"Vandal": 1}
    assert players[BRIM].duels == {
        JETT: Duel(kills=2, deaths=0, damage_dealt=300, damage_taken=0),
        SAGE: Duel(kills=0, deaths=1, damage_dealt=0, damage_taken=150),
    }
    for name, player in players.items():
        assert sum(player.weapon_kills.values()) == player.kills
        assert name not in player.duels


def test_team_based_flag_alone_decides_whether_teams_are_returned():
    data = sp.deathmatch()
    data["metadata"]["isTeamBased"] = True
    assert [team.team for team in parse_match(data).teams] == [BRIM, JETT, SAGE]
