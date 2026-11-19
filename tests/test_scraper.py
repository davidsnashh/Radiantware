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


def test_a_rate_limit_from_the_site_is_retried(tmp_path):
    backend = FakeBackend("browser", FetchResult(429, ""), answer({"ok": 1}))

    assert get(scraper(tmp_path, backend)) == {"ok": 1}


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
