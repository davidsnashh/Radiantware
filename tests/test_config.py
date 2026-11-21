"""Settings read from the environment."""

import pytest
from pydantic import ValidationError

from config import Settings

PATHS = ("TRN_DATA_DIR", "TRN_REPLAY_DIR", "TRN_BROWSER_EXECUTABLE")


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name in PATHS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path


def test_a_path_may_start_with_the_home_folder(home):
    made = Settings(
        _env_file=None, data_dir="~/data", replay_dir="~/replays", browser_executable="~/chrome"
    )

    assert made.cache_path == home / "data" / "cache.sqlite3"
    assert made.replay_dir == home / "replays"
    assert made.browser_executable == home / "chrome"


def test_a_path_from_the_environment_is_expanded_too(home, monkeypatch):
    monkeypatch.setenv("TRN_REPLAY_DIR", "~/replays")

    assert Settings(_env_file=None).replay_dir == home / "replays"


def test_paths_that_are_not_set_stay_unset(home):
    made = Settings(_env_file=None)

    assert made.replay_dir is None
    assert made.browser_executable is None


def test_a_home_folder_that_does_not_exist_is_a_settings_error(home):
    with pytest.raises(ValidationError, match="home directory"):
        Settings(_env_file=None, replay_dir="~nosuchuser/replays")
