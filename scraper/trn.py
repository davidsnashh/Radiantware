"""Tracker.gg client: paced, retried requests made from a real browser session.

Tracker.gg has no public Valorant API, so this reads the JSON endpoints its
own profile pages load. Cloudflare challenges plain HTTP clients and direct
navigation to those endpoints, but lets the same requests through when they
are made by a page on tracker.gg, which is what PlaywrightBackend sets up.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import plistlib
import random
import sys
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Literal, Protocol
from xml.parsers.expat import ExpatError

import httpx

from config import Settings
from models import (
    AgentInsight,
    Aggregate,
    GameData,
    Leaderboard,
    MapInsight,
    MatchDetails,
    MatchPage,
    PlayerProfile,
    PremierTeam,
    RankShare,
    SearchResult,
    StatHistory,
    StatsBundle,
)

from . import locks, parsers, utils
from .exceptions import (
    BackendUnavailableError,
    BadRequestError,
    CloudflareBlockedError,
    MatchNotFoundError,
    NoDataError,
    PlayerNotFoundError,
    PrivateProfileError,
    RateLimitedError,
    TrackerError,
    TransientError,
    UpstreamError,
)
from .utils import RiotId

log = logging.getLogger(__name__)

_SITE_ORIGIN = "https://tracker.gg/"
# A tiny document on the site's origin, used as the page API requests are made from.
_ANCHOR_URL = "https://tracker.gg/robots.txt"
# A real page, loaded only when Cloudflare wants to run a challenge.
_CHALLENGE_URL = "https://tracker.gg/valorant"
_CHALLENGE_TITLES = ("just a moment", "attention required", "access denied")

# How long a backend is left alone after Cloudflare blocked it.
_BLOCK_COOLDOWN = 300.0

# Chrome will not share a profile, so copies of the server that have a browser
# open at the same time each take one of these.
_MAX_PROFILES = 3
# How often a copy looks whether it is its turn to make a request, and how long
# it waits for one when nothing says how long a request can take.
_TURN_POLL = 0.1
_TURN_TIMEOUT = 60.0

_FETCH_JS = """
async ({url, timeout}) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
        const response = await fetch(url, {
            credentials: "include",
            headers: {Accept: "application/json, text/plain, */*"},
            signal: controller.signal,
        });
        return {status: response.status, body: await response.text()};
    } catch (error) {
        return {status: 0, body: `${error.name}: ${error.message}`};
    } finally {
        clearTimeout(timer);
    }
}
"""


@dataclass(frozen=True, slots=True)
class FetchResult:
    # 0 means the browser could not complete the request at all.
    status: int
    body: str


class Backend(Protocol):
    name: str

    async def fetch(self, url: str) -> FetchResult: ...

    async def close(self) -> None: ...


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text.splitlines()[0][:300]


def _other_chrome_installs(folders: Sequence[Path] | None = None) -> list[Path]:
    """Chrome on a Mac in the places the browser library does not look.

    It only tries /Applications/Google Chrome.app. That misses a copy in the
    user's own Applications folder and one that Finder named "Google Chrome 2".
    """
    if sys.platform != "darwin":
        return []
    usual = Path("/Applications/Google Chrome.app")
    found = []
    for folder in folders or (Path("/Applications"), Path.home() / "Applications"):
        for app in sorted(folder.glob("Google Chrome*.app")):
            info = _app_info(app)
            # Beta and Canary have identifiers of their own.
            if app != usual and info.get("CFBundleIdentifier") == "com.google.Chrome":
                name = info.get("CFBundleExecutable") or "Google Chrome"
                found.append(app / "Contents" / "MacOS" / name)
    return found


def _app_info(app: Path) -> dict[str, Any]:
    """What a Mac app says about itself, or nothing when that cannot be read."""
    try:
        info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    except (OSError, ValueError, ExpatError):
        return {}
    return info if isinstance(info, dict) else {}


def _load_playwright() -> Any:
    """Prefer patchright, a drop-in Playwright build without the usual automation tells."""
    try:
        from patchright import async_api
    except ImportError:
        try:
            from playwright import async_api
        except ImportError as exc:
            raise BackendUnavailableError(
                "No browser automation library is installed. Run: pip install patchright"
            ) from exc
    return async_api


class PlaywrightBackend:
    """Keeps one persistent browser page on tracker.gg and fetches API URLs from it."""

    name = "playwright"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # _lock serialises requests, _lifecycle_lock serialises starting and stopping.
        self._lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._lifecycle_tasks: set[asyncio.Task[None]] = set()
        self._driver: Any = None
        self._context: Any = None
        self._page: Any = None
        self._profile_dir = settings.browser_profile_dir
        self._profile_lock: IO[bytes] | None = None
        self._user_agent = settings.user_agent
        self._user_agent_checked = settings.user_agent is not None or not settings.headless
        self._idle_task: asyncio.Task[None] | None = None

    async def fetch(self, url: str) -> FetchResult:
        async with self._lock:
            self._cancel_idle_close()
            try:
                return await self._fetch(url)
            except TrackerError:
                raise
            except Exception as exc:
                # Usually a crashed or closed browser, so start clean next time.
                await self._run_to_completion(self._stop)
                raise UpstreamError(f"Browser request failed: {_first_line(exc)}") from exc
            finally:
                self._schedule_idle_close()

    async def close(self) -> None:
        self._cancel_idle_close()
        async with self._lock:
            await self._run_to_completion(self._stop)

    async def _fetch(self, url: str) -> FetchResult:
        page = await self._ensure_page()
        result = await self._fetch_in_page(page, url)
        if self._is_blocked(result):
            log.warning("Cloudflare interfered with a request; trying to clear the challenge")
            await self._goto(page, _CHALLENGE_URL)
            await self._goto(page, _ANCHOR_URL)
            result = await self._fetch_in_page(page, url)
            if result.status == 0:
                raise CloudflareBlockedError(
                    f"The browser could not reach tracker.gg's data API ({result.body}), "
                    "which usually means Cloudflare is blocking it."
                )
            if self._is_blocked(result):
                raise CloudflareBlockedError(
                    "Cloudflare keeps challenging requests to tracker.gg's data API."
                )
        return result

    @staticmethod
    def _is_blocked(result: FetchResult) -> bool:
        # A challenged cross-origin request has no CORS headers, so fetch() just fails.
        return result.status == 0 or parsers.is_cloudflare_challenge(result.body)

    async def _fetch_in_page(self, page: Any, url: str) -> FetchResult:
        timeout = self._settings.request_timeout
        raw = await asyncio.wait_for(
            page.evaluate(_FETCH_JS, {"url": url, "timeout": int(timeout * 1000)}),
            timeout + 10,
        )
        if raw["status"] == 0 and raw["body"].startswith("AbortError"):
            raise UpstreamError(f"Tracker.gg did not answer within {timeout:.0f} seconds.")
        return FetchResult(raw["status"], raw["body"])

    async def _ensure_page(self) -> Any:
        await self._run_to_completion(self._start)
        page = self._page
        if page is None or page.is_closed():
            pages = self._context.pages
            page = self._page = pages[0] if pages else await self._context.new_page()
        if not page.url.startswith(_SITE_ORIGIN):
            await self._goto(page, _ANCHOR_URL)
        return page

    async def _goto(self, page: Any, url: str) -> None:
        """Navigate, then wait out a Cloudflare challenge if one is shown."""
        timeout_ms = int(self._settings.request_timeout * 1000)
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        deadline = time.monotonic() + self._settings.challenge_timeout
        while True:
            title = (await page.title()).casefold()
            if not any(marker in title for marker in _CHALLENGE_TITLES):
                return
            if time.monotonic() >= deadline:
                raise CloudflareBlockedError(
                    "Cloudflare showed a challenge that did not clear within "
                    f"{self._settings.challenge_timeout:.0f} seconds."
                )
            await asyncio.sleep(1)

    async def _run_to_completion(self, step: Callable[[], Awaitable[None]]) -> None:
        """Run a start or stop step that keeps going even if the caller is cancelled.

        A tool call can be cancelled at any await. Abandoning a launch or a
        teardown half way would leak a browser that keeps the profile locked.
        """

        async def run() -> None:
            async with self._lifecycle_lock:
                await step()

        task = asyncio.ensure_future(run())
        self._lifecycle_tasks.add(task)
        task.add_done_callback(self._lifecycle_done)
        await asyncio.shield(task)

    def _lifecycle_done(self, task: asyncio.Task[None]) -> None:
        self._lifecycle_tasks.discard(task)
        # Collect the outcome so an abandoned step does not log an unretrieved exception.
        if not task.cancelled():
            task.exception()

    async def _start(self) -> None:
        if self._context is not None:
            return
        api = _load_playwright()
        self._claim_profile()
        driver = None
        failures: list[str] = []
        try:
            driver = await api.async_playwright().start()
            for target in self._launch_targets():
                try:
                    self._context = await self._open(driver, target)
                    break
                except api.Error as exc:
                    label = next(iter(target.values()))
                    failures.append(f"{label}: {_first_line(exc)}")
            else:
                raise BackendUnavailableError(
                    "Could not start a browser (" + "; ".join(failures) + "). Install Google "
                    "Chrome, run 'patchright install chromium', or point TRN_BROWSER_EXECUTABLE "
                    "at a Chrome binary."
                )
        except BaseException:
            try:
                if driver is not None:
                    with contextlib.suppress(Exception):
                        await driver.stop()
            finally:
                # Not before the driver is down: it is what closes a half-started browser.
                self._release_profile()
            raise
        self._driver = driver
        log.info(
            "browser started (headless=%s, profile=%s)",
            self._settings.headless,
            self._profile_dir.name,
        )
        # Covers a launch whose caller was cancelled and so never schedules this itself.
        self._schedule_idle_close()

    def _claim_profile(self) -> None:
        """Take a browser profile that no other copy of the server has open."""
        if self._profile_lock is not None:
            return
        base = self._settings.browser_profile_dir
        for number in range(1, _MAX_PROFILES + 1):
            profile = base if number == 1 else base.with_name(f"{base.name}-{number}")
            try:
                lock = locks.try_lock(profile.with_name(f"{profile.name}.lock"))
            except OSError as exc:
                # No file locking here, so carry on the way a single copy would.
                log.warning("could not lock a browser profile: %s", _first_line(exc))
                lock = None
            else:
                if lock is None:
                    continue
            profile.mkdir(parents=True, exist_ok=True)
            self._profile_dir, self._profile_lock = profile, lock
            return
        raise BackendUnavailableError(
            f"All {_MAX_PROFILES} browser profiles are in use by other running copies of "
            "this server. Close one of them, or wait until its browser has been idle for a "
            "while."
        )

    def _release_profile(self) -> None:
        if self._profile_lock is not None:
            self._profile_lock.close()
            self._profile_lock = None

    def _launch_targets(self) -> list[dict[str, str]]:
        if self._settings.browser_executable:
            return [{"executable_path": str(self._settings.browser_executable)}]
        channel = self._settings.browser_channel
        targets = [{"channel": channel}]
        if channel == "chrome":
            targets += [{"executable_path": str(path)} for path in _other_chrome_installs()]
        # Fall back to the bundled Chromium when the preferred browser is missing.
        if channel != "chromium":
            targets.append({"channel": "chromium"})
        return targets

    async def _open(self, driver: Any, target: dict[str, str]) -> Any:
        context = await self._open_context(driver, target)
        if self._user_agent_checked:
            return context
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            native = await page.evaluate("navigator.userAgent")
        except BaseException:
            with contextlib.suppress(Exception):
                await context.close()
            raise
        if "Headless" in native:
            # Headless Chrome calls itself "HeadlessChrome", which is the one thing
            # Cloudflare challenges here. Relaunch with the same user agent minus that
            # word; a launch flag keeps client hints intact, unlike a CDP override.
            self._user_agent = native.replace("Headless", "")
            await context.close()
            context = await self._open_context(driver, target)
        self._user_agent_checked = True
        return context

    async def _open_context(self, driver: Any, target: dict[str, str]) -> Any:
        args = [f"--user-agent={self._user_agent}"] if self._user_agent else []
        return await driver.chromium.launch_persistent_context(
            user_data_dir=str(self._profile_dir),
            headless=self._settings.headless,
            no_viewport=True,
            args=args,
            **target,
        )

    async def _stop(self) -> None:
        context, driver = self._context, self._driver
        self._context = self._page = self._driver = None
        try:
            if context is not None:
                with contextlib.suppress(Exception):
                    await context.close()
        finally:
            try:
                if driver is not None:
                    with contextlib.suppress(Exception):
                        await driver.stop()
            finally:
                # Only now is the profile free for another copy.
                self._release_profile()

    def _cancel_idle_close(self) -> None:
        if self._idle_task is not None:
            self._idle_task.cancel()
            self._idle_task = None

    def _schedule_idle_close(self) -> None:
        self._cancel_idle_close()
        if self._context is not None and self._settings.browser_idle_seconds > 0:
            self._idle_task = asyncio.create_task(self._close_when_idle())

    async def _close_when_idle(self) -> None:
        await asyncio.sleep(self._settings.browser_idle_seconds)
        async with self._lock:
            log.info("closing idle browser")
            await self._run_to_completion(self._stop)


class FlareSolverrBackend:
    """Loads URLs through a FlareSolverr (or API-compatible) proxy server."""

    name = "flaresolverr"
    _SESSION = "valorant-trn-mcp"

    def __init__(self, settings: Settings) -> None:
        endpoint = (settings.flaresolverr_url or "").rstrip("/")
        self._endpoint = endpoint if endpoint.endswith("/v1") else f"{endpoint}/v1"
        self._max_timeout_ms = settings.flaresolverr_timeout_ms
        self._client: httpx.AsyncClient | None = None

    async def fetch(self, url: str) -> FetchResult:
        # Naming a session makes FlareSolverr reuse one browser, and its clearance.
        reply = await self._command(
            {
                "cmd": "request.get",
                "url": url,
                "maxTimeout": self._max_timeout_ms,
                "session": self._SESSION,
            }
        )
        solution = reply.get("solution") or {}
        return FetchResult(int(solution.get("status") or 0), solution.get("response") or "")

    async def close(self) -> None:
        if self._client is None:
            return
        with contextlib.suppress(TrackerError):
            await self._command({"cmd": "sessions.destroy", "session": self._SESSION})
        await self._client.aclose()
        self._client = None

    async def _command(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._max_timeout_ms / 1000 + 15)
        try:
            response = await self._client.post(self._endpoint, json=payload)
            reply = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BackendUnavailableError(
                f"FlareSolverr at {self._endpoint} is not reachable: {_first_line(exc)}"
            ) from exc
        if not isinstance(reply, dict) or reply.get("status") != "ok":
            message = reply.get("message") if isinstance(reply, dict) else None
            raise CloudflareBlockedError(
                f"FlareSolverr could not load the page: {message or 'unknown error'}"
            )
        return reply


class _BudgetUsedUp(RateLimitedError):
    """The local hourly budget is spent, which trying again cannot change."""


class RequestPacer:
    """Leaves a random, human-like gap between requests and enforces an hourly budget.

    Given a folder, both are shared with every other copy of the server that
    uses the same folder, so that together they still act like one visitor.
    Sharing only adds waiting: a copy never goes faster than it would alone.
    """

    def __init__(
        self,
        min_delay: float,
        max_delay: float,
        max_per_hour: int,
        folder: Path | None = None,
        *,
        one_at_a_time: bool = True,
        turn_timeout: float = _TURN_TIMEOUT,
    ) -> None:
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._max_per_hour = max_per_hour
        self._one_at_a_time = one_at_a_time
        self._turn_timeout = turn_timeout
        self._lock = asyncio.Lock()
        # This copy's own requests, on a clock that cannot be set.
        self._last_activity = 0.0
        self._recent: deque[float] = deque()
        # Every copy's requests, on the wall clock. The file lists the starts of the
        # last hour, and its modification time is the last start or finish.
        self._shared = folder / "pacing.json" if folder else None
        self._shared_last = 0.0
        self._shared_recent: list[float] = []
        self._turn: IO[bytes] | None = None

    async def wait(self) -> None:
        async with self._lock:
            turn, self._turn = self._turn, None
            gap = random.uniform(self._min_delay, self._max_delay)
            deadline = time.monotonic() + self._turn_timeout
            while True:
                if turn is None and time.monotonic() < deadline:
                    turn = await self._take_turn(deadline)
                try:
                    remaining = self._remaining(gap)
                    if remaining <= 0:
                        self._record_start()
                        break
                except BaseException:
                    self._end_turn(turn)
                    raise
                # Given up for the length of the gap, so that the other copies get in.
                self._end_turn(turn)
                turn = None
                await asyncio.sleep(remaining)
            if self._one_at_a_time:
                # Kept until finished(), so other copies wait for the request itself too.
                self._turn = turn
            else:
                self._end_turn(turn)

    def finished(self) -> None:
        """Count the gap from the end of a request, however long it took."""
        self._last_activity = time.monotonic()
        self._shared_last = time.time()
        if self._shared is not None:
            with contextlib.suppress(OSError):
                os.utime(self._shared)
        turn, self._turn = self._turn, None
        self._end_turn(turn)

    def _remaining(self, gap: float) -> float:
        """How long the next request still has to wait. Raises once the budget is used up."""
        clock, now = time.monotonic(), time.time()
        while self._recent and clock - self._recent[0] >= 3600:
            self._recent.popleft()
        self._load(now)
        if self._max_per_hour:
            until_free = []
            if len(self._recent) >= self._max_per_hour:
                until_free.append(3600 - (clock - self._recent[0]))
            if len(self._shared_recent) >= self._max_per_hour:
                until_free.append(3600 - (now - self._shared_recent[0]))
            if until_free:
                raise _BudgetUsedUp(
                    f"The local budget of {self._max_per_hour} tracker.gg requests per hour "
                    "is used up. The next request is allowed in about "
                    f"{max(until_free) / 60:.0f} minutes."
                )
        waits = [0.0]
        if self._last_activity:
            waits.append(self._last_activity + gap - clock)
        if self._shared_last:
            waits.append(self._shared_last + gap - now)
        return max(waits)

    def _record_start(self) -> None:
        self._last_activity = time.monotonic()
        self._recent.append(self._last_activity)
        self._shared_last = time.time()
        self._shared_recent.append(self._shared_last)
        self._save()

    async def _take_turn(self, deadline: float) -> IO[bytes] | None:
        """Wait until no other copy that shares the folder is deciding or fetching."""
        while self._shared is not None:
            try:
                turn = locks.try_lock(self._shared.with_suffix(".lock"))
            except OSError as exc:
                log.warning("pacing is not shared with other copies: %s", _first_line(exc))
                self._shared = None
                break
            if turn is not None:
                return turn
            if time.monotonic() >= deadline:
                log.warning(
                    "another copy is still busy after %.0f seconds; going ahead",
                    self._turn_timeout,
                )
                break
            await asyncio.sleep(_TURN_POLL)
        return None

    @staticmethod
    def _end_turn(turn: IO[bytes] | None) -> None:
        if turn is not None:
            turn.close()

    def _load(self, now: float) -> None:
        """Take in what every copy has recorded, when the file can be read."""
        if self._shared is not None:
            try:
                self._shared_last = max(self._shared_last, self._shared.stat().st_mtime)
                starts = [float(start) for start in json.loads(self._shared.read_text())]
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError) as exc:
                log.warning("pacing state is unreadable and starts afresh: %s", _first_line(exc))
            else:
                self._shared_recent = starts
        ahead = self._shared_last > now or any(start > now for start in self._shared_recent)
        # Times from before the clock was set back count as now. Left as they are, the
        # gap would never pass and the starts would stay in the budget for too long.
        self._shared_last = min(self._shared_last, now)
        self._shared_recent = sorted(
            min(start, now) for start in self._shared_recent if now - start < 3600
        )
        if ahead:
            self._save()
            if self._shared is not None:
                with contextlib.suppress(OSError):
                    os.utime(self._shared, (now, now))

    def _save(self) -> None:
        if self._shared is None:
            return
        try:
            self._shared.write_text(json.dumps(self._shared_recent))
        except OSError as exc:
            log.warning("pacing state could not be saved: %s", _first_line(exc))


Subject = Literal["player", "match", "search", "data"]


def _raise_api_error(status: int, errors: list[Any], subject: Subject, label: str) -> None:
    """Translate tracker.gg's error list. Codes come first: FlareSolverr hides the status."""
    entries = [error for error in errors if isinstance(error, dict)]
    codes = " ".join(str(error.get("code") or "") for error in entries)
    message = next((str(e["message"]) for e in entries if e.get("message")), codes)

    if "Private" in codes or status in (403, 451):
        raise PrivateProfileError(
            f"The tracker.gg profile of {label} is private. Its owner has to sign in at "
            "tracker.gg and make it public before stats can be read."
        )
    if "NoData" in codes:
        raise NoDataError(f"Tracker.gg has no data for {label} in this scope.")
    if "NotFound" in codes or status == 404:
        if subject == "match":
            raise MatchNotFoundError(f"Tracker.gg has no match with the ID {label}.")
        if subject == "data":
            raise NoDataError(f"Tracker.gg has no {label}.")
        raise PlayerNotFoundError(
            f"Tracker.gg could not find {label}. The Riot ID may be misspelled, or the "
            "profile does not exist."
        )
    if "InvalidParameters" in codes or status == 400:
        raise BadRequestError(f"Tracker.gg rejected the request for {label}: {message}")
    if status == 429:
        raise RateLimitedError("Tracker.gg is rate limiting this connection. Try again later.")
    raise UpstreamError(f"Tracker.gg returned an error for {label}: {message}")


