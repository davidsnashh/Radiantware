import asyncio
import json
import time

import pytest

from config import Settings
from scraper import (
    BackendUnavailableError,
    CloudflareBlockedError,
    MatchNotFoundError,
    NoDataError,
    PlayerNotFoundError,
    PrivateProfileError,
    RateLimitedError,
    RiotId,
    TrackerScraper,
    UpstreamError,
    trn,
)
from scraper.locks import try_lock
from scraper.trn import FetchResult

PLAYER = RiotId.parse("Brim Stone#TST")
CHALLENGE = "<html><title>Just a moment...</title></html>"


def answer(data, status=200):
    return FetchResult(status, json.dumps({"data": data}))


def failure(code, status, message="it went wrong"):
    return FetchResult(status, json.dumps({"errors": [{"code": code, "message": message}]}))


class FakeBackend:
    def __init__(self, name, *results):
        self.name = name
        self.results = list(results)
        self.calls = 0

    async def fetch(self, url):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def close(self):
        pass


@pytest.fixture(autouse=True)
def no_retry_jitter(monkeypatch):
    monkeypatch.setattr(trn.random, "random", lambda: 0.0)


class Clock:
    """The wall clock, which a test can move."""

    def __init__(self):
        self.real, self.ahead = time.time, 0.0

    def __call__(self):
        return self.real() + self.ahead


@pytest.fixture
def clock(monkeypatch):
    moved = Clock()
    monkeypatch.setattr(time, "time", moved)
    return moved


def scraper(folder, *backends, **settings):
    options = {"min_delay": 0, "max_delay": 0, "backoff_base": 0, "max_requests_per_hour": 0}
    client = TrackerScraper(Settings(_env_file=None, data_dir=folder, **(options | settings)))
    client._backends = list(backends)
    return client


def get(client, subject="player", label="Brim Stone#TST"):
    return asyncio.run(client._get("https://example.invalid/data", subject, label))


def test_the_data_member_of_the_answer_is_returned(tmp_path):
    client = scraper(tmp_path, FakeBackend("browser", answer({"rank": "Gold 2"})))

    assert get(client) == {"rank": "Gold 2"}


def test_json_inside_a_browser_viewer_page_is_read(tmp_path):
    page = '<html><body><pre>{"data": {"ok": true}}</pre></body></html>'
    client = scraper(tmp_path, FakeBackend("browser", FetchResult(200, page)))

    assert get(client) == {"ok": True}


@pytest.mark.parametrize(
    ("subject", "error"),
    [("player", PlayerNotFoundError), ("match", MatchNotFoundError), ("data", NoDataError)],
)
def test_not_found_names_what_was_missing(tmp_path, subject, error):
    client = scraper(
        tmp_path, FakeBackend("browser", failure("CollectorResultStatus::NotFound", 404))
    )

    with pytest.raises(error):
        get(client, subject)


def test_a_private_profile_is_reported_as_private(tmp_path):
    backend = FakeBackend("browser", failure("CollectorResultStatus::Private", 451))

    with pytest.raises(PrivateProfileError, match="private"):
        get(scraper(tmp_path, backend))
    assert backend.calls == 1


def test_no_data_for_a_player_means_empty_stats(tmp_path):
    client = scraper(tmp_path, FakeBackend("browser", failure("NoData", 200)))

    stats = asyncio.run(client.fetch_stats(PLAYER, "competitive", None))

    assert not stats.agents and not stats.maps


def test_a_failing_request_is_retried_and_then_given_up(tmp_path):
    backend = FakeBackend("browser", *[FetchResult(500, "oops")] * 3)

    with pytest.raises(UpstreamError):
        get(scraper(tmp_path, backend, max_retries=2))
    assert backend.calls == 3


def test_a_retry_that_works_returns_the_data(tmp_path):
    backend = FakeBackend("browser", FetchResult(502, "bad gateway"), answer({"ok": 1}))

    assert get(scraper(tmp_path, backend)) == {"ok": 1}
    assert backend.calls == 2


def rate_limited_then(*results):
    return FakeBackend("browser", FetchResult(429, ""), *results)


def test_a_rate_limit_from_the_site_is_not_retried(tmp_path):
    backend = rate_limited_then(answer({"ok": 1}))

    with pytest.raises(RateLimitedError, match="rate limiting this connection"):
        get(scraper(tmp_path, backend))
    assert backend.calls == 1


