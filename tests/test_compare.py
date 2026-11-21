"""Ranking players by a weighted score, with the working shown."""

import asyncio
from decimal import ROUND_HALF_UP, Decimal
from random import Random

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import analysis
import server
from models import PlayerProfile, Season
from scraper import UpstreamError

BRIM = ("Brim Stone#TST", {"acs": 250.0, "kd": 1.2, "kast": 74.0, "adr": 160.0, "matches": 42})
JETT = ("Jett Lag#0001", {"acs": 200.0, "kd": 1.5, "kast": 70.0, "adr": 140.0, "matches": 37})
SAGE = ("Sage Advice#HEAL", {"acs": 150.0, "kd": 0.9, "kast": 80.0, "adr": 110.0, "matches": 4})


def ranked(result):
    return [row["riot_id"] for row in result["ranking"]]


def test_the_default_weights_are_used_and_shown_when_none_are_given():
    result = analysis.compare_players([BRIM, JETT])

    assert result["weights"] == {"acs": 0.4, "kd": 0.3, "kast": 0.2, "adr": 0.1}
    assert result["default_weights"] is True
    assert "100 points" in result["method"]


def test_given_weights_are_scaled_to_add_up_to_one():
    result = analysis.compare_players([BRIM, JETT], {"acs": 3, "kd": 1})

    assert result["weights"] == {"acs": 0.75, "kd": 0.25}
    assert result["default_weights"] is False


def test_the_best_value_is_worth_100_points_and_the_rest_a_share_of_it():
    result = analysis.compare_players([BRIM, JETT, SAGE], {"acs": 1})
    points = {row["riot_id"]: row["breakdown"]["acs"]["points"] for row in result["ranking"]}

    assert result["best_values"] == {"acs": 250.0}
    assert points == {BRIM[0]: 100.0, JETT[0]: 80.0, SAGE[0]: 60.0}


def test_a_score_is_the_sum_of_weight_times_points():
    brim = analysis.compare_players([BRIM, JETT], {"acs": 0.5, "kd": 0.5})["ranking"][0]

    assert brim["riot_id"] == BRIM[0]
    assert brim["breakdown"] == {
        "acs": {"value": 250.0, "points": 100.0, "weight": 0.5, "contribution": 50.0},
        "kd": {"value": 1.2, "points": 80.0, "weight": 0.5, "contribution": 40.0},
    }
    assert brim["score"] == 90.0


def some_comparisons(count=300):
    """Comparisons of made-up players on awkward weights, the same ones on every run."""
    random = Random(26)
    for _ in range(count):
        stats = random.sample(analysis.COMPARABLE, random.randint(1, len(analysis.COMPARABLE)))
        weights = {stat: random.choice([1, 2, 1 / 3, 0.07, 5.5]) for stat in stats}
        players = [
            (f"Player {number}#TST", {stat: round(random.uniform(0.1, 300), 2) for stat in stats})
            for number in range(random.randint(2, 6))
        ]
        yield analysis.compare_players(players, weights)


def on_paper(*factors):
    """A product worked out exactly and rounded to two decimals with a half going up."""
    product = Decimal(1)
    for factor in factors:
        product *= Decimal(str(factor))
    return float(product.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def test_the_numbers_shown_give_every_contribution_and_score():
    for result in some_comparisons():
        for row in result["ranking"]:
            parts = row["breakdown"].values()
            for part in parts:
                assert on_paper(part["weight"], part["points"]) == part["contribution"]
            assert round(sum(part["contribution"] for part in parts), 2) == row["score"]


def test_a_half_is_rounded_up_the_way_it_is_done_by_hand():
    # 80.13 points at half weight is 40.065, which a float multiplication puts just below.
    players = [("One#TST", {"acs": 100.0, "kd": 1.0}), ("Two#TST", {"acs": 80.13, "kd": 1.0})]
    two = analysis.compare_players(players, {"acs": 1, "kd": 1})["ranking"][1]

    assert two["breakdown"]["acs"] == {
        "value": 80.13,
        "points": 80.13,
        "weight": 0.5,
        "contribution": 40.07,
    }
    assert two["score"] == 90.07


def test_the_weights_shown_always_add_up_to_one():
    for result in some_comparisons():
        assert round(sum(result["weights"].values()), 4) == 1


def test_rounded_thirds_still_add_up_to_one():
    result = analysis.compare_players([BRIM, JETT], {"acs": 1, "kd": 1, "kast": 1})

    assert result["weights"] == {"acs": 0.3334, "kd": 0.3333, "kast": 0.3333}


def test_nobody_is_ranked_above_a_player_with_a_higher_score():
    for result in some_comparisons():
        scores = [row["score"] for row in result["ranking"]]
        assert scores == sorted(scores, reverse=True)


def test_players_are_ranked_best_first_with_their_matches():
    result = analysis.compare_players([SAGE, JETT, BRIM])

    assert ranked(result) == [BRIM[0], JETT[0], SAGE[0]]
    assert [row["rank"] for row in result["ranking"]] == [1, 2, 3]
    assert [row["matches"] for row in result["ranking"]] == [42, 37, 4]


def test_the_weights_decide_who_comes_first():
    by_score = analysis.compare_players([BRIM, JETT], {"acs": 1})
    by_duels = analysis.compare_players([BRIM, JETT], {"kd": 1})

    assert ranked(by_score) == [BRIM[0], JETT[0]]
    assert ranked(by_duels) == [JETT[0], BRIM[0]]


def test_the_lead_over_the_next_player_is_split_by_stat():
    first, last = analysis.compare_players([BRIM, JETT], {"acs": 0.5, "kd": 0.5})["ranking"]

    # Brim: 50 + 40. Jett: 40 + 50.
    assert first["ahead_of_next"] == {"by": 0.0, "from": {"acs": 10.0, "kd": -10.0}}
    assert "ahead_of_next" not in last


def test_the_split_of_a_lead_adds_up_to_the_lead():
    for result in some_comparisons():
        for row in result["ranking"][:-1]:
            lead = row["ahead_of_next"]
            assert round(sum(lead["from"].values()), 2) == lead["by"]


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 1, 0), (1, 2, 0)])
def test_players_with_the_same_score_keep_the_order_they_came_in(order):
    twins = [(f"Twin {number}#TST", dict(BRIM[1])) for number in order]

    assert ranked(analysis.compare_players(twins)) == [name for name, _ in twins]


