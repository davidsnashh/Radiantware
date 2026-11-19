"""parse_match: the scoreboard and what the per-round rows add to each player.

The expected numbers are worked out by hand from the tables in sample_payloads.
"""

from collections import Counter

import pytest
import sample_payloads as sp
from sample_payloads import BLUE, BRIM, CYPHER, JETT, RED, SAGE

from models import Duel, Shots
from scraper.parsers import parse_match, parse_stats_bundle

NAMES = (BRIM, JETT, SAGE, CYPHER)
KILL_EVENTS = 14
KILLS_ON_OPPONENTS = 11


def by_name(match):
    return {player.riot_id: player for player in match.players}


def without(data, kind):
    data["segments"] = [segment for segment in data["segments"] if segment["type"] != kind]
    return data


@pytest.fixture
def match():
    return parse_match(sp.sample_match())


@pytest.fixture
def players(match):
    return by_name(match)


def test_match_header(match):
    assert match.match_id == sp.MATCH_ID
    assert match.played_at == "2026-03-01T18:00:00+00:00"
    assert (match.map, match.mode, match.playlist) == ("Ascent", "Competitive", "competitive")
    assert match.ranked is True
    assert match.duration_minutes == 25.5
    assert match.rounds == 6


def test_teams_carry_result_score_and_starting_side(match):
    red, blue = match.teams
    assert (red.team, red.won, red.rounds_won, red.rounds_lost) == (RED, True, 4, 2)
    assert (blue.team, blue.won, blue.rounds_won, blue.rounds_lost) == (BLUE, False, 2, 4)
    assert (red.started_on, blue.started_on) == ("attack", "defense")
    assert red.rounds_won + blue.rounds_won == match.rounds


def test_players_are_grouped_by_team_with_the_highest_acs_first(match):
    assert [player.riot_id for player in match.players] == [SAGE, CYPHER, BRIM, JETT]
    assert [player.team for player in match.players] == [BLUE, BLUE, RED, RED]


def test_player_identity(players):
    brim, jett = players[BRIM], players[JETT]
    assert (brim.team, brim.agent, brim.rank) == (RED, "Brimstone", "Gold 2")
    assert (brim.party_id, brim.account_level) == ("7", 120)
    assert (jett.party_id, jett.account_level) == (None, None)


def test_player_labels_and_performance_parts(players):
    brim = players[BRIM]
    assert brim.tags == ["Top Frag", "Planter"]
    assert brim.performance_grade == "distinction"
    assert brim.performance_parts == {
        "damage": 12.35,
        "kill_impact": 20.5,
        "death_impact": -4.25,
        "plants": 1.0,
    }
    assert (brim.performance_score, brim.performance_rank, brim.tracker_score) == (61.5, 1, 780)
    assert players[JETT].tags is None
    assert players[JETT].performance_parts is None


def test_scoreboard_line_is_rounded(players):
    brim = players[BRIM]
    assert (brim.kills, brim.deaths, brim.assists, brim.kd) == (4, 3, 1, 1.33)
    assert (brim.acs, brim.adr, brim.damage_delta_per_round) == (190.0, 106.7, 31.7)
    assert (brim.hs_pct, brim.kast, brim.econ_rating) == (21.4, 83.3, 42.5)
    assert (brim.damage, brim.damage_received, brim.combat_score) == (640, 450, 1140)
    assert (brim.rounds_survived, brim.deaths_traded, brim.trade_kills) == (3, 1, 0)
    assert (brim.plants, brim.defuses) == (1, 0)


def test_side_rounds_add_up_to_rounds_played(match, players):
    for player in players.values():
        assert player.attack.rounds + player.defense.rounds == match.rounds
        assert (player.attack.rounds, player.defense.rounds) == (3, 3)


def test_side_round_wins_add_up_to_the_teams_score(match, players):
    won = {team.team: team.rounds_won for team in match.teams}
    for player in players.values():
        assert player.attack.rounds_won + player.defense.rounds_won == won[player.team]