def test_nothing_is_requested_while_the_site_is_rate_limiting(tmp_path):
    backend = rate_limited_then(answer({"ok": 1}))
    client = scraper(tmp_path, backend)
    with pytest.raises(RateLimitedError):
        get(client)

    with pytest.raises(RateLimitedError, match="paused for another 5 min"):
        get(client)
    assert backend.calls == 1


def pause_left(client):
    return client._pause_state()[0] - time.time()


def turn_is_free(folder):
    free = try_lock(folder / "pacing.lock")
    if free is not None:
        free.close()
    return free is not None


def test_requests_go_on_once_the_pause_is_over(tmp_path, clock):
    backend = rate_limited_then(answer({"ok": 1}))
    client = scraper(tmp_path, backend)
    with pytest.raises(RateLimitedError):
        get(client)

    clock.ahead += 301

    assert get(client) == {"ok": 1}


def test_the_pause_doubles_up_to_an_hour_while_the_site_keeps_rate_limiting(tmp_path, clock):
    client = scraper(tmp_path, FakeBackend("browser", *[FetchResult(429, "")] * 6))
    pauses = []
    for _ in range(6):
        with pytest.raises(RateLimitedError):
            get(client)
        pauses.append(round(pause_left(client)))
        clock.ahead += pauses[-1] + 1

    assert pauses == [300, 600, 1200, 2400, 3600, 3600]


def test_one_answer_that_works_makes_the_next_pause_short_again(tmp_path, clock):
    backend = rate_limited_then(FetchResult(429, ""), answer({"ok": 1}), FetchResult(429, ""))
    client = scraper(tmp_path, backend)
    for _ in range(2):
        with pytest.raises(RateLimitedError):
            get(client)
        clock.ahead += 601
    get(client)

    with pytest.raises(RateLimitedError):
        get(client)
    assert round(pause_left(client)) == 300


def test_refusals_in_one_burst_count_once(tmp_path):
    client = scraper(tmp_path)
    client._pause()
    client._pause()

    assert round(pause_left(client)) == 300


def test_a_rate_limit_after_a_failure_ends_the_retries_and_starts_the_pause(tmp_path):
    backend = FakeBackend(
        "browser", FetchResult(500, "oops"), FetchResult(429, ""), answer({"ok": 1})
    )
    client = scraper(tmp_path, backend, max_retries=3)

    with pytest.raises(RateLimitedError):
        get(client)
    assert backend.calls == 2
    assert pause_left(client) > 0


def test_another_copy_holds_back_as_well(tmp_path):
    one = scraper(tmp_path, rate_limited_then())
    waiting = FakeBackend("browser", answer({"ok": 1}))
    other = scraper(tmp_path, waiting)
    with pytest.raises(RateLimitedError):
        get(one)

    with pytest.raises(RateLimitedError, match="paused for another 5 min"):
        get(other)
    assert waiting.calls == 0


def test_the_pause_outlasts_a_restart(tmp_path):
    with pytest.raises(RateLimitedError):
        get(scraper(tmp_path, rate_limited_then()))
    backend = FakeBackend("browser", answer({"ok": 1}))

    with pytest.raises(RateLimitedError, match="paused"):
        get(scraper(tmp_path, backend))
    assert backend.calls == 0


def test_copies_count_the_rate_limits_in_a_row_together(tmp_path, clock):
    one, other = scraper(tmp_path, rate_limited_then()), scraper(tmp_path, rate_limited_then())
    with pytest.raises(RateLimitedError):
        get(one)
    clock.ahead += 301

    with pytest.raises(RateLimitedError):
        get(other)
    assert round(pause_left(one)) == 600


def test_an_answer_that_works_in_one_copy_ends_the_count_for_all(tmp_path, clock):
    one = scraper(tmp_path, rate_limited_then(FetchResult(429, "")))
    other = scraper(tmp_path, FakeBackend("browser", answer({"ok": 1})))
    with pytest.raises(RateLimitedError):
        get(one)
    clock.ahead += 301
    get(other)

    with pytest.raises(RateLimitedError):
        get(one)
    assert round(pause_left(one)) == 300


class RateLimitedSlowly:
    name = "browser"

    async def fetch(self, url):
        await asyncio.sleep(0.05)
        return FetchResult(429, "")

    async def close(self):
        pass


