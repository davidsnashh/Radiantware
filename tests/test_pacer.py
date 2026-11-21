import asyncio
import json
import time

import pytest

from scraper import RateLimitedError, trn
from scraper.locks import try_lock
from scraper.trn import RequestPacer

GAP = 0.15


def pacer(folder, per_hour=0, gap=GAP, **options):
    return RequestPacer(gap, gap, per_hour, folder, **options)


async def request(pacing, took=0.0):
    await pacing.wait()
    await asyncio.sleep(took)
    pacing.finished()


async def timed(awaitable):
    started = time.monotonic()
    await awaitable
    return time.monotonic() - started


def starts(folder):
    return json.loads((folder / "pacing.json").read_text())


def test_the_first_request_does_not_wait(tmp_path):
    assert asyncio.run(timed(pacer(tmp_path).wait())) < GAP / 2


def test_the_next_request_waits_for_the_gap(tmp_path):
    async def run():
        pacing = pacer(tmp_path)
        await request(pacing)
        return await timed(pacing.wait())

    assert GAP * 0.9 <= asyncio.run(run()) < GAP + 0.3


def test_the_gap_counts_from_the_end_of_a_request(tmp_path):
    async def run():
        pacing = pacer(tmp_path)
        await request(pacing, took=GAP * 2)
        return await timed(pacing.wait())

    assert GAP * 0.9 <= asyncio.run(run()) < GAP + 0.3


def test_the_hourly_budget_is_enforced(tmp_path):
    async def run():
        pacing = pacer(tmp_path, per_hour=2, gap=0)
        await request(pacing)
        await request(pacing)
        await pacing.wait()

    with pytest.raises(RateLimitedError, match="2 tracker.gg requests per hour"):
        asyncio.run(run())


def test_a_budget_of_zero_means_no_limit(tmp_path):
    async def run():
        pacing = pacer(tmp_path, per_hour=0, gap=0)
        for _ in range(25):
            await request(pacing)

    asyncio.run(run())
    assert len(starts(tmp_path)) == 25


def test_requests_older_than_an_hour_leave_the_budget(tmp_path):
    long_ago = time.time() - 3700
    (tmp_path / "pacing.json").write_text(json.dumps([long_ago, long_ago + 1]))

    asyncio.run(request(pacer(tmp_path, per_hour=2, gap=0)))

    assert len(starts(tmp_path)) == 1


def test_copies_share_the_budget(tmp_path):
    async def run():
        one, other = pacer(tmp_path, per_hour=2, gap=0), pacer(tmp_path, per_hour=2, gap=0)
        await request(one)
        await request(other)
        await one.wait()

    with pytest.raises(RateLimitedError):
        asyncio.run(run())


def test_copies_with_other_folders_have_their_own_budget(tmp_path):
    async def run():
        await request(pacer(tmp_path / "a", per_hour=1, gap=0))
        await request(pacer(tmp_path / "b", per_hour=1, gap=0))

    asyncio.run(run())


def test_copies_share_the_gap(tmp_path):
    async def run():
        await request(pacer(tmp_path))
        return await timed(pacer(tmp_path).wait())

    assert GAP * 0.9 <= asyncio.run(run()) < GAP + 0.3


def test_another_copy_waits_until_the_request_is_over(tmp_path):
    async def run():
        one, other = pacer(tmp_path), pacer(tmp_path)
        await one.wait()
        waiting = asyncio.create_task(other.wait())
        await asyncio.sleep(GAP * 2)
        still_waiting = not waiting.done()
        one.finished()
        waited_after = await timed(waiting)
        other.finished()
        return still_waiting, waited_after

    still_waiting, waited_after = asyncio.run(run())
    assert still_waiting
    assert GAP * 0.9 <= waited_after < GAP + 0.4


def test_two_at_a_time_lets_requests_overlap(tmp_path):
    async def run():
        one = pacer(tmp_path, one_at_a_time=False)
        other = pacer(tmp_path, one_at_a_time=False)
        await one.wait()
        return await timed(other.wait())

    assert GAP * 0.9 <= asyncio.run(run()) < GAP + 0.4


