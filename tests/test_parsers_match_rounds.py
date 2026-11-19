"""parse_match: the round log, with spike events, kills, positions and buy types."""

import pytest
import sample_payloads as sp
from sample_payloads import BLUE, BRIM, CYPHER, JETT, RED, SAGE

from models import SpikeEvent
from scraper.parsers import parse_match

NAMES = (BRIM, JETT, SAGE, CYPHER)


def lines_of(rounds, name):
    return [line for played in rounds for line in played.players if line.riot_id == name]


def round_row(data, number, name):
    return next(
        segment
        for segment in data["segments"]
        if segment["type"] == "player-round"
        and segment["attributes"] == {"round": number, "platformUserIdentifier": name}
    )


def one_kill_match(killer_at, victim_at, **metadata):
    segments = [
        sp.player_summary(BRIM, RED),
        sp.player_summary(SAGE, BLUE),
        sp.round_summary(1, RED, "Elimination"),
        sp.kill(1, 1_000, BRIM, SAGE, "Vandal", killer_at=killer_at, victim_at=victim_at),
    ]
    return parse_match(sp.match_payload(segments, **metadata)).round_log[0].kills[0]


@pytest.fixture
def match():
    return parse_match(sp.sample_match())


@pytest.fixture
def rounds(match):
    return match.round_log


def test_round_log_lists_every_round_in_order(rounds):
    assert [
        (played.round, played.attackers, played.winner, played.ending) for played in rounds
    ] == [
        (1, RED, RED, "Elimination"),
        (2, RED, RED, "Bomb detonated"),
        (3, RED, BLUE, "Elimination"),
        (4, BLUE, RED, "Bomb defused"),
        (5, BLUE, BLUE, "Elimination"),
        (6, BLUE, RED, "Elimination"),
    ]


def test_round_wins_by_ending_add_up_to_the_score(match):
    red, blue = match.teams
    assert red.round_wins == {"Elimination": 2, "Bomb detonated": 1, "Bomb defused": 1}
    assert blue.round_wins == {"Elimination": 2}
    for team in match.teams:
        assert sum(team.round_wins.values()) == team.rounds_won


def test_plants_are_counted_per_team_and_site(match):
    red, blue = match.teams
    assert red.plants_by_site == {"A": 1}
    assert blue.plants_by_site == {"B": 1}


def test_spike_plant_and_detonation(rounds):
    played = rounds[1]
    assert played.plant == SpikeEvent(by=BRIM, site="A", time=30.0, at=[0.4, 0.3])
    assert played.detonated_at == 75.0
    assert played.defuse is None


def test_spike_plant_and_defuse(rounds):
    played = rounds[3]
    assert played.plant == SpikeEvent(by=SAGE, site="B", time=40.0, at=[0.6, 0.6])
    assert played.defuse == SpikeEvent(by=JETT, time=70.0, at=[0.6, 0.6])
    assert played.detonated_at is None


def test_rounds_without_a_plant_have_no_spike_events(rounds):
    for played in (rounds[0], rounds[2], rounds[4], rounds[5]):
        assert (played.plant, played.defuse, played.detonated_at) == (None, None, None)


def test_kills_are_listed_in_time_order_in_seconds(rounds):
    first = [(kill.time, kill.killer, kill.victim, kill.weapon) for kill in rounds[0].kills]
    assert first == [
        (20.0, BRIM, SAGE, "Classic"),
        (28.0, JETT, BRIM, "Classic"),
        (35.5, JETT, CYPHER, "Ghost"),
    ]
    for played in rounds:
        times = [kill.time for kill in played.kills]
        assert times == sorted(times)


def test_kill_assists_and_alternate_fire(rounds):
    kills = [kill for played in rounds for kill in played.kills]
    assert [kill.assists for kill in kills if kill.assists] == [[JETT]]
    assert [(kill.weapon, kill.killer) for kill in kills if kill.alt_fire] == [("Bucky", JETT)]
    assert {kill.alt_fire for kill in kills} == {True, None}


