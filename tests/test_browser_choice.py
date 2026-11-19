import plistlib
from pathlib import Path

import pytest

from config import Settings
from scraper import trn
from scraper.trn import PlaywrightBackend, _other_chrome_installs

CHROME = "com.google.Chrome"


def app(folder, name, bundle_id=CHROME, executable="Google Chrome"):
    contents = folder / f"{name}.app" / "Contents"
    contents.mkdir(parents=True)
    info = {"CFBundleIdentifier": bundle_id, "CFBundleExecutable": executable}
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    return contents / "MacOS" / executable


def targets(tmp_path, **settings):
    backend = PlaywrightBackend(Settings(_env_file=None, data_dir=tmp_path, **settings))
    return backend._launch_targets()


@pytest.fixture
def on_a_mac(monkeypatch):
    monkeypatch.setattr(trn.sys, "platform", "darwin")


@pytest.fixture
def one_more_chrome(monkeypatch):
    monkeypatch.setattr(trn, "_other_chrome_installs", lambda: [Path("/elsewhere/Chrome")])


def test_a_copy_that_finder_renamed_is_found(tmp_path, on_a_mac):
    binary = app(tmp_path, "Google Chrome 2")

    assert _other_chrome_installs([tmp_path]) == [binary]


def test_every_folder_is_searched_in_order(tmp_path, on_a_mac):
    first = app(tmp_path / "system", "Google Chrome 2")
    second = app(tmp_path / "user", "Google Chrome")

    assert _other_chrome_installs([tmp_path / "system", tmp_path / "user"]) == [first, second]


def test_beta_and_canary_are_not_taken_for_chrome(tmp_path, on_a_mac):
    app(tmp_path, "Google Chrome Canary", "com.google.Chrome.canary")
    app(tmp_path, "Google Chrome Beta", "com.google.Chrome.beta")

    assert _other_chrome_installs([tmp_path]) == []


def test_an_app_that_cannot_be_read_is_skipped(tmp_path, on_a_mac):
    broken = tmp_path / "Google Chrome 3.app" / "Contents"
    broken.mkdir(parents=True)
    (broken / "Info.plist").write_text("not a property list")
    (tmp_path / "Google Chrome 4.app").mkdir()

    assert _other_chrome_installs([tmp_path]) == []


def test_a_folder_that_does_not_exist_is_fine(tmp_path, on_a_mac):
    assert _other_chrome_installs([tmp_path / "missing"]) == []


def test_nothing_is_searched_off_a_mac(tmp_path, monkeypatch):
    app(tmp_path, "Google Chrome 2")
    monkeypatch.setattr(trn.sys, "platform", "linux")

    assert _other_chrome_installs([tmp_path]) == []


def test_chrome_is_tried_where_it_usually_is_then_elsewhere_then_chromium(
    tmp_path, one_more_chrome
):
    assert targets(tmp_path) == [
        {"channel": "chrome"},
        {"executable_path": "/elsewhere/Chrome"},
        {"channel": "chromium"},
    ]


def test_a_browser_path_from_the_settings_is_the_only_one_tried(tmp_path, one_more_chrome):
    chosen = targets(tmp_path, browser_executable="/my/own/chrome")

    assert chosen == [{"executable_path": "/my/own/chrome"}]


def test_another_channel_does_not_look_for_chrome(tmp_path, one_more_chrome):
    assert targets(tmp_path, browser_channel="msedge") == [
        {"channel": "msedge"},
        {"channel": "chromium"},
    ]


def test_chromium_alone_is_tried_once(tmp_path, one_more_chrome):
    assert targets(tmp_path, browser_channel="chromium") == [{"channel": "chromium"}]
