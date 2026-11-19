"""Teammate and round statistics, checked against totals worked out by hand."""

from __future__ import annotations

import pytest
from sample_matches import (
    JETT,
    ME,
    OMEN,
    SAGE,
    SOVA,
    VIPER,
    match,
    match_id,
    player,
    round_match,
    scoreboards,
    short_round_match,
)

import analysis
from models import Kill, MatchEntry, MatchTeam, Round, RoundPlayer

DETAIL_ONLY = {"attack", "defense", "buys", "weapon_kills", "tags"}


def teammates(**options) -> dict:
    return analysis.teammate_stats(ME, scoreboards(), **options)


def by_name(result: dict) -> dict[str, dict]:
    return {row["riot_id"]: row for row in result["teammates"]}


def rounds_of(*matches) -> dict:
    return analysis.round_stats(ME, list(matches))


def tally(rounds: int, won: int, win_rate: float) -> dict:
    return {"rounds": rounds, "won": won, "win_rate": win_rate}


def lines(*buys: str | None) -> list[RoundPlayer]:
    return [RoundPlayer(riot_id=f"Player {n}#TST", buy=buy) for n, buy in enumerate(buys)]


def test_teammates_are_ranked_by_matches_played_together():
    result = teammates()
    rows = result["teammates"]
    assert [row["riot_id"] for row in rows] == [JETT, OMEN, SAGE]
    assert [row["games_together"] for row in rows] == [3, 2, 2]
    assert [row["rank"] for row in rows] == [1, 2, 3]
    assert result["matches_analyzed"] == 4
    assert result["teammates_seen"] == 3


def test_equal_matches_together_are_ordered_by_matches_in_the_same_party():
    rows = by_name(teammates())
    # SAGE won both shared matches and OMEN none, yet OMEN queued with ME once.
    assert (rows[OMEN]["games_in_party"], rows[SAGE]["games_in_party"]) == (1, 0)
    assert rows[OMEN]["rank"] < rows[SAGE]["rank"]
    # A match in which neither is in a party is not a match in the same party.
    assert rows[JETT]["games_in_party"] == 2


def test_top_limits_the_rows_without_changing_what_was_counted():
    result = teammates(top=2)
    assert [row["riot_id"] for row in result["teammates"]] == [JETT, OMEN]
    assert result["teammates_seen"] == 3
    assert result["teammates"] == teammates()["teammates"][:2]
    assert teammates(top=0)["teammates"] == []


def test_opponents_and_unnamed_players_are_not_teammates():
    assert set(by_name(teammates())) == {JETT, OMEN, SAGE}


def test_teammate_row_has_their_own_totals():
    jett = by_name(teammates())[JETT]
    assert (jett["kills"], jett["deaths"], jett["assists"]) == (47, 43, 10)
    assert jett["kd"] == 1.09
    assert (jett["wins"], jett["losses"], jett["win_rate"]) == (2, 1, 66.7)
    assert jett["rounds"] == 60
    assert jett["account_level"] == 82
    assert jett["agents"] == {"Jett": 2, "Raze": 1}
    assert "games" not in jett


def test_a_draw_is_neither_a_win_nor_a_loss():
    omen = by_name(teammates())[OMEN]
    assert (omen["games_together"], omen["wins"], omen["losses"]) == (2, 0, 1)
    assert omen["win_rate"] == 0.0


def test_missing_values_are_skipped_instead_of_counted_as_zero():
    # JETT's third line has no ACS, opening duels, trades or clutches: 44 of the 60 rounds count.
    jett = by_name(teammates())[JETT]
    assert jett["acs"] == 232.7
    assert (jett["first_kills"], jett["first_deaths"]) == (10, 8)
    assert jett["first_kill_rate"] == 22.7
    assert jett["first_death_rate"] == 18.2
    assert jett["entry_success_rate"] == 55.6
    assert (jett["deaths_traded"], jett["deaths_traded_rate"]) == (11, 40.7)
    assert (jett["clutches"], jett["clutches_lost"], jett["clutch_win_rate"]) == (3, 1, 75.0)
    assert jett["clutches_by_size"] == {"1v1": 1, "1v2": 2}
    assert list(jett["clutches_by_size"]) == ["1v1", "1v2"]