def test_a_copy_that_was_waiting_its_turn_sends_nothing_once_the_pause_began(tmp_path):
    waiting = FakeBackend("browser", answer({"ok": 1}))
    one, other = scraper(tmp_path, RateLimitedSlowly()), scraper(tmp_path, waiting)

    async def both():
        url = "https://example.invalid/data"
        return await asyncio.gather(
            one._get(url, "data", "x"), other._get(url, "data", "x"), return_exceptions=True
        )

    first, second = asyncio.run(both())

    assert isinstance(first, RateLimitedError)
    assert isinstance(second, RateLimitedError) and "paused" in str(second)
    assert waiting.calls == 0
    assert turn_is_free(tmp_path)


def test_an_answer_that_was_under_way_does_not_end_a_pause(tmp_path):
    other = scraper(tmp_path)

    class AnswersLate:
        name = "browser"

        async def fetch(self, url):
            # Another copy is refused while this request is under way.
            other._pause()
            return answer({"ok": 1})

        async def close(self):
            pass

    client = scraper(tmp_path, AnswersLate())

    assert get(client) == {"ok": 1}
    assert pause_left(client) > 0


def test_a_clock_that_was_set_back_does_not_stretch_the_pause(tmp_path, clock):
    client = scraper(tmp_path, FakeBackend("browser", answer({"ok": 1})))
    client._pause()
    clock.ahead -= 86400

    assert round(pause_left(client)) == 3600
    clock.ahead += 3601
    assert get(client) == {"ok": 1}


@pytest.mark.parametrize(
    "content",
    ["", "not json", "[1, 2]", '{"until": "soon"}', '{"until": 1e999, "in_a_row": 1e999}'],
)
def test_a_pause_file_that_cannot_be_read_is_ignored(tmp_path, content):
    (tmp_path / "rate-limit.json").write_text(content)
    client = scraper(tmp_path, FakeBackend("browser", answer({"ok": 1})))

    assert get(client) == {"ok": 1}


def test_the_pause_holds_for_this_copy_when_it_cannot_be_written_down(tmp_path):
    backend = rate_limited_then(answer({"ok": 1}))
    client = scraper(tmp_path, backend)
    (tmp_path / "in-the-way").write_text("")
    client._pause_file = tmp_path / "in-the-way" / "rate-limit.json"
    with pytest.raises(RateLimitedError):
        get(client)

    with pytest.raises(RateLimitedError, match="paused"):
        get(client)
    assert backend.calls == 1


def test_the_turn_is_free_after_a_request_refused_by_the_pause(tmp_path):
    client = scraper(tmp_path, rate_limited_then())
    for _ in range(2):
        with pytest.raises(RateLimitedError):
            get(client)

    assert turn_is_free(tmp_path)


def test_a_spent_local_budget_does_not_start_a_pause(tmp_path):
    backend = FakeBackend("browser", answer({"ok": 1}), answer({"ok": 2}))
    client = scraper(tmp_path, backend, max_requests_per_hour=1)
    get(client)
    with pytest.raises(RateLimitedError, match="local budget"):
        get(client)

    assert pause_left(client) <= 0
    assert not (tmp_path / "rate-limit.json").exists()


def test_a_rate_limit_named_in_the_error_list_is_recognised(tmp_path):
    backend = FakeBackend("browser", failure("RateLimitExceeded", 200), answer({"ok": 1}))

    with pytest.raises(RateLimitedError):
        get(scraper(tmp_path, backend))
    assert backend.calls == 1


def test_a_rate_limit_page_is_recognised(tmp_path):
    page = "<html><body>Error 1015: you are being rate limited</body></html>"
    backend = FakeBackend("browser", FetchResult(200, page))

    with pytest.raises(RateLimitedError):
        get(scraper(tmp_path, backend, max_retries=0))


def test_a_player_that_does_not_exist_is_not_retried(tmp_path):
    backend = FakeBackend("browser", failure("CollectorResultStatus::NotFound", 404))

    with pytest.raises(PlayerNotFoundError):
        get(scraper(tmp_path, backend))
    assert backend.calls == 1


