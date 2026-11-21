"""The helpers in server.py that shape data already loaded. Nothing here fetches."""

from __future__ import annotations

import json

import pytest
from sample_matches import (
    CARRIED_OVER,
    JETT,
    ME,
    SAGE,
    SOVA,
    SPENT,
    VIPER,
    history_entry,
    match,
    player,
    round_match,
    scoreboards,
)

import server
from models import (
    AgentStats,
    GameAct,
    GameAgent,
    GameData,
    GameMap,
    MapStats,
    MatchEntry,
    PlayerProfile,
    Season,
    SeasonStats,
    StatsBundle,
)
from scraper.utils import RiotId

RID = RiotId.parse(ME)
TEAM_OF = {ME: "Red", JETT: "Red", VIPER: "Blue", SOVA: "Blue"}


def size(row: dict) -> int:
    return len(json.dumps(row, separators=(",", ":")))


def rows_of(count: int) -> list[dict]:
    """Rows of exactly 20 characters each."""
    rows = [{"n": f"{number:012d}"} for number in range(count)]
    assert all(size(row) == 20 for row in rows)
    return rows


def test_fit_keeps_everything_within_the_budget():
    rows = rows_of(3)
    assert server.fit(rows, 60) == rows
    assert server.fit(rows, 1000) == rows
    assert server.fit([], 10) == []


def test_fit_keeps_the_leading_rows_that_fit():
    rows = rows_of(5)
    assert server.fit(rows, 59) == rows[:2]
    assert server.fit(rows, 40) == rows[:2]
    assert server.fit(rows, 39) == rows[:1]
    assert server.fit(rows, 99) == rows[:4]


def test_fit_always_keeps_the_first_row():
    rows = rows_of(3)
    assert server.fit(rows, 5) == rows[:1]
    assert server.fit(rows, 0) == rows[:1]
    assert server.fit(rows[:1], 0) == rows[:1]


def test_fit_stops_at_the_first_row_that_does_not_fit():
    big = {"n": "x" * 100}
    rows = [*rows_of(1), big, *rows_of(2)]
    assert server.fit(rows, 70) == rows[:1]