def test_unreported_stats_are_left_out_while_real_zeros_stay():
    sage = by_name(teammates())[SAGE]
    assert (sage["first_kills"], sage["first_deaths"], sage["clutches"]) == (0, 0, 0)
    assert sage["first_kill_rate"] == 0.0
    # No opening duel and no clutch situation, so there is nothing to take a share of.
    for absent in ("entry_success_rate", "clutch_win_rate", "deaths_traded", "hs_pct", "adr"):
        assert absent not in sage


def test_averages_are_weighted_by_rounds_played():
    rows = by_name(teammates())
    # 150 over 20 rounds and 195 over 16; 180 over 24 and 240 over 30.
    assert rows[SAGE]["acs"] == 170.0
    assert rows[OMEN]["acs"] == 213.3
    assert (rows[SAGE]["rounds_survived"], rows[SAGE]["survival_rate"]) == (18, 50.0)


def test_record_with_and_without_each_teammate():
    rows = by_name(teammates())
    with_sage = {"games": 2, "wins": 2, "win_rate": 100.0, "kd": 2.0, "acs": 272.2}
    with_omen = {"games": 2, "wins": 0, "win_rate": 0.0, "kd": 0.86, "acs": 177.8}
    assert rows[JETT]["your_record_with"] == {
        "games": 3,
        "wins": 2,
        "win_rate": 66.7,
        "kd": 1.33,
        "acs": 223.3,
    }
    assert rows[JETT]["your_record_without"] == {
        "games": 1,
        "wins": 0,
        "win_rate": 0.0,
        "kd": 1.0,
        "acs": 200.0,
    }
    assert rows[SAGE]["your_record_with"] == with_sage
    assert rows[SAGE]["your_record_without"] == with_omen
    assert rows[OMEN]["your_record_with"] == with_omen
    assert rows[OMEN]["your_record_without"] == with_sage


def test_record_without_is_left_out_for_a_teammate_who_never_missed_a_match():
    everyone = [player(ME, "Red", 10, 10, 2), player(JETT, "Red", 8, 9, 3), player(VIPER, "Blue")]
    row = analysis.teammate_stats(ME, [match(21, "Bind", 20, "Red", everyone)])["teammates"][0]
    assert row["your_record_with"]["games"] == 1
    assert "your_record_without" not in row


def test_records_with_and_without_add_up_to_all_matches():
    result = teammates()
    for row in result["teammates"]:
        together, apart = row["your_record_with"], row["your_record_without"]
        assert together["games"] == row["games_together"]
        assert together["games"] + apart["games"] == result["matches_analyzed"]
        assert together["wins"] + apart["wins"] == result["your_stats"]["wins"]


def test_per_map_breakdown_of_a_teammate():
    result = teammates()
    assert by_name(result)[JETT]["by_map"] == {
        "Ascent": {"games": 2, "wins": 2, "win_rate": 100.0, "kd": 0.74, "acs": 200.0},
        "Bind": {"games": 1, "wins": 0, "win_rate": 0.0, "kd": 2.0, "acs": 260.0},
    }
    for row in result["teammates"]:
        assert sum(entry["games"] for entry in row["by_map"].values()) == row["games_together"]
        assert sum(entry["wins"] for entry in row["by_map"].values()) == row["wins"]


def test_your_stats_cover_every_analysed_match():
    own = teammates()["your_stats"]
    assert (own["games"], own["wins"], own["losses"], own["win_rate"]) == (4, 2, 1, 50.0)
    assert (own["kills"], own["deaths"], own["assists"], own["kd"]) == (72, 60, 21, 1.2)
    assert own["rounds"] == 90
    assert own["acs"] == 215.6
    # ADR and first kills are known for some matches only.
    assert own["adr"] == 127.3
    assert (own["first_kills"], own["first_kill_rate"]) == (3, 15.0)


def test_most_played_rank_comes_from_the_given_list():
    listed = [OMEN.upper(), "Stranger Danger#NOPE", JETT]
    rows = by_name(teammates(most_played=listed))
    assert rows[OMEN]["most_played_rank"] == 1
    assert rows[JETT]["most_played_rank"] == 3
    assert "most_played_rank" not in rows[SAGE]
    assert all("most_played_rank" not in row for row in teammates()["teammates"])


def test_riot_ids_are_matched_whatever_their_case():
    assert analysis.teammate_stats(ME.upper(), scoreboards()) == teammates()
    # One scoreboard spells JETT in capitals: still one teammate, under the first spelling seen.
    names = [row["riot_id"] for row in teammates()["teammates"]]
    assert names.count(JETT) == 1
    assert JETT.upper() not in names