def test_log_keeps_the_suicide_team_kill_and_spike_death(rounds):
    kills = [(kill.killer, kill.victim, kill.weapon) for played in rounds for kill in played.kills]
    assert len(kills) == 14
    assert (JETT, BRIM, "Classic") in kills
    assert (SAGE, SAGE, "Fall") in kills
    assert [kill for kill in kills if kill[2] == "Bomb"] == [(CYPHER, CYPHER, "Bomb")]
    assert [kill.weapon for kill in rounds[1].kills] == ["Sheriff", "Bomb", "Vandal"]


def test_round_lines_count_kills_and_damage_on_the_other_team_only(rounds):
    jett = lines_of(rounds, JETT)[0]
    row = sp.ROUND_ROWS[JETT][0]
    assert (row[3], row[5]) == (2, 240)
    assert (jett.kills, jett.damage) == (1, 140)
    sage = lines_of(rounds, SAGE)[2]
    assert (sage.kills, sage.damage, sage.deaths) == (0, 0, 1)


def test_round_lines_add_up_to_the_scoreboard(match, rounds):
    for player in match.players:
        lines = lines_of(rounds, player.riot_id)
        assert len(lines) == 6
        assert sum(line.kills for line in lines) == player.kills
        assert sum(line.damage for line in lines) == player.damage
        assert sum(line.score for line in lines) == player.combat_score
        assert sum(line.spent for line in lines) == player.credits_spent


def test_round_line_carries_the_players_economy(rounds):
    brim = lines_of(rounds, BRIM)[1]
    assert (brim.loadout_value, brim.spent, brim.remaining) == (4700, 3900, 5100)
    assert (brim.score, brim.kills, brim.deaths, brim.assists, brim.damage) == (250, 1, 0, 0, 150)


def test_buy_types_per_round(rounds):
    assert {name: [line.buy for line in lines_of(rounds, name)] for name in NAMES} == {
        BRIM: ["pistol", "full", "full", "pistol", "semi", "full"],
        JETT: ["pistol", "semi", "semi", "pistol", "eco", "semi"],
        SAGE: ["pistol", "eco", "full", "pistol", "semi", "full"],
        CYPHER: ["pistol", "semi", "eco", "pistol", "full", None],
    }


@pytest.mark.parametrize(
    ("spent", "buy"),
    [(0, "eco"), (1000, "eco"), (1050, "semi"), (3850, "semi"), (3900, "full"), (9000, "full")],
)
def test_buy_type_goes_by_credits_spent(spent, buy):
    data = sp.sample_match()
    round_row(data, 2, BRIM)["stats"]["spentCredits"]["value"] = spent
    assert lines_of(parse_match(data).round_log, BRIM)[1].buy == buy


def test_buy_type_is_unknown_without_the_credits_spent():
    data = sp.sample_match()
    del round_row(data, 2, BRIM)["stats"]["spentCredits"]
    assert lines_of(parse_match(data).round_log, BRIM)[1].buy is None


def test_first_round_of_each_half_is_a_pistol_round_whatever_was_spent(rounds):
    assert sp.ROUND_ROWS[JETT][3][0] == 0
    for played in rounds:
        buys = {line.buy for line in played.players if not line.away}
        assert (buys == {"pistol"}) == (played.round in (1, 4))
        assert ("pistol" in buys) == (played.round in (1, 4))
    data = sp.sample_match()
    round_row(data, 1, BRIM)["stats"]["spentCredits"]["value"] = 5000
    assert lines_of(parse_match(data).round_log, BRIM)[0].buy == "pistol"


def test_side_swaps_in_overtime_are_not_pistol_rounds():
    attacking = [RED, RED, BLUE, BLUE, RED, BLUE]
    segments = [sp.player_summary(BRIM, RED), sp.player_summary(SAGE, BLUE)]
    for number, attackers in enumerate(attacking, start=1):
        segments.append(sp.round_summary(number, RED, "Elimination"))
        for name, team in ((BRIM, RED), (SAGE, BLUE)):
            side = "attacker" if team == attackers else "defender"
            row = sp.player_round(number, name, team, side, team == RED, spentCredits=2000)
            segments.append(row)
    rounds = parse_match(sp.match_payload(segments)).round_log
    expected = ["pistol", "semi", "pistol", "semi", "semi", "semi"]
    assert [line.buy for line in lines_of(rounds, BRIM)] == expected
    assert [line.buy for line in lines_of(rounds, SAGE)] == expected
    assert [played.attackers for played in rounds] == attacking


