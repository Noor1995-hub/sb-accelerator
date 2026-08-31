"""seen-events cache: M365 dedup BEFORE the fetch.

The measured failure this exists for: `m365 ids` needs full event reads, so
every candidate the calendar search returned was fetched (50-83k tokens each)
before dedup could say 25 of 27 were already synced or transcript-less — and
the next run re-fetched the same 25. triage() answers from the cheap search
listing alone which occurrences still need that fetch; record() writes the
outcomes back.

Doctrine, same as scan-cache.json: a cache, not a ledger. Deleting it costs
re-checks, never correctness — the vault's source-recording-id ledger still
dedups every write.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from vaultlib import seenevents, syncjob

NOW = datetime(2026, 8, 31, 18, 0, 0)  # naive UTC, like the module works in


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "20-meetings").mkdir()
    return tmp_path


def listing_event(event_id="AAMkAGId1", start="2026-08-28T14:00:00.0000000",
                  end="2026-08-28T15:00:00.0000000",
                  subject="Weekly sync") -> dict:
    return {
        "id": event_id,
        "subject": subject,
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
    }


def outcome(event_id="AAMkAGId1", start_utc="2026-08-28T14:00:00",
            kind="written", recording_id="m365:0123456789abcdef") -> dict:
    entry = {"id": event_id, "start_utc": start_utc, "outcome": kind}
    if kind == "written":
        entry["recording_id"] = recording_id
    return entry


def test_fresh_cache_sends_every_event_to_fetch(tmp_path):
    root = make_vault(tmp_path)
    events = [listing_event(), listing_event(event_id="AAMkAGId2")]
    result = seenevents.triage(root, events, NOW)
    assert [e["id"] for e in result["fetch"]] == ["AAMkAGId1", "AAMkAGId2"]
    assert all(e["reason"] == "unseen" for e in result["fetch"])
    assert result["filtered"] == {"written": 0, "no_transcript_final": 0,
                                  "skipped": 0}


def test_triage_filters_written_and_skipped_occurrences(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(root, [
        outcome(),
        outcome(event_id="AAMkAGId2", kind="skipped"),
    ], NOW)
    events = [listing_event(), listing_event(event_id="AAMkAGId2"),
              listing_event(event_id="AAMkAGId3")]
    result = seenevents.triage(root, events, NOW)
    assert [e["id"] for e in result["fetch"]] == ["AAMkAGId3"]
    assert result["filtered"] == {"written": 1, "no_transcript_final": 0,
                                  "skipped": 1}


def test_two_occurrences_of_one_series_are_distinct(tmp_path):
    """A recurring series can surface the same event id with different
    occurrence starts; a written Monday must not filter out Wednesday."""
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(start_utc="2026-08-24T14:00:00")], NOW)
    monday = listing_event(start="2026-08-24T14:00:00.0000000",
                           end="2026-08-24T15:00:00.0000000")
    wednesday = listing_event(start="2026-08-26T14:00:00.0000000",
                              end="2026-08-26T15:00:00.0000000")
    result = seenevents.triage(root, [monday, wednesday], NOW)
    assert len(result["fetch"]) == 1
    assert result["fetch"][0]["start_utc"] == "2026-08-26T14:00:00"


def test_no_transcript_inside_48h_is_rechecked(tmp_path):
    """Teams transcripts arrive with delay: a no-transcript answer is
    provisional until the meeting has been over for 48 hours."""
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind="no-transcript")], NOW)
    # meeting ended 2026-08-28T15:00; 47h59m later it is still provisional
    almost = datetime(2026, 8, 30, 14, 59, 0)
    result = seenevents.triage(root, [listing_event()], almost)
    assert [e["reason"] for e in result["fetch"]] == ["recheck-no-transcript"]


def test_no_transcript_after_48h_is_final(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind="no-transcript")], NOW)
    past = datetime(2026, 8, 30, 15, 1, 0)  # 48h01m after the event end
    result = seenevents.triage(root, [listing_event()], past)
    assert result["fetch"] == []
    assert result["filtered"]["no_transcript_final"] == 1


def test_recording_an_outcome_round_trips(tmp_path):
    root = make_vault(tmp_path)
    recorded = seenevents.record(root, [outcome()], NOW)
    assert recorded["recorded"] == 1
    cache = json.loads(
        (root / seenevents.CACHE_RELPATH).read_text(encoding="utf-8"))
    entry = cache["events"]["AAMkAGId1|2026-08-28T14:00:00"]
    assert entry["outcome"] == "written"
    assert entry["recording_id"] == "m365:0123456789abcdef"
    assert entry["checked_at"] == "2026-08-31T18:00:00"


def test_record_normalizes_graph_datetimes_to_the_triage_key(tmp_path):
    """The full event read says 2026-08-28T14:00:00.0000000, the search
    listing the same — both must land on one key, not two."""
    root = make_vault(tmp_path)
    seenevents.record(
        root, [outcome(start_utc="2026-08-28T14:00:00.0000000Z")], NOW)
    result = seenevents.triage(root, [listing_event()], NOW)
    assert result["fetch"] == []


def test_record_rewrites_a_provisional_outcome(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind="no-transcript")], NOW)
    seenevents.record(root, [outcome()], NOW + timedelta(hours=5))
    result = seenevents.triage(root, [listing_event()],
                               NOW + timedelta(hours=6))
    assert result["fetch"] == []
    assert result["filtered"]["written"] == 1


def test_written_requires_a_namespaced_recording_id(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(seenevents.SeenEventsError, match="recording_id"):
        seenevents.record(root, [{"id": "A", "start_utc": "2026-08-28T14:00:00",
                                  "outcome": "written"}], NOW)
    with pytest.raises(seenevents.SeenEventsError, match="m365:"):
        seenevents.record(root, [outcome(recording_id="plaud:abc")], NOW)


def test_record_rejects_unknown_outcomes(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(seenevents.SeenEventsError, match="outcome"):
        seenevents.record(root, [outcome(kind="maybe")], NOW)


def test_triage_raises_on_a_non_array_or_non_object_listing(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(seenevents.SeenEventsError):
        seenevents.triage(root, {"value": []}, NOW)
    with pytest.raises(seenevents.SeenEventsError):
        seenevents.triage(root, ["not-an-event"], NOW)


def test_triage_warns_and_fetches_an_unkeyable_event(tmp_path):
    """Fail open: an entry whose start cannot be parsed cannot be cached,
    but it can still be fetched — losing an event is the one wrong answer."""
    root = make_vault(tmp_path)
    weird = {"id": "AAMkAGId9", "subject": "odd",
             "start": {"dateTime": "not-a-date", "timeZone": "UTC"}}
    result = seenevents.triage(root, [weird], NOW)
    assert [e["id"] for e in result["fetch"]] == ["AAMkAGId9"]
    assert result["fetch"][0]["reason"] == "unkeyed"
    assert result["warnings"]


def test_triage_warns_on_an_event_without_an_id(tmp_path):
    # No id means no fetch URI either — surfaced, never silently dropped.
    root = make_vault(tmp_path)
    event = listing_event()
    del event["id"]
    result = seenevents.triage(root, [event], NOW)
    assert result["fetch"] == []
    assert result["warnings"]


def test_deleting_the_cache_only_costs_rechecks(tmp_path):
    """The doctrine test: with the cache gone everything re-fetches, and the
    vault ledger still dedups the write — nothing is written twice."""
    root = make_vault(tmp_path)
    rid = "m365:0123456789abcdef"
    seenevents.record(root, [outcome(recording_id=rid)], NOW)
    # the meeting note the earlier run wrote — the real ledger
    (root / "20-meetings" / "28-08-26-weekly-sync.md").write_text(
        "---\ndate: 2026-08-28T16:00\nsource-recording-id: " + rid
        + "\n---\n", encoding="utf-8")

    (root / seenevents.CACHE_RELPATH).unlink()
    result = seenevents.triage(root, [listing_event()], NOW)
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]  # re-checks
    assert syncjob.dedup(root, [rid])["new"] == []               # never re-writes


def test_a_corrupt_cache_is_a_cold_cache(tmp_path):
    root = make_vault(tmp_path)
    path = root / seenevents.CACHE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{torn", encoding="utf-8")
    result = seenevents.triage(root, [listing_event()], NOW)
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]


def test_record_prunes_occurrences_older_than_the_horizon(tmp_path):
    root = make_vault(tmp_path)
    old = outcome(event_id="AAMkAGOld", start_utc="2026-06-01T14:00:00")
    seenevents.record(root, [old], datetime(2026, 6, 1, 18, 0, 0))
    result = seenevents.record(root, [outcome()], NOW)
    assert result["pruned"] == 1
    cache = json.loads(
        (root / seenevents.CACHE_RELPATH).read_text(encoding="utf-8"))
    assert list(cache["events"]) == ["AAMkAGId1|2026-08-28T14:00:00"]


def test_final_after_hours_is_the_named_constant():
    assert seenevents.NO_TRANSCRIPT_FINAL_AFTER_HOURS == 48
