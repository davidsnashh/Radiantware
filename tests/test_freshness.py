"""How an answer says where its data came from and how old it is."""

import asyncio
import json

import pytest

import server
from scraper import UpstreamError
from server import Loaded, Provenance, ago, envelope, load

NOW = 1_800_000_000.0
DAY = 86400
WARNING = "⚠️"


class Clock:
    now = NOW

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    ticking = Clock()
    monkeypatch.setattr(server.time, "time", ticking)
    return ticking


def scraped(age=0.0, ttl=2700.0):
    return Loaded({}, NOW - age, cached=False, expires_at=NOW - age + ttl)


def cached(age, ttl=2700.0):
    return Loaded({}, NOW - age, cached=True, expires_at=NOW - age + ttl)


def stale(age, ttl=2700.0, failure="Tracker.gg did not answer within 30 seconds."):
    expires = NOW - age + ttl
    return Loaded({}, NOW - age, cached=True, warning=failure, expires_at=expires, stale=True)


def meta(*pieces, undated=()):
    origin = Provenance()
    for piece in pieces:
        origin.add(piece)
    for piece in undated:
        origin.add(piece, undated=True)
    return origin.as_dict()["meta"]


def test_a_scraped_answer_is_live_and_not_stale():
    assert meta(scraped()) == {
        "provider": "tracker.gg",
        "source": "live",
        "cached_at": "2027-01-15T08:00:00+00:00",
        "age_seconds": 0,
        "is_stale": False,
        "stale_reason": None,
        "ttl_remaining_seconds": 2700,
    }


def test_an_answer_from_the_cache_says_so_with_its_age_and_time_left():
    assert meta(cached(600)) == {
        "provider": "tracker.gg",
        "source": "cache",
        "cached_at": "2027-01-15T07:50:00+00:00",
        "age_seconds": 600,
        "is_stale": False,
        "stale_reason": "within_ttl",
        "ttl_remaining_seconds": 2100,
    }


def test_data_served_after_a_failed_scrape_is_stale_and_warns_in_words():
    info = meta(stale(18 * DAY))

    assert (info["source"], info["is_stale"], info["stale_reason"]) == (
        "cache",
        True,
        "scrape_failed",
    )
    assert info["age_seconds"] == 18 * DAY
    assert info["ttl_remaining_seconds"] == 0
    warning = (
        f"{WARNING} This data is from the cache and may be outdated (scraped 18 days ago). "
        "A fresh copy could not be fetched: Tracker.gg did not answer within 30 seconds."
    )
    assert info["warnings"] == [warning]


def test_a_stale_answer_never_has_the_meta_of_a_fresh_one():
    fresh, old = meta(cached(600)), meta(stale(600))

    assert fresh != old
    assert "warnings" not in fresh


def test_an_answer_is_live_as_soon_as_one_piece_was_scraped():
    info = meta(cached(600), scraped())

    assert (info["source"], info["stale_reason"]) == ("live", None)


def test_the_oldest_piece_sets_the_age_and_the_soonest_expiry_the_time_left():
    info = meta(cached(100, ttl=5000), cached(900, ttl=5400), cached(300, ttl=1000))

    assert info["age_seconds"] == 900
    assert info["ttl_remaining_seconds"] == 700


def test_data_that_never_changes_does_not_make_an_answer_look_old():
    info = meta(cached(600, ttl=1200), undated=[cached(20 * DAY, ttl=30 * DAY)])

    assert info["age_seconds"] == 600
    assert info["ttl_remaining_seconds"] == 600


def test_an_answer_made_only_of_unchanging_data_still_has_a_date():
    info = meta(undated=[cached(20 * DAY, ttl=30 * DAY), cached(3 * DAY, ttl=30 * DAY)])

    assert info["age_seconds"] == 20 * DAY
    assert info["ttl_remaining_seconds"] == 10 * DAY
    assert info["stale_reason"] == "within_ttl"


def test_one_stale_piece_among_fresh_ones_is_named_as_a_part():
    info = meta(scraped(ttl=1200), undated=[stale(40 * DAY, ttl=30 * DAY)])

    assert info["source"] == "live"
    assert info["is_stale"] is True
    assert info["age_seconds"] == 40 * DAY
    assert info["ttl_remaining_seconds"] == 0
    assert info["warnings"][0].startswith(
        f"{WARNING} Part of this data is from the cache and may be outdated (scraped 40 days ago)"
    )