@pytest.mark.parametrize(
    ("name", "side", "round_win_rate", "acs", "adr", "damage_delta"),
    [
        (BRIM, "attack", 66.7, 200.0, 113.3, 43.3),
        (BRIM, "defense", 66.7, 180.0, 100.0, 20.0),
        (JETT, "attack", 66.7, 93.3, 56.7, -43.3),
        (JETT, "defense", 66.7, 150.0, 73.3, 23.3),
        (SAGE, "attack", 33.3, 213.3, 130.0, 6.7),
        (SAGE, "defense", 33.3, 86.7, 70.0, -40.0),
        (CYPHER, "attack", 33.3, 0.0, 0.0, -50.0),
        (CYPHER, "defense", 33.3, 166.7, 100.0, 40.0),
    ],
)
def test_side_per_round_numbers_are_rebuilt_from_the_rounds(
    players, name, side, round_win_rate, acs, adr, damage_delta
):
    split = getattr(players[name], side)
    assert split.round_win_rate == round_win_rate
    assert split.acs == acs
    assert split.adr == adr
    assert split.damage_delta_per_round == damage_delta


def test_tracker_ggs_own_side_per_round_numbers_never_come_through(players):
    wrong = set(sp.WRONG_SIDE_NUMBERS.values())
    for player in players.values():
        for split in (player.attack, player.defense):
            found = {split.acs, split.adr, split.round_win_rate, split.damage_delta_per_round}
            assert not found & wrong


def test_side_scores_and_damage_add_up_to_the_match_totals(players):
    for player in players.values():
        attack, defense = player.attack, player.defense
        score = attack.acs * attack.rounds + defense.acs * defense.rounds
        dealt = attack.adr * attack.rounds + defense.adr * defense.rounds
        # each side is rounded to one decimal over three rounds
        assert score == pytest.approx(player.combat_score, abs=0.31)
        assert dealt == pytest.approx(player.damage, abs=0.31)


def test_side_damage_delta_adds_up_to_damage_dealt_minus_received(players):
    for player in players.values():
        attack, defense = player.attack, player.defense
        delta = (
            attack.damage_delta_per_round * attack.rounds
            + defense.damage_delta_per_round * defense.rounds
        )
        assert delta == pytest.approx(player.damage - player.damage_received, abs=0.31)


def test_side_kills_leave_out_the_kill_on_a_teammate(players):
    jett = players[JETT]
    assert sp.SUMMARY_STATS[JETT]["attackKills"] == 2
    assert jett.attack.kills == 1
    for player in players.values():
        assert player.attack.kills + player.defense.kills == player.kills


@pytest.mark.parametrize(
    ("name", "attack_kd", "defense_kd"),
    [(BRIM, 1.0, 2.0), (JETT, 0.5, 1.0), (SAGE, 1.0, 0.33), (CYPHER, 0.0, 2.0)],
)
def test_side_kd_uses_the_recounted_kills(players, name, attack_kd, defense_kd):
    assert players[name].attack.kd == attack_kd
    assert players[name].defense.kd == defense_kd


def test_side_counts_from_the_scoreboard_are_kept(players):
    attack, defense = players[BRIM].attack, players[BRIM].defense
    assert (attack.deaths, attack.assists, attack.first_kills, attack.first_deaths) == (2, 1, 1, 0)
    assert (defense.deaths, defense.assists, defense.first_kills, defense.first_deaths) == (
        1,
        0,
        1,
        1,
    )
    assert (attack.entry_success_rate, defense.entry_success_rate) == (100.0, 50.0)


def test_weapon_kills(players):
    assert players[BRIM].weapon_kills == {"Ghost": 2, "Classic": 1, "Vandal": 1}
    assert players[JETT].weapon_kills == {"Ghost": 1, "Bucky": 1}
    assert players[SAGE].weapon_kills == {"Phantom": 2, "Sheriff": 1}
    assert players[CYPHER].weapon_kills == {"Operator": 2}
    assert next(iter(players[BRIM].weapon_kills)) == "Ghost"
    assert next(iter(players[SAGE].weapon_kills)) == "Phantom"


def test_weapon_kills_add_up_to_kills(players):
    for player in players.values():
        assert sum(player.weapon_kills.values()) == player.kills


def test_suicide_spike_death_and_team_kill_are_nobodys_kill(match, players):
    events = sum(len(played.kills) for played in match.round_log)
    assert events == KILL_EVENTS
    by_weapon = Counter()
    for player in players.values():
        by_weapon.update(player.weapon_kills)
    assert sum(by_weapon.values()) == KILLS_ON_OPPONENTS
    assert "Bomb" not in by_weapon
    assert "Fall" not in by_weapon
    # Jett's only Classic kill was on Brim
    assert "Classic" not in players[JETT].weapon_kills
    duels = [duel for player in players.values() for duel in player.duels.values()]
    assert sum(duel.kills for duel in duels) == KILLS_ON_OPPONENTS