def test_a_stat_one_player_lacks_is_left_out_for_everyone():
    unranked = ("Omen Clature#SHDW", {"acs": 210.0, "kd": 1.0, "matches": 9})
    result = analysis.compare_players([BRIM, unranked], {"acs": 1, "kd": 1, "kast": 2})

    assert result["left_out"] == {"kast": "no value for Omen Clature#SHDW"}
    assert result["weights"] == {"acs": 0.5, "kd": 0.5}
    assert all(set(row["breakdown"]) == {"acs", "kd"} for row in result["ranking"])


def test_nothing_is_left_out_when_everyone_has_every_stat():
    assert "left_out" not in analysis.compare_players([BRIM, JETT])


def test_no_stat_in_common_cannot_be_compared():
    with pytest.raises(ValueError, match="nothing to compare"):
        analysis.compare_players([BRIM, ("Empty#TST", {"matches": 3})])


def test_a_stat_where_nobody_scored_gives_no_points():
    idle = [("One#TST", {"acs": 0, "kd": 1.0}), ("Two#TST", {"acs": 0, "kd": 0.5})]
    result = analysis.compare_players(idle, {"acs": 1, "kd": 1})

    assert [row["breakdown"]["acs"]["points"] for row in result["ranking"]] == [0.0, 0.0]
    assert ranked(result) == ["One#TST", "Two#TST"]


def test_a_stat_with_no_weight_is_ignored():
    result = analysis.compare_players([BRIM, JETT], {"acs": 1, "kd": 0})

    assert result["weights"] == {"acs": 1.0}


@pytest.mark.parametrize(
    ("weights", "complaint"),
    [
        ({"rizz": 1}, "Cannot weigh rizz"),
        ({"acs": -1}, "must not be negative"),
        ({"acs": "a lot"}, "has to be a number"),
        ({"acs": True}, "has to be a number"),
        ({"acs": float("inf")}, "finite"),
        ({"acs": float("nan")}, "finite"),
        ({"acs": 1e308, "kd": 1e308}, "too large"),
        ({"acs": 0.00001, "kd": 1}, "too small"),
        ({"acs": 0, "kd": 0}, "above zero"),
        ({}, "above zero"),
    ],
)
def test_weights_that_make_no_sense_are_refused(weights, complaint):
    with pytest.raises(ValueError, match=complaint):
        analysis.compare_players([BRIM, JETT], weights)


def test_an_unknown_stat_is_answered_with_the_ones_that_can_be_used():
    with pytest.raises(ValueError, match="acs, adr, kd, kda, kast, hs_pct, win_rate"):
        analysis.compare_players([BRIM, JETT], {"clutch_factor": 1})


def test_one_player_is_not_a_comparison():
    with pytest.raises(ValueError, match="at least two"):
        analysis.compare_players([BRIM])


def remember(name, stats, act="act-5", label="E26: A5", *, ttl=600, shown_as=None):
    """Put a player's profile and act stats in the cache, as a scrape would have."""
    profile = PlayerProfile(
        riot_id=shown_as or name, default_season=act, seasons=[Season(id=act, short_name=label)]
    )
    key = {"v": server.CACHE_VERSION}
    scope = {"playlist": "competitive", "season": act, **key}

    async def store():
        await server.cache.set("profile", profile.dump(), ttl, name, key)
        await server.cache.set("season_stats", stats, ttl, name, scope)

    asyncio.run(store())


def compare(*names, **options):
    result = asyncio.run(server.compare_players(riot_ids=list(names), **options))
    return result.structured_content