def test_unchanging_data_does_not_set_the_age_of_a_stale_answer():
    info = meta(stale(2 * DAY, ttl=1200), undated=[cached(20 * DAY, ttl=30 * DAY)])

    assert info["age_seconds"] == 2 * DAY
    assert info["ttl_remaining_seconds"] == 0
    assert "scraped 2 days ago" in info["warnings"][0]


def test_unchanging_data_that_went_stale_does_set_the_age():
    info = meta(cached(600), undated=[stale(40 * DAY, ttl=30 * DAY)])

    assert info["age_seconds"] == 40 * DAY


def test_a_stale_piece_among_cached_ones_makes_the_whole_answer_cache():
    info = meta(cached(600), stale(2 * DAY))

    assert info["source"] == "cache"
    assert info["warnings"][0].startswith(f"{WARNING} This data is from the cache")


def test_pieces_collected_apart_count_like_pieces_collected_together():
    pieces, unchanging = [stale(3 * DAY), cached(900)], cached(20 * DAY, ttl=30 * DAY)
    apart, whole = Provenance(), Provenance()
    whole.add(scraped())
    whole.warnings.append("tracker.gg is slow")
    for piece in pieces:
        apart.add(piece)
    apart.add(unchanging, undated=True)
    apart.warnings += ["tracker.gg is slow", "Career totals are unavailable right now."]

    whole.include(apart)

    together = meta(scraped(), *pieces, undated=[unchanging])
    slow = ["tracker.gg is slow", "Career totals are unavailable right now."]
    assert whole.as_dict()["meta"] == {**together, "warnings": together["warnings"] + slow}
    assert apart.stale and not Provenance().stale


def test_a_refresh_that_failed_is_stale_even_while_the_old_copy_is_within_its_lifetime():
    info = meta(stale(600, ttl=2700))

    assert info["is_stale"] is True
    assert info["ttl_remaining_seconds"] == 2100


def test_the_oldest_stale_piece_is_the_one_the_warning_names():
    info = meta(stale(2 * DAY, failure="first"), stale(9 * DAY, failure="second"))

    assert "scraped 9 days ago" in info["warnings"][0]
    assert info["warnings"][0].endswith("second")


def test_other_warnings_follow_the_stale_one_and_are_listed_once():
    origin = Provenance()
    origin.add(Loaded({}, NOW, cached=False, warning="tracker.gg is slow"))
    origin.add(stale(DAY))
    origin.add(Loaded({}, NOW, cached=False, warning="tracker.gg is slow"))
    origin.warnings.append("Career totals are unavailable right now.")

    warnings = origin.as_dict()["meta"]["warnings"]
    assert warnings[0].startswith(WARNING)
    assert warnings[1:] == ["tracker.gg is slow", "Career totals are unavailable right now."]


def test_an_answer_built_from_nothing_claims_no_date():
    info = Provenance().as_dict()["meta"]

    assert (info["source"], info["cached_at"], info["age_seconds"]) == ("live", None, None)
    assert info["ttl_remaining_seconds"] is None


@pytest.mark.parametrize(
    ("seconds", "words"),
    [
        (0, "less than a minute ago"),
        (59, "less than a minute ago"),
        (60, "1 minute ago"),
        (3599, "59 minutes ago"),
        (3600, "1 hour ago"),
        (DAY - 1, "23 hours ago"),
        (2 * DAY - 1, "1 day ago"),
        (18 * DAY, "18 days ago"),
    ],
)
def test_an_age_in_words(seconds, words):
    assert ago(seconds) == words


def answer(*pieces):
    origin = Provenance()
    for piece in pieces:
        origin.add(piece)
    return envelope({"riot_id": "Brim Stone#TST", "kd": 1.2, **origin.as_dict()})


def test_an_answer_goes_out_as_data_and_meta():
    result = answer(scraped())

    assert [block.type for block in result.content] == ["text"]
    sent = json.loads(result.content[0].text)
    assert sent == result.structured_content
    assert sent["data"] == {"riot_id": "Brim Stone#TST", "kd": 1.2}
    assert sent["meta"]["source"] == "live"