def _unwrap(result: FetchResult, subject: Subject, label: str) -> Any:
    """Return the payload's data member, or raise the matching error."""
    if result.status == 429 or parsers.is_rate_limit_page(result.body):
        raise RateLimitedError("Tracker.gg is rate limiting this connection. Try again later.")
    try:
        payload = parsers.extract_json(result.body)
    except ValueError as exc:
        raise UpstreamError(
            f"Tracker.gg sent an unreadable response (HTTP {result.status})."
        ) from exc
    if not isinstance(payload, dict):
        raise UpstreamError("Tracker.gg sent an unexpected response.")
    if payload.get("errors"):
        _raise_api_error(result.status, payload["errors"], subject, label)
    if result.status >= 400 or "data" not in payload:
        raise UpstreamError(f"Tracker.gg sent an unexpected response (HTTP {result.status}).")
    return payload["data"]


def _longest_request(settings: Settings) -> float:
    """An upper limit on the time one request can take, in seconds.

    The worst case is a browser that has to start and then sit through a
    Cloudflare challenge: two launches, five page loads or fetches and three
    waits for a challenge to clear.
    """
    browser = 80 + 5 * settings.request_timeout + 3 * settings.challenge_timeout
    proxy = settings.flaresolverr_timeout_ms / 1000 + 15
    return max(browser, proxy)


