"""Runtime settings, read from the environment or a local .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRN_",
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    # Where the SQLite cache and the browser profile live.
    data_dir: Path = BASE_DIR / ".data"

    # Cache lifetimes in seconds.
    cache_ttl_overview: int = Field(45 * MINUTE, ge=0)
    cache_ttl_agents: int = Field(90 * MINUTE, ge=0)
    cache_ttl_maps: int = Field(90 * MINUTE, ge=0)
    cache_ttl_matches: int = Field(20 * MINUTE, ge=0)
    cache_ttl_career: int = Field(6 * HOUR, ge=0)
    cache_ttl_search: int = Field(1 * HOUR, ge=0)
    # Finished matches never change, so their scoreboards can be kept for a long time.
    cache_ttl_match_details: int = Field(30 * DAY, ge=0)

    # Scraping backend. The other one is used as a fallback when it is available.
    backend: Literal["playwright", "flaresolverr"] = "playwright"

    # Browser.
    headless: bool = True
    browser_channel: str = "chrome"
    browser_executable: Path | None = None
    user_agent: str | None = None
    browser_idle_seconds: int = Field(120, ge=0)

    # Politeness.
    min_delay: float = Field(1.5, ge=0)
    max_delay: float = Field(4.0, ge=0)
    max_concurrent_scrapes: int = Field(1, ge=1, le=2)
    max_requests_per_hour: int = Field(240, ge=0)

    # Failure handling.
    max_retries: int = Field(2, ge=0, le=3)
    backoff_base: float = Field(2.0, ge=0)
    request_timeout: float = Field(30.0, gt=0)
    challenge_timeout: float = Field(30.0, gt=0)

    flaresolverr_url: str | None = Field(
        None, validation_alias=AliasChoices("FLARESOLVERR_URL", "TRN_FLARESOLVERR_URL")
    )
    flaresolverr_timeout_ms: int = Field(60_000, ge=1_000)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    transport: Literal["stdio", "streamable-http"] = Field(
        "stdio", validation_alias="MCP_TRANSPORT"
    )
    host: str = Field("127.0.0.1", validation_alias="MCP_HOST")
    port: int = Field(8000, validation_alias="MCP_PORT", ge=1, le=65535)

    @model_validator(mode="after")
    def _check_delays(self) -> Settings:
        if self.max_delay < self.min_delay:
            raise ValueError("TRN_MAX_DELAY must not be smaller than TRN_MIN_DELAY")
        return self

    @property
    def cache_path(self) -> Path:
        return self.data_dir / "cache.sqlite3"

    @property
    def browser_profile_dir(self) -> Path:
        return self.data_dir / "browser-profile"


def _env_name(field: object) -> str:
    name = str(field)
    return name if name.isupper() else f"TRN_{name.upper()}"


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        # A plain message instead of a pydantic traceback in the MCP client's log.
        problems = "; ".join(
            f"{_env_name(error['loc'][0]) if error['loc'] else 'settings'}: {error['msg']}"
            for error in exc.errors()
        )
        raise SystemExit(f"Invalid configuration. {problems}") from None