def test_match_without_the_player_is_not_analysed():
    stranger = match(
        5,
        "Lotus",
        13,
        "Red",
        [player(JETT, "Red", 30, 0, 0), player(VIPER, "Blue", 0, 30, 0)],
    )
    assert analysis.teammate_stats(ME, [*scoreboards(), stranger]) == teammates()


def test_headline_view_is_a_subset_of_the_detailed_view():
    brief, full = teammates(), teammates(detailed=True)
    assert brief["your_stats"].items() <= full["your_stats"].items()
    assert len(brief["teammates"]) == len(full["teammates"])
    for short, long in zip(brief["teammates"], full["teammates"], strict=True):
        assert short.items() <= long.items()
        assert set(long) - set(short) <= DETAIL_ONLY
    assert set(by_name(full)[JETT]) - set(by_name(brief)[JETT]) == DETAIL_ONLY


def test_detailed_sides_add_up_to_the_matches_that_have_them():
    jett = by_name(teammates(detailed=True))[JETT]
    assert jett["attack"] == {
        "kills": 23,
        "deaths": 13,
        "kd": 1.77,
        "acs": 240.0,
        "rounds": 24,
        "rounds_won": 12,
        "round_win_rate": 50.0,
    }
    assert jett["defense"] == {
        "kills": 16,
        "deaths": 14,
        "kd": 1.14,
        "acs": 226.0,
        "rounds": 20,
        "rounds_won": 12,
        "round_win_rate": 60.0,
    }
    # The third scoreboard has no sides, so the two cover its first two: 15 + 24 kills in 44 rounds.
    assert jett["attack"]["kills"] + jett["defense"]["kills"] == 39
    assert jett["attack"]["rounds"] + jett["defense"]["rounds"] == 44


def test_detailed_buys_add_up_to_the_matches_that_have_them():
    buys = by_name(teammates(detailed=True))[JETT]["buys"]
    assert buys == {
        "pistol": {"kills": 4, "deaths": 3, "kd": 1.33, "rounds": 4},
        "full": {"kills": 32, "deaths": 20, "kd": 1.6, "rounds": 36},
        "eco": {"kills": 3, "deaths": 4, "kd": 0.75, "rounds": 4},
    }
    assert sum(buy["rounds"] for buy in buys.values()) == 44
    assert sum(buy["kills"] for buy in buys.values()) == 39


def test_kills_by_weapon_add_up_to_kills():
    jett = by_name(teammates(detailed=True))[JETT]
    assert jett["weapon_kills"] == {"Vandal": 24, "Operator": 10, "Phantom": 8, "Sheriff": 5}
    assert list(jett["weapon_kills"]) == ["Vandal", "Operator", "Phantom", "Sheriff"]
    assert sum(jett["weapon_kills"].values()) == jett["kills"]
    assert jett["tags"] == {"Top Frag": 2, "Trader": 1}


def test_teammate_without_detail_data_gets_no_empty_blocks():
    sage = by_name(teammates(detailed=True))[SAGE]
    assert not DETAIL_ONLY & set(sage)


def renamed_match(*extra_rows) -> tuple:
    board = match(
        6,
        "Pearl",
        20,
        "Red",
        [
            player("Old Brim#TST", "Red", 9, 8, 7, agent="Brimstone"),
            player(JETT, "Red", 5, 5, 5, agent="Jett"),
            player(VIPER, "Blue", 9, 8, 7, agent="Viper"),
            *extra_rows,
        ],
    )
    entry = MatchEntry(match_id=board.match_id, agent="Brimstone", kills=9, deaths=8, assists=7)
    return board, entry


def test_player_is_found_by_name_before_anything_else():
    board = scoreboards()[0]
    assert analysis.find_player(board, ME.lower()).riot_id == ME
    assert analysis.find_player(board, "Nobody Home#TST") is None


def test_renamed_player_is_found_by_the_line_from_their_history():
    board, entry = renamed_match()
    assert analysis.find_player(board, ME) is None
    assert analysis.find_player(board, ME, entry).riot_id == "Old Brim#TST"

    result = analysis.teammate_stats(ME, [board], entries={board.match_id: entry})
    assert result["matches_analyzed"] == 1
    assert [row["riot_id"] for row in result["teammates"]] == [JETT]
    assert analysis.teammate_stats(ME, [board])["matches_analyzed"] == 0


