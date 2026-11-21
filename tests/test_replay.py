"""Replay files: finding them works, reading them is a documented placeholder."""

import asyncio
import os

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import server
from scraper import TrackerError, replay
from scraper.replay import ReplayError, ReplayNotSupportedError


def write(folder, name, size=1_500_000, changed=None):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"\0" * size)
    if changed is not None:
        os.utime(path, (changed, changed))
    return path


@pytest.fixture
def replays_here(tmp_path, monkeypatch):
    monkeypatch.setattr(server.settings, "replay_dir", tmp_path)
    return tmp_path


def call(tool, **arguments):
    return asyncio.run(tool(**arguments)).structured_content


def test_replay_files_are_listed_newest_first(tmp_path):
    write(tmp_path, "older.vrf", changed=1_000)
    write(tmp_path, "newest.dem", changed=3_000)
    write(tmp_path, "middle.VRF", changed=2_000)

    assert [found.path.name for found in replay.find_replays(tmp_path)] == [
        "newest.dem",
        "middle.VRF",
        "older.vrf",
    ]


def test_other_files_and_folders_are_not_replays(tmp_path):
    write(tmp_path, "notes.txt")
    write(tmp_path, "clip.mp4")
    (tmp_path / "folder.vrf").mkdir()

    assert replay.find_replays(tmp_path) == []


def test_no_folder_means_no_replays(tmp_path):
    assert replay.find_replays(None) == []
    assert replay.find_replays(tmp_path / "missing") == []


def test_a_replay_is_described_by_name_path_size_and_date(tmp_path):
    path = write(tmp_path, "match.vrf", size=2_340_000, changed=1_800_000_000)

    assert replay.find_replays(tmp_path)[0].describe() == {
        "file": "match.vrf",
        "path": str(path),
        "size_mb": 2.3,
        "modified_at": "2027-01-15T08:00:00+00:00",
    }