def test_pacing_twice_inside_one_request_keeps_the_turn(tmp_path):
    async def run():
        pacing = pacer(tmp_path)
        await pacing.wait()
        await pacing.wait()
        held = try_lock(tmp_path / "pacing.lock") is None
        pacing.finished()
        return held

    assert asyncio.run(run())
    assert len(starts(tmp_path)) == 2


def test_the_turn_is_given_back_after_a_request(tmp_path):
    asyncio.run(request(pacer(tmp_path)))

    free = try_lock(tmp_path / "pacing.lock")
    assert free is not None
    free.close()


def test_the_turn_is_given_back_when_the_budget_is_used_up(tmp_path):
    async def run():
        strict = pacer(tmp_path, per_hour=1, gap=0)
        await request(strict)
        with pytest.raises(RateLimitedError) as refused:
            await strict.wait()
        # While the error is kept, only giving the turn back on purpose frees it.
        free = try_lock(tmp_path / "pacing.lock")
        return free, refused

    free, _ = asyncio.run(run())
    assert free is not None
    free.close()


def test_a_cancelled_wait_gives_its_turn_back(tmp_path):
    async def run():
        slow = pacer(tmp_path, gap=30)
        await request(slow)
        waiting = asyncio.create_task(slow.wait())
        await asyncio.sleep(0.05)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        free = try_lock(tmp_path / "pacing.lock")
        return free

    free = asyncio.run(run())
    assert free is not None
    free.close()
    assert len(starts(tmp_path)) == 1


def test_a_copy_that_never_gives_its_turn_up_is_not_waited_for_forever(tmp_path):
    async def run():
        stuck, other = pacer(tmp_path, gap=0), pacer(tmp_path, gap=0, turn_timeout=0.2)
        await stuck.wait()
        waited = await timed(other.wait())
        other.finished()
        stuck.finished()
        return waited

    assert 0.2 <= asyncio.run(run()) < 1.0


def test_a_copy_that_stopped_waiting_for_its_turn_still_keeps_the_gap(tmp_path):
    async def run():
        stuck, other = pacer(tmp_path, gap=0.6), pacer(tmp_path, gap=0.6, turn_timeout=0.2)
        await stuck.wait()
        waited = await timed(other.wait())
        other.finished()
        stuck.finished()
        return waited

    assert 0.55 <= asyncio.run(run()) < 1.2


def test_a_copy_asking_back_to_back_lets_another_copy_in(tmp_path):
    async def run():
        busy, other = pacer(tmp_path, gap=0.3), pacer(tmp_path, gap=0.3)
        made = 0

        async def keep_asking():
            nonlocal made
            while True:
                await request(busy, took=0.02)
                made += 1

        asking = asyncio.create_task(keep_asking())
        await asyncio.sleep(0.05)
        try:
            await asyncio.wait_for(request(other), timeout=6)
        finally:
            asking.cancel()
        return made

    # The one request under way when the other copy turned up, and at most the next.
    assert asyncio.run(run()) <= 2


def test_two_copies_asking_back_to_back_take_turns(tmp_path):
    async def run():
        order = []

        async def keep_asking(name):
            # The gap is longer than a copy ever sleeps between two looks at the turn.
            pacing = pacer(tmp_path, gap=0.25)
            for _ in range(3):
                await request(pacing, took=0.02)
                order.append(name)

        await asyncio.gather(keep_asking("one"), keep_asking("other"))
        return order

    assert asyncio.run(run()) in (["one", "other"] * 3, ["other", "one"] * 3)


def test_a_copy_that_is_next_in_line_keeps_the_turn_while_it_waits(tmp_path):
    async def run():
        await request(pacer(tmp_path, gap=0.3))
        waiting = asyncio.create_task(pacer(tmp_path, gap=0.3).wait())
        await asyncio.sleep(0.1)
        held = try_lock(tmp_path / "pacing.lock") is None
        await waiting
        return held

    assert asyncio.run(run())