def test_the_tool_ranks_cached_players_and_says_where_the_numbers_came_from():
    remember(*BRIM)
    remember(*JETT)

    answer = compare(BRIM[0], JETT[0])

    assert [row["riot_id"] for row in answer["data"]["ranking"]] == [BRIM[0], JETT[0]]
    assert (answer["data"]["playlist"], answer["data"]["season"]) == ("competitive", "E26: A5")
    assert answer["data"]["default_weights"] is True
    assert (answer["meta"]["source"], answer["meta"]["stale_reason"]) == ("cache", "within_ttl")


def test_the_tool_takes_weights():
    remember(*BRIM)
    remember(*JETT)

    answer = compare(BRIM[0], JETT[0], weights={"kd": 1})

    assert [row["riot_id"] for row in answer["data"]["ranking"]] == [JETT[0], BRIM[0]]
    assert answer["data"]["weights"] == {"kd": 1.0}


def test_the_tool_points_out_players_with_few_matches():
    remember(*BRIM)
    remember(*SAGE)

    note = compare(BRIM[0], SAGE[0])["data"]["note"]

    assert "Sage Advice#HEAL (4)" in note
    assert BRIM[0] not in note


def test_the_tool_says_when_the_players_numbers_are_from_different_acts():
    remember(*BRIM)
    remember("Old Timer#TST", dict(JETT[1]), act="act-4", label="E26: A4")

    data = compare(BRIM[0], "Old Timer#TST")["data"]

    assert "different acts" in data["note"]
    assert "season" not in data
    assert {row["riot_id"]: row["season"] for row in data["ranking"]} == {
        BRIM[0]: "E26: A5",
        "Old Timer#TST": "E26: A4",
    }


def test_the_tool_sets_aside_a_player_without_games():
    remember(*BRIM)
    remember(*JETT)
    remember("New Here#TST", {})

    data = compare(BRIM[0], JETT[0], "New Here#TST")["data"]

    assert data["not_ranked"] == ["New Here#TST"]
    assert len(data["ranking"]) == 2


@pytest.mark.parametrize(
    ("names", "options", "complaint"),
    [
        ((BRIM[0], "brim stone#tst"), {}, "two different Riot IDs"),
        ((BRIM[0], JETT[0]), {"weights": {"rizz": 1}}, "Cannot weigh rizz"),
        ((BRIM[0], "not a riot id"), {}, "is not a Riot ID"),
    ],
)
def test_the_tool_explains_what_it_cannot_do(names, options, complaint):
    remember(*BRIM)
    remember(*JETT)

    with pytest.raises(ToolError, match=complaint):
        compare(*names, **options)


def test_the_tool_needs_two_players_with_games():
    remember(*BRIM)
    remember("New Here#TST", {})

    with pytest.raises(ToolError, match="Fewer than two"):
        compare(BRIM[0], "New Here#TST")


class Unreachable:
    """Tracker.gg on a day when nothing gets through."""

    async def fetch_profile(self, rid):
        raise UpstreamError("Tracker.gg did not answer within 30 seconds.")

    async def fetch_stats(self, rid, playlist, season_id):
        raise UpstreamError("Tracker.gg did not answer within 30 seconds.")


def test_the_tool_names_the_player_whose_numbers_could_not_be_refreshed(monkeypatch):
    monkeypatch.setattr(server, "tracker", Unreachable())
    remember(*BRIM)
    remember("Stale Mate#TST", dict(JETT[1]), ttl=0)

    answer = compare(BRIM[0], "Stale Mate#TST")

    old = {row["riot_id"]: row.get("stale", False) for row in answer["data"]["ranking"]}
    assert old == {BRIM[0]: False, "Stale Mate#TST": True}
    assert "could not be fetched for Stale Mate#TST" in answer["data"]["note"]
    assert answer["meta"]["is_stale"] is True


def test_a_refresh_that_fails_for_everyone_is_not_called_a_part(monkeypatch):
    monkeypatch.setattr(server, "tracker", Unreachable())
    remember(*BRIM)
    remember(*JETT)

    result = asyncio.run(server.compare_players(riot_ids=[BRIM[0], JETT[0]], force_refresh=True))

    assert result.content[0].text.startswith("\u26a0\ufe0f This data is from the cache")
    assert all(row["stale"] for row in result.structured_content["data"]["ranking"])


def test_an_unknown_act_is_reported_with_the_player_it_is_unknown_for():
    remember(*BRIM)
    remember(*JETT)

    with pytest.raises(ToolError, match="Brim Stone#TST: Unknown season 'E1: A1'"):
        compare(BRIM[0], JETT[0], season="E1: A1")


def test_two_ids_that_show_the_same_name_keep_their_own_act():
    remember(*BRIM)
    remember("Name Sake#TST", dict(JETT[1]), act="act-4", label="E26: A4", shown_as=BRIM[0])

    data = compare(BRIM[0], "Name Sake#TST")["data"]

    assert {row["riot_id"]: row["season"] for row in data["ranking"]} == {
        BRIM[0]: "E26: A5",
        "Name Sake#TST": "E26: A4",
    }