def test_a_stale_answer_starts_with_the_warning_before_the_data():
    result = answer(stale(18 * DAY))

    assert len(result.content) == 2
    assert result.content[0].text.startswith(
        f"{WARNING} This data is from the cache and may be outdated (scraped 18 days ago)"
    )
    sent = json.loads(result.content[1].text)
    assert sent["meta"]["is_stale"] is True
    assert sent["meta"]["warnings"][0] == result.content[0].text


def test_a_stale_answer_never_reads_like_a_fresh_one():
    fresh, old = answer(cached(18 * DAY, ttl=30 * DAY)), answer(stale(18 * DAY))

    assert [block.text for block in fresh.content] != [block.text for block in old.content]
    assert len(fresh.content) == 1


def test_sending_an_answer_leaves_it_as_it_was():
    built = {"kd": 1.2, **Provenance().as_dict()}
    before = dict(built)

    first, second = envelope(built), envelope(built)

    assert built == before
    assert first.structured_content == second.structured_content
    assert set(second.structured_content) == {"data", "meta"}


def test_an_answer_that_is_not_from_tracker_has_no_meta():
    result = envelope({"status": "not_implemented"})

    assert result.structured_content == {"data": {"status": "not_implemented"}}


def loading(name, ttl, fetch, **options):
    return asyncio.run(load(name, "brim stone#tst", {"case": name}, ttl, fetch, **options))


def returns(value):
    async def fetch():
        return value

    return fetch


def fails(message="Tracker.gg did not answer within 30 seconds."):
    async def fetch():
        raise UpstreamError(message)

    return fetch


def test_a_first_load_is_scraped_and_the_next_comes_from_the_cache():
    first = loading("freshness-live", 600, returns({"kd": 1.2}))
    again = loading("freshness-live", 600, fails())

    assert (first.cached, first.stale, first.expires_at) == (False, False, NOW + 600)
    assert (again.cached, again.stale, again.value) == (True, False, {"kd": 1.2})
    assert again.expires_at == NOW + 600


def test_an_expired_copy_is_served_as_stale_when_the_scrape_fails():
    loading("freshness-expired", 0, returns({"kd": 1.2}))
    served = loading("freshness-expired", 600, fails("Cloudflare keeps challenging requests."))

    assert (served.cached, served.stale, served.value) == (True, True, {"kd": 1.2})
    assert served.warning == "Cloudflare keeps challenging requests."


def test_a_forced_refresh_that_fails_serves_the_old_copy_as_stale(clock):
    loading("freshness-forced", 600, returns({"kd": 1.2}))
    clock.now += 60
    served = loading("freshness-forced", 600, fails(), force=True)

    assert served.stale is True
    assert served.expires_at == NOW + 600


def test_a_copy_too_old_for_the_caller_is_stale_when_it_cannot_be_replaced(clock):
    loading("freshness-newer", 600, returns({"kd": 1.2}))
    clock.now += 60
    served = loading("freshness-newer", 600, fails(), not_before=clock.now - 10)

    assert (served.cached, served.stale, served.value) == (True, True, {"kd": 1.2})


def test_a_copy_new_enough_for_the_caller_is_served_as_it_is(clock):
    loading("freshness-new-enough", 600, returns({"kd": 1.2}))
    clock.now += 60
    served = loading("freshness-new-enough", 600, fails(), not_before=clock.now - 100)

    assert (served.cached, served.stale) == (True, False)


def test_a_failed_scrape_with_nothing_cached_is_an_error():
    with pytest.raises(UpstreamError):
        loading("freshness-nothing", 600, fails())


def test_stale_data_can_be_refused():
    loading("freshness-refused", 0, returns({"kd": 1.2}))

    with pytest.raises(UpstreamError):
        loading("freshness-refused", 600, fails(), allow_stale=False)


def test_a_stale_load_turns_into_a_warned_answer():
    loading("freshness-whole", 0, returns({"kd": 1.2}))
    origin = Provenance()
    origin.add(loading("freshness-whole", 600, fails()))

    result = envelope({"kd": 1.2, **origin.as_dict()})

    assert result.content[0].text.startswith(WARNING)
    assert result.structured_content["meta"]["stale_reason"] == "scrape_failed"
