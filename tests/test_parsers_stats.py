"""parse_stats_bundle: the overall line, agents, maps, roles and weapons of one scope."""

import pytest
from sample_payloads import segment, stat_segments

from models import Ability, Rank, Shots, StatsBundle
from scraper.parsers import parse_stats_bundle


@pytest.fixture
def act():
    return parse_stats_bundle(stat_segments())


@pytest.fixture
def all_acts():
    return parse_stats_bundle(stat_segments(None))


def test_headline_numbers_are_rounded(act):
    stats = act.season_stats
    assert (stats.kd, stats.kda) == (1.2, 1.6)
    assert (stats.acs, stats.adr, stats.damage_delta_per_round) == (231.5, 150.3, 12.3)
    assert (stats.hs_pct, stats.kast) == (24.6, 71.2)
    assert (stats.win_rate, stats.round_win_rate) == (60.0, 54.8)
    assert (stats.performance_score, stats.econ_rating) == (55.6, 61.3)
    assert stats.tracker_score == 742


def test_record_adds_up(act):
    stats = act.season_stats
    assert stats.wins + stats.losses + stats.ties == stats.matches == 20
    assert stats.rounds_won + stats.rounds_lost == stats.rounds == 420


def test_sides_add_up_to_the_whole(act):
    stats = act.season_stats
    attack, defense = stats.attack, stats.defense
    assert attack.rounds + defense.rounds == stats.rounds
    assert attack.rounds_won + defense.rounds_won == stats.rounds_won
    assert attack.kills + defense.kills == stats.kills
    assert attack.deaths + defense.deaths == stats.deaths
    assert attack.first_kills + defense.first_kills == stats.first_kills
    assert attack.trade_kills + defense.trade_kills == stats.trade_kills
    assert (attack.round_win_rate, defense.round_win_rate) == (51.2, 58.5)


def test_time_played_comes_in_hours_and_match_length_in_minutes(act):
    assert act.season_stats.hours_played == 12.5
    assert act.season_stats.avg_match_minutes == 35.0


def test_entry_success_rate_is_first_kills_as_a_percentage_of_opened_rounds(act):
    stats = act.season_stats
    assert (stats.first_kills, stats.first_deaths) == (45, 30)
    assert stats.entry_success_rate == 60.0
    assert stats.attack.entry_success_rate == 60.0
    assert stats.defense.entry_success_rate == 60.0


def test_entry_success_rate_is_missing_when_no_round_was_opened():
    stats = parse_stats_bundle([segment("season", firstBloods=0, firstDeaths=0, esr=0)])
    assert stats.season_stats.entry_success_rate is None


def test_clutches_by_size_add_up_and_skip_sizes_that_never_happened(act):
    stats = act.season_stats
    assert stats.clutches_by_size == {"1v1": 5, "1v2": 3, "1v3": 1}
    assert sum(stats.clutches_by_size.values()) == stats.clutches
    assert stats.clutches_lost_by_size == {"1v1": 4, "1v2": 6, "1v3": 4}
    assert sum(stats.clutches_lost_by_size.values()) == stats.clutches_lost


def test_multi_kills_are_the_rounds_with_three_or_more_kills(act):
    stats = act.season_stats
    assert (stats.double_kills, stats.triple_kills, stats.quadra_kills) == (30, 10, 3)
    # 10 rounds with three kills, 3 with four and 1 with five
    assert stats.multi_kills == 14


def test_ability_casts_are_keyed_by_slot(act):
    assert act.season_stats.ability_casts == {"c": 100, "q": 200, "e": 150, "x": 40}


def test_shots_are_split_by_body_part(act):
    assert act.season_stats.shots_dealt == Shots(head=280, body=800, leg=60)
    assert act.season_stats.shots_received == Shots(head=200, body=700, leg=90)


def test_rank_takes_its_tier_number_from_the_icon(act):
    assert act.season_stats.rank == Rank(tier="Gold 2", tier_id=13)


def test_peak_rank_carries_rating_position_and_act(act):
    assert act.season_stats.peak_rank == Rank(
        tier="Immortal 3", tier_id=26, rr=312, leaderboard_rank=480, act="E26: A4"
    )


def test_percentiles_are_keyed_by_our_stat_names(act):
    assert act.season_stats.percentiles == {"win_rate": 71.5, "kd": 88.0, "acs": 93.2}


def test_agents_are_sorted_by_matches_and_add_up_to_the_act(act):
    assert [(row.agent, row.role, row.matches) for row in act.agents] == [
        ("Jett", "Duelist", 12),
        ("Sage", "Sentinel", 8),
    ]
    assert sum(row.matches for row in act.agents) == act.season_stats.matches
    assert sum(row.kills for row in act.agents) == act.season_stats.kills
    assert sum(row.pick_rate for row in act.agents) == 100.0


def test_agent_abilities_carry_name_and_casts(act):
    jett, sage = act.agents
    assert jett.abilities == {
        "c": Ability(name="Cloudburst", casts=30),
        "q": Ability(name="Updraft", casts=45),
        "e": Ability(name="Tailwind", casts=80),
        "x": Ability(name="Blade Storm", casts=9),
    }
    assert jett.ability_casts is None
    assert sage.abilities == {"c": Ability(casts=31), "x": Ability(casts=6)}