def test_history_line_shared_by_two_players_identifies_nobody():
    board, entry = renamed_match(player(SOVA, "Blue", 9, 8, 7, agent="Brimstone"))
    assert analysis.find_player(board, ME, entry) is None


def test_history_row_without_a_stat_line_identifies_nobody():
    board, _ = renamed_match()
    assert analysis.find_player(board, ME, MatchEntry(match_id=board.match_id)) is None


@pytest.mark.parametrize(
    ("red", "blue", "expected"),
    [
        (True, False, True),
        (False, True, False),
        (False, False, None),
        (None, None, None),
        (None, True, None),
    ],
)
def test_team_won(red, blue, expected):
    board = match(7, "Icebox", 20, None, [])
    board.teams = [MatchTeam(team="Red", won=red), MatchTeam(team="Blue", won=blue)]
    assert analysis.team_won(board, "Red") is expected


def test_team_won_is_unknown_for_a_team_that_is_not_listed():
    board = scoreboards()[0]
    assert analysis.team_won(board, "Green") is None
    assert analysis.team_won(board, None) is None


@pytest.mark.parametrize(
    ("buys", "expected"),
    [
        (["full", "full", "full", "eco", "semi"], "full"),
        (["eco", "eco", "eco", "full", "full"], "eco"),
        (["eco", "eco", "full", "full", "semi"], "full"),
        (["pistol", "eco"], "eco"),
        (["semi", "eco"], "semi"),
        (["full", "semi"], "full"),
        (["pistol"] * 5, "pistol"),
        ([None, None, "eco"], "eco"),
        (["semi", "mystery", "mystery"], "semi"),
        ([None, None], None),
        ([], None),
    ],
)
def test_team_buy_is_what_most_players_were_on_and_the_bigger_on_a_tie(buys, expected):
    assert analysis.team_buy(lines(*buys)) == expected
    assert analysis.team_buy(lines(*reversed(buys))) == expected


def test_round_totals_by_side():
    result = rounds_of(round_match())
    assert result["matches_analyzed"] == 1
    assert result["rounds"] == tally(8, 4, 50.0)
    assert {key: result["attack"][key] for key in ("rounds", "won", "win_rate")} == tally(
        4, 2, 50.0
    )
    assert {key: result["defense"][key] for key in ("rounds", "won", "win_rate")} == tally(
        4, 2, 50.0
    )
    assert "matches_without_round_data" not in result


def test_rounds_with_and_without_a_spike_plant():
    result = rounds_of(round_match())
    assert result["attack"]["spike_planted"] == tally(2, 1, 50.0)
    assert result["attack"]["spike_not_planted"] == tally(2, 1, 50.0)
    # On defense a win after the plant is a retake: one of three.
    assert result["defense"]["spike_planted"] == tally(3, 1, 33.3)
    assert result["defense"]["spike_not_planted"] == tally(1, 1, 100.0)


def test_planted_rounds_by_site():
    result = rounds_of(round_match())
    assert result["attack"]["by_site"] == {"A": tally(1, 1, 100.0), "B": tally(1, 0, 0.0)}
    assert result["defense"]["by_site"] == {"A": tally(2, 1, 50.0), "B": tally(1, 0, 0.0)}


def test_round_sections_agree_with_each_other():
    result = rounds_of(round_match())
    total = result["rounds"]
    for count in ("rounds", "won"):
        assert result["attack"][count] + result["defense"][count] == total[count]
        for side in ("attack", "defense"):
            block = result[side]
            planted, unplanted = block["spike_planted"], block["spike_not_planted"]
            assert planted[count] + unplanted[count] == block[count]
            assert sum(site[count] for site in block["by_site"].values()) == planted[count]
        opening = result["opening"]
        assert opening["first_kill"][count] + opening["first_death"][count] == total[count]
        assert sum(matchup[count] for matchup in result["economy"].values()) == total[count]
    assert sum(result["endings"]["won"].values()) == total["won"]
    assert sum(result["endings"]["lost"].values()) == total["rounds"] - total["won"]


def test_pistol_rounds_and_the_round_after():
    result = rounds_of(round_match())
    assert result["pistol_rounds"] == tally(2, 1, 50.0)
    assert result["after_pistol_win"] == tally(1, 1, 100.0)
    assert result["after_pistol_loss"] == tally(1, 1, 100.0)


