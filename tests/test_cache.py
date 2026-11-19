"""The SQLite cache, on a temporary file and a clock the tests move by hand."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from types import SimpleNamespace

import pytest

from cache import SQLiteCache, sqlite_cache

ME = "Brim Stone#TST"
JETT = "Jett Lag#0001"
START = 1_000_000.0


class Clock:
    def __init__(self) -> None:
        self.now = START

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(sqlite_cache, "time", SimpleNamespace(time=lambda: clock.now))
    return clock


@pytest.fixture
def store(tmp_path, clock):
    store = SQLiteCache(tmp_path / "cache.sqlite3", stale_grace=100)
    yield store
    asyncio.run(store.close())


def get(store: SQLiteCache, *args, **kwargs):
    return asyncio.run(store.get(*args, **kwargs))


def put(store: SQLiteCache, *args, **kwargs) -> None:
    asyncio.run(store.set(*args, **kwargs))


def value_of(store: SQLiteCache, *args, **kwargs):
    entry = get(store, *args, **kwargs)
    return entry and entry.value


def test_value_comes_back_with_its_times(store):
    put(store, "overview", {"kd": 1.2, "agents": ["Jett", "Sage"]}, 60, ME)
    entry = get(store, "overview", ME)
    assert entry.value == {"kd": 1.2, "agents": ["Jett", "Sage"]}
    assert entry.created_at == START
    assert entry.expires_at == START + 60
    assert not entry.is_expired


def test_unknown_key_is_a_miss(store):
    assert get(store, "overview", ME) is None


def test_entry_is_served_until_its_ttl_has_passed(store, clock):
    put(store, "overview", "fresh", 60, ME)
    clock.advance(59)
    assert value_of(store, "overview", ME) == "fresh"
    clock.advance(1)
    assert get(store, "overview", ME) is None


def test_expired_entry_is_only_returned_with_allow_stale(store, clock):
    put(store, "overview", "old", 60, ME)
    clock.advance(61)
    assert get(store, "overview", ME) is None
    stale = get(store, "overview", ME, allow_stale=True)
    assert stale.value == "old"
    assert stale.is_expired
    assert stale.created_at == START


def test_riot_ids_are_matched_case_insensitively(store):
    put(store, "overview", "mine", 60, ME)
    assert value_of(store, "overview", ME.upper()) == "mine"
    assert value_of(store, "overview", f"  {ME.lower()} ") == "mine"
    assert get(store, "overview", JETT) is None


def test_params_order_does_not_matter(store):
    put(store, "maps", "split", 60, ME, {"playlist": "competitive", "season": "s1"})
    assert value_of(store, "maps", ME, {"season": "s1", "playlist": "competitive"}) == "split"


def test_different_params_are_different_entries(store):
    put(store, "maps", "act one", 60, ME, {"season": "s1"})
    put(store, "maps", "act two", 60, ME, {"season": "s2"})
    assert value_of(store, "maps", ME, {"season": "s1"}) == "act one"
    assert value_of(store, "maps", ME, {"season": "s2"}) == "act two"
    assert get(store, "maps", ME, {"season": "s3"}) is None


def test_no_params_and_empty_params_are_the_same_entry(store):
    put(store, "profile", "bare", 60, ME)
    assert value_of(store, "profile", ME, {}) == "bare"


def test_tools_do_not_share_entries(store):
    put(store, "agents", "agent table", 60, ME)
    assert get(store, "maps", ME) is None


def test_entry_without_a_riot_id(store):
    put(store, "game_data", {"maps": ["Split"]}, 60)
    assert value_of(store, "game_data") == {"maps": ["Split"]}
    assert get(store, "game_data", ME) is None


def test_storing_again_replaces_the_value_and_the_ttl(store, clock):
    put(store, "overview", "first", 10, ME)
    clock.advance(5)
    put(store, "overview", "second", 60, ME.lower())
    clock.advance(30)
    entry = get(store, "overview", ME)
    assert entry.value == "second"
    assert entry.created_at == START + 5


def test_text_outside_ascii_survives(store):
    put(store, "search", {"riot_id": "Jétt Läg#0001", "note": "狙撃"}, 60)
    assert value_of(store, "search") == {"riot_id": "Jétt Läg#0001", "note": "狙撃"}


def test_entries_survive_closing_and_a_second_cache_on_the_same_file(store, tmp_path):
    put(store, "overview", "kept", 60, ME)
    asyncio.run(store.close())
    assert value_of(store, "overview", ME) == "kept"

    other = SQLiteCache(tmp_path / "cache.sqlite3")
    try:
        assert value_of(other, "overview", ME) == "kept"
    finally:
        asyncio.run(other.close())


def test_missing_folders_are_created(tmp_path, clock):
    path = tmp_path / "not" / "there" / "yet" / "cache.sqlite3"
    nested = SQLiteCache(path)
    try:
        put(nested, "overview", 1, 60, ME)
        assert value_of(nested, "overview", ME) == 1
        assert path.is_file()
    finally:
        asyncio.run(nested.close())


def fill(store: SQLiteCache) -> None:
    put(store, "overview", "my overview", 60, ME)
    put(store, "maps", "my maps", 60, ME, {"season": "s1"})
    put(store, "maps", "my other maps", 60, ME, {"season": "s2"})
    put(store, "maps", "their maps", 60, JETT)
    put(store, "game_data", "lists", 60)


def test_invalidate_by_tool(store):
    fill(store)
    assert asyncio.run(store.invalidate(tool="maps")) == 3
    assert get(store, "maps", ME, {"season": "s1"}) is None
    assert get(store, "maps", JETT) is None
    assert value_of(store, "overview", ME) == "my overview"
    assert value_of(store, "game_data") == "lists"


def test_invalidate_by_riot_id(store):
    fill(store)
    assert asyncio.run(store.invalidate(riot_id=f" {ME.upper()} ")) == 3
    assert get(store, "overview", ME) is None
    assert get(store, "maps", ME, {"season": "s2"}) is None
    assert value_of(store, "maps", JETT) == "their maps"
    assert value_of(store, "game_data") == "lists"


def test_invalidate_by_tool_and_riot_id(store):
    fill(store)
    assert asyncio.run(store.invalidate(tool="maps", riot_id=ME)) == 2
    assert value_of(store, "overview", ME) == "my overview"
    assert value_of(store, "maps", JETT) == "their maps"


def test_invalidate_without_a_filter_empties_the_cache(store):
    fill(store)
    assert asyncio.run(store.invalidate()) == 5
    assert get(store, "game_data") is None
    assert asyncio.run(store.invalidate()) == 0


def test_purge_only_drops_entries_past_the_stale_grace_period(store, clock):
    put(store, "long gone", 1, 10)
    put(store, "just expired", 2, 150)
    put(store, "fresh", 3, 1000)
    # Grace is 100 seconds: the first ran out 190 seconds ago, the second 50.
    clock.advance(200)
    assert asyncio.run(store.purge_expired()) == 1
    assert get(store, "long gone", allow_stale=True) is None
    assert value_of(store, "just expired", allow_stale=True) == 2
    assert value_of(store, "fresh") == 3
    assert asyncio.run(store.purge_expired()) == 0


def test_purge_keeps_an_entry_exactly_at_the_end_of_the_grace_period(store, clock):
    put(store, "edge", 1, 10)
    clock.advance(110)
    assert asyncio.run(store.purge_expired()) == 0
    clock.advance(1)
    assert asyncio.run(store.purge_expired()) == 1


def test_broken_cache_file_is_a_logged_miss(tmp_path, clock, caplog):
    path = tmp_path / "cache.sqlite3"
    path.write_bytes(b"this was never a database" * 200)
    broken = SQLiteCache(path)
    with caplog.at_level(logging.WARNING, logger=sqlite_cache.log.name):
        assert get(broken, "overview", ME) is None
        assert get(broken, "overview", ME, allow_stale=True) is None
    assert "cache read failed for overview" in caplog.text


def test_broken_cache_file_does_not_fail_writes_or_deletes(tmp_path, clock, caplog):
    path = tmp_path / "cache.sqlite3"
    path.write_bytes(b"this was never a database" * 200)
    broken = SQLiteCache(path)
    with caplog.at_level(logging.WARNING, logger=sqlite_cache.log.name):
        put(broken, "overview", "lost", 60, ME)
        assert asyncio.run(broken.invalidate(tool="overview")) == 0
        assert asyncio.run(broken.purge_expired()) == 0
    assert "cache write failed for overview" in caplog.text
    assert "cache delete failed" in caplog.text
    asyncio.run(broken.close())


def test_row_that_is_not_json_is_a_logged_miss(store, tmp_path, caplog):
    put(store, "overview", "fine", 60, ME)
    asyncio.run(store.close())
    with sqlite3.connect(tmp_path / "cache.sqlite3") as conn:
        conn.execute("UPDATE cache SET value = '{half a value'")
    conn.close()

    with caplog.at_level(logging.WARNING, logger=sqlite_cache.log.name):
        assert get(store, "overview", ME) is None
    assert "cache read failed for overview" in caplog.text


def test_value_that_cannot_be_stored_is_logged_and_keeps_the_old_entry(store, caplog):
    put(store, "overview", "kept", 60, ME)
    with caplog.at_level(logging.WARNING, logger=sqlite_cache.log.name):
        put(store, "overview", {"players": {JETT}}, 60, ME)
    assert "cache write failed for overview" in caplog.text
    assert value_of(store, "overview", ME) == "kept"