def test_kills_per_ability_are_not_reported(act):
    assert "kills" not in Ability.model_fields
    jett = act.agents[0].dump()
    assert all(set(ability) == {"name", "casts"} for ability in jett["abilities"].values())
    assert not [key for key in act.season_stats.dump() if "ability" in key and "cast" not in key]


def test_agent_top_maps_are_the_three_most_played(act):
    jett, sage = act.agents
    assert [(entry.name, entry.matches) for entry in jett.top_maps] == [
        ("Ascent", 5),
        ("District Nine", 4),
        ("Split", 2),
    ]
    ascent = jett.top_maps[0]
    assert (ascent.wins, ascent.losses, ascent.kd) == (4, 1, 1.52)
    assert [(entry.name, entry.matches) for entry in sage.top_maps] == [("Split", 4)]


def test_maps_are_sorted_by_matches_and_add_up_to_the_act(act):
    assert [(row.map, row.matches) for row in act.maps] == [
        ("Ascent", 10),
        ("Split", 6),
        ("Bind", 4),
    ]
    assert sum(row.matches for row in act.maps) == act.season_stats.matches


def test_map_top_agents_are_the_three_most_played(act):
    ascent, split, bind = act.maps
    assert [(entry.name, entry.matches) for entry in ascent.top_agents] == [
        ("Jett", 4),
        ("Sage", 3),
        ("Sova", 2),
    ]
    assert (ascent.top_agents[0].win_rate, ascent.top_agents[0].acs) == (75.0, 250.0)
    assert [entry.name for entry in split.top_agents] == ["Sage"]
    assert bind.top_agents is None


def test_map_rows_keep_their_attack_and_defense_numbers(act):
    ascent = act.maps[0]
    assert (ascent.attack.rounds, ascent.attack.rounds_won) == (100, 48)
    assert (ascent.defense.rounds, ascent.defense.rounds_won) == (110, 67)


def test_roles_are_sorted_by_matches(act):
    assert [(row.role, row.matches, row.kills) for row in act.roles] == [
        ("Duelist", 12, 200),
        ("Sentinel", 8, 100),
    ]


def test_weapons_are_sorted_by_kills(act):
    assert [(row.weapon, row.category, row.kills) for row in act.weapons] == [
        ("Vandal", "Rifle", 120),
        ("Classic", "Sidearm", 20),
        ("Melee", "Melee", 0),
    ]


def test_weapon_row_numbers(act):
    vandal, classic, _ = act.weapons
    assert (vandal.matches, vandal.rounds, vandal.deaths) == (18, 200, 90)
    assert (vandal.kd, vandal.hs_pct, vandal.damage) == (1.33, 31.3, 21_000)
    assert vandal.shots_dealt == Shots(head=100, body=200, leg=20)
    assert (vandal.alt_fire_kills, classic.alt_fire_kills) == (0, 6)


def test_weapon_kill_distances_are_in_metres(act):
    vandal, classic, melee = act.weapons
    # 240000 cm over 120 kills, and 15000 cm over 20
    assert (vandal.avg_kill_distance_m, classic.avg_kill_distance_m) == (20.0, 7.5)
    assert (vandal.longest_kill_m, classic.longest_kill_m) == (52.3, 21.1)
    assert melee.avg_kill_distance_m is None
    assert melee.longest_kill_m is None


def test_one_act_keeps_the_numbers_that_exist_per_act(act):
    stats = act.season_stats
    assert (stats.mvps, stats.thrifty_rounds, stats.trade_kills) == (6, 5, 22)
    assert (stats.attack.trade_kills, stats.defense.trade_kills) == (12, 10)
    assert sum(row.mvps for row in act.agents) == stats.mvps
    assert sum(row.thrifty_rounds for row in act.maps) == stats.thrifty_rounds
    assert sum(row.trade_kills for row in act.roles) == stats.trade_kills
    assert [row.damage_received for row in act.weapons[:2]] == [15_000, 1_800]


def test_all_act_totals_leave_out_the_placeholder_numbers(all_acts):
    rows = [all_acts.season_stats, *all_acts.agents, *all_acts.maps, *all_acts.roles]
    assert len(rows) == 8
    for row in rows:
        assert (row.mvps, row.thrifty_rounds, row.trade_kills) == (None, None, None)
        for side in (row.attack, row.defense):
            assert side is None or side.trade_kills is None
    assert [row.damage_received for row in all_acts.weapons] == [None, None, None]


def test_all_act_totals_keep_everything_else(act, all_acts):
    hidden = {"mvps": None, "thrifty_rounds": None, "trade_kills": None}
    expected = act.season_stats.model_copy(deep=True, update=hidden)
    expected.attack.trade_kills = expected.defense.trade_kills = None
    assert all_acts.season_stats == expected
    assert all_acts.agents[0].attack.kills == 110
    assert [row.damage for row in all_acts.weapons[:2]] == [21_000, 3_100]
    assert [row.kills for row in all_acts.weapons] == [row.kills for row in act.weapons]


def test_only_the_first_overall_segment_is_used():
    bundle = parse_stats_bundle([segment("season", kills=7), segment("season", kills=99)])
    assert bundle.season_stats.kills == 7


def test_no_segments_give_an_empty_bundle():
    assert parse_stats_bundle([]) == StatsBundle()
    assert parse_stats_bundle(None) == StatsBundle()
