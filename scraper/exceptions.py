"""Errors raised by the scraper. Their messages are written for the end user."""

from __future__ import annotations


class TrackerError(Exception):
    """Base class for every scraper failure."""


class InvalidRiotIdError(TrackerError, ValueError):
    """The supplied Riot ID, match ID or playlist is malformed."""


class PlayerNotFoundError(TrackerError):
    """Tracker.gg does not know this Riot ID."""


class PrivateProfileError(TrackerError):
    """The profile exists but its owner has not made it public."""


class MatchNotFoundError(TrackerError):
    """Tracker.gg has no data for this match."""


class NoDataError(TrackerError):
    """The player exists but has nothing recorded for the requested scope."""


class BadRequestError(TrackerError):
    """Tracker.gg rejected the request parameters."""


class TransientError(TrackerError):
    """Failures that may go away on their own; cached data is a fair substitute."""


class RateLimitedError(TransientError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class CloudflareBlockedError(TransientError):
    """Cloudflare served a challenge or block page that could not be passed."""


class BackendUnavailableError(TransientError):
    """The browser or FlareSolverr could not be started or reached."""


class UpstreamError(TransientError):
    """Tracker.gg answered with something unexpected (5xx, timeout, bad payload)."""