def test_the_games_own_folder_is_only_known_on_windows(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\brim\AppData\Local")
    monkeypatch.setattr(replay.sys, "platform", "darwin")
    assert replay.default_folder() is None

    monkeypatch.setattr(replay.sys, "platform", "win32")
    assert replay.default_folder().parts[-3:] == ("VALORANT", "Saved", "Demos")

    monkeypatch.delenv("LOCALAPPDATA")
    assert replay.default_folder() is None


def test_a_replay_path_has_to_be_a_replay_file_that_exists(tmp_path):
    path = write(tmp_path, "match.vrf")

    assert replay.open_replay(str(path)).path == path
    with pytest.raises(ReplayError, match="There is no replay file"):
        replay.open_replay(str(tmp_path / "gone.vrf"))
    with pytest.raises(ReplayError, match="is not a replay file"):
        replay.open_replay(str(write(tmp_path, "notes.txt")))


def test_a_replay_somewhere_else_is_refused_as_local_only():
    with pytest.raises(ReplayError, match="Other players' replays cannot be fetched"):
        replay.open_replay("https://tracker.gg/valorant/match/123.vrf")


def test_reading_a_replay_is_not_built_and_says_what_to_use_instead(tmp_path):
    found = replay.open_replay(str(write(tmp_path, "match.vrf")))

    with pytest.raises(ReplayNotSupportedError, match="get_match_rounds"):
        replay.parser.parse(found)
    assert issubclass(ReplayNotSupportedError, TrackerError)


def test_the_planned_analyses_say_what_they_will_answer():
    assert [plan.name for plan in replay.PLANNED] == ["round_state", "line_of_sight", "utility"]
    for plan in replay.PLANNED:
        described = plan.describe()
        assert described["analysis"] == plan.name
        assert described["will_answer"] and described["needs"]


def test_listing_replays_tells_what_is_here_and_that_analysis_is_not(replays_here):
    write(replays_here, "match.vrf", changed=1_800_000_000)

    answer = call(server.list_local_replays)

    assert "meta" not in answer
    data = answer["data"]
    assert (data["folder"], data["count"]) == (str(replays_here), 1)
    assert data["replays"][0]["file"] == "match.vrf"
    assert data["analysis_available"] is False
    assert replay.LOCAL_ONLY in data["limitations"]
    assert "note" not in data


def test_listing_an_empty_folder_says_how_replays_get_there(replays_here):
    data = call(server.list_local_replays)["data"]

    assert data["count"] == 0
    assert "downloaded in the game" in data["note"]


def test_listing_without_a_folder_says_how_to_set_one(monkeypatch):
    monkeypatch.setattr(server.settings, "replay_dir", None)
    monkeypatch.setattr(replay.sys, "platform", "darwin")

    data = call(server.list_local_replays)["data"]

    assert "folder" not in data
    assert "TRN_REPLAY_DIR" in data["note"]


def test_analysing_a_replay_answers_not_implemented_with_the_plan(replays_here):
    path = write(replays_here, "match.vrf")
    questions = ["Where did I die most?"]

    data = call(server.analyze_replay, path=str(path), questions=questions)["data"]

    assert data["status"] == "not_implemented"
    assert data["replay"]["file"] == "match.vrf"
    assert data["questions"] == questions
    assert [plan["analysis"] for plan in data["planned"]] == [
        "round_state",
        "line_of_sight",
        "utility",
    ]
    assert "get_match_rounds" in data["meanwhile"]
    assert data["limitations"] == [replay.LOCAL_ONLY, replay.UNDOCUMENTED]


def test_analysing_without_questions_returns_an_empty_list(replays_here):
    path = write(replays_here, "match.vrf")

    assert call(server.analyze_replay, path=str(path))["data"]["questions"] == []


def test_utility_effectiveness_names_the_questions_it_will_answer(replays_here):
    path = write(replays_here, "match.vrf")

    data = call(server.get_utility_effectiveness, path=str(path))["data"]

    assert data["status"] == "not_implemented"
    assert [plan["analysis"] for plan in data["planned"]] == ["utility"]
    answers = " ".join(data["planned"][0]["will_answer"])
    assert "flashes blinded an enemy" in answers
    assert "followed by a kill" in answers


@pytest.mark.parametrize("tool", [server.analyze_replay, server.get_utility_effectiveness])
def test_a_replay_that_is_not_on_this_computer_is_a_clear_error(tool, replays_here):
    with pytest.raises(ToolError, match="Replays are local only"):
        call(tool, path=str(replays_here / "someone-elses.vrf"))


def test_a_replay_path_may_start_with_the_home_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    path = write(tmp_path / "replays", "match.vrf")

    assert replay.open_replay("~/replays/match.vrf").path == path


def test_a_replay_named_from_the_working_folder_is_answered_with_its_whole_path(
    tmp_path, monkeypatch
):
    path = write(tmp_path, "match.vrf")
    monkeypatch.chdir(tmp_path)

    assert replay.open_replay("match.vrf").path == path


@pytest.mark.parametrize(
    "path", ["~nosuchuser/match.vrf", "bad\0name.vrf", "", "x" * 5000 + ".vrf"]
)
def test_a_path_that_cannot_be_used_is_a_short_clear_error(path):
    with pytest.raises(ReplayError) as refused:
        replay.open_replay(path)

    assert len(str(refused.value)) < 700


@pytest.mark.parametrize("tool", [server.analyze_replay, server.get_utility_effectiveness])
def test_a_path_that_cannot_be_used_is_not_an_unexpected_error(tool):
    with pytest.raises(ToolError) as refused:
        call(tool, path="~nosuchuser/match.vrf")

    assert "Unexpected" not in str(refused.value)
    assert "is not a path that can be used" in str(refused.value)


def test_a_replay_folder_that_is_missing_is_reported_as_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(server.settings, "replay_dir", tmp_path / "nowhere")

    data = call(server.list_local_replays)["data"]

    assert data["count"] == 0
    assert "does not exist" in data["note"]


def test_a_replay_folder_that_is_a_file_is_reported_as_one(tmp_path, monkeypatch):
    monkeypatch.setattr(server.settings, "replay_dir", write(tmp_path, "match.vrf"))

    assert "is not a folder" in call(server.list_local_replays)["data"]["note"]


def test_a_replay_folder_that_may_not_be_read_is_a_clear_error(replays_here, monkeypatch):
    def refuse(folder):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(type(replays_here), "iterdir", refuse)

    with pytest.raises(ToolError, match="cannot be read"):
        call(server.list_local_replays)


def test_the_replay_tools_are_marked_as_working_on_this_computer_only():
    tools = {tool.name: tool.annotations for tool in asyncio.run(server.mcp.list_tools())}

    for name in ("list_local_replays", "analyze_replay", "get_utility_effectiveness"):
        assert (tools[name].read_only_hint, tools[name].open_world_hint) == (True, False)
    assert tools["get_player_overview"].open_world_hint is True
