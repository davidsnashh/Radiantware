import subprocess
import sys
from pathlib import Path

from scraper.locks import try_lock

ROOT = Path(__file__).resolve().parent.parent

HOLD_UNTIL_TOLD = """
import sys
from pathlib import Path
from scraper.locks import try_lock

held = try_lock(Path(sys.argv[1]))
print("locked" if held else "busy", flush=True)
sys.stdin.read()
"""


def test_a_held_lock_cannot_be_taken_again(tmp_path):
    path = tmp_path / "pacing.lock"
    first = try_lock(path)
    assert first is not None
    assert try_lock(path) is None
    first.close()


def test_a_closed_lock_is_free_again(tmp_path):
    path = tmp_path / "pacing.lock"
    try_lock(path).close()
    again = try_lock(path)
    assert again is not None
    again.close()


def test_locks_on_different_files_are_independent(tmp_path):
    first = try_lock(tmp_path / "browser-profile.lock")
    second = try_lock(tmp_path / "browser-profile-2.lock")
    assert first is not None and second is not None
    first.close()
    second.close()


def test_the_folder_is_created_when_missing(tmp_path):
    held = try_lock(tmp_path / "not" / "there" / "yet.lock")
    assert held is not None
    held.close()


def test_another_process_is_kept_out_until_the_holder_dies(tmp_path):
    path = tmp_path / "pacing.lock"
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_UNTIL_TOLD, str(path)],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        assert try_lock(path) is None
        # Killed rather than asked to stop: a crash must not leave the lock behind.
        holder.kill()
        holder.wait(timeout=5)
        freed = try_lock(path)
        assert freed is not None
        freed.close()
    finally:
        holder.kill()
        holder.wait(timeout=5)
        holder.stdin.close()
        holder.stdout.close()