def test_round_after_a_pistol_win_is_kept_apart_from_the_one_after_a_loss():
    def entry(number: int, winner: str, buy: str) -> Round:
        both = [RoundPlayer(riot_id=ME, buy=buy), RoundPlayer(riot_id=VIPER, buy=buy)]
        return Round(round=number, winner=winner, attackers="Red", players=both)

    log = [
        entry(1, "Red", "pistol"),
        entry(2, "Blue", "eco"),
        entry(3, "Blue", "full"),
        entry(13, "Blue", "pistol"),
        entry(14, "Red", "full"),
        entry(15, "Red", "full"),
    ]
    board = match(13, "Sunset", 6, None, [player(ME, "Red"), player(VIPER, "Blue")], round_log=log)
    result = rounds_of(board)
    assert result["pistol_rounds"] == tally(2, 1, 50.0)
    assert result["after_pistol_win"] == tally(1, 0, 0.0)
    assert result["after_pistol_loss"] == tally(1, 1, 100.0)


def test_a_pistol_round_counts_when_the_player_was_away_for_it():
    def entry(number: int, my_buy: str | None, buy: str) -> Round:
        everyone = [
            RoundPlayer(riot_id=ME, buy=my_buy, away=True if my_buy is None else None),
            RoundPlayer(riot_id=JETT, buy=buy),
            RoundPlayer(riot_id=VIPER, buy=buy),
        ]
        return Round(round=number, winner="Red", attackers="Red", players=everyone)

    everyone = [player(ME, "Red"), player(JETT, "Red"), player(VIPER, "Blue")]
    log = [entry(1, None, "pistol"), entry(2, "eco", "eco")]
    result = rounds_of(match(22, "Haven", 2, "Red", everyone, round_log=log))
    assert result["pistol_rounds"] == tally(1, 1, 100.0)
    assert result["after_pistol_win"] == tally(1, 1, 100.0)
    assert result["economy"]["pistol vs pistol"] == tally(1, 1, 100.0)


def test_opening_duels_of_the_team():
    opening = rounds_of(round_match())["opening"]
    assert opening == {"first_kill": tally(3, 3, 100.0), "first_death": tally(5, 1, 20.0)}


def test_economy_by_both_teams_buy_most_common_first():
    economy = rounds_of(round_match())["economy"]
    assert economy == {
        "full vs full": tally(3, 1, 33.3),
        "pistol vs pistol": tally(2, 1, 50.0),
        "full vs eco": tally(1, 1, 100.0),
        "eco vs full": tally(1, 0, 0.0),
        "semi vs full": tally(1, 1, 100.0),
    }
    assert list(economy)[:2] == ["full vs full", "pistol vs pistol"]


def test_round_is_left_out_of_the_economy_when_one_teams_buy_is_unknown():
    lines_of_round = [RoundPlayer(riot_id=ME, buy="full"), RoundPlayer(riot_id=VIPER, away=True)]
    log = [Round(round=2, winner="Red", attackers="Red", players=lines_of_round)]
    board = match(14, "Sunset", 1, "Red", [player(ME, "Red"), player(VIPER, "Blue")], round_log=log)
    result = rounds_of(board)
    assert result["rounds"] == tally(1, 1, 100.0)
    assert result["economy"] == {}


def test_how_rounds_ended():
    endings = rounds_of(round_match())["endings"]
    assert endings == {
        "won": {"Elimination": 2, "Detonate": 1, "Defuse": 1},
        "lost": {"Detonate": 2, "Defuse": 1, "Elimination": 1},
    }
    assert next(iter(endings["won"])) == "Elimination"
    assert next(iter(endings["lost"])) == "Detonate"


def test_the_players_own_numbers():
    own = rounds_of(round_match())["you"]
    assert own == {
        "first_kill": tally(2, 2, 100.0),
        "first_death": tally(4, 0, 0.0),
        # Six kills and four deaths in fights. One of each has no distance.
        "avg_kill_time": 26.7,
        "avg_death_time": 20.5,
        "avg_kill_distance_m": 21.6,
        "avg_death_distance_m": 25.0,
        "killed_by": {"Vandal": 2, "Operator": 1, "Ghost": 1},
    }


