"""Every tool that reads tracker.gg says how fresh its answer is, whatever happens to the scrape."""

import asyncio
import datetime as dt
import json
import time

import pytest
import sample_payloads as sp

import server
from cache import SQLiteCache
from models import (
    AgentInsight,
    Aggregate,
    DayStats,
    GameData,
    Leaderboard,
    LeaderboardRow,
    MapInsight,
    MatchEntry,
    MatchPage,
    PartyRecord,
    PremierTeam,
    RankShare,
    SearchResult,
    StatHistory,
    TeammateRecord,
)
from scraper import UpstreamError, parsers

DAY = 86400
REPLAY_TOOLS = {"list_local_replays", "analyze_replay", "get_utility_effectiveness"}
PLAYER = sp.BRIM


def game_data():
    now = dt.datetime.now(dt.UTC)
    act = {
        "id": sp.ACT_ID,
        "name": "V26: ACT 5",
        "starts": (now - dt.timedelta(days=10)).isoformat(),
        "ends": (now + dt.timedelta(days=300)).isoformat(),
    }
    return GameData.model_validate(
        {
            "agents": [{"name": "Brimstone", "uuid": "agent-brimstone"}],
            "maps": [{"name": "Split", "uuid": "map-split"}],
            "weapons": [{"name": "Vandal"}],
            "acts": [act],
            "playlists": {"competitive": "Competitive"},
        }
    )


class FakeTracker:
    """Answers like tracker.gg would, or fails once it is told to."""

    def __init__(self):
        self.failure = None
        self.calls = 0

    def asked(self):
        self.calls += 1
        if self.failure:
            raise self.failure

    async def fetch_profile(self, rid):
        self.asked()
        return parsers.parse_profile(sp.sample_profile())

    async def fetch_stats(self, rid, playlist, season_id):
        self.asked()
        return parsers.parse_stats_bundle(sp.stat_segments(season_id))

    async def fetch_match_page(self, rid, playlist, page=0, **filters):
        self.asked()
        entry = MatchEntry(match_id=sp.MATCH_ID, map="Split", agent="Brimstone")
        return MatchPage(matches=[entry], next_page=None)

    async def fetch_match(self, match_id):
        self.asked()
        return parsers.parse_match(sp.sample_match())

    async def fetch_aggregate(self, rid, playlist):
        self.asked()
        return Aggregate(
            teammates=[TeammateRecord(riot_id=sp.JETT, matches=3)],
            parties=[PartyRecord(party_size=1, matches=3)],
            days=[DayStats(date="2026-11-20", matches=3)],
        )

    async def fetch_stat_history(self, rid, stat, playlist):
        self.asked()
        return StatHistory(stat=stat, points=[{"date": "2026-11-20", "value": 1.1}])

    async def fetch_distribution(self, region, act_id):
        self.asked()
        return [RankShare(tier="Gold 1", share=50.0, players=10)]

    async def fetch_leaderboard(self, region, act_id, skip, take):
        self.asked()
        return Leaderboard(title="Leaderboard", rows=[LeaderboardRow(riot_id=sp.JETT, rank=1)])

    async def fetch_agent_insights(self):
        self.asked()
        return [AgentInsight(agent="Jett")]

    async def fetch_map_insights(self):
        self.asked()
        return [MapInsight(map="Split")]

    async def fetch_premier(self, roster_id):
        self.asked()
        return PremierTeam(roster_id=roster_id, name="Team")

    async def fetch_game_data(self):
        self.asked()
        return game_data()

    async def search(self, query):
        self.asked()
        return [SearchResult(riot_id=PLAYER)]


class Progress:
    async def report_progress(self, *args, **kwargs):
        pass


class Clock:
    def __init__(self):
        self.real, self.ahead = time.time, 0.0

    def __call__(self):
        return self.real() + self.ahead