def test_suicide_is_not_a_kill_when_players_have_no_team():
    segments = [
        sp.player_summary(BRIM, None),
        sp.player_summary(SAGE, None),
        sp.kill(1, 1_000, BRIM, SAGE, "Vandal"),
        sp.kill(2, 1_000, BRIM, BRIM, None, cause="Fall"),
    ]
    brim = by_name(parse_match(sp.match_payload(segments)))[BRIM]
    assert brim.weapon_kills == {"Vandal": 1}
    assert brim.duels == {SAGE: Duel(kills=1)}


def test_a_spike_death_is_nobodys_kill_even_when_it_names_an_opponent():
    segments = [
        sp.player_summary(BRIM, RED),
        sp.player_summary(SAGE, BLUE),
        sp.kill(1, 1_000, BRIM, SAGE, "Vandal"),
        sp.kill(2, 9_000, BRIM, SAGE, None, cause="Bomb"),
    ]
    brim = by_name(parse_match(sp.match_payload(segments)))[BRIM]
    assert brim.weapon_kills == {"Vandal": 1}
    assert brim.duels == {SAGE: Duel(kills=1)}


def test_duels(players):
    assert players[BRIM].duels == {
        SAGE: Duel(kills=3, deaths=1, damage_dealt=450, damage_taken=300),
        CYPHER: Duel(kills=1, deaths=1, damage_dealt=190, damage_taken=150),
    }
    assert players[JETT].duels == {
        SAGE: Duel(kills=1, deaths=2, damage_dealt=250, damage_taken=300),
        CYPHER: Duel(kills=1, deaths=1, damage_dealt=140, damage_taken=150),
    }
    assert list(players[BRIM].duels) == [SAGE, CYPHER]
    assert list(players[SAGE].duels) == [JETT, BRIM]


def test_duel_table_mirrors_itself(players):
    for name, player in players.items():
        for opponent, duel in player.duels.items():
            mirrored = players[opponent].duels[name]
            assert (duel.kills, duel.deaths) == (mirrored.deaths, mirrored.kills)
            assert (duel.damage_dealt, duel.damage_taken) == (
                mirrored.damage_taken,
                mirrored.damage_dealt,
            )


def test_duels_are_only_against_the_other_team(players):
    for player in players.values():
        opponents = {name for name in NAMES if sp.TEAM_OF[name] != player.team}
        assert set(player.duels) == opponents


def test_duels_add_up_to_the_scoreboard(players):
    for player in players.values():
        duels = player.duels.values()
        assert sum(duel.kills for duel in duels) == player.kills
        assert sum(duel.damage_dealt for duel in duels) == player.damage
        assert sum(duel.damage_taken for duel in duels) == player.damage_received


def test_friendly_fire_is_left_out_of_damage(players):
    # Jett did 100 to Brim in round 1, which tracker.gg's round row counts.
    jett, brim = players[JETT], players[BRIM]
    assert sum(duel.damage_dealt for duel in jett.duels.values()) == 390
    assert jett.attack.adr == 56.7
    assert brim.attack.damage_delta_per_round == 43.3
    assert BRIM not in jett.duels
    assert JETT not in brim.duels


@pytest.mark.parametrize(
    ("name", "dealt", "received"),
    [
        (BRIM, (3, 9, 2), (1, 6, 0)),
        (JETT, (0, 13, 4), (2, 4, 0)),
        (SAGE, (2, 9, 0), (3, 13, 3)),
        (CYPHER, (1, 1, 0), (0, 9, 3)),
    ],
)
def test_shots_count_hits_between_the_teams(players, name, dealt, received):
    parts = ("head", "body", "leg")
    assert players[name].shots_dealt == Shots(**dict(zip(parts, dealt, strict=True)))
    assert players[name].shots_received == Shots(**dict(zip(parts, received, strict=True)))


def test_hits_dealt_by_one_team_are_the_hits_received_by_the_other(players):
    def total(team, field):
        hits = Counter()
        for player in players.values():
            if player.team == team:
                hits.update(getattr(player, field).model_dump())
        return hits

    assert total(RED, "shots_dealt") == total(BLUE, "shots_received")
    assert total(BLUE, "shots_dealt") == total(RED, "shots_received")