def test_fit_defaults_to_the_answer_budget():
    row = {"n": "x" * (server.ANSWER_BUDGET // 2 - 8)}
    assert size(row) == server.ANSWER_BUDGET // 2
    assert len(server.fit([row] * 2)) == 2
    assert len(server.fit([row] * 3)) == 2


STAT_ROW = {
    "agent": "Jett",
    "role": "Duelist",
    "pick_rate": 40.0,
    "matches": 10,
    "win_rate": 60.0,
    "kd": 1.2,
    "plants": 3,
    "econ_rating": 55.0,
    "attack": {"kd": 1.1, "round_win_rate": 55.0},
    "top_maps": [
        {"name": "Ascent", "matches": 4, "win_rate": 50.0, "kd": 1.3, "acs": 220.0},
        {"name": "Bind", "matches": 2},
    ],
}


def test_stat_view_keeps_the_headline_numbers_and_labels():
    assert server.stat_view(STAT_ROW, detailed=False) == {
        "agent": "Jett",
        "role": "Duelist",
        "pick_rate": 40.0,
        "matches": 10,
        "win_rate": 60.0,
        "kd": 1.2,
        "top_maps": [
            {"name": "Ascent", "matches": 4, "win_rate": 50.0},
            {"name": "Bind", "matches": 2},
        ],
    }


def test_stat_view_trims_top_agents_of_a_map_row_too():
    row = {
        "map": "Split",
        "kast": 70.0,
        "top_agents": [{"name": "Sage", "matches": 3, "adr": 90.0}],
    }
    assert server.stat_view(row, detailed=False) == {
        "map": "Split",
        "kast": 70.0,
        "top_agents": [{"name": "Sage", "matches": 3}],
    }


def test_stat_view_detailed_is_the_whole_row():
    assert server.stat_view(STAT_ROW, detailed=True) == STAT_ROW
    headline = server.stat_view(STAT_ROW, detailed=False)
    assert set(headline) < set(STAT_ROW)


def test_stat_view_leaves_the_row_it_was_given_alone():
    before = json.dumps(STAT_ROW)
    server.stat_view(STAT_ROW, detailed=False)
    assert json.dumps(STAT_ROW) == before


def test_side_headlines_flatten_win_rate_and_kd_per_side():
    row = {
        "map": "Split",
        "attack": {"round_win_rate": 55.0, "kd": 1.1, "acs": 200.0},
        "defense": {"round_win_rate": 45.0},
    }
    assert server.side_headlines(row) == {
        "attack_round_win_rate": 55.0,
        "attack_kd": 1.1,
        "defense_round_win_rate": 45.0,
    }


def test_side_headlines_of_a_row_without_sides_are_empty():
    assert server.side_headlines({"map": "Split"}) == {}
    assert server.side_headlines({"attack": None, "defense": {}}) == {}


def test_small_shaping_helpers():
    assert server.compact({"a": 0, "b": None, "c": "", "d": False, "e": []}) == {
        "a": 0,
        "c": "",
        "d": False,
        "e": [],
    }
    assert server.squash(" KAY/O ") == "kayo"
    assert server.squash("E9: A2") == "e9a2"
    assert server.squash(None) == ""
    assert server.scope("competitive", "act-7") == {"playlist": "competitive", "season": "act-7"}
    assert server.scope("unrated", None) == {"playlist": "unrated", "season": "all"}


def test_player_row_has_the_core_numbers_that_are_known():
    jett = scoreboards()[0].players[1]
    assert server.player_row(jett) == {
        "riot_id": JETT,
        "agent": "Jett",
        "kills": 15,
        "deaths": 15,
        "assists": 3,
        "acs": 200.0,
        "first_kills": 4,
        "first_deaths": 2,
    }


def test_player_row_marks_who_shares_the_given_party():
    board = scoreboards()[0]
    jett, sage = board.players[1], board.players[2]
    assert server.player_row(jett, "p1")["in_party"] is True
    assert server.player_row(jett, "p9")["in_party"] is False
    assert server.player_row(sage, "p1")["in_party"] is False
    assert "in_party" not in server.player_row(jett)


def test_detailed_player_row_is_the_whole_line_without_the_big_blocks():
    jett = scoreboards()[0].players[1]
    row = server.player_row(jett, "p1", detailed=True)
    brief = server.player_row(jett, "p1")
    assert brief.items() <= row.items()
    assert row["clutches_by_size"] == {"1v2": 1}
    assert row["tags"] == ["Top Frag", "Trader"]
    assert row["account_level"] == 82
    hidden = {"team", "party_id", "attack", "defense", "buys", "weapon_kills", "duels"}
    assert not hidden & set(row)
    assert set(row) | hidden >= set(jett.dump())


def test_match_view_without_a_scoreboard():
    view = server.match_view(RID, history_entry(), None, include_opponents=True)
    assert view["scoreboard_available"] is False
    assert view["url"] == f"https://tracker.gg/valorant/match/{history_entry().match_id}"
    assert view["score"] == "13-7"
    assert (view["kills"], view["deaths"], view["assists"]) == (20, 10, 5)
    assert "teammates" not in view
    assert "opponents" not in view


def test_match_view_keeps_the_long_history_fields_for_detail_only():
    long_fields = {"combat_score", "tracker_score", "last_deaths", "suicides", "shots_dealt"}
    brief = server.match_view(RID, history_entry(), None, False)
    full = server.match_view(RID, history_entry(), None, False, detailed=True)
    assert not long_fields & set(brief)
    assert long_fields <= set(full)
    assert brief.items() <= full.items()


def test_match_view_has_no_score_when_the_rounds_are_unknown():
    entry = MatchEntry(match_id=history_entry().match_id, rounds_won=13)
    assert "score" not in server.match_view(RID, entry, None, False)


def test_match_view_lists_teammates_from_the_scoreboard():
    board = scoreboards()[0]
    view = server.match_view(RID, history_entry(), board, include_opponents=False)
    assert "scoreboard_available" not in view
    assert view["duration_minutes"] == 34.5
    assert (view["first_kills"], view["first_deaths"], view["plants"]) == (3, 1, 4)
    assert "defuses" not in view
    assert [row["riot_id"] for row in view["teammates"]] == [JETT, SAGE]
    assert [row["in_party"] for row in view["teammates"]] == [True, False]
    assert view["party_size"] == 2
    assert "opponents" not in view


def test_match_view_splits_everybody_else_into_teammates_and_opponents():
    board = scoreboards()[0]
    view = server.match_view(RID, history_entry(), board, include_opponents=True)
    assert [row["riot_id"] for row in view["opponents"]] == [VIPER, SOVA]
    assert all("in_party" not in row for row in view["opponents"])
    assert 1 + len(view["teammates"]) + len(view["opponents"]) == len(board.players)
    listed = [row["riot_id"] for row in view["teammates"] + view["opponents"]]
    assert ME not in listed


def test_match_view_counts_only_the_players_own_party():
    solo = scoreboards()[2]
    entry = MatchEntry(match_id=solo.match_id)
    view = server.match_view(RID, entry, solo, False)
    # Nobody in that match has a party, which must not read as one shared party.
    assert len(view["teammates"]) == 2
    assert view["party_size"] == 1
    assert not any(row.get("in_party") for row in view["teammates"])


def test_detailed_match_view_carries_whole_scoreboard_lines():
    board = scoreboards()[0]
    view = server.match_view(RID, history_entry(), board, True, detailed=True)
    assert view["adr"] == 160.0
    assert view["plants"] == 4
    assert "team" not in view
    assert "party_id" not in view
    jett = view["teammates"][0]
    assert jett["clutches"] == 1
    assert jett["in_party"] is True
    assert "weapon_kills" not in jett
    assert "attack" not in jett


def test_match_view_when_the_player_is_not_on_the_scoreboard():
    board = scoreboards()[0]
    entry = MatchEntry(match_id=board.match_id, rounds_won=13, rounds_lost=7)
    view = server.match_view(RiotId.parse("Nobody Home#TST"), entry, board, True)
    assert view["scoreboard_available"] is False
    assert "teammates" not in view


def test_match_view_finds_a_renamed_player_by_their_history_line():
    board = scoreboards()[0]
    board.players[0].riot_id = "Old Brim#TST"
    view = server.match_view(RID, history_entry(), board, False)
    assert [row["riot_id"] for row in view["teammates"]] == [JETT, SAGE]


def test_match_view_of_a_free_for_all_has_only_opponents():
    board = match(
        20,
        "District",
        0,
        None,
        [player(ME, None, 40, 20, 3), player(JETT, None, 30, 25, 1), player(SOVA, None, 20, 30, 2)],
    )
    board.teams = []
    view = server.match_view(RID, MatchEntry(match_id=board.match_id), board, True)
    assert view["teammates"] == []
    assert view["party_size"] == 1
    assert [row["riot_id"] for row in view["opponents"]] == [JETT, SOVA]


def second_round():
    return round_match().round_log[1]


def test_round_view_tells_the_round_and_the_kills_in_order():
    view = server.round_view(second_round(), {"Red": 2, "Blue": 0}, TEAM_OF, None, False)
    assert view["round"] == 2
    assert (view["winner"], view["ending"], view["attackers"]) == ("Red", "Detonate", "Red")
    assert view["score"] == {"Red": 2, "Blue": 0}
    assert view["detonated_at"] == 80.0
    assert view["plant"] == {"by": ME, "site": "A", "time": 35.0}
    assert view["kills"] == [
        {"time": 15.0, "killer": SOVA, "victim": JETT, "weapon": "Sheriff"},
        {"time": 30.0, "killer": ME, "victim": SOVA, "weapon": "Vandal"},
        {"time": 40.0, "killer": ME, "victim": VIPER, "weapon": "Vandal"},
    ]
    assert "players" not in view
    assert "player" not in view


def test_round_view_adds_up_each_teams_economy():
    entry = second_round()
    view = server.round_view(entry, {}, TEAM_OF, None, False)
    assert view["economy"] == {
        "Red": {
            "buy": "full",
            "loadout_value": 2 * (SPENT["full"] + CARRIED_OVER),
            "spent": 2 * SPENT["full"],
        },
        "Blue": {
            "buy": "eco",
            "loadout_value": 2 * (SPENT["eco"] + CARRIED_OVER),
            "spent": 2 * SPENT["eco"],
        },
    }
    for total in ("spent", "loadout_value"):
        assert sum(team[total] for team in view["economy"].values()) == sum(
            getattr(line, total) for line in entry.players
        )


def test_detailed_round_view_adds_positions_assists_and_every_line():
    brief = server.round_view(second_round(), {}, TEAM_OF, None, False)
    full = server.round_view(second_round(), {}, TEAM_OF, None, True)
    assert full["plant"] == {"by": ME, "site": "A", "time": 35.0, "at": [0.4, 0.6]}
    assert full["kills"][1] == {
        "time": 30.0,
        "killer": ME,
        "victim": SOVA,
        "weapon": "Vandal",
        "assists": [JETT],
        "distance_m": 20.0,
        "killer_at": [0.5, 0.5],
        "victim_at": [0.6, 0.4],
    }
    for short, long in zip(brief["kills"], full["kills"], strict=True):
        assert short.items() <= long.items()
    assert {
        team: [line["riot_id"] for line in lines] for team, lines in full["players"].items()
    } == {
        "Red": [ME, JETT],
        "Blue": [VIPER, SOVA],
    }
    assert {
        key: value for key, value in full.items() if key not in ("players", "kills", "plant")
    } == {key: value for key, value in brief.items() if key not in ("kills", "plant")}


def test_round_view_follows_one_player_whatever_the_case_of_the_name():
    view = server.round_view(second_round(), {}, TEAM_OF, ME.upper(), False)
    assert view["player"] == {
        "buy": "full",
        "loadout_value": SPENT["full"] + CARRIED_OVER,
        "spent": SPENT["full"],
    }
    assert "player" not in server.round_view(second_round(), {}, TEAM_OF, SAGE, False)


def test_round_view_of_a_round_with_a_defuse_hides_its_position_without_detail():
    sixth = round_match().round_log[5]
    assert server.round_view(sixth, {}, TEAM_OF, None, False)["defuse"] == {
        "by": ME,
        "site": "A",
        "time": 70.0,
    }
    assert server.round_view(sixth, {}, TEAM_OF, None, True)["defuse"]["at"] == [0.3, 0.7]
    assert sixth.defuse.at == [0.3, 0.7]


def test_round_view_of_a_round_without_player_lines_has_no_economy():
    last = round_match().round_log[-1]
    view = server.round_view(last, {"Red": 4, "Blue": 4}, TEAM_OF, ME, True)
    assert "economy" not in view
    assert "players" not in view
    assert "player" not in view
    assert "winner" not in view
    assert len(view["kills"]) == 1


def test_round_view_leaves_out_lines_of_players_without_a_team():
    view = server.round_view(second_round(), {}, {ME: "Red", JETT: "Red"}, None, True)
    assert list(view["economy"]) == ["Red"]
    assert list(view["players"]) == ["Red"]


AGENTS = [
    GameAgent(name="KAY/O", uuid="agent-1"),
    GameAgent(name="Jett", uuid="agent-2"),
    GameAgent(name="Unreleased"),
]


@pytest.mark.parametrize(
    ("name", "uuid"),
    [("KAY/O", "agent-1"), ("kayo", "agent-1"), ("Kay O", "agent-1"), (" JETT ", "agent-2")],
)
def test_named_ignores_case_spacing_and_punctuation(name, uuid):
    assert server.named(AGENTS, name, "agent").uuid == uuid


def test_named_works_for_maps():
    maps = [GameMap(name="Split", uuid="map-1"), GameMap(name="Bind", uuid="map-2")]
    assert server.named(maps, "bind", "map").name == "Bind"


@pytest.mark.parametrize("name", ["Brimstone", "", "Jet"])
def test_named_reports_an_unknown_name_with_the_ones_it_knows(name):
    with pytest.raises(server.ToolError) as caught:
        server.named(AGENTS, name, "agent")
    message = str(caught.value)
    assert f"Unknown agent '{name}'" in message
    assert "KAY/O, Jett" in message
    assert "Unreleased" not in message


def test_named_does_not_find_a_row_without_an_id():
    with pytest.raises(server.ToolError):
        server.named(AGENTS, "Unreleased", "agent")


# The dates are far enough from today that "current" never depends on it.
ACTS = GameData(
    acts=[
        GameAct(id="act-c", name="V9: ACT III", starts="2999-01-01T00:00:00+00:00"),
        GameAct(id="act-b", name="E9: A2", starts="2001-06-01T00:00:00+00:00"),
        GameAct(id="act-a", name="E9: A1", starts="2001-01-01T00:00:00+00:00"),
        GameAct(id="act-z", name="Closed Beta"),
    ]
)


@pytest.mark.parametrize("season", ["current", "Current", " latest ", "default", ""])
def test_find_act_current_is_the_newest_act_that_has_started(season):
    assert server.find_act(ACTS, season).id == "act-b"


@pytest.mark.parametrize(
    ("season", "act_id"),
    [
        ("E9: A1", "act-a"),
        ("e9: a2", "act-b"),
        ("Episode 9 Act 3", "act-c"),
        ("V9: A3", "act-c"),
        ("E9: A III", "act-c"),
        ("ACT-A", "act-a"),
        (" act-z ", "act-z"),
    ],
)
def test_find_act_by_name_in_any_spelling_or_by_id(season, act_id):
    assert server.find_act(ACTS, season).id == act_id


@pytest.mark.parametrize("season", ["E9: A4", "E8: A1", "Closed Beta 2", "next"])
def test_find_act_reports_an_unknown_act(season):
    with pytest.raises(server.ToolError) as caught:
        server.find_act(ACTS, season)
    assert f"Unknown act '{season}'" in str(caught.value)
    assert "E9: A2" in str(caught.value)


@pytest.mark.parametrize(
    ("given", "expected"),
    [("eu", "eu"), ("EU", "eu"), (" na ", "na"), ("N.A.", "na"), ("LATAM", "latam"), ("Kr", "kr")],
)
def test_region_key(given, expected):
    assert server.region_key(given) == expected
    assert expected in server.REGIONS


@pytest.mark.parametrize("given", ["mars", "", "europe", "eu west"])
def test_region_key_rejects_an_unknown_region(given):
    with pytest.raises(server.ToolError) as caught:
        server.region_key(given)
    assert all(region in str(caught.value) for region in server.REGIONS)


def profile(**changes) -> PlayerProfile:
    fields = {
        "riot_id": ME,
        "default_season": "s2",
        "seasons": [
            Season(id="s3", name="V9: ACT III", short_name="V9: A3"),
            Season(id="s2", name="Episode 9: Act 2", short_name="E9: A2"),
            Season(id="s1", name="Episode 9: Act 1"),
        ],
    }
    return PlayerProfile(**{**fields, **changes})


@pytest.mark.parametrize("season", ["all", "All Acts", " Career ", "lifetime", "overall"])
def test_resolve_season_all_acts_is_none(season):
    assert server.resolve_season(profile(), season) is None


def test_resolve_season_current_is_the_profiles_default_act():
    assert server.resolve_season(profile(), "current") == "s2"
    assert server.resolve_season(profile(), "") == "s2"
    assert server.resolve_season(profile(default_season=None), "latest") == "s3"
    assert server.resolve_season(profile(default_season=None, seasons=[]), "current") is None


@pytest.mark.parametrize(
    ("season", "season_id"),
    [
        ("E9: A3", "s3"),
        ("v9:a3", "s3"),
        ("V9: ACT III", "s3"),
        ("E9: A2", "s2"),
        ("Episode 9 Act 1", "s1"),
        ("episode9:act1", "s1"),
        ("S1", "s1"),
    ],
)
def test_resolve_season_by_act_name_in_any_spelling_or_by_id(season, season_id):
    assert server.resolve_season(profile(), season) == season_id


def test_resolve_season_reports_an_unknown_act_with_the_ones_it_knows():
    with pytest.raises(server.ToolError) as caught:
        server.resolve_season(profile(), "E3: A1")
    assert "Unknown season 'E3: A1'" in str(caught.value)
    assert "V9: A3, E9: A2, Episode 9: Act 1" in str(caught.value)


def test_season_label():
    assert server.season_label(profile(), None) == "All Acts"
    assert server.season_label(profile(), "s3") == "V9: A3"
    assert server.season_label(profile(), "s1") == "Episode 9: Act 1"
    assert server.season_label(profile(), "s0") == "s0"


def test_dump_section_gives_rows_label_first_and_without_unknowns():
    bundle = StatsBundle(
        season_stats=SeasonStats(matches=12, kd=1.1),
        agents=[AgentStats(matches=3, role="Duelist", agent="Jett")],
        maps=[MapStats(win_rate=50.0, map="Split")],
    )
    assert server.dump_section(bundle, "season_stats") == {"matches": 12, "kd": 1.1}
    agents = server.dump_section(bundle, "agents")
    assert agents == [{"agent": "Jett", "role": "Duelist", "matches": 3}]
    assert list(agents[0]) == ["agent", "role", "matches"]
    assert list(server.dump_section(bundle, "maps")[0]) == ["map", "win_rate"]
    assert server.dump_section(bundle, "weapons") == []
    assert server.dump_section(StatsBundle(), "season_stats") is None