# For each tool: how to call it, and how far ahead its cached data has expired
# while a stale copy may still be served (a week past the end of its lifetime).
TOOLS = {
    "get_player_overview": (lambda: server.get_player_overview(riot_id=PLAYER), 2),
    "get_player_agents": (lambda: server.get_player_agents(riot_id=PLAYER), 2),
    "get_player_maps": (lambda: server.get_player_maps(riot_id=PLAYER), 2),
    "get_player_weapons": (lambda: server.get_player_weapons(riot_id=PLAYER), 2),
    "get_recent_matches": (
        lambda: server.get_recent_matches(riot_id=PLAYER, ctx=Progress(), limit=5),
        2,
    ),
    "get_match_details": (lambda: server.get_match_details(match_id_or_url=sp.MATCH_ID), 31),
    "get_match_rounds": (lambda: server.get_match_rounds(match_id_or_url=sp.MATCH_ID), 31),
    "get_round_stats": (lambda: server.get_round_stats(riot_id=PLAYER, ctx=Progress()), 2),
    "get_teammate_stats": (lambda: server.get_teammate_stats(riot_id=PLAYER, ctx=Progress()), 2),
    "compare_players": (lambda: server.compare_players(riot_ids=[PLAYER, sp.JETT]), 2),
    "get_top_teammates": (lambda: server.get_top_teammates(riot_id=PLAYER), 2),
    "get_daily_stats": (lambda: server.get_daily_stats(riot_id=PLAYER), 2),
    "get_stat_history": (lambda: server.get_stat_history(riot_id=PLAYER), 2),
    "get_rank_distribution": (lambda: server.get_rank_distribution(), 2),
    "get_leaderboard": (lambda: server.get_leaderboard(), 2),
    "get_meta_insights": (lambda: server.get_meta_insights(), 2),
    "get_premier_team": (lambda: server.get_premier_team(riot_id=PLAYER), 2),
    "get_game_data": (lambda: server.get_game_data(kind="agents"), 8),
    "search_player": (lambda: server.search_player(query="Brim"), 2),
}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A tracker that can be made to fail, a cache of its own and a clock that can be moved."""
    tracker, clock = FakeTracker(), Clock()
    monkeypatch.setattr(server, "tracker", tracker)
    monkeypatch.setattr(server, "cache", SQLiteCache(tmp_path / "cache.sqlite3"))
    monkeypatch.setattr(time, "time", clock)
    return tracker, clock


def ask(name):
    result = asyncio.run(TOOLS[name][0]())
    blocks = [block.text for block in result.content]
    answer = result.structured_content
    assert json.loads(blocks[-1]) == answer
    assert set(answer) == {"data", "meta"}
    assert "meta" not in answer["data"]
    return blocks, answer["meta"]


def test_every_tool_that_reads_tracker_is_covered_here():
    registered = {tool.name for tool in asyncio.run(server.mcp.list_tools())}

    assert registered - REPLAY_TOOLS == set(TOOLS)


@pytest.mark.parametrize("name", TOOLS)
def test_a_first_answer_is_live(name, world):
    blocks, meta = ask(name)

    assert len(blocks) == 1
    assert (meta["source"], meta["is_stale"], meta["stale_reason"]) == ("live", False, None)
    assert meta["age_seconds"] < 5
    assert meta["ttl_remaining_seconds"] > 0


@pytest.mark.parametrize("name", TOOLS)
def test_the_same_answer_again_comes_from_the_cache_without_asking_tracker(name, world):
    tracker, _ = world
    ask(name)
    asked_before = tracker.calls

    blocks, meta = ask(name)

    assert tracker.calls == asked_before
    assert len(blocks) == 1
    assert (meta["source"], meta["is_stale"], meta["stale_reason"]) == (
        "cache",
        False,
        "within_ttl",
    )


@pytest.mark.parametrize("name", TOOLS)
def test_an_answer_that_could_not_be_refreshed_is_stale_and_says_so_first(name, world):
    tracker, clock = world
    ask(name)
    clock.ahead = TOOLS[name][1] * DAY
    tracker.failure = UpstreamError("Tracker.gg did not answer within 30 seconds.")

    blocks, meta = ask(name)

    assert (meta["source"], meta["is_stale"], meta["stale_reason"]) == (
        "cache",
        True,
        "scrape_failed",
    )
    assert meta["ttl_remaining_seconds"] == 0
    assert meta["age_seconds"] >= TOOLS[name][1] * DAY
    assert len(blocks) == 2
    assert blocks[0] == meta["warnings"][0]
    assert blocks[0].startswith("⚠️ This data is from the cache and may be outdated")
    assert "Tracker.gg did not answer within 30 seconds." in blocks[0]


def test_an_act_filter_from_lists_that_could_not_be_refreshed_marks_the_answer_stale(world):
    tracker, clock = world
    asyncio.run(server.get_rank_distribution())
    # The lists of acts are a week old by then, the distribution is not asked for again
    # because it is made to look fresh.
    clock.ahead = 8 * DAY
    tracker.failure = UpstreamError("Tracker.gg did not answer within 30 seconds.")

    async def keep_the_distribution_fresh():
        rows = [{"tier": "Gold 1", "share": 50.0, "players": 10}]
        params = {"region": "na", "act": sp.ACT_ID, "v": server.CACHE_VERSION}
        await server.cache.set("distribution", rows, 3600, "", params)

    asyncio.run(keep_the_distribution_fresh())
    result = asyncio.run(server.get_rank_distribution())

    assert result.structured_content["meta"]["is_stale"] is True
    assert len(result.content) == 2
