"""Per-recording fetch-error counter: a cache, not a ledger.

There is no other retry state anywhere in this plugin — a recording that
fails to fetch forever (an oversized transcript, a Plaud id the connector
now returns `[]` for) retried at full dispatch cost on every run, with no
way to stop. `record` counts consecutive failing *calendar days* per id and,
at the third distinct day, suppresses it via `syncjob.skip` — never at the
third attempt in one day, which would park an id that only ever failed once.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from vaultlib import fetcherrors, syncjob

DAY1 = datetime(2026, 9, 10, 9, 0, 0)  # naive UTC, like every cache here
DAY1_LATER = datetime(2026, 9, 10, 19, 0, 0)
DAY2 = datetime(2026, 9, 11, 9, 0, 0)
DAY3 = datetime(2026, 9, 12, 9, 0, 0)


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "20-meetings").mkdir()
    return tmp_path


def write_meeting(root: Path, stem: str, recording_id: str) -> None:
    lines = ["---", "date: 2026-09-01T10:00", "type: meeting",
             f"source-recording-id: {recording_id}", "---", "",
             "## Key Takeaways", "- x"]
    (root / "20-meetings" / f"{stem}.md").write_text(
        "\n".join(lines), encoding="utf-8")


def entry(recording_id="plaud:abc123", reason="transport error") -> dict:
    return {"id": recording_id, "reason": reason}


def test_missing_file_loads_as_empty(tmp_path):
    root = make_vault(tmp_path)
    assert fetcherrors.load(root) == {"version": 1, "recordings": {}}


def test_malformed_json_loads_as_empty(tmp_path):
    root = make_vault(tmp_path)
    path = root / fetcherrors.STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{torn", encoding="utf-8")
    assert fetcherrors.load(root) == {"version": 1, "recordings": {}}


def test_wrong_version_loads_as_empty(tmp_path):
    root = make_vault(tmp_path)
    path = root / fetcherrors.STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 99, "recordings": {}}),
                    encoding="utf-8")
    assert fetcherrors.load(root) == {"version": 1, "recordings": {}}


def test_first_failure_records_count_one(tmp_path):
    root = make_vault(tmp_path)
    result = fetcherrors.record(root, [entry()], DAY1)
    assert result == {"recorded": ["plaud:abc123"], "parked": [],
                     "cleared": [], "already_parked": []}
    state = fetcherrors.load(root)
    rec = state["recordings"]["plaud:abc123"]
    assert rec["count"] == 1
    assert rec["last_reason"] == "transport error"
    assert rec["first_seen"] == "2026-09-10T09:00:00"


def test_two_failures_same_day_do_not_double_count(tmp_path):
    """Three runs on one day must not park an id that only failed once."""
    root = make_vault(tmp_path)
    fetcherrors.record(root, [entry()], DAY1)
    fetcherrors.record(root, [entry(reason="still failing")], DAY1_LATER)
    state = fetcherrors.load(root)
    rec = state["recordings"]["plaud:abc123"]
    assert rec["count"] == 1
    assert rec["last_reason"] == "still failing"
    assert rec["last_seen"] == "2026-09-10T19:00:00"


def test_third_distinct_day_parks_and_writes_skip_line(tmp_path):
    root = make_vault(tmp_path)
    fetcherrors.record(root, [entry(reason="day one")], DAY1)
    fetcherrors.record(root, [entry(reason="day two")], DAY2)
    result = fetcherrors.record(root, [entry(reason="day three")], DAY3)
    assert result["parked"] == [{"id": "plaud:abc123", "reason": "day three"}]
    assert result["recorded"] == ["plaud:abc123"]
    # parked: the file no longer tracks it — the skip list is now authoritative
    state = fetcherrors.load(root)
    assert "plaud:abc123" not in state["recordings"]
    skipped = syncjob.read_skip_records(root)
    assert len(skipped) == 1
    assert skipped[0]["recording_id"] == "plaud:abc123"
    assert skipped[0]["reason"] == "parked after 3 fetch-errors: day three"


def test_two_distinct_days_does_not_park(tmp_path):
    root = make_vault(tmp_path)
    fetcherrors.record(root, [entry()], DAY1)
    result = fetcherrors.record(root, [entry()], DAY2)
    assert result["parked"] == []
    assert syncjob.read_skip_list(root) == set()
    state = fetcherrors.load(root)
    assert state["recordings"]["plaud:abc123"]["count"] == 2


def test_park_reason_names_the_last_failure_reason(tmp_path):
    root = make_vault(tmp_path)
    fetcherrors.record(root, [entry(reason="oversized transcript")], DAY1)
    fetcherrors.record(root, [entry(reason="oversized transcript")], DAY2)
    fetcherrors.record(root, [entry(reason="oversized transcript")], DAY3)
    skipped = syncjob.read_skip_records(root)
    assert skipped[0]["reason"] == (
        "parked after 3 fetch-errors: oversized transcript")


def test_ids_are_canonicalized(tmp_path):
    """A Plaud id spelled with the of_ object prefix is the same recording
    as the bare-hex spelling — same as everywhere else this plugin compares
    ids."""
    root = make_vault(tmp_path)
    fetcherrors.record(root, [entry(recording_id="plaud:of_abc123")], DAY1)
    fetcherrors.record(root, [entry(recording_id="plaud:abc123")], DAY2)
    state = fetcherrors.load(root)
    assert list(state["recordings"]) == ["plaud:abc123"]
    assert state["recordings"]["plaud:abc123"]["count"] == 2


def test_prune_drops_entries_older_than_14_days(tmp_path):
    root = make_vault(tmp_path)
    fetcherrors.record(root, [entry(recording_id="plaud:stale")], DAY1)
    later = datetime(2026, 9, 25, 9, 0, 0)  # 15 days after DAY1
    fetcherrors.record(root, [entry(recording_id="plaud:fresh")], later)
    state = fetcherrors.load(root)
    assert "plaud:stale" not in state["recordings"]
    assert "plaud:fresh" in state["recordings"]


def test_clear_removes_a_tracked_id(tmp_path):
    root = make_vault(tmp_path)
    fetcherrors.record(root, [entry()], DAY1)
    result = fetcherrors.clear(root, ["plaud:abc123"])
    assert result == {"cleared": ["plaud:abc123"]}
    assert fetcherrors.load(root)["recordings"] == {}


def test_clear_is_idempotent_for_an_untracked_id(tmp_path):
    root = make_vault(tmp_path)
    result = fetcherrors.clear(root, ["plaud:neverseen"])
    assert result == {"cleared": []}


def test_clear_canonicalizes_ids(tmp_path):
    root = make_vault(tmp_path)
    fetcherrors.record(root, [entry(recording_id="plaud:abc123")], DAY1)
    result = fetcherrors.clear(root, ["plaud:of_abc123"])
    assert result == {"cleared": ["plaud:abc123"]}


def test_record_self_heals_a_tracked_id_now_in_the_vault_ledger(tmp_path):
    """`record` runs after a batch's outcomes are already banked, so an id
    that failed before and now has a meeting note on disk succeeded on a
    later attempt — no separate clear call should be needed for it."""
    root = make_vault(tmp_path)
    fetcherrors.record(root, [entry(recording_id="plaud:retried")], DAY1)
    write_meeting(root, "2026-09-01-retried-meeting", "plaud:retried")
    result = fetcherrors.record(root, [entry(recording_id="plaud:other")], DAY2)
    assert "plaud:retried" in result["cleared"]
    state = fetcherrors.load(root)
    assert "plaud:retried" not in state["recordings"]
    assert "plaud:other" in state["recordings"]


def test_record_rejects_a_non_list_payload(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(fetcherrors.FetchErrorsError, match="array"):
        fetcherrors.record(root, {"id": "plaud:abc123"}, DAY1)


def test_record_rejects_an_entry_missing_a_reason(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(fetcherrors.FetchErrorsError, match="reason"):
        fetcherrors.record(root, [{"id": "plaud:abc123"}], DAY1)


def test_record_rejects_an_entry_missing_an_id(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(fetcherrors.FetchErrorsError, match="id"):
        fetcherrors.record(root, [{"reason": "x"}], DAY1)


def test_clear_rejects_a_non_list_payload(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(fetcherrors.FetchErrorsError, match="array"):
        fetcherrors.clear(root, "plaud:abc123")


# ---------------------------------------------------------------------------
# Fix round 1: a non-namespaced id must fail immediately, not two days later
# inside syncjob.skip's own validation, deep in the park branch, aborting a
# whole batch that also carried well-formed entries.

def test_a_non_namespaced_id_fails_on_the_first_call(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(fetcherrors.FetchErrorsError, match="namespace"):
        fetcherrors.record(
            root, [{"id": "not-namespaced", "reason": "x"}], DAY1)
    # Nothing was mutated: the malformed entry never reached load()/save().
    assert not (root / fetcherrors.STATE_RELPATH).exists()


def test_a_non_namespaced_id_does_not_survive_two_good_days(tmp_path):
    """The bug this guards against: a malformed id was silently accepted and
    counted for two days, then blew up inside syncjob.skip on day three,
    losing every other entry in that same call. It must never even get
    past day one."""
    root = make_vault(tmp_path)
    with pytest.raises(fetcherrors.FetchErrorsError):
        fetcherrors.record(
            root, [{"id": "bogus:not-a-real-namespace", "reason": "x"}], DAY1)
    assert fetcherrors.load(root) == {"version": 1, "recordings": {}}


def test_a_malformed_id_in_a_mixed_batch_aborts_before_any_write(tmp_path):
    """A well-formed sibling entry in the same call must not be silently
    lost either — the whole call fails up front, before state is loaded."""
    root = make_vault(tmp_path)
    with pytest.raises(fetcherrors.FetchErrorsError):
        fetcherrors.record(root, [
            entry(recording_id="plaud:good"),
            {"id": "not-namespaced", "reason": "x"},
        ], DAY1)
    assert fetcherrors.load(root) == {"version": 1, "recordings": {}}


# ---------------------------------------------------------------------------
# Fix round 1: an id already on the skip list must never be re-tracked from
# zero — a stale re-submission of a just-parked id (fetch_errors_batch.json
# accumulating across banking calls in one run, say) must not un-park the
# counting clock.

def test_an_already_skip_listed_id_is_not_retracked(tmp_path):
    root = make_vault(tmp_path)
    syncjob.skip(root, "plaud:abc123", reason="parked after 3 fetch-errors: x")
    result = fetcherrors.record(root, [entry()], DAY1)
    assert result["already_parked"] == ["plaud:abc123"]
    assert result["recorded"] == []
    assert result["parked"] == []
    state = fetcherrors.load(root)
    assert "plaud:abc123" not in state["recordings"]


def test_resubmitting_a_just_parked_id_in_the_same_run_does_not_reset_it(tmp_path):
    root = make_vault(tmp_path)
    fetcherrors.record(root, [entry(reason="d1")], DAY1)
    fetcherrors.record(root, [entry(reason="d2")], DAY2)
    park_result = fetcherrors.record(root, [entry(reason="d3")], DAY3)
    assert park_result["parked"] == [{"id": "plaud:abc123", "reason": "d3"}]
    # A later banking call this same day resubmits the same id (e.g. a
    # stale batch file) — it must come back as already_parked, not restart
    # the counter at 1.
    again = fetcherrors.record(root, [entry(reason="d3 again")], DAY3)
    assert again["already_parked"] == ["plaud:abc123"]
    assert again["recorded"] == []
    state = fetcherrors.load(root)
    assert "plaud:abc123" not in state["recordings"]


def test_parse_now_defaults_to_the_clock(tmp_path):
    assert isinstance(fetcherrors.parse_now(None), datetime)


def test_parse_now_accepts_graph_form_timestamps():
    parsed = fetcherrors.parse_now("2026-09-10T09:00:00.0000000Z")
    assert parsed == datetime(2026, 9, 10, 9, 0, 0)


def test_parse_now_rejects_an_unparseable_string():
    with pytest.raises(fetcherrors.FetchErrorsError):
        fetcherrors.parse_now("not-a-date")


# ---------------------------------------------------------------------------
# Final review, item 1: pruning runs AFTER incrementing, keyed on last_seen,
# so the docstring must describe a rolling per-failure gap, not a fixed
# 14-day window from the first failure.

def test_module_docstring_describes_a_rolling_gap_not_a_fixed_window():
    doc = " ".join(fetcherrors.__doc__.split())
    assert "each within 14 days of the previous failure" in doc
    assert "within a 14-day window" not in doc


def test_three_failures_13_days_apart_still_park(tmp_path):
    """The behavior item 1's docstring fix describes: consecutive failures
    up to 14 days apart never reset the counter, even though the total span
    (26 days here) is well past PRUNE_AFTER_DAYS."""
    root = make_vault(tmp_path)
    day0 = datetime(2026, 1, 1, 9, 0, 0)
    day13 = datetime(2026, 1, 14, 9, 0, 0)
    day26 = datetime(2026, 1, 27, 9, 0, 0)
    fetcherrors.record(root, [entry(reason="d0")], day0)
    fetcherrors.record(root, [entry(reason="d13")], day13)
    result = fetcherrors.record(root, [entry(reason="d26")], day26)
    assert result["parked"] == [{"id": "plaud:abc123", "reason": "d26"}]


# ---------------------------------------------------------------------------
# Review round 2 (PR #218 inline finding): last_seen was overwritten with
# `stamp` before the staleness check could ever see the *previous* gap for
# this same id, so three failures months apart still combined into a park.
# record() must now reset an id's own count when its prior entry is already
# stale, rather than relying solely on _prune (which only ever catches a
# *different* id's stale entry sharing the same call).

def test_three_failures_60_days_apart_never_park(tmp_path):
    """Each gap (60 days) far exceeds the 14-day horizon, so every failure
    must start counting fresh — count stays at 1 every time, never parks."""
    root = make_vault(tmp_path)
    day0 = datetime(2026, 1, 1, 9, 0, 0)
    day60 = datetime(2026, 3, 2, 9, 0, 0)
    day120 = datetime(2026, 5, 1, 9, 0, 0)

    result0 = fetcherrors.record(root, [entry(reason="d0")], day0)
    assert result0["parked"] == []
    assert fetcherrors.load(root)["recordings"]["plaud:abc123"]["count"] == 1

    result60 = fetcherrors.record(root, [entry(reason="d60")], day60)
    assert result60["parked"] == []
    entry60 = fetcherrors.load(root)["recordings"]["plaud:abc123"]
    assert entry60["count"] == 1
    assert entry60["first_seen"] == "2026-03-02T09:00:00"

    result120 = fetcherrors.record(root, [entry(reason="d120")], day120)
    assert result120["parked"] == []
    entry120 = fetcherrors.load(root)["recordings"]["plaud:abc123"]
    assert entry120["count"] == 1
    assert entry120["first_seen"] == "2026-05-01T09:00:00"


def test_three_failures_10_days_apart_park_on_the_third(tmp_path):
    """Each gap (10 days) is well inside the 14-day horizon, so the count
    keeps accumulating and parks on the third distinct day, same as the
    13-day-gap case above."""
    root = make_vault(tmp_path)
    day0 = datetime(2026, 1, 1, 9, 0, 0)
    day10 = datetime(2026, 1, 11, 9, 0, 0)
    day20 = datetime(2026, 1, 21, 9, 0, 0)
    fetcherrors.record(root, [entry(reason="d0")], day0)
    result10 = fetcherrors.record(root, [entry(reason="d10")], day10)
    assert result10["parked"] == []
    assert fetcherrors.load(root)["recordings"]["plaud:abc123"]["count"] == 2
    result20 = fetcherrors.record(root, [entry(reason="d20")], day20)
    assert result20["parked"] == [{"id": "plaud:abc123", "reason": "d20"}]


# ---------------------------------------------------------------------------
# Final review, item 5: clear() stays a library-only helper — no CLI verb.

def test_clear_docstring_states_it_is_library_only():
    assert "library helper" in fetcherrors.clear.__doc__
    assert "CLI verb" in fetcherrors.clear.__doc__