def test_a_copy_that_just_went_gives_the_turn_up_while_it_waits(tmp_path):
    async def run():
        pacing = pacer(tmp_path, gap=0.3)
        await request(pacing)
        waiting = asyncio.create_task(pacing.wait())
        await asyncio.sleep(0.1)
        free = try_lock(tmp_path / "pacing.lock")
        if free is not None:
            free.close()
        await waiting
        pacing.finished()
        return free is not None

    assert asyncio.run(run())


def test_a_cancelled_wait_of_the_next_in_line_gives_its_turn_back(tmp_path):
    async def run():
        await request(pacer(tmp_path, gap=30))
        waiting = asyncio.create_task(pacer(tmp_path, gap=30).wait())
        await asyncio.sleep(0.05)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        return try_lock(tmp_path / "pacing.lock")

    free = asyncio.run(run())
    assert free is not None
    free.close()
    assert len(starts(tmp_path)) == 1


def test_an_unreadable_state_file_is_started_afresh(tmp_path):
    (tmp_path / "pacing.json").write_text("{not json")

    asyncio.run(request(pacer(tmp_path, per_hour=5)))

    assert len(starts(tmp_path)) == 1


def test_without_a_folder_nothing_is_written(tmp_path):
    async def run():
        pacing = RequestPacer(GAP, GAP, 0)
        await request(pacing)
        return await timed(pacing.wait())

    assert GAP * 0.9 <= asyncio.run(run()) < GAP + 0.3
    assert list(tmp_path.iterdir()) == []


def test_pacing_goes_on_alone_when_the_folder_cannot_be_locked(tmp_path, monkeypatch):
    def refuse(path):
        raise OSError("locks are not supported here")

    monkeypatch.setattr(trn.locks, "try_lock", refuse)

    async def run():
        pacing = pacer(tmp_path)
        await request(pacing)
        return await timed(pacing.wait())

    assert GAP * 0.9 <= asyncio.run(run()) < GAP + 0.3
    assert not (tmp_path / "pacing.json").exists()


def set_the_clock(monkeypatch, by):
    real = time.time
    monkeypatch.setattr(trn.time, "time", lambda: real() + by)


def test_a_clock_that_was_set_back_does_not_cause_a_long_wait(tmp_path, monkeypatch):
    async def run():
        pacing = pacer(tmp_path)
        await request(pacing)
        set_the_clock(monkeypatch, -7200)
        return await timed(asyncio.wait_for(pacing.wait(), timeout=3))

    assert GAP * 0.9 <= asyncio.run(run()) < GAP + 0.3


def test_starts_from_before_the_clock_was_set_back_leave_the_budget_within_the_hour(tmp_path):
    later = time.time() + 7200
    (tmp_path / "pacing.json").write_text(json.dumps([later, later + 1]))

    with pytest.raises(RateLimitedError):
        asyncio.run(pacer(tmp_path, per_hour=2, gap=0).wait())

    assert max(starts(tmp_path)) <= time.time()


def test_a_clock_that_was_set_forward_does_not_free_the_budget(tmp_path, monkeypatch):
    async def run():
        pacing = pacer(tmp_path, per_hour=2, gap=0)
        await request(pacing)
        await request(pacing)
        set_the_clock(monkeypatch, 7200)
        await pacing.wait()

    with pytest.raises(RateLimitedError):
        asyncio.run(run())


def test_a_clock_that_was_set_forward_does_not_skip_the_gap(tmp_path, monkeypatch):
    async def run():
        pacing = pacer(tmp_path)
        await request(pacing)
        set_the_clock(monkeypatch, 7200)
        return await timed(pacing.wait())

    assert GAP * 0.9 <= asyncio.run(run()) < GAP + 0.3


def test_requests_in_the_same_instant_are_all_counted(tmp_path, monkeypatch):
    # Some clocks only tick every 16 milliseconds.
    monkeypatch.setattr(trn.time, "time", lambda: 1_800_000_000.0)

    async def run():
        pacing = pacer(tmp_path, per_hour=3, gap=0)
        for _ in range(3):
            await request(pacing)
        await pacing.wait()

    with pytest.raises(RateLimitedError):
        asyncio.run(run())