def test_suicides_and_team_kills_are_not_fights():
    board = round_match()
    cleaned = round_match()
    # Round 4 opens with a suicide and round 8 with a kill on a teammate.
    for index in (3, 7):
        cleaned.round_log[index].kills = cleaned.round_log[index].kills[1:]
    assert rounds_of(board) == rounds_of(cleaned)


@pytest.mark.parametrize("killer", [None, "Left Early#GONE"])
def test_a_death_without_a_known_killer_is_not_an_opening_duel(killer):
    kills = [Kill(time=3, killer=killer, victim=VIPER, weapon="Vandal")]
    log = [Round(round=1, winner="Red", attackers="Red", kills=kills)]
    board = match(23, "Icebox", 1, "Red", [player(ME, "Red"), player(VIPER, "Blue")], round_log=log)
    empty = {"rounds": 0, "won": 0}
    assert rounds_of(board)["opening"] == {"first_kill": empty, "first_death": empty}


def test_a_spike_death_is_not_an_opening_duel():
    kills = [
        Kill(time=80, killer=ME, victim=VIPER, weapon="Bomb"),
        Kill(time=85, killer=SOVA, victim=ME, weapon="Vandal"),
    ]
    log = [Round(round=1, winner="Red", attackers="Red", kills=kills)]
    everyone = [player(ME, "Red"), player(VIPER, "Blue"), player(SOVA, "Blue")]
    result = rounds_of(match(24, "Lotus", 1, "Red", everyone, round_log=log))
    assert result["opening"]["first_kill"] == {"rounds": 0, "won": 0}
    assert result["opening"]["first_death"] == tally(1, 1, 100.0)
    assert result["you"]["first_death"] == tally(1, 1, 100.0)


def test_undecided_round_is_left_out():
    without = round_match()
    assert without.round_log[-1].winner is None
    without.round_log = without.round_log[:-1]
    assert rounds_of(round_match()) == rounds_of(without)


def test_rounds_are_counted_from_the_players_team_whichever_it_is():
    result = rounds_of(short_round_match())
    assert result["rounds"] == tally(3, 2, 66.7)
    assert result["attack"]["rounds"] == 2
    assert result["attack"]["won"] == 1
    assert result["defense"]["rounds"] == 0
    assert "by_site" not in result["attack"]
    assert result["endings"] == {"won": {"Elimination": 1, "Unknown": 1}, "lost": {"Time": 1}}


def test_bare_rounds_give_no_pistol_economy_or_fight_numbers():
    result = rounds_of(short_round_match())
    empty = {"rounds": 0, "won": 0}
    assert result["pistol_rounds"] == empty
    assert result["after_pistol_win"] == empty
    assert result["opening"] == {"first_kill": empty, "first_death": empty}
    assert result["economy"] == {}
    assert result["you"] == {"first_kill": empty, "first_death": empty}


def test_round_stats_add_up_over_matches():
    no_log = scoreboards()[0]
    stranger = match(5, "Lotus", 13, "Red", [player(JETT, "Red"), player(VIPER, "Blue")])
    result = rounds_of(round_match(), short_round_match(), no_log, stranger)
    assert result["matches_analyzed"] == 2
    assert result["matches_without_round_data"] == 1
    assert result["rounds"] == tally(11, 6, 54.5)
    assert (result["attack"]["rounds"], result["attack"]["won"]) == (6, 3)
    assert (result["defense"]["rounds"], result["defense"]["won"]) == (4, 2)
    assert sum(result["endings"]["won"].values()) == 6
    assert sum(result["endings"]["lost"].values()) == 5


def test_round_stats_find_a_renamed_player_through_the_history():
    board = round_match()
    board.match_id = match_id(12)
    old_name = "Old Brim#TST"
    board.players[0].riot_id = old_name
    for entry in board.round_log:
        for line in entry.players or []:
            if line.riot_id == ME:
                line.riot_id = old_name
        for kill in entry.kills or []:
            kill.killer = old_name if kill.killer == ME else kill.killer
            kill.victim = old_name if kill.victim == ME else kill.victim
    entry = MatchEntry(match_id=board.match_id, agent="Brimstone", kills=6, deaths=4, assists=1)

    assert analysis.round_stats(ME, [board])["matches_analyzed"] == 0
    assert analysis.round_stats(ME, [board], {board.match_id: entry}) == rounds_of(round_match())


def test_round_stats_ignore_the_case_of_the_riot_id():
    assert analysis.round_stats(ME.upper(), [round_match()]) == rounds_of(round_match())
