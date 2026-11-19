"""Match history pages, search results, tracker.gg's own totals and stat history."""

import pytest
from sample_payloads import (
    BRIM,
    JETT,
    MATCH_ID,
    SAGE,
    sample_aggregate,
    sample_match_page,
    sample_rank_history,
    sample_search,
    sample_stat_history,
)

from models import Aggregate, MatchPage, Shots
from scraper.parsers import parse_aggregate, parse_match_page, parse_search, parse_stat_history

SECOND_MATCH_ID = "00000000-0000-4000-8000-00000000000b"


def test_match_page_skips_rows_without_a_match_id():
    page = parse_match_page(sample_match_page())
    assert [entry.match_id for entry in page.matches] == [MATCH_ID, SECOND_MATCH_ID]


def test_match_page_row_describes_the_match():
    entry = parse_match_page(sample_match_page()).matches[0]
    assert entry.played_at == "2026-03-01T18:00:00+00:00"
    assert (entry.map, entry.mode, entry.season) == ("Ascent", "Competitive", "E26: A5")
    assert (entry.result, entry.rounds_won, entry.rounds_lost) == ("victory", 13, 9)
    assert (entry.agent, entry.rank) == ("Jett", "Gold 2")


def test_match_page_row_carries_the_players_own_line():
    entry = parse_match_page(sample_match_page()).matches[0]
    assert (entry.kills, entry.deaths, entry.assists, entry.kd) == (21, 14, 5, 1.5)
    assert (entry.acs, entry.adr, entry.hs_pct, entry.kast) == (262.4, 171.4, 28.6, 77.3)
    assert (entry.damage, entry.combat_score) == (3770, 5774)
    assert (entry.performance_rank, entry.tracker_score) == (2, 812)
    assert (entry.last_deaths, entry.suicides) == (3, 0)
    assert entry.shots_dealt == Shots(head=12, body=28, leg=2)


def test_match_page_result_falls_back_to_the_players_own_segment():
    entry = parse_match_page(sample_match_page()).matches[1]
    assert (entry.result, entry.agent) == ("defeat", "Sage")
    assert (entry.rounds_won, entry.rounds_lost) == (7, 13)
    assert entry.rank is None


@pytest.mark.parametrize(("upstream", "expected"), [(1, 1), (7, 7), (None, None), ("2", None)])
def test_match_page_next_page_is_a_page_number_or_nothing(upstream, expected):
    data = sample_match_page()
    data["metadata"]["next"] = upstream
    assert parse_match_page(data).next_page == expected


def test_empty_match_page():
    assert parse_match_page({}) == MatchPage()


def test_search_lists_the_results_that_have_a_riot_id():
    results = parse_search(sample_search())
    assert [(result.riot_id, result.status) for result in results] == [
        (JETT, "online"),
        (BRIM, None),
    ]


def test_search_without_results():
    assert parse_search(None) == []
    assert parse_search([]) == []


def test_aggregate_teammates_are_sorted_by_matches_together():
    teammates = parse_aggregate(sample_aggregate()).teammates
    assert [(row.riot_id, row.matches) for row in teammates] == [(JETT, 30), (SAGE, 8)]
    jett = teammates[0]
    assert (jett.wins, jett.losses, jett.win_rate) == (18, 12, 60.0)
    assert (jett.kd, jett.avg_placement) == (1.24, 3.8)
    assert jett.last_played == "2026-03-01T18:00:00+00:00"
    assert all(row.wins + row.losses == row.matches for row in teammates)


def test_aggregate_skips_party_sizes_without_matches():
    parties = parse_aggregate(sample_aggregate()).parties
    assert [(row.party_size, row.matches, row.wins) for row in parties] == [
        (1, 14, 6),
        (2, 10, 6),
        (5, 6, 5),
    ]
    assert [row.win_rate for row in parties] == [42.9, 60.0, 83.3]
    assert sum(row.matches for row in parties) == 30


def test_aggregate_days_are_the_days_played_in_date_order():
    days = parse_aggregate(sample_aggregate()).days
    assert [(day.date, day.matches, day.wins, day.losses) for day in days] == [
        ("2026-02-27", 1, 0, 1),
        ("2026-03-01", 3, 2, 1),
    ]
    assert [(day.kills, day.deaths, day.kd) for day in days] == [(12, 16, 0.75), (62, 44, 1.4)]


def test_aggregate_day_numbers():
    quiet, busy = parse_aggregate(sample_aggregate()).days
    assert (busy.adr, busy.performance_score, busy.avg_placement) == (158.4, 58.3, 3.7)
    # 6,300,000 ms and 2,190,000 ms
    assert (busy.minutes_played, quiet.minutes_played) == (105.0, 36.5)
    assert (quiet.adr, quiet.performance_score) == (None, None)


def test_empty_aggregate():
    assert parse_aggregate({}) == Aggregate()


def test_stat_history_points_are_in_date_order():
    history = parse_stat_history(sample_stat_history(), "kDRatio")
    assert history.stat == "K/D Ratio"
    assert [(point.date, point.value) for point in history.points] == [
        ("2026-03-01", 1.23),
        ("2026-03-02", 1.5),
        ("2026-03-03", 0.87),
    ]
    assert all(point.tier is None and point.rr is None for point in history.points)


def test_stat_history_best_matches_carry_the_stats_value():
    # The history rows spell the key kdRatio where the request says kDRatio.
    best = parse_stat_history(sample_stat_history(), "kDRatio").best_matches
    assert [(match.match_id, match.value) for match in best] == [
        (MATCH_ID, 3.25),
        (SECOND_MATCH_ID, 2.5),
    ]
    assert (best[0].kills, best[0].deaths, best[0].agent) == (26, 8, "Jett")
    assert best[0].season == "E26: A5"


def test_stat_history_best_match_without_the_stat_has_no_value():
    best = parse_stat_history(sample_stat_history(), "scorePerRound").best_matches
    assert [match.value for match in best] == [None, None]
    assert [match.kills for match in best] == [26, 20]


@pytest.mark.parametrize("data", [{"history": None, "bestMatches": []}, {}])
def test_stat_history_of_an_unknown_stat_is_none(data):
    assert parse_stat_history(data, "noSuchStat") is None


def test_rank_history_carries_tier_rating_and_leaderboard_position():
    history = parse_stat_history(sample_rank_history(), "rank")
    assert history.stat == "Rating"
    assert [
        (point.date, point.tier, point.rr, point.leaderboard_rank) for point in history.points
    ] == [
        ("2026-03-01", "Immortal 3", 310, None),
        ("2026-03-02", "Radiant", 450, 212),
    ]
    assert all(point.value is None for point in history.points)
    assert history.best_matches == []
