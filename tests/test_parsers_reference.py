"""Data that is not about one player: distribution, leaderboard, insights, Premier, game data."""

import pytest
from sample_payloads import (
    ACT_ID,
    BRIM,
    CYPHER,
    JETT,
    ROSTER_ID,
    SAGE,
    sample_agent_insights,
    sample_distribution,
    sample_game_data,
    sample_leaderboard,
    sample_map_insights,
    sample_premier,
    stats,
)

from models import PremierStage
from scraper.parsers import (
    parse_agent_insights,
    parse_distribution,
    parse_game_data,
    parse_leaderboard,
    parse_map_insights,
    parse_premier,
)


def test_distribution_keeps_the_rows_with_a_tier_in_order():
    rows = parse_distribution(sample_distribution())
    assert [(row.tier, row.share, row.players) for row in rows] == [
        ("Iron 1", 10.0, 2_000),
        ("Gold 2", 50.0, 10_000),
        ("Diamond 1", 39.95, 7_990),
        ("Radiant", 0.05, 10),
    ]
    assert sum(row.players for row in rows) == 20_000
    assert sum(row.share for row in rows) == pytest.approx(100.0)


def test_distribution_rounds_shares_and_tolerates_missing_numbers():
    rows = parse_distribution([{"tier": "Gold 1", "pct": 33.33333}, {"tier": "Gold 2"}])
    assert [(row.share, row.players) for row in rows] == [(33.33, None), (None, None)]


def test_empty_distribution():
    assert parse_distribution(None) == []


def test_leaderboard_header():
    board = parse_leaderboard(sample_leaderboard())
    assert board.title == "Competitive Rating"
    assert board.updated_at == "2026-03-02T06:00:00+00:00"


def test_leaderboard_rows_carry_rating_tier_and_wins():
    rows = parse_leaderboard(sample_leaderboard()).rows
    assert [(row.rank, row.riot_id, row.rr, row.tier, row.wins) for row in rows] == [
        (1, JETT, 987, "Radiant", 88),
        (2, "hidden-2", 951, "Radiant", 97),
        (3, BRIM, 640, "Immortal 3", 71),
    ]
    assert all(isinstance(row.rr, int) for row in rows)


def test_empty_leaderboard():
    board = parse_leaderboard({})
    assert (board.title, board.rows) == (None, [])


def test_agent_insights_are_sorted_by_pick_rate():
    rows = parse_agent_insights(sample_agent_insights())
    assert [(row.agent, row.role, row.tier, row.pick_rate) for row in rows] == [
        ("Jett", "Duelist", "S", 14.57),
        ("Sage", "Sentinel", "A", 8.12),
    ]


def test_agent_insight_numbers():
    jett, sage = parse_agent_insights(sample_agent_insights())
    assert (jett.win_rate, jett.kd, jett.damage_delta_per_round) == (49.8, 1.08, 6.2)
    assert (jett.kills_per_match, jett.deaths_per_match, jett.assists_per_match) == (
        17.3,
        15.9,
        3.4,
    )
    assert (sage.win_rate, sage.kd, sage.damage_delta_per_round) == (51.3, 0.93, -3.3)


def test_map_insights_are_sorted_by_play_rate():
    rows = parse_map_insights(sample_map_insights())
    assert [(row.map, row.play_rate, row.attackers_kd, row.defenders_kd) for row in rows] == [
        ("Ascent", 14.34, 1.01, 0.99),
        ("Split", 9.87, 0.98, 1.02),
    ]


def test_insights_without_rows():
    assert parse_agent_insights({}) == []
    assert parse_map_insights({}) == []


def test_premier_team_header():
    team = parse_premier(sample_premier())
    assert (team.roster_id, team.name) == (ROSTER_ID, "Test Squad")
    assert (team.region, team.zone, team.division) == ("eu", "Central Europe", "Elite 2")
    assert (team.league_score, team.rank, team.wins, team.losses) == (675, 12, 8, 4)
    assert team.created_at == "2025-09-01T12:00:00+00:00"


def test_premier_team_without_a_standing_has_no_rank():
    data = sample_premier()
    data["rank"] = 0
    assert parse_premier(data).rank is None


def test_premier_roster_comes_first_ordered_by_matches():
    players = parse_premier(sample_premier()).players
    assert [(player.riot_id, player.roster_role, player.matches) for player in players] == [
        (JETT, "captain", 12),
        (BRIM, "owner", 10),
        (SAGE, "member", 4),
        (CYPHER, "member", None),
        ("Omen Gone#LEFT", None, 20),
    ]


def test_premier_player_numbers():
    jett = parse_premier(sample_premier()).players[0]
    assert (jett.wins, jett.losses) == (8, 4)
    assert (jett.round_win_rate, jett.acs, jett.damage_delta_per_round) == (56.8, 244.4, 21.1)
    assert (jett.hs_pct, jett.kast, jett.tracker_score) == (30.1, 74.2, 803)


def test_premier_player_agents_are_ordered_by_matches():
    players = {player.riot_id: player for player in parse_premier(sample_premier()).players}
    assert list(players[JETT].agents.items()) == [("Jett", 9), ("Raze", 3)]
    assert sum(players[JETT].agents.values()) == players[JETT].matches
    assert players[BRIM].agents == {"Brimstone": 10}
    assert players[SAGE].agents is None