def test_player_who_was_not_in_the_game_for_a_round_is_away(rounds):
    away = [
        (played.round, line.riot_id) for played in rounds for line in played.players if line.away
    ]
    assert away == [(6, CYPHER)]
    cypher = lines_of(rounds, CYPHER)[5]
    assert cypher.buy is None
    assert (cypher.spent, cypher.loadout_value, cypher.score) == (0, 0, 0)


def test_idle_player_seen_during_the_round_is_not_away():
    data = sp.sample_match()
    shot = next(
        segment
        for segment in data["segments"]
        if segment["type"] == "player-round-kills" and segment["attributes"]["round"] == 6
    )
    shot["metadata"]["playerLocations"].append(
        {"platformUserIdentifier": CYPHER, "location": sp.spot(0, 0)}
    )
    cypher = lines_of(parse_match(data).round_log, CYPHER)[5]
    assert cypher.away is None
    assert cypher.buy == "eco"


def test_kill_positions_are_minimap_coordinates(rounds):
    kill = rounds[0].kills[0]
    # Brim stood at game x 1000, y 2000: minimap x is 2000 * 0.0001 + 0.5 and
    # minimap y is 1000 * -0.0001 + 0.5. Sage fell at x 1000, y 5000.
    assert kill.killer_at == [0.7, 0.4]
    assert kill.victim_at == [1.0, 0.4]


def test_positions_are_rounded_to_three_decimals():
    kill = one_kill_match(sp.spot(1234, 0), sp.spot(0, -4321))
    assert kill.killer_at == [0.5, 0.377]
    assert kill.victim_at == [0.068, 0.5]


def test_position_off_the_map_picture_is_left_out(rounds):
    kill = rounds[2].kills[2]
    assert (kill.killer, kill.victim) == (CYPHER, JETT)
    assert kill.killer_at == [0.5, 0.5]
    assert kill.victim_at is None
    assert kill.distance_m is None


def test_kill_without_positions(rounds):
    kill = rounds[0].kills[2]
    assert (kill.killer_at, kill.victim_at, kill.distance_m) == (None, None, None)
    victim_only = rounds[2].kills[1]
    assert (victim_only.killer_at, victim_only.victim_at) == (None, [0.5, 0.5])
    assert victim_only.distance_m is None


def test_no_minimap_positions_without_the_maps_numbers():
    kill = one_kill_match(sp.spot(1000, 2000), sp.spot(1000, 5000), mapDetails=None)
    assert (kill.killer_at, kill.victim_at) == (None, None)
    assert kill.distance_m == 30.0


@pytest.mark.parametrize(
    ("victim_at", "metres"),
    [
        ((300, 400), 5.0),
        ((0, 1250), 12.5),
        ((1234, 0), 12.3),
        ((15_000, 0), 150.0),
        ((15_010, 0), None),
        ((0, -40_000), None),
    ],
)
def test_kill_distance_is_in_metres_up_to_150(victim_at, metres):
    assert one_kill_match(sp.spot(0, 0), sp.spot(*victim_at)).distance_m == metres


def test_kill_distances_in_the_sample_match(rounds):
    assert rounds[0].kills[0].distance_m == 30.0
    assert rounds[1].kills[2].distance_m == 12.5
    # 11000 cm apart on both axes is about 155.6 m, though both spots are on the minimap
    far = rounds[1].kills[0]
    assert (far.killer_at, far.victim_at) == ([-0.05, 1.05], [1.05, -0.05])
    assert far.distance_m is None


def test_spike_position_is_a_minimap_coordinate(rounds):
    # planted at game x 2000, y -1000
    assert rounds[1].plant.at == [0.4, 0.3]
    data = sp.sample_match()
    summary = next(
        segment
        for segment in data["segments"]
        if segment["type"] == "round-summary" and segment["attributes"]["round"] == 2
    )
    summary["metadata"]["plant"]["location"] = None
    plant = parse_match(data).round_log[1].plant
    assert (plant.by, plant.site, plant.time, plant.at) == (BRIM, "A", 30.0, None)