def test_multi_kill_rounds_leave_out_the_kill_on_a_teammate(players):
    assert sp.SUMMARY_STATS[JETT]["doubleKills"] == 1
    assert {name: players[name].double_kills for name in NAMES} == {
        BRIM: 1,
        JETT: 0,
        SAGE: 1,
        CYPHER: 1,
    }
    for player in players.values():
        assert (player.triple_kills, player.quadra_kills, player.aces, player.multi_kills) == (
            0,
            0,
            0,
            0,
        )


def test_rounds_are_counted_by_the_number_of_kills():
    foes = [f"Dummy {number}#FOE" for number in range(1, 6)]
    segments = [
        sp.player_summary(BRIM, RED, tripleKills=0, quadraKills=2, pentaKills=1, multiKills=3),
        sp.player_summary(JETT, RED),
        *(sp.player_summary(foe, BLUE) for foe in foes),
    ]
    # Five kills, then four, then three and one on a teammate, then two.
    for number, victims in enumerate((foes, foes[:4], [*foes[:3], JETT], foes[:2]), start=1):
        segments += [
            sp.kill(number, 1_000 * order, BRIM, victim, "Vandal")
            for order, victim in enumerate(victims, start=1)
        ]
    brim = by_name(parse_match(sp.match_payload(segments)))[BRIM]
    assert (brim.double_kills, brim.triple_kills, brim.quadra_kills, brim.aces) == (1, 1, 1, 1)
    assert brim.multi_kills == 3
    assert brim.weapon_kills == {"Vandal": 14}


def test_team_first_deaths(players):
    assert {name: players[name].team_first_deaths for name in NAMES} == {
        BRIM: 3,
        JETT: 1,
        SAGE: 4,
        CYPHER: 1,
    }


def test_a_spike_death_is_not_a_teams_first_death(players):
    # In round 2 the spike takes Cypher five seconds before Sage is shot.
    data = sp.sample_match()
    for segment in data["segments"]:
        if segment["type"] == "player-round-kills" and segment["attributes"]["round"] == 2:
            segment["metadata"]["finishingDamage"]["damageType"] = "Weapon"
    shot = by_name(parse_match(data))
    assert (shot[CYPHER].team_first_deaths, shot[SAGE].team_first_deaths) == (2, 3)
    assert (players[CYPHER].team_first_deaths, players[SAGE].team_first_deaths) == (1, 4)


def test_a_suicide_and_a_team_kill_are_a_teams_first_death(players):
    # Brim dies first for Red in round 1 (shot by Jett), Sage first for Blue in round 3 (fell).
    data = sp.sample_match()
    data["segments"] = [
        segment
        for segment in data["segments"]
        if segment["type"] != "player-round-kills"
        or segment["attributes"]["platformUserIdentifier"]
        != segment["attributes"]["opponentPlatformUserIdentifier"]
        and sp.TEAM_OF[segment["attributes"]["platformUserIdentifier"]]
        != sp.TEAM_OF[segment["attributes"]["opponentPlatformUserIdentifier"]]
    ]
    opponents_only = by_name(parse_match(data))
    assert (opponents_only[BRIM].team_first_deaths, opponents_only[SAGE].team_first_deaths) == (
        2,
        3,
    )
    assert (players[BRIM].team_first_deaths, players[SAGE].team_first_deaths) == (3, 4)


def test_buy_rows_are_ordered_and_skip_types_never_bought(players):
    assert list(players[BRIM].buys) == ["pistol", "semi", "full"]
    assert list(players[JETT].buys) == ["pistol", "eco", "semi"]
    assert list(players[SAGE].buys) == ["pistol", "eco", "semi", "full"]
    assert list(players[CYPHER].buys) == ["pistol", "eco", "semi", "full"]


def test_buy_row_numbers(players):
    buys = players[BRIM].buys
    assert (buys["pistol"].rounds, buys["pistol"].rounds_won, buys["pistol"].kills) == (2, 2, 3)
    assert (buys["full"].rounds, buys["full"].rounds_won, buys["full"].kills) == (3, 2, 1)
    assert sum(row.rounds for row in buys.values()) == 6
    # Cypher sat out round 6, which tracker.gg gives no buy type
    assert sum(row.rounds for row in players[CYPHER].buys.values()) == 5


def test_buy_rows_carry_no_headshot_rate(players):
    rows = [row for player in players.values() for row in player.buys.values()]
    assert len(rows) == 14
    assert all(row.hs_pct is None for row in rows)


