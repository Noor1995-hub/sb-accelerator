"""One run at a time (#271)."""
from datetime import datetime, timedelta

import pytest

from vaultlib import runlock

T0 = datetime(2026, 10, 12, 12, 0)


def test_acquire_on_free_vault(tmp_path):
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0)
    assert result["acquired"] and not result["took_over"]
    assert (tmp_path / runlock.LOCK_RELPATH).is_file()


def test_fresh_lock_of_another_routine_refuses(tmp_path):
    runlock.acquire(tmp_path, "evening-sync", now=T0)
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0 + timedelta(minutes=30))
    assert result["acquired"] is False
    assert result["holder"]["routine"] == "evening-sync"


def test_stale_lock_is_taken_over(tmp_path):
    runlock.acquire(tmp_path, "evening-sync", now=T0)
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0 + timedelta(hours=3))
    assert result["acquired"] and result["stale"] and result["took_over"]


def test_same_routine_takes_its_own_lock_over(tmp_path):
    """A crashed interactive call must not lock the owner out for two hours."""
    runlock.acquire(tmp_path, "sync-recordings", now=T0)
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0 + timedelta(minutes=5))
    assert result["acquired"] and result["took_over"]


def test_release_only_removes_own_lock(tmp_path):
    runlock.acquire(tmp_path, "evening-sync", now=T0)
    assert runlock.release(tmp_path, "sync-recordings")["released"] is False
    assert (tmp_path / runlock.LOCK_RELPATH).is_file()
    assert runlock.release(tmp_path, "evening-sync")["released"] is True
    assert not (tmp_path / runlock.LOCK_RELPATH).exists()


def test_unreadable_lock_counts_as_stale(tmp_path):
    path = tmp_path / runlock.LOCK_RELPATH
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0)
    assert result["acquired"] and result["stale"]


def test_routine_name_is_validated(tmp_path):
    with pytest.raises(runlock.RunLockError):
        runlock.acquire(tmp_path, "Evening Sync", now=T0)


def test_wait_retries_once_after_sleeping(tmp_path, monkeypatch):
    """#271: the evening run waits inside the CLI — one allowlisted call per
    retry, never a sleep command a scheduled run would be prompted for."""
    runlock.acquire(tmp_path, "sync-recordings", now=T0)
    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        runlock.release(tmp_path, "sync-recordings")

    monkeypatch.setattr(runlock.time, "sleep", fake_sleep)
    result = runlock.acquire(tmp_path, "evening-sync", now=T0, wait=60)
    assert slept == [60] and result["acquired"] is True


def test_wait_still_refused_reports_holder(tmp_path, monkeypatch):
    runlock.acquire(tmp_path, "sync-recordings", now=T0)
    monkeypatch.setattr(runlock.time, "sleep", lambda s: None)
    result = runlock.acquire(tmp_path, "evening-sync", now=T0, wait=60)
    assert result["acquired"] is False
    assert result["holder"]["routine"] == "sync-recordings"


def test_wait_is_capped_below_the_bash_timeout(tmp_path):
    with pytest.raises(runlock.RunLockError):
        runlock.acquire(tmp_path, "evening-sync", now=T0, wait=300)


def test_timezone_aware_lock_counts_as_unreadable(tmp_path):
    path = tmp_path / runlock.LOCK_RELPATH
    path.parent.mkdir(parents=True)
    path.write_text('{"routine": "evening-sync", "started_at": "2026-10-12T12:00+02:00", "host": "x"}',
                    encoding="utf-8")
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0)
    assert result["acquired"] and result["stale"]


def test_lock_dated_in_the_future_is_stale(tmp_path):
    """Clock skew between two hosts, or the October DST fall-back."""
    runlock.acquire(tmp_path, "evening-sync", now=T0 + timedelta(hours=1))
    result = runlock.acquire(tmp_path, "sync-recordings", now=T0)
    assert result["acquired"] and result["stale"]
