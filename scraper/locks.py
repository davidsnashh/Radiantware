"""File locks shared by every copy of the server that uses the same data folder."""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO

if os.name == "nt":
    import msvcrt
else:
    import fcntl


def try_lock(path: Path) -> IO[bytes] | None:
    """Lock a file, or return None while someone else holds it.

    The lock lasts until the returned handle is closed. The system drops it
    when the process dies, so a crash never leaves a stale lock behind.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("ab")
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, PermissionError):
        handle.close()
        return None
    except BaseException:
        handle.close()
        raise
    return handle