def test_buy_rows_agree_with_the_buy_types_in_the_round_log(match, players):
    for name, player in players.items():
        seen = Counter(
            line.buy
            for played in match.round_log
            for line in played.players
            if line.riot_id == name and line.buy
        )
        assert seen == {kind: row.rounds for kind, row in player.buys.items()}


def test_credits_spent_and_average_loadout(players):
    assert {name: players[name].credits_spent for name in NAMES} == {
        BRIM: 15_050,
        JETT: 10_150,
        SAGE: 14_550,
        CYPHER: 6_950,
    }
    assert {name: players[name].avg_loadout_value for name in NAMES} == {
        BRIM: 3_050,
        JETT: 2_342,
        SAGE: 2_958,
        CYPHER: 1_558,
    }


def test_entry_success_rate_is_a_percentage(players):
    assert {name: players[name].entry_success_rate for name in NAMES} == {
        BRIM: 66.7,
        JETT: 50.0,
        SAGE: 40.0,
        CYPHER: 0.0,
    }


def test_entry_success_rate_is_on_the_same_scale_as_on_a_profile(players):
    # Two first kills and one first death: tracker.gg says 66.67 here and 0.6667 on a profile.
    row = sp.segment("season", firstBloods=2, firstDeaths=1, esr=0.6667)
    profile = parse_stats_bundle([row]).season_stats
    assert sp.SUMMARY_STATS[BRIM]["esr"] == pytest.approx(66.67, abs=0.01)
    assert profile.entry_success_rate == players[BRIM].entry_success_rate == 66.7


def test_ability_casts_are_keyed_by_slot_without_kills(players):
    assert players[BRIM].ability_casts == {"c": 3, "q": 4, "e": 6, "x": 1}
    assert players[JETT].ability_casts is None
    assert not [key for key in players[BRIM].dump() if "ability" in key and "cast" not in key]


def test_clutches_by_size(players):
    cypher, sage = players[CYPHER], players[SAGE]
    assert (cypher.clutches, cypher.clutches_by_size) == (1, {"1v2": 1})
    assert (cypher.clutches_lost, cypher.clutches_lost_by_size) == (0, None)
    assert (sage.clutches, sage.clutches_by_size) == (0, None)
    assert (sage.clutches_lost, sage.clutches_lost_by_size) == (1, {"1v2": 1})


def test_scoreboard_without_round_data_has_no_round_numbers():
    data = sp.sample_match()
    data["segments"] = [
        segment
        for segment in data["segments"]
        if segment["type"] in ("team-summary", "player-summary")
    ]
    match = parse_match(data)
    brim = by_name(match)[BRIM]
    assert match.round_log is None
    assert (brim.kills, brim.attack.kills, brim.defense.deaths) == (4, 2, 1)
    for split in (brim.attack, brim.defense):
        assert split.rounds is None
        assert (split.acs, split.adr) == (None, None)
        assert (split.round_win_rate, split.damage_delta_per_round) == (None, None)
    assert (brim.buys, brim.weapon_kills, brim.duels) == (None, None, None)
    assert (brim.credits_spent, brim.avg_loadout_value) == (None, None)
    assert brim.team_first_deaths is None
    assert brim.shots_dealt == Shots(head=3)
    assert [team.started_on for team in match.teams] == [None, None]


def test_match_that_ended_before_the_sides_swapped_has_one_side():
    data = sp.sample_match()
    data["segments"] = [
        segment for segment in data["segments"] if (segment["attributes"].get("round") or 0) <= 3
    ]
    players = by_name(parse_match(data))
    assert players[BRIM].defense is None
    assert players[SAGE].attack is None
    assert (players[BRIM].attack.rounds, players[BRIM].attack.acs) == (3, 200.0)
    assert (players[SAGE].defense.rounds, players[SAGE].defense.acs) == (3, 86.7)


def test_without_damage_rows_adr_comes_from_the_round_rows():
    cypher = by_name(parse_match(without(sp.sample_match(), "player-round-damage")))[CYPHER]
    # 300 damage in round 3 is all of Cypher's defense half
    assert cypher.defense.adr == 100.0
    assert cypher.defense.damage_delta_per_round is None
    assert cypher.shots_dealt == Shots(head=1)
    assert cypher.shots_received is None
    assert cypher.duels[JETT] == Duel(kills=1, deaths=1)
