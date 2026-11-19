import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OPEN_AT_A_SET_TIME = """
import asyncio, logging, sys, time
from pathlib import Path
from cache import SQLiteCache

problems = []
watch = logging.Handler()
watch.emit = lambda record: problems.append(record.getMessage())
logging.getLogger("cache.sqlite_cache").addHandler(watch)

async def main():
    cache = SQLiteCache(Path(sys.argv[1]))
    await asyncio.sleep(max(0, float(sys.argv[2]) - time.time()))
    await cache.purge_expired()
    await cache.set("overview", {"copy": sys.argv[3]}, 60, "Brim Stone#TST", {"copy": sys.argv[3]})
    stored = await cache.get("overview", "Brim Stone#TST", {"copy": sys.argv[3]})
    await cache.close()
    print("ok" if stored and not problems else "; ".join(problems or ["value missing"]))

asyncio.run(main())
"""


def test_copies_that_create_the_cache_at_the_same_moment_both_work(tmp_path):
    for attempt in range(3):
        path = tmp_path / str(attempt) / "cache.sqlite3"
        together = str(time.time() + 0.8)
        copies = [
            subprocess.Popen(
                [sys.executable, "-c", OPEN_AT_A_SET_TIME, str(path), together, name],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                text=True,
            )
            for name in ("one", "two")
        ]
        assert [copy.communicate(timeout=30)[0].strip() for copy in copies] == ["ok", "ok"]