def test_premier_ranks_are_named_from_tier_numbers():
    players = {player.riot_id: player for player in parse_premier(sample_premier()).players}
    assert (players[JETT].rank, players[JETT].peak_rank) == ("Immortal 3", "Radiant")
    assert (players[BRIM].rank, players[BRIM].peak_rank) == ("Gold 2", "Iron 1")
    assert (players[SAGE].rank, players[SAGE].peak_rank) == (None, None)


@pytest.mark.parametrize(
    ("number", "name"),
    [
        (2, None),
        (3, "Iron 1"),
        (5, "Iron 3"),
        (6, "Bronze 1"),
        (11, "Silver 3"),
        (12, "Gold 1"),
        (17, "Platinum 3"),
        (18, "Diamond 1"),
        (21, "Ascendant 1"),
        (24, "Immortal 1"),
        (26, "Immortal 3"),
        (27, "Radiant"),
        (28, None),
    ],
)
def test_tier_numbers(number, name):
    row = {
        "type": "player-summary",
        "metadata": {"platformUserIdentifier": JETT},
        "stats": stats(rating=number),
    }
    assert parse_premier({"playerStats": [row]}).players[0].rank == name


def test_premier_stages():
    first, second = parse_premier(sample_premier()).stages
    assert first == PremierStage(
        stage="Stage 1",
        division="Elite 1",
        score=540,
        wins=5,
        losses=2,
        rounds_won=80,
        rounds_lost=61,
    )
    assert (second.stage, second.playoff_placement) == ("Stage 2", 3)


def test_premier_matches_are_newest_first_with_the_teams_own_score():
    matches = parse_premier(sample_premier()).matches
    assert [
        (match.played_at[:10], match.opponent, match.map, match.rounds_won, match.rounds_lost)
        for match in matches
    ] == [
        ("2026-02-28", "Third Squad", "Ascent", 11, 13),
        ("2026-02-21", "Other Squad", "Split", 13, 7),
    ]
    assert [match.won for match in matches] == [False, True]
    assert all((match.rounds_won > match.rounds_lost) == match.won for match in matches)
    assert [(match.league_points, match.league_points_change) for match in matches] == [
        (575, -25),
        (600, 100),
    ]
    assert matches[0].match_id == "00000000-0000-4000-8000-0000000000c2"


def test_premier_match_without_the_teams_row_has_no_score():
    data = sample_premier()
    data["id"] = "another-roster"
    matches = parse_premier(data).matches
    assert [(match.rounds_won, match.rounds_lost) for match in matches] == [(None, None)] * 2


def test_premier_team_stats():
    team = parse_premier(sample_premier())
    assert (team.stats.matches, team.stats.wins, team.stats.losses) == (12, 8, 4)
    assert team.stats.kills == 900
    data = sample_premier()
    del data["teamStats"]
    assert parse_premier(data).stats is None


def test_game_agents_are_sorted_by_name_with_role_and_abilities():
    jett, sage = parse_game_data(sample_game_data()).agents
    assert (jett.name, jett.uuid, jett.role, jett.abilities) == (
        "Jett",
        "agent-jett",
        "Duelist",
        None,
    )
    assert (sage.name, sage.role) == ("Sage", "Sentinel")
    assert sage.abilities == {
        "c": "Barrier Orb",
        "q": "Slow Orb",
        "e": "Healing Orb",
        "x": "Resurrection",
    }


def test_game_maps_and_weapons_need_a_name():
    data = parse_game_data(sample_game_data())
    assert [(row.name, row.uuid) for row in data.maps] == [("Ascent", "map-ascent")]
    assert [(row.name, row.category, row.cost) for row in data.weapons] == [
        ("Vandal", "Rifles", 2900),
        ("Phantom", "Rifles", 2900),
        ("Classic", "Sidearms", 0),
    ]


def test_game_acts_are_newest_first_and_named_like_profiles_name_them():
    acts = parse_game_data(sample_game_data()).acts
    assert [(act.id, act.name) for act in acts] == [
        (ACT_ID, "E26: A5"),
        ("act-26-4", "E26: A4"),
        ("act-25-6", "E25: A6"),
    ]
    assert (acts[0].starts, acts[0].ends) == (
        "2026-02-25T00:00:00+00:00",
        "2026-04-15T00:00:00+00:00",
    )
    assert [act.starts for act in acts] == sorted((act.starts for act in acts), reverse=True)


def test_an_act_is_named_by_the_short_names_it_has():
    seasons = [
        {"shortName": "Closed Beta", "seasons": [{"id": "act-0"}]},
        {"seasons": [{"id": "act-1"}]},
    ]
    names = {act.id: act.name for act in parse_game_data({"seasons": seasons}).acts}
    assert names == {"act-0": "Closed Beta", "act-1": "act-1"}


def test_game_playlists_map_key_to_label():
    data = parse_game_data(sample_game_data())
    assert data.playlists == {"competitive": "Competitive", "premier": "premier"}


def test_empty_game_data():
    data = parse_game_data({})
    assert (data.agents, data.maps, data.weapons, data.acts, data.playlists) == ([], [], [], [], {})