def test_the_local_budget_stops_requests_without_retrying(tmp_path):
    backend = FakeBackend("browser", answer({"ok": 1}), answer({"ok": 2}))
    client = scraper(tmp_path, backend, max_requests_per_hour=1)
    get(client)

    with pytest.raises(RateLimitedError, match="local budget"):
        get(client)
    assert backend.calls == 1


def test_a_cloudflare_block_moves_on_to_the_next_backend(tmp_path):
    browser = FakeBackend("browser", FetchResult(200, CHALLENGE))
    proxy = FakeBackend("proxy", answer({"ok": 1}))

    assert get(scraper(tmp_path, browser, proxy)) == {"ok": 1}
    assert (browser.calls, proxy.calls) == (1, 1)


def test_a_blocked_backend_is_left_alone_for_a_while(tmp_path):
    browser = FakeBackend("browser", FetchResult(200, CHALLENGE), answer({"never": "asked"}))
    proxy = FakeBackend("proxy", answer({"ok": 1}), answer({"ok": 2}))
    client = scraper(tmp_path, browser, proxy)
    get(client)

    assert get(client) == {"ok": 2}
    assert browser.calls == 1


def test_a_block_with_no_other_backend_says_how_to_get_going(tmp_path):
    client = scraper(tmp_path, FakeBackend("browser", FetchResult(200, CHALLENGE)))

    with pytest.raises(CloudflareBlockedError, match="TRN_HEADLESS=false"):
        get(client)


def test_a_backend_that_cannot_start_is_reported(tmp_path):
    broken = FakeBackend("browser", BackendUnavailableError("Could not start a browser."))

    with pytest.raises(BackendUnavailableError, match="Could not start a browser"):
        get(scraper(tmp_path, broken))


def test_the_turn_is_free_again_after_a_request_whatever_happened(tmp_path):
    client = scraper(
        tmp_path,
        FakeBackend("browser", answer({"ok": 1}), failure("NotFound", 404), RuntimeError("boom")),
    )
    get(client)
    with pytest.raises(PlayerNotFoundError):
        get(client)
    with pytest.raises(RuntimeError):
        get(client)

    free = try_lock(tmp_path / "pacing.lock")
    assert free is not None
    free.close()


class SlowBackend:
    name = "browser"

    def __init__(self, spans):
        self.spans = spans

    async def fetch(self, url):
        started = time.monotonic()
        await asyncio.sleep(0.2)
        self.spans.append((started, time.monotonic()))
        return answer({"ok": True})

    async def close(self):
        pass


def two_copies_fetching_at_once(folder, **settings):
    spans = []
    one = scraper(folder, SlowBackend(spans), **settings)
    other = scraper(folder, SlowBackend(spans), **settings)

    async def both():
        url = "https://example.invalid/data"
        await asyncio.gather(one._get(url, "data", "x"), other._get(url, "data", "x"))

    asyncio.run(both())
    return sorted(spans)


def test_two_copies_make_one_request_at_a_time(tmp_path):
    (_, first_ended), (second_started, _) = two_copies_fetching_at_once(tmp_path)

    assert second_started >= first_ended


def test_two_copies_set_to_two_at_a_time_may_overlap(tmp_path):
    spans = two_copies_fetching_at_once(tmp_path, max_concurrent_scrapes=2)
    (_, first_ended), (second_started, _) = spans

    assert second_started < first_ended


def test_a_spent_budget_met_between_two_backends_is_not_retried(tmp_path):
    browser = FakeBackend("browser", FetchResult(200, CHALLENGE))
    proxy = FakeBackend("proxy", answer({"ok": 1}))
    client = scraper(tmp_path, browser, proxy, max_requests_per_hour=1, backoff_base=3)
    started = time.monotonic()

    with pytest.raises(RateLimitedError, match="local budget"):
        get(client)
    assert time.monotonic() - started < 1
    assert proxy.calls == 0
    # A budget of our own that ran out is not tracker.gg asking for fewer requests.
    assert pause_left(client) <= 0


def test_two_copies_count_their_requests_together(tmp_path):
    one = scraper(tmp_path, FakeBackend("browser", answer({"ok": 1})), max_requests_per_hour=2)
    other = scraper(
        tmp_path,
        FakeBackend("browser", answer({"ok": 2}), answer({"ok": 3})),
        max_requests_per_hour=2,
    )
    get(one)
    get(other)

    with pytest.raises(RateLimitedError):
        get(other)
