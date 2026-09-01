"""Per-adapter last-sync watermark: a cache, not a ledger.

`dates window`'s discovery cap (a later task) needs a floor narrower than
"always the full trailing window" once an adapter has synced cleanly before.
lastsync remembers, per adapter, the UTC instant the last clean sync run
covered through. Doctrine, same as scan-cache.json and seen-events.json: a
missing, unreadable, malformed, or version-mismatched file is a normal cold
state, answered as None rather than raised — deleting this file only widens
the next window back out to the discovery cap, it never loses or duplicates
a sync.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from vaultlib import lastsync

NOW = datetime(2026, 8, 31, 18, 0, 0)  # naive UTC, like the module works in


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "20-meetings").mkdir()
    return tmp_path


def test_set_then_read_round_trips(tmp_path):
    root = make_vault(tmp_path)
    result = lastsync.set_mark(root, "m365", "2026-08-30T14:00:00", NOW)
    assert result["advanced"] is True
    assert result["last_utc_to"] == "2026-08-30T14:00:00"
    assert lastsync.read(root, "m365") == datetime(2026, 8, 30, 14, 0, 0)


def test_missing_file_reads_as_none(tmp_path):
    root = make_vault(tmp_path)
    assert lastsync.read(root, "m365") is None


def test_malformed_json_reads_as_none(tmp_path):
    root = make_vault(tmp_path)
    path = root / lastsync.STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{torn", encoding="utf-8")
    assert lastsync.read(root, "m365") is None


def test_wrong_version_reads_as_none(tmp_path):
    root = make_vault(tmp_path)
    path = root / lastsync.STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": lastsync.STATE_VERSION + 1,
        "adapters": {"m365": {"last_utc_to": "2026-08-30T14:00:00",
                              "set_at": "2026-08-30T15:00:00"}},
    }), encoding="utf-8")
    assert lastsync.read(root, "m365") is None


def test_malformed_stored_entry_reads_as_none(tmp_path):
    root = make_vault(tmp_path)
    path = root / lastsync.STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": lastsync.STATE_VERSION,
        "adapters": {"m365": {"last_utc_to": "not-a-date"}},
    }), encoding="utf-8")
    assert lastsync.read(root, "m365") is None


def test_unknown_adapter_raises_on_read(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(lastsync.LastSyncError, match="adapter"):
        lastsync.read(root, "zoom")


def test_unknown_adapter_raises_on_set_mark(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(lastsync.LastSyncError, match="adapter"):
        lastsync.set_mark(root, "zoom", "2026-08-30T14:00:00", NOW)


def test_setting_one_adapter_does_not_clobber_the_other(tmp_path):
    root = make_vault(tmp_path)
    lastsync.set_mark(root, "m365", "2026-08-30T14:00:00", NOW)
    lastsync.set_mark(root, "plaud", "2026-08-29T09:00:00", NOW)
    assert lastsync.read(root, "m365") == datetime(2026, 8, 30, 14, 0, 0)
    assert lastsync.read(root, "plaud") == datetime(2026, 8, 29, 9, 0, 0)


def test_a_later_mark_advances(tmp_path):
    root = make_vault(tmp_path)
    lastsync.set_mark(root, "m365", "2026-08-30T14:00:00", NOW)
    result = lastsync.set_mark(root, "m365", "2026-08-31T14:00:00", NOW)
    assert result["advanced"] is True
    assert result["last_utc_to"] == "2026-08-31T14:00:00"
    assert lastsync.read(root, "m365") == datetime(2026, 8, 31, 14, 0, 0)


def test_an_earlier_mark_after_a_later_one_is_a_no_op(tmp_path):
    """Monotonicity: a stale replay must never widen-then-corrupt the next
    window by pulling the floor backward."""
    root = make_vault(tmp_path)
    lastsync.set_mark(root, "m365", "2026-08-31T14:00:00", NOW)
    result = lastsync.set_mark(root, "m365", "2026-08-30T14:00:00", NOW)
    assert result["advanced"] is False
    assert result["last_utc_to"] == "2026-08-31T14:00:00"
    assert lastsync.read(root, "m365") == datetime(2026, 8, 31, 14, 0, 0)


def test_an_equal_mark_is_a_no_op(tmp_path):
    root = make_vault(tmp_path)
    lastsync.set_mark(root, "m365", "2026-08-31T14:00:00", NOW)
    result = lastsync.set_mark(root, "m365", "2026-08-31T14:00:00", NOW)
    assert result["advanced"] is False
    assert result["last_utc_to"] == "2026-08-31T14:00:00"


def test_graph_form_datetimes_are_normalized(tmp_path):
    """Graph emits 7-digit fractions and a trailing Z; both must land on the
    same stored key as the plain ISO form."""
    root = make_vault(tmp_path)
    lastsync.set_mark(root, "m365", "2026-08-30T14:00:00.0000000Z", NOW)
    assert lastsync.read(root, "m365") == datetime(2026, 8, 30, 14, 0, 0)


def test_malformed_utc_to_raises(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(lastsync.LastSyncError):
        lastsync.set_mark(root, "m365", "not-a-date", NOW)


def test_set_at_is_stamped_from_now_utc(tmp_path):
    root = make_vault(tmp_path)
    result = lastsync.set_mark(root, "m365", "2026-08-30T14:00:00", NOW)
    assert result["set_at"] == "2026-08-31T18:00:00"
    cache = json.loads((root / lastsync.STATE_RELPATH).read_text(encoding="utf-8"))
    assert cache["adapters"]["m365"]["set_at"] == "2026-08-31T18:00:00"


def test_a_no_op_does_not_rewrite_set_at(tmp_path):
    root = make_vault(tmp_path)
    lastsync.set_mark(root, "m365", "2026-08-31T14:00:00", NOW)
    from datetime import timedelta
    later = NOW + timedelta(hours=5)
    result = lastsync.set_mark(root, "m365", "2026-08-30T14:00:00", later)
    assert result["set_at"] == "2026-08-31T18:00:00"


def test_deleting_the_file_only_widens_the_next_window(tmp_path):
    root = make_vault(tmp_path)
    lastsync.set_mark(root, "m365", "2026-08-30T14:00:00", NOW)
    (root / lastsync.STATE_RELPATH).unlink()
    assert lastsync.read(root, "m365") is None


def test_adapters_constant(tmp_path):
    assert lastsync.ADAPTERS == ("m365", "plaud")