class TrackerScraper:
    """High-level, rate-limited access to tracker.gg's Valorant data."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._backends = self._build_backends(settings)
        self._blocked_until: dict[str, float] = {}
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_scrapes)
        self._pacer = RequestPacer(
            settings.min_delay,
            settings.max_delay,
            settings.max_requests_per_hour,
            settings.data_dir,
            one_at_a_time=settings.max_concurrent_scrapes == 1,
            turn_timeout=_longest_request(settings),
        )

    @staticmethod
    def _build_backends(settings: Settings) -> list[Backend]:
        backends: list[Backend] = [PlaywrightBackend(settings)]
        if settings.flaresolverr_url:
            flaresolverr = FlareSolverrBackend(settings)
            if settings.backend == "flaresolverr":
                backends.insert(0, flaresolverr)
            else:
                backends.append(flaresolverr)
        elif settings.backend == "flaresolverr":
            log.warning(
                "TRN_BACKEND=flaresolverr but FLARESOLVERR_URL is not set; using the browser"
            )
        return backends

    async def fetch_profile(self, riot_id: RiotId) -> PlayerProfile:
        data = await self._get(utils.profile_url(riot_id), "player", str(riot_id))
        return parsers.parse_profile(data)

    async def fetch_stats(
        self, riot_id: RiotId, playlist: str, season_id: str | None
    ) -> StatsBundle:
        """Stats, agents and maps for one act, or for all acts when season_id is None."""
        url = utils.segments_url(riot_id, playlist, season_id)
        try:
            data = await self._get(url, "player", str(riot_id))
        except NoDataError:
            return StatsBundle()
        return parsers.parse_stats_bundle(data)

    async def fetch_match_page(
        self,
        riot_id: RiotId,
        playlist: str,
        page: int = 0,
        *,
        season_id: str | None = None,
        map_id: str | None = None,
        agent_id: str | None = None,
    ) -> MatchPage:
        url = utils.matches_url(riot_id, playlist, page, season_id, map_id, agent_id)
        try:
            data = await self._get(url, "player", str(riot_id))
        except NoDataError:
            return MatchPage()
        return parsers.parse_match_page(data)

    async def fetch_match(self, match_id: str) -> MatchDetails:
        data = await self._get(utils.match_url(match_id), "match", match_id)
        return parsers.parse_match(data)

    async def fetch_aggregate(self, riot_id: RiotId, playlist: str) -> Aggregate:
        """Tracker.gg's own totals over its recent window: teammates, party sizes and days."""
        url = utils.aggregate_url(riot_id, playlist)
        try:
            data = await self._get(url, "player", str(riot_id))
        except NoDataError:
            return Aggregate()
        return parsers.parse_aggregate(data)

    async def fetch_stat_history(self, riot_id: RiotId, stat: str, playlist: str) -> StatHistory:
        url = utils.stat_history_url(riot_id, stat, playlist)
        history = parsers.parse_stat_history(await self._get(url, "player", str(riot_id)), stat)
        if history is None:
            raise BadRequestError(f"Tracker.gg keeps no history of a stat called '{stat}'.")
        return history

    async def fetch_distribution(self, region: str, act_id: str) -> list[RankShare]:
        url = utils.distribution_url(region, act_id)
        return parsers.parse_distribution(await self._get(url, "data", "rank distribution"))

    async def fetch_leaderboard(
        self, region: str, act_id: str, skip: int, take: int
    ) -> Leaderboard:
        url = utils.leaderboard_url(region, act_id, skip, take)
        return parsers.parse_leaderboard(await self._get(url, "data", "such leaderboard"))

    async def fetch_agent_insights(self) -> list[AgentInsight]:
        data = await self._get(utils.insights_url("agents"), "data", "agent insights")
        return parsers.parse_agent_insights(data)

    async def fetch_map_insights(self) -> list[MapInsight]:
        data = await self._get(utils.insights_url("maps"), "data", "map insights")
        return parsers.parse_map_insights(data)

    async def fetch_premier(self, roster_id: str) -> PremierTeam:
        data = await self._get(utils.premier_url(roster_id), "data", "Premier team with that ID")
        return parsers.parse_premier(data)

    async def fetch_game_data(self) -> GameData:
        return parsers.parse_game_data(await self._get(utils.game_data_url(), "data", "game data"))

    async def search(self, query: str) -> list[SearchResult]:
        data = await self._get(utils.search_url(query), "search", f"'{query}'")
        return parsers.parse_search(data)

    async def close(self) -> None:
        for backend in self._backends:
            with contextlib.suppress(Exception):
                await backend.close()

    async def _get(self, url: str, subject: Subject, label: str) -> Any:
        async with self._semaphore:
            retries = 0
            while True:
                # Outside the try: an exhausted local budget must not be retried.
                await self._pacer.wait()
                try:
                    return await self._attempt(url, subject, label)
                except _BudgetUsedUp:
                    raise
                except (UpstreamError, RateLimitedError) as exc:
                    if retries >= self._settings.max_retries:
                        raise
                    delay = self._settings.backoff_base * 2**retries + random.random()
                    if isinstance(exc, RateLimitedError):
                        delay *= 5
                    retries += 1
                    log.warning("request failed (%s); retrying in %.1fs", exc, delay)
                    await asyncio.sleep(delay)

    async def _attempt(self, url: str, subject: Subject, label: str) -> Any:
        try:
            result = await self._fetch(url)
        finally:
            self._pacer.finished()
        return _unwrap(result, subject, label)

    async def _fetch(self, url: str) -> FetchResult:
        """Try each backend in order, moving on when one is blocked or unavailable."""
        failures: list[tuple[str, TransientError]] = []
        site_was_hit = False
        for backend in self._backends:
            paused = self._blocked_until.get(backend.name, 0.0) - time.monotonic()
            if paused > 0:
                reason = (
                    f"The {backend.name} backend is paused for another "
                    f"{math.ceil(paused / 60)} min after a Cloudflare block."
                )
                failures.append((backend.name, CloudflareBlockedError(reason)))
                continue
            if site_was_hit:
                # The blocked attempt already reached tracker.gg, so pace this one as well.
                await self._pacer.wait()
            try:
                result = await backend.fetch(url)
                if parsers.is_cloudflare_challenge(result.body):
                    raise CloudflareBlockedError("Cloudflare answered with a challenge page.")
            except CloudflareBlockedError as exc:
                # Leave the backend alone for a while rather than knock on every request.
                self._blocked_until[backend.name] = time.monotonic() + _BLOCK_COOLDOWN
                site_was_hit = True
                failures.append((backend.name, exc))
            except BackendUnavailableError as exc:
                failures.append((backend.name, exc))
            else:
                log.debug("%s fetched %s (HTTP %s)", backend.name, url, result.status)
                return result
            log.warning("%s backend failed: %s", backend.name, failures[-1][1])
        raise self._failure(failures)

    def _failure(self, failures: list[tuple[str, TransientError]]) -> TransientError:
        """One error for the caller that says what every backend ran into."""
        if not failures:
            return BackendUnavailableError("No scraping backend is configured.")
        reasons = [(name, str(exc).rstrip(". ") + ".") for name, exc in failures]
        if len(reasons) == 1:
            detail = reasons[0][1]
        else:
            detail = " ".join(f"[{name}] {reason}" for name, reason in reasons)
        if not any(isinstance(exc, CloudflareBlockedError) for _, exc in failures):
            return BackendUnavailableError(detail)
        advice = ["wait a few minutes"]
        if self._settings.headless:
            advice.append(
                "set TRN_HEADLESS=false so a challenge can be solved in a visible browser "
                "window (the clearance is remembered)"
            )
        if not self._settings.flaresolverr_url:
            advice.append("set FLARESOLVERR_URL to use FlareSolverr as a fallback")
        return CloudflareBlockedError(f"{detail} To get going again: {', or '.join(advice)}.")
