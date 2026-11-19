import asyncio
import types
from pathlib import Path

import pytest

from config import Settings
from scraper import BackendUnavailableError, trn
from scraper.locks import try_lock
from scraper.trn import PlaywrightBackend


def copy_of_the_server(folder):
    settings = Settings(_env_file=None, data_dir=folder, browser_idle_seconds=0)
    return PlaywrightBackend(settings)


class NoBrowser(Exception):
    pass


def fake_browser_library(launched, works=True, stopping_takes=0.0, drivers=None):
    class Page:
        async def evaluate(self, script):
            return "Mozilla/5.0 Chrome/130.0"

    class Context:
        def __init__(self):
            self.pages = [Page()]

        async def close(self):
            pass

    class Chromium:
        async def launch_persistent_context(self, user_data_dir, **options):
            launched.append(Path(user_data_dir).name)
            if not works:
                raise NoBrowser("nothing to launch")
            return Context()

    class Driver:
        chromium = Chromium()

        async def stop(self):
            await asyncio.sleep(stopping_takes)

    class Starter:
        async def start(self):
            if drivers is not None:
                drivers.append("started")
            return Driver()

    return types.SimpleNamespace(async_playwright=Starter, Error=NoBrowser)


def is_free(folder, profile="browser-profile"):
    held = try_lock(folder / f"{profile}.lock")
    if held is None:
        return False
    held.close()
    return True


def test_two_copies_launch_their_browsers_on_a_profile_each(tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr(trn, "_load_playwright", lambda: fake_browser_library(launched))

    async def run():
        one, other = copy_of_the_server(tmp_path), copy_of_the_server(tmp_path)
        await one._start()
        await other._start()
        both_held = not is_free(tmp_path) and not is_free(tmp_path, "browser-profile-2")
        await one._stop()
        await other._stop()
        return both_held

    assert asyncio.run(run())
    assert launched == ["browser-profile", "browser-profile-2"]
    assert is_free(tmp_path) and is_free(tmp_path, "browser-profile-2")


def test_a_failed_launch_frees_the_profile_once_the_driver_is_down(tmp_path, monkeypatch):
    library = fake_browser_library([], works=False, stopping_takes=0.3)
    monkeypatch.setattr(trn, "_load_playwright", lambda: library)

    async def run():
        starting = asyncio.ensure_future(copy_of_the_server(tmp_path)._start())
        await asyncio.sleep(0.1)
        held_while_stopping = not is_free(tmp_path)
        with pytest.raises(BackendUnavailableError, match="Could not start a browser"):
            await starting
        return held_while_stopping

    assert asyncio.run(run())
    assert is_free(tmp_path)


def test_stopping_frees_the_profile_once_the_driver_is_down(tmp_path, monkeypatch):
    library = fake_browser_library([], stopping_takes=0.3)
    monkeypatch.setattr(trn, "_load_playwright", lambda: library)

    async def run():
        backend = copy_of_the_server(tmp_path)
        await backend._start()
        stopping = asyncio.ensure_future(backend._stop())
        await asyncio.sleep(0.1)
        held_while_stopping = not is_free(tmp_path)
        await stopping
        return held_while_stopping

    assert asyncio.run(run())
    assert is_free(tmp_path)


def test_no_driver_is_started_when_every_profile_is_taken(tmp_path, monkeypatch):
    drivers = []
    library = fake_browser_library([], drivers=drivers)
    monkeypatch.setattr(trn, "_load_playwright", lambda: library)
    holders = [copy_of_the_server(tmp_path) for _ in range(trn._MAX_PROFILES)]
    for holder in holders:
        holder._claim_profile()

    with pytest.raises(BackendUnavailableError, match="in use by other running copies"):
        asyncio.run(copy_of_the_server(tmp_path)._start())
    for holder in holders:
        holder._release_profile()
    assert drivers == []


def test_the_first_copy_takes_the_main_profile(tmp_path):
    backend = copy_of_the_server(tmp_path)
    backend._claim_profile()

    assert backend._profile_dir == tmp_path / "browser-profile"
    assert backend._profile_dir.is_dir()
    backend._release_profile()


def test_each_copy_with_a_browser_open_gets_its_own_profile(tmp_path):
    copies = [copy_of_the_server(tmp_path) for _ in range(trn._MAX_PROFILES)]
    for backend in copies:
        backend._claim_profile()

    names = [backend._profile_dir.name for backend in copies]
    assert names == ["browser-profile", "browser-profile-2", "browser-profile-3"]
    for backend in copies:
        backend._release_profile()


def test_one_copy_too_many_is_told_why(tmp_path):
    copies = [copy_of_the_server(tmp_path) for _ in range(trn._MAX_PROFILES)]
    for backend in copies:
        backend._claim_profile()

    with pytest.raises(BackendUnavailableError, match="in use by other running copies"):
        copy_of_the_server(tmp_path)._claim_profile()
    for backend in copies:
        backend._release_profile()


def test_a_released_profile_is_used_again(tmp_path):
    first, second, third = (copy_of_the_server(tmp_path) for _ in range(3))
    first._claim_profile()
    second._claim_profile()
    first._release_profile()
    third._claim_profile()

    assert third._profile_dir.name == "browser-profile"
    second._release_profile()
    third._release_profile()


def test_stopping_the_browser_frees_its_profile(tmp_path):
    backend = copy_of_the_server(tmp_path)
    backend._claim_profile()

    asyncio.run(backend._stop())

    free = try_lock(tmp_path / "browser-profile.lock")
    assert free is not None
    free.close()


def test_copies_with_other_folders_do_not_get_in_each_others_way(tmp_path):
    one, other = copy_of_the_server(tmp_path / "a"), copy_of_the_server(tmp_path / "b")
    one._claim_profile()
    other._claim_profile()

    assert one._profile_dir.name == other._profile_dir.name == "browser-profile"
    one._release_profile()
    other._release_profile()


def test_without_file_locks_the_main_profile_is_used(tmp_path, monkeypatch):
    def refuse(path):
        raise OSError("locks are not supported here")

    monkeypatch.setattr(trn.locks, "try_lock", refuse)
    backend = copy_of_the_server(tmp_path)
    backend._claim_profile()

    assert backend._profile_dir == tmp_path / "browser-profile"
    assert backend._profile_lock is None
