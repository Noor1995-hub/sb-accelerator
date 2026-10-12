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
                                  "no_transcript_waiting": 0,
                                  "skipped": 0, "forbidden": 0, "no_access": 0,
                                  "external": 0}


def test_a_windows_zone_listing_keys_on_the_same_utc_start(tmp_path):
    """A mailbox with its own time zone answers in it ("Romance Standard
    Time"); triage used to refuse the whole listing, so nothing synced."""
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Paris")
    except Exception:
        pytest.skip("no tz database on host")
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome()], NOW)
    event = listing_event(start="2026-08-28T16:00:00.0000000",
                          end="2026-08-28T17:00:00.0000000")
    event["start"]["timeZone"] = event["end"]["timeZone"] = "Romance Standard Time"
    fresh = listing_event(event_id="AAMkAGId2", start="2026-08-28T16:00:00.0000000",
                          end="2026-08-28T17:00:00.0000000")
    fresh["start"]["timeZone"] = fresh["end"]["timeZone"] = "Romance Standard Time"
    result = seenevents.triage(root, [event, fresh], NOW)
    assert result["filtered"]["written"] == 1
    assert [(e["id"], e["start_utc"]) for e in result["fetch"]] == [
        ("AAMkAGId2", "2026-08-28T14:00:00")]


def test_a_listing_in_an_unresolvable_zone_is_refused(tmp_path):
    root = make_vault(tmp_path)
    event = listing_event()
    event["start"]["timeZone"] = "Not A Zone"
    with pytest.raises(seenevents.SeenEventsError, match="refusing to guess"):
        seenevents.triage(root, [event], NOW)


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
                                  "no_transcript_waiting": 0,
                                  "skipped": 1, "forbidden": 0, "no_access": 0,
                                  "external": 0}


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
    # checked well outside the 6h recheck hold, so only the 48h final
    # window is under test here
    checked_at = datetime(2026, 8, 28, 16, 0, 0)  # 1h after the meeting ends
    seenevents.record(root, [outcome(kind="no-transcript")], checked_at)
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


def test_recent_recheck_is_filtered_as_waiting(tmp_path):
    """A recheck costs a dispatch; three runs a day must not pay three
    times. A no-transcript answer checked minutes ago stays held."""
    root = make_vault(tmp_path)
    ev = listing_event("ev1", "2026-08-31T10:00:00", "2026-08-31T11:00:00",
                       "Weekly")
    seenevents.record(
        root, [outcome("ev1", "2026-08-31T10:00:00", "no-transcript")], NOW)
    result = seenevents.triage(root, [ev], NOW + timedelta(hours=3))
    assert result["fetch"] == []
    assert result["filtered"]["no_transcript_waiting"] == 1


def test_recheck_boundary_is_inclusive_at_6h(tmp_path):
    # checked_at exactly 6h old -> fetch (>=6h re-checks); 5h59m -> waiting
    root = make_vault(tmp_path)
    ev = listing_event("ev1", "2026-08-31T10:00:00", "2026-08-31T11:00:00",
                       "Weekly")
    seenevents.record(
        root, [outcome("ev1", "2026-08-31T10:00:00", "no-transcript")], NOW)
    exactly_6h = seenevents.triage(root, [ev], NOW + timedelta(hours=6))
    assert [e["reason"] for e in exactly_6h["fetch"]] == \
        ["recheck-no-transcript"]
    almost_6h = seenevents.triage(
        root, [ev], NOW + timedelta(hours=5, minutes=59))
    assert almost_6h["fetch"] == []
    assert almost_6h["filtered"]["no_transcript_waiting"] == 1


def test_stale_recheck_still_fetches(tmp_path):
    # 7h since check, <48h since end -> fetch, reason recheck-no-transcript
    root = make_vault(tmp_path)
    ev = listing_event("ev1", "2026-08-31T10:00:00", "2026-08-31T11:00:00",
                       "Weekly")
    seenevents.record(
        root, [outcome("ev1", "2026-08-31T10:00:00", "no-transcript")], NOW)
    result = seenevents.triage(root, [ev], NOW + timedelta(hours=7))
    assert [e["reason"] for e in result["fetch"]] == \
        ["recheck-no-transcript"]


def test_final_wins_over_waiting(tmp_path):
    # end + 49h AND checked 1h ago -> filtered["no_transcript_final"], not
    # waiting: the 48h final horizon is checked before the recheck hold.
    root = make_vault(tmp_path)
    ev = listing_event("ev1", "2026-08-31T10:00:00", "2026-08-31T11:00:00",
                       "Weekly")
    checked_at = datetime(2026, 9, 2, 11, 0, 0)  # end + 48h
    seenevents.record(
        root, [outcome("ev1", "2026-08-31T10:00:00", "no-transcript")],
        checked_at)
    now = checked_at + timedelta(hours=1)  # end + 49h, checked 1h ago
    result = seenevents.triage(root, [ev], now)
    assert result["fetch"] == []
    assert result["filtered"]["no_transcript_final"] == 1
    assert result["filtered"]["no_transcript_waiting"] == 0


def test_refresh_restarts_the_hold(tmp_path):
    # record() no-transcript again at T+7h -> triage at T+8h -> waiting
    root = make_vault(tmp_path)
    ev = listing_event("ev1", "2026-08-31T10:00:00", "2026-08-31T11:00:00",
                       "Weekly")
    seenevents.record(
        root, [outcome("ev1", "2026-08-31T10:00:00", "no-transcript")], NOW)
    seenevents.record(
        root, [outcome("ev1", "2026-08-31T10:00:00", "no-transcript")],
        NOW + timedelta(hours=7))
    result = seenevents.triage(root, [ev], NOW + timedelta(hours=8))
    assert result["fetch"] == []
    assert result["filtered"]["no_transcript_waiting"] == 1


def test_missing_or_malformed_checked_at_fails_open(tmp_path):
    # an entry without checked_at, and one with "not-a-date" -> both fetch
    root = make_vault(tmp_path)
    cache_path = root / seenevents.CACHE_RELPATH
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "version": seenevents.CACHE_VERSION,
        "events": {
            "ev1|2026-08-31T10:00:00": {"outcome": "no-transcript"},
            "ev2|2026-08-31T10:00:00": {"outcome": "no-transcript",
                                        "checked_at": "not-a-date"},
        },
    }), encoding="utf-8")
    ev1 = listing_event("ev1", "2026-08-31T10:00:00", "2026-08-31T11:00:00",
                        "Weekly")
    ev2 = listing_event("ev2", "2026-08-31T10:00:00", "2026-08-31T11:00:00",
                        "Weekly")
    result = seenevents.triage(root, [ev1, ev2], NOW)
    assert [e["reason"] for e in result["fetch"]] == \
        ["recheck-no-transcript", "recheck-no-transcript"]


def test_forbidden_is_terminal_immediately(tmp_path):
    """A cross-tenant 403 is a settled answer, not a "not yet": unlike
    no-transcript, which stays provisional for 48h because Teams delivers
    transcripts late, a forbidden fetch never heals, so it is filtered from
    the very next triage and stays filtered a week later."""
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind="forbidden")], NOW)
    soon = NOW + timedelta(minutes=1)
    result = seenevents.triage(root, [listing_event()], soon)
    assert result["fetch"] == []
    assert result["filtered"]["forbidden"] == 1
    later = NOW + timedelta(days=7)
    result = seenevents.triage(root, [listing_event()], later)
    assert result["fetch"] == []
    assert result["filtered"]["forbidden"] == 1


def test_no_access_is_terminal_immediately(tmp_path):
    """A 403 whose body names Graph code 3003 means the vault owner attended
    but did not organise the meeting — this connector resolves transcripts
    through the organiser-only lookup, so the condition heals only through a
    permission or connector change, never a per-run retry. Settled like
    forbidden, but counted and reported separately."""
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind="no-access")], NOW)
    soon = NOW + timedelta(minutes=1)
    result = seenevents.triage(root, [listing_event()], soon)
    assert result["fetch"] == []
    assert result["filtered"]["no_access"] == 1
    assert result["filtered"]["forbidden"] == 0
    later = NOW + timedelta(days=7)
    result = seenevents.triage(root, [listing_event()], later)
    assert result["fetch"] == []
    assert result["filtered"]["no_access"] == 1


def test_no_access_requires_no_recording_id(tmp_path):
    root = make_vault(tmp_path)
    recorded = seenevents.record(root, [{
        "id": "AAMkAGId1", "start_utc": "2026-08-28T14:00:00",
        "outcome": "no-access",
    }], NOW)
    assert recorded["recorded"] == 1


def test_no_access_prunes_at_the_same_30_day_horizon(tmp_path):
    root = make_vault(tmp_path)
    old = outcome(event_id="AAMkAGOld", start_utc="2026-06-01T14:00:00",
                  kind="no-access")
    seenevents.record(root, [old], datetime(2026, 6, 1, 18, 0, 0))
    result = seenevents.record(root, [outcome()], NOW)
    assert result["pruned"] == 1


def test_forbidden_requires_no_recording_id(tmp_path):
    root = make_vault(tmp_path)
    recorded = seenevents.record(root, [{
        "id": "AAMkAGId1", "start_utc": "2026-08-28T14:00:00",
        "outcome": "forbidden",
    }], NOW)
    assert recorded["recorded"] == 1


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


def test_an_unkeyed_outcome_is_skipped_and_the_batch_still_lands(tmp_path):
    # Review 2026-10-12: triage hands an `unkeyed` occurrence over with
    # start_utc null; one such entry used to fail the whole banking call.
    root = make_vault(tmp_path)
    unkeyed = {**outcome(), "id": "AAMkAGId2", "start_utc": None,
               "outcome": "no-transcript"}
    unkeyed.pop("recording_id", None)
    recorded = seenevents.record(root, [outcome(), unkeyed], NOW)
    assert (recorded["recorded"], recorded["skipped_unkeyed"]) == (1, 1)
    cache = json.loads((root / seenevents.CACHE_RELPATH).read_text(encoding="utf-8"))
    assert list(cache["events"]) == ["AAMkAGId1|2026-08-28T14:00:00"]


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


# ---------------------------------------------------------------------------
# The not-ended guard. M365 synthesizes meetingTranscriptUrl for future
# occurrences too (it is the base64-encoded join URL), so without this guard
# a future meeting reaches dispatch — and on a recurring series the synthetic
# URL can answer with *past* occurrences' transcripts: future-dated junk. A
# live run nearly dispatched extraction workers for 34 such events.


def test_triage_defers_an_occurrence_that_has_not_ended(tmp_path):
    root = make_vault(tmp_path)
    future = listing_event(start="2026-09-03T14:00:00.0000000",
                           end="2026-09-03T15:00:00.0000000")
    result = seenevents.triage(root, [future], NOW)
    assert result["fetch"] == []
    assert result["deferred"] == [{"id": "AAMkAGId1",
                                   "start_utc": "2026-09-03T14:00:00",
                                   "subject": "Weekly sync",
                                   "event_uri":
                                       "calendar:///events/AAMkAGId1",
                                   "reason": "not-ended"}]


def test_triage_defers_a_meeting_still_in_progress(tmp_path):
    # No transcript can exist before the meeting ends, so in-progress is
    # deferred exactly like future.
    root = make_vault(tmp_path)
    running = listing_event(start="2026-08-31T17:30:00.0000000",
                            end="2026-08-31T18:30:00.0000000")
    result = seenevents.triage(root, [running], NOW)
    assert result["fetch"] == []
    assert [e["reason"] for e in result["deferred"]] == ["not-ended"]


def test_triage_defers_a_future_start_with_no_end(tmp_path):
    root = make_vault(tmp_path)
    event = listing_event(start="2026-09-03T14:00:00.0000000")
    del event["end"]
    result = seenevents.triage(root, [event], NOW)
    assert result["fetch"] == []
    assert [e["reason"] for e in result["deferred"]] == ["not-ended"]


def test_a_deferred_occurrence_fetches_normally_after_it_ends(tmp_path):
    # Deferral is per-run and never recorded, so the occurrence must sync
    # normally on the first run after the meeting happens.
    root = make_vault(tmp_path)
    event = listing_event(start="2026-09-03T14:00:00.0000000",
                          end="2026-09-03T15:00:00.0000000")
    assert seenevents.triage(root, [event], NOW)["fetch"] == []
    later = datetime(2026, 9, 3, 16, 0, 0)
    result = seenevents.triage(root, [event], later)
    assert result["deferred"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]


def test_the_not_ended_guard_outranks_the_cache(tmp_path):
    # Nothing legitimate can record an outcome for an unfinished occurrence,
    # so if one exists (clock skew, an improvised window) it must not
    # resurrect the fetch — deferral is checked before the cache.
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(start_utc="2026-09-03T14:00:00")], NOW)
    event = listing_event(start="2026-09-03T14:00:00.0000000",
                          end="2026-09-03T15:00:00.0000000")
    result = seenevents.triage(root, [event], NOW)
    assert result["fetch"] == []
    assert result["filtered"]["written"] == 0
    assert [e["reason"] for e in result["deferred"]] == ["not-ended"]


def test_past_events_are_never_deferred(tmp_path):
    root = make_vault(tmp_path)
    result = seenevents.triage(root, [listing_event()], NOW)
    assert result["deferred"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]


# ---------------------------------------------------------------------------
# forget() — the hand-editable-cache fallback made deterministic. A
# consultant forces a re-check after client IT changes a permission by
# dropping every cached entry with one outcome, rather than editing the
# JSON file by hand or deleting the whole cache (which would also cost a
# re-check on every unrelated occurrence).


def test_forget_drops_only_entries_with_the_named_outcome(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(root, [
        outcome(event_id="AAMkAGId1", kind="no-access"),
        outcome(event_id="AAMkAGId2", kind="forbidden"),
        outcome(event_id="AAMkAGId3", kind="written"),
    ], NOW)
    result = seenevents.forget(root, "no-access")
    assert result["forgotten"] == 1
    assert result["remaining"] == 2
    cache = json.loads(
        (root / seenevents.CACHE_RELPATH).read_text(encoding="utf-8"))
    outcomes_left = {v["outcome"] for v in cache["events"].values()}
    assert outcomes_left == {"forbidden", "written"}


def test_forget_is_a_noop_on_a_cold_cache(tmp_path):
    root = make_vault(tmp_path)
    result = seenevents.forget(root, "no-access")
    assert result == {"forgotten": 0, "remaining": 0}


def test_forget_rejects_an_outcome_not_in_the_closed_vocabulary(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(seenevents.SeenEventsError, match="outcome"):
        seenevents.forget(root, "maybe")


def test_forgetting_no_access_lets_the_occurrence_be_fetched_again(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind="no-access")], NOW)
    still_settled = seenevents.triage(root, [listing_event()], NOW)
    assert still_settled["fetch"] == []
    seenevents.forget(root, "no-access")
    after_forget = seenevents.triage(root, [listing_event()], NOW)
    assert [e["reason"] for e in after_forget["fetch"]] == ["unseen"]


# Review finding #4 (minor, round 1): forget("written") would silently drop
# up to 30 days of written history and re-trigger a paid dispatch wave for
# meetings already synced; forget("skipped") would undo a deliberate human
# decision the skip list already recorded why for. Both are refused. Only
# the outcomes that never heal on their own — no-access, forbidden,
# no-transcript — are legitimate forget targets.


def test_forget_refuses_written(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind="written")], NOW)
    with pytest.raises(seenevents.SeenEventsError, match="written"):
        seenevents.forget(root, "written")
    # refused before anything is dropped
    cache = json.loads(
        (root / seenevents.CACHE_RELPATH).read_text(encoding="utf-8"))
    assert len(cache["events"]) == 1


def test_forget_refuses_skipped(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(root, [{
        "id": "AAMkAGId1", "start_utc": "2026-08-28T14:00:00",
        "outcome": "skipped",
    }], NOW)
    with pytest.raises(seenevents.SeenEventsError, match="skipped"):
        seenevents.forget(root, "skipped")


@pytest.mark.parametrize("allowed", ["no-access", "forbidden", "no-transcript"])
def test_forget_allows_the_outcomes_that_never_heal_on_their_own(
    tmp_path, allowed
):
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind=allowed)], NOW)
    result = seenevents.forget(root, allowed)
    assert result["forgotten"] == 1


# ---------------------------------------------------------------------------
# Fix round 1, IMPORTANT: no undo existed for a triage-caught duplicate's
# seen-events entry (banked as `skipped`, which the bulk forget() refuses to
# touch). forget_event targets exactly one occurrence, regardless of its
# outcome — the undo `sync m365-forget --event-id --start-utc` needs.


def test_forget_event_removes_a_skipped_entry_the_bulk_form_refuses(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(root, [{
        "id": "AAMkAGId1", "start_utc": "2026-08-28T14:00:00",
        "outcome": "skipped",
    }], NOW)
    result = seenevents.forget_event(
        root, "AAMkAGId1", "2026-08-28T14:00:00")
    assert result == {"forgotten": 1, "remaining": 0}
    result2 = seenevents.triage(
        root, [listing_event(event_id="AAMkAGId1",
                             start="2026-08-28T14:00:00.0000000",
                             end="2026-08-28T15:00:00.0000000")], NOW)
    assert [e["reason"] for e in result2["fetch"]] == ["unseen"]


def test_forget_event_removes_a_written_entry_too(tmp_path):
    """Unlike the bulk form, the targeted form has no closed-vocabulary
    restriction — it names one occurrence, not a whole class of outcomes."""
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind="written")], NOW)
    result = seenevents.forget_event(
        root, "AAMkAGId1", "2026-08-28T14:00:00")
    assert result == {"forgotten": 1, "remaining": 0}


def test_forget_event_refuses_an_id_not_on_the_cache(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(seenevents.SeenEventsError, match="nothing to forget"):
        seenevents.forget_event(root, "AAMkAGId9", "2026-08-28T14:00:00")


def test_forget_event_leaves_other_entries_untouched(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(root, [
        outcome(event_id="AAMkAGId1", kind="skipped"),
        outcome(event_id="AAMkAGId2", kind="written"),
    ], NOW)
    result = seenevents.forget_event(
        root, "AAMkAGId1", "2026-08-28T14:00:00")
    assert result["remaining"] == 1
    cache = json.loads(
        (root / seenevents.CACHE_RELPATH).read_text(encoding="utf-8"))
    assert list(cache["events"]) == ["AAMkAGId2|2026-08-28T14:00:00"]


def test_forget_event_normalizes_graph_datetimes_in_the_key(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(
        root, [outcome(start_utc="2026-08-28T14:00:00.0000000Z")], NOW)
    result = seenevents.forget_event(
        root, "AAMkAGId1", "2026-08-28T14:00:00Z")
    assert result == {"forgotten": 1, "remaining": 0}


# Review finding #5 (minor, round 1): the fail-open branch in triage() (an
# outcome value this version does not know) was only ever exercised
# indirectly, through record()'s own validation rejecting it first. Writing
# the unknown value straight into the cache file bypasses record() and
# proves triage() itself refuses to trust an outcome it cannot recognise.


# ---------------------------------------------------------------------------
# The external-organizer filter (home_domains). triage() does not read
# config itself — these tests build vaults with no config.json at all, so
# home_domains always arrives as an explicit keyword from the caller.


def test_home_domains_none_filters_nothing(tmp_path):
    root = make_vault(tmp_path)
    ev = listing_event()
    ev["organizer"] = "someone@other-org.example"
    result = seenevents.triage(root, [ev], NOW, home_domains=None)
    assert result["external"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]


def test_organizer_outside_home_domains_is_external(tmp_path):
    root = make_vault(tmp_path)
    ev = listing_event()
    ev["organizer"] = "someone@other-org.example"
    result = seenevents.triage(root, [ev], NOW, home_domains=["example.com"])
    assert result["fetch"] == []
    assert result["external"] == [{
        "id": "AAMkAGId1", "start_utc": "2026-08-28T14:00:00",
        "subject": "Weekly sync",
        "event_uri": "calendar:///events/AAMkAGId1",
        "organizer": "someone@other-org.example",
    }]
    assert result["filtered"]["external"] == 1


def test_organizer_inside_home_domains_is_not_external(tmp_path):
    root = make_vault(tmp_path)
    ev = listing_event()
    ev["organizer"] = "someone@example.com"
    result = seenevents.triage(root, [ev], NOW, home_domains=["example.com"])
    assert result["external"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]


def test_domain_match_is_casefolded(tmp_path):
    root = make_vault(tmp_path)
    ev = listing_event()
    ev["organizer"] = "someone@Example.COM"
    result = seenevents.triage(root, [ev], NOW, home_domains=["example.com"])
    assert result["external"] == []
    result2 = seenevents.triage(root, [ev], NOW, home_domains=["EXAMPLE.COM"])
    assert result2["external"] == []


def test_organizer_dict_with_address_shape_is_read(tmp_path):
    """The full event-read shape: {"address": "..."}."""
    root = make_vault(tmp_path)
    ev = listing_event()
    ev["organizer"] = {"address": "someone@other-org.example"}
    result = seenevents.triage(root, [ev], NOW, home_domains=["example.com"])
    assert result["filtered"]["external"] == 1
    assert result["external"][0]["organizer"] == "someone@other-org.example"


def test_organizer_dict_with_email_address_shape_is_read(tmp_path):
    """Graph's own event shape: {"emailAddress": {"address": "..."}}."""
    root = make_vault(tmp_path)
    ev = listing_event()
    ev["organizer"] = {"emailAddress": {"address": "someone@other-org.example"}}
    result = seenevents.triage(root, [ev], NOW, home_domains=["example.com"])
    assert result["filtered"]["external"] == 1
    assert result["external"][0]["organizer"] == "someone@other-org.example"


def test_missing_organizer_fails_open_with_a_warning(tmp_path):
    root = make_vault(tmp_path)
    ev = listing_event()  # no "organizer" key at all
    result = seenevents.triage(root, [ev], NOW, home_domains=["example.com"])
    assert result["external"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]
    assert result["warnings"]
    assert "AAMkAGId1" in result["warnings"][0]
    assert "Weekly sync" in result["warnings"][0]


def test_organizer_with_no_at_sign_fails_open_with_a_warning(tmp_path):
    root = make_vault(tmp_path)
    ev = listing_event()
    ev["organizer"] = "not-an-email"
    result = seenevents.triage(root, [ev], NOW, home_domains=["example.com"])
    assert result["external"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]
    assert result["warnings"]


def test_external_outranks_a_cached_forbidden_outcome(tmp_path):
    """An occurrence cached as forbidden/no-access by an earlier run must
    surface as external once home_domains excludes its organizer — the
    filter may only just have been configured."""
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind="forbidden")], NOW)
    ev = listing_event()
    ev["organizer"] = "someone@other-org.example"
    result = seenevents.triage(root, [ev], NOW, home_domains=["example.com"])
    assert result["fetch"] == []
    assert result["filtered"]["forbidden"] == 0
    assert result["filtered"]["external"] == 1


def test_external_outranks_a_cached_no_access_outcome(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind="no-access")], NOW)
    ev = listing_event()
    ev["organizer"] = "someone@other-org.example"
    result = seenevents.triage(root, [ev], NOW, home_domains=["example.com"])
    assert result["fetch"] == []
    assert result["filtered"]["no_access"] == 0
    assert result["filtered"]["external"] == 1


def test_external_outranks_a_cached_written_outcome(tmp_path):
    root = make_vault(tmp_path)
    seenevents.record(root, [outcome(kind="written")], NOW)
    ev = listing_event()
    ev["organizer"] = "someone@other-org.example"
    result = seenevents.triage(root, [ev], NOW, home_domains=["example.com"])
    assert result["fetch"] == []
    assert result["filtered"]["written"] == 0
    assert result["filtered"]["external"] == 1


def test_external_outranks_not_ended(tmp_path):
    """A future external meeting is still external — never deferred."""
    root = make_vault(tmp_path)
    future = listing_event(start="2026-09-03T14:00:00.0000000",
                           end="2026-09-03T15:00:00.0000000")
    future["organizer"] = "someone@other-org.example"
    result = seenevents.triage(root, [future], NOW, home_domains=["example.com"])
    assert result["deferred"] == []
    assert result["fetch"] == []
    assert result["filtered"]["external"] == 1


def test_triage_fails_open_on_an_unrecognized_outcome_value_on_disk(tmp_path):
    root = make_vault(tmp_path)
    cache_path = root / seenevents.CACHE_RELPATH
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "version": seenevents.CACHE_VERSION,
        "events": {
            "AAMkAGId1|2026-08-28T14:00:00": {
                "outcome": "some-future-outcome-this-version-never-shipped",
                "checked_at": "2026-08-28T18:00:00",
            },
        },
    }), encoding="utf-8")
    result = seenevents.triage(root, [listing_event()], NOW)
    assert [e["id"] for e in result["fetch"]] == ["AAMkAGId1"]
    assert result["fetch"][0]["reason"] == "unseen"


# --- triage hands back the event URI, so nobody rebuilds it ---------------
#
# Issue #205: the orchestrator hand-percent-encoded a URL-safe event id into
# m365_routing.json's `uri`, turning `-` into `%2F`, and every worker
# dispatched with it got a 400 from Graph. triage already holds the listing
# id, so it emits the URI too — the routing step copies an opaque string
# instead of transforming one.

URLSAFE_ID = "AAkALgAAAAAAHYQDEapmEc2byACqAC-EWg0A0ceR5yDk4k28EdzA-CuLTw_AA"


def test_triage_emits_an_event_uri_for_every_fetch_survivor(tmp_path):
    root = make_vault(tmp_path)
    result = seenevents.triage(root, [listing_event(event_id=URLSAFE_ID)],
                               NOW)
    assert result["fetch"][0]["event_uri"] == (
        f"calendar:///events/{URLSAFE_ID}")


def test_triage_never_encodes_the_url_safe_substitutes(tmp_path):
    """The regression, at the layer the orchestrator actually reads."""
    root = make_vault(tmp_path)
    result = seenevents.triage(root, [listing_event(event_id=URLSAFE_ID)],
                               NOW)
    uri = result["fetch"][0]["event_uri"]
    assert "%2F" not in uri and "%2B" not in uri


def test_triage_emits_the_event_uri_on_deferred_and_external_entries(tmp_path):
    """A probe dispatch and an external-tenant report both name the
    occurrence; neither should have to rebuild its URI either."""
    root = make_vault(tmp_path)
    future = seenevents.triage(
        root,
        [listing_event(event_id=URLSAFE_ID,
                       start="2026-09-30T14:00:00.0000000",
                       end="2026-09-30T15:00:00.0000000")],
        NOW)
    assert future["deferred"][0]["reason"] == "not-ended"
    assert future["deferred"][0]["event_uri"] == (
        f"calendar:///events/{URLSAFE_ID}")

    outside = seenevents.triage(
        root,
        [{**listing_event(event_id=URLSAFE_ID),
          "organizer": "someone@other-tenant.example"}],
        NOW, home_domains=["example.com"])
    assert outside["external"][0]["event_uri"] == (
        f"calendar:///events/{URLSAFE_ID}")


def test_triage_emits_the_event_uri_on_an_unkeyable_entry(tmp_path):
    """No parseable start still means a fetchable event — and the fetch
    needs a URI."""
    root = make_vault(tmp_path)
    event = listing_event(event_id=URLSAFE_ID)
    event["start"] = {"dateTime": "not-a-date", "timeZone": "UTC"}
    result = seenevents.triage(root, [event], NOW)
    assert result["fetch"][0]["reason"] == "unkeyed"
    assert result["fetch"][0]["event_uri"] == (
        f"calendar:///events/{URLSAFE_ID}")


# ---------------------------------------------------------------------------
# A2: triage-time --collide. `m365 ids` cannot be used here (the listing
# carries no meetingTranscriptUrl), so the collide inputs are computed from
# the listing itself: owner-local start (`_occurrence_dt` + `utc_to_local`)
# and `(end - start)` minutes. A precise cross-namespace match moves a fetch
# survivor into the new top-level `duplicate` bucket instead of dispatching a
# worker for it at all — the 26% problem the plan's cost table names.


def make_meeting_note(root: Path, stem: str, *, date: str, duration: int,
                      recording_id: str) -> None:
    (root / "20-meetings").mkdir(exist_ok=True)
    (root / "20-meetings" / f"{stem}.md").write_text(
        f"---\ndate: {date}\ntype: meeting\n"
        f"recording-duration: {duration}\nsource: recorder\n"
        f"source-recording-id: {recording_id}\n---\n\nbody\n",
        encoding="utf-8")


def test_collide_moves_a_precise_cross_namespace_match_to_duplicate(tmp_path):
    root = make_vault(tmp_path)
    make_meeting_note(root, "28-08-26-weekly-sync",
                      date="2026-08-28T14:00", duration=60,
                      recording_id="plaud:abc123")
    result = seenevents.triage(root, [listing_event()], NOW,
                              collide=True, utc_offset="+00:00")
    assert result["fetch"] == []
    assert result["duplicate"] == [{
        "id": "AAMkAGId1", "start_utc": "2026-08-28T14:00:00",
        "subject": "Weekly sync", "event_uri": "calendar:///events/AAMkAGId1",
        "existing_stem": "28-08-26-weekly-sync",
        "existing_id": "plaud:abc123",
    }]


def test_collide_same_namespace_match_stays_in_fetch(tmp_path):
    root = make_vault(tmp_path)
    make_meeting_note(root, "28-08-26-weekly-sync",
                      date="2026-08-28T14:00", duration=60,
                      recording_id="m365:0123456789abcdef")
    result = seenevents.triage(root, [listing_event()], NOW,
                              collide=True, utc_offset="+00:00")
    assert result["duplicate"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]


def test_collide_imprecise_match_stays_in_fetch(tmp_path):
    root = make_vault(tmp_path)
    make_meeting_note(root, "28-08-26-weekly-sync",
                      date="2026-08-28", duration=60,
                      recording_id="plaud:abc123")
    result = seenevents.triage(root, [listing_event()], NOW,
                              collide=True, utc_offset="+00:00")
    assert result["duplicate"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]


def test_without_collide_flag_duplicate_bucket_stays_empty(tmp_path):
    root = make_vault(tmp_path)
    make_meeting_note(root, "28-08-26-weekly-sync",
                      date="2026-08-28T14:00", duration=60,
                      recording_id="plaud:abc123")
    result = seenevents.triage(root, [listing_event()], NOW)
    assert result["duplicate"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]


def test_collide_checks_each_recurring_occurrence_independently(tmp_path):
    root = make_vault(tmp_path)
    make_meeting_note(root, "24-08-26-weekly-sync",
                      date="2026-08-24T14:00", duration=60,
                      recording_id="plaud:abc123")
    monday = listing_event(start="2026-08-24T14:00:00.0000000",
                           end="2026-08-24T15:00:00.0000000")
    wednesday = listing_event(start="2026-08-26T14:00:00.0000000",
                              end="2026-08-26T15:00:00.0000000")
    result = seenevents.triage(root, [monday, wednesday], NOW,
                              collide=True, utc_offset="+00:00")
    assert [d["start_utc"] for d in result["duplicate"]] == \
        ["2026-08-24T14:00:00"]
    assert [e["start_utc"] for e in result["fetch"]] == \
        ["2026-08-26T14:00:00"]


def test_collide_non_strong_precise_match_stays_in_fetch(tmp_path):
    """Fix round 1, CRITICAL: a back-to-back note (starts exactly when the
    candidate ends) is a *match* under collide's 15-minute grace but has
    zero real overlap — must never be auto-settled as a duplicate."""
    root = make_vault(tmp_path)
    make_meeting_note(root, "28-08-26-back-to-back",
                      date="2026-08-28T15:00", duration=60,
                      recording_id="plaud:abc123")
    result = seenevents.triage(root, [listing_event()], NOW,
                              collide=True, utc_offset="+00:00")
    assert result["duplicate"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]


def test_collide_no_end_listing_entry_stays_in_fetch(tmp_path):
    """Fix wave 2, IMPORTANT: a listing entry with no `end` falls back to
    `end = start` (occurrence duration 0), which `syncjob.collide` floors
    to a 1-minute window — and a 1-minute window's own strong-match
    threshold is ceil(1/2) == 1, so a single overlapping minute trivially
    satisfies it. Without a guard this auto-skips on a fabricated window
    that was never a real duration in the first place; it must stay in
    `fetch` and let the write-time net (which sees a real payload duration)
    decide instead."""
    root = make_vault(tmp_path)
    make_meeting_note(root, "28-08-26-weekly-sync",
                      date="2026-08-28T14:00", duration=60,
                      recording_id="plaud:abc123")
    no_end_event = {
        "id": "AAMkAGId1", "subject": "Weekly sync",
        "start": {"dateTime": "2026-08-28T14:00:00.0000000",
                  "timeZone": "UTC"},
    }
    result = seenevents.triage(root, [no_end_event], NOW,
                              collide=True, utc_offset="+00:00")
    assert result["duplicate"] == []
    assert [e["reason"] for e in result["fetch"]] == ["unseen"]


def test_collide_preload_warnings_reach_triage(tmp_path):
    """PR #216 review: load_collide_notes' own warnings (an unparseable
    20-meetings/*.md file) were silently dropped — collide() starts from
    warnings=[] when notes is pre-injected, and _collide_duplicate never
    reads result["warnings"], so nothing ever surfaced them to the caller
    under --collide. triage() must fold them into its own warnings list."""
    root = make_vault(tmp_path)
    (root / "20-meetings" / "broken.md").write_text("---\n: not yaml\n",
                                                    encoding="utf-8")
    result = seenevents.triage(root, [listing_event()], NOW,
                              collide=True, utc_offset="+00:00")
    assert any("broken.md" in w for w in result["warnings"])


def test_collide_preload_warnings_appear_once_per_triage_call(tmp_path):
    """Even with multiple fetch survivors in one triage call (each of which
    would otherwise trigger its own collide() call), the preload warning
    must appear exactly once — it is a property of the vault's
    20-meetings/ folder, not of any one candidate."""
    root = make_vault(tmp_path)
    (root / "20-meetings" / "broken.md").write_text("---\n: not yaml\n",
                                                    encoding="utf-8")
    ev1 = listing_event(event_id="AAMkAGId1",
                        start="2026-08-28T10:00:00.0000000",
                        end="2026-08-28T11:00:00.0000000")
    ev2 = listing_event(event_id="AAMkAGId2",
                        start="2026-08-28T12:00:00.0000000",
                        end="2026-08-28T13:00:00.0000000")
    result = seenevents.triage(root, [ev1, ev2], NOW,
                              collide=True, utc_offset="+00:00")
    matching = [w for w in result["warnings"] if "broken.md" in w]
    assert len(matching) == 1


def test_collide_loads_notes_once_and_reuses_them_across_candidates(
        tmp_path, monkeypatch
):
    """Fix round 1, MINOR 6: collide used to re-glob 20-meetings/ per
    candidate; triage --collide must load once and pass `notes=` through."""
    root = make_vault(tmp_path)
    make_meeting_note(root, "28-08-26-weekly-sync",
                      date="2026-08-28T14:00", duration=60,
                      recording_id="plaud:abc123")
    calls = {"load": 0, "notes_passed": []}
    real_load = syncjob.load_collide_notes
    real_collide = syncjob.collide

    def counting_load(root_arg):
        calls["load"] += 1
        return real_load(root_arg)

    def spying_collide(root_arg, start, duration, *, notes=None):
        calls["notes_passed"].append(notes is not None)
        return real_collide(root_arg, start, duration, notes=notes)

    monkeypatch.setattr(syncjob, "load_collide_notes", counting_load)
    monkeypatch.setattr(syncjob, "collide", spying_collide)

    ev1 = listing_event(event_id="AAMkAGId1",
                        start="2026-08-28T10:00:00.0000000",
                        end="2026-08-28T11:00:00.0000000")
    ev2 = listing_event(event_id="AAMkAGId2",
                        start="2026-08-28T12:00:00.0000000",
                        end="2026-08-28T13:00:00.0000000")
    seenevents.triage(root, [ev1, ev2], NOW, collide=True, utc_offset="+00:00")
    assert calls["load"] == 1
    assert calls["notes_passed"] == [True, True]


def test_collide_duplicate_settles_as_skipped_and_filters_next_run(tmp_path):
    root = make_vault(tmp_path)
    make_meeting_note(root, "28-08-26-weekly-sync",
                      date="2026-08-28T14:00", duration=60,
                      recording_id="plaud:abc123")
    result = seenevents.triage(root, [listing_event()], NOW,
                              collide=True, utc_offset="+00:00")
    dup = result["duplicate"][0]
    seenevents.record(root, [{
        "id": dup["id"], "start_utc": dup["start_utc"], "outcome": "skipped",
    }], NOW)
    again = seenevents.triage(root, [listing_event()], NOW,
                              collide=True, utc_offset="+00:00")
    assert again["fetch"] == []
    assert again["duplicate"] == []
    assert again["filtered"]["skipped"] == 1


# ---------------------------------------------------------------------------
# A4: seenevents.settle_duplicate — the one CLI verb `sync settle-duplicate`
# calls, for the unattended path: writes the skip-list line (via
# `syncjob.skip`) and, when the underlying m365 occurrence is known, the
# seen-events `skipped` entry too. Validated before the first write, then
# the two writes happen in order, skip line first — the "two writes that
# must not come apart" shape `syncjob.park` set the precedent for.


def test_settle_duplicate_writes_the_skip_list_line(tmp_path):
    root = make_vault(tmp_path)
    result = seenevents.settle_duplicate(
        root, "m365:aaaa111122223333", "plaud:abc123",
        "28-08-26-weekly-sync")
    assert result["recording_id"] == "m365:aaaa111122223333"
    assert result["reason"] == (
        "same meeting already synced as plaud:abc123 "
        "(28-08-26-weekly-sync)")
    assert syncjob.read_skip_records(root) == [{
        "recording_id": "m365:aaaa111122223333",
        "reason": result["reason"], "source_name": None,
    }]
    assert result["seen_events_recorded"] is False


def test_settle_duplicate_also_banks_the_seen_events_entry_when_known(
        tmp_path):
    root = make_vault(tmp_path)
    result = seenevents.settle_duplicate(
        root, "m365:aaaa111122223333", "plaud:abc123",
        "28-08-26-weekly-sync",
        event_id="AAMkAGId1", start_utc="2026-08-28T14:00:00", now_utc=NOW)
    assert result["seen_events_recorded"] is True
    assert "m365:aaaa111122223333" in syncjob.read_skip_list(root)
    # the same occurrence now filters at triage, unattended, no --collide
    # needed: the skip-list line alone would not do that, only the cache
    # entry does.
    triaged = seenevents.triage(
        root, [listing_event(event_id="AAMkAGId1",
                             start="2026-08-28T14:00:00.0000000",
                             end="2026-08-28T15:00:00.0000000")], NOW)
    assert triaged["fetch"] == []
    assert triaged["filtered"]["skipped"] == 1


def test_settle_duplicate_requires_both_event_keys_or_neither(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(seenevents.SeenEventsError,
                       match="travel together"):
        seenevents.settle_duplicate(
            root, "m365:aaaa111122223333", "plaud:abc123",
            "28-08-26-weekly-sync", event_id="AAMkAGId1")
    with pytest.raises(seenevents.SeenEventsError,
                       match="travel together"):
        seenevents.settle_duplicate(
            root, "m365:aaaa111122223333", "plaud:abc123",
            "28-08-26-weekly-sync", start_utc="2026-08-28T14:00:00")


def test_settle_duplicate_is_idempotent_on_the_skip_list(tmp_path):
    root = make_vault(tmp_path)
    seenevents.settle_duplicate(
        root, "m365:aaaa111122223333", "plaud:abc123",
        "28-08-26-weekly-sync")
    result = seenevents.settle_duplicate(
        root, "m365:aaaa111122223333", "plaud:abc123",
        "28-08-26-weekly-sync")
    assert result["already_present"] is True
    assert len(syncjob.read_skip_records(root)) == 1


# Fix round 1, MINOR 2: settle_duplicate wrote the skip-list line first and
# only validated the seen-events entry afterward — a malformed start_utc
# left the skip-list line written but the seen-events entry never banked,
# the two ledgers out of sync. Validate before either write.


def test_settle_duplicate_validates_before_writing_the_skip_list_line(
        tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(seenevents.SeenEventsError):
        seenevents.settle_duplicate(
            root, "m365:aaaa111122223333", "plaud:abc123",
            "28-08-26-weekly-sync",
            event_id="AAMkAGId1", start_utc="not-a-date")
    assert syncjob.read_skip_records(root) == []


# ---------------------------------------------------------------------------
# Fix wave 2, IMPORTANT: sync unskip alone leaves a worker-settled m365
# duplicate's seen-events entry in place, permanently filtering the
# occurrence out of every future triage. seenevents.unsettle_duplicate
# reverses both writes settle_duplicate made — the undo `sync
# unsettle-duplicate` needs.


def test_unsettle_duplicate_removes_the_skip_list_line(tmp_path):
    root = make_vault(tmp_path)
    seenevents.settle_duplicate(
        root, "plaud:aaaa111122223333", "plaud:abc123",
        "28-08-26-weekly-sync")
    result = seenevents.unsettle_duplicate(root, "plaud:aaaa111122223333")
    assert result == {"recording_id": "plaud:aaaa111122223333",
                      "removed": True, "forgot": False, "reason": None}
    assert syncjob.read_skip_list(root) == set()


def test_unsettle_duplicate_also_forgets_the_seen_events_entry(tmp_path):
    root = make_vault(tmp_path)
    seenevents.settle_duplicate(
        root, "m365:aaaa111122223333", "plaud:abc123",
        "28-08-26-weekly-sync",
        event_id="AAMkAGId1", start_utc="2026-08-28T14:00:00", now_utc=NOW)
    result = seenevents.unsettle_duplicate(
        root, "m365:aaaa111122223333",
        event_id="AAMkAGId1", start_utc="2026-08-28T14:00:00")
    assert result["removed"] is True
    assert result["forgot"] is True
    assert syncjob.read_skip_list(root) == set()
    # the occurrence is fetchable again, both ledgers cleared
    triaged = seenevents.triage(
        root, [listing_event(event_id="AAMkAGId1",
                             start="2026-08-28T14:00:00.0000000",
                             end="2026-08-28T15:00:00.0000000")], NOW)
    assert [e["reason"] for e in triaged["fetch"]] == ["unseen"]


def test_unsettle_duplicate_tolerates_a_missing_seen_events_entry(tmp_path):
    """The occurrence may have already aged out of the cache's own 30-day
    retention — that must not stop the skip-list line from being removed,
    only report honestly that there was nothing left to forget."""
    root = make_vault(tmp_path)
    seenevents.settle_duplicate(
        root, "m365:aaaa111122223333", "plaud:abc123",
        "28-08-26-weekly-sync")  # no event_id/start_utc -> no cache entry
    result = seenevents.unsettle_duplicate(
        root, "m365:aaaa111122223333",
        event_id="AAMkAGId1", start_utc="2026-08-28T14:00:00")
    assert result["removed"] is True
    assert result["forgot"] is False
    assert result["reason"] is None
    assert syncjob.read_skip_list(root) == set()


def test_unsettle_duplicate_refuses_to_forget_a_non_skipped_entry(tmp_path):
    """forget_event deletes regardless of outcome, so a caller passing
    mismatched event keys (a typo, or a stale id) could otherwise drop some
    other occurrence's `written`/`no-transcript`/etc. entry. unsettle_
    duplicate must check the outcome first and refuse to touch anything
    that isn't the `skipped` entry it itself is supposed to be undoing."""
    root = make_vault(tmp_path)
    seenevents.settle_duplicate(
        root, "m365:aaaa111122223333", "plaud:abc123",
        "28-08-26-weekly-sync")  # no event keys -> no seen-events entry
    # a real, unrelated occurrence recorded as written
    seenevents.record(root, [{
        "id": "AAMkAGId1", "start_utc": "2026-08-28T14:00:00",
        "outcome": "written", "recording_id": "m365:0123456789abcdef",
    }], NOW)
    result = seenevents.unsettle_duplicate(
        root, "m365:aaaa111122223333",
        event_id="AAMkAGId1", start_utc="2026-08-28T14:00:00")
    assert result["removed"] is True  # the skip-list line still comes off
    assert result["forgot"] is False
    assert result["reason"] == "outcome is written, not skipped"
    # the unrelated written entry survives untouched
    cache = json.loads(
        (root / seenevents.CACHE_RELPATH).read_text(encoding="utf-8"))
    assert cache["events"]["AAMkAGId1|2026-08-28T14:00:00"]["outcome"] == \
        "written"


def test_unsettle_duplicate_normalizes_a_padded_event_id_the_guard_lookup(
        tmp_path):
    """PR #216 review: the guard used to build its lookup key from the raw
    event_id while forget_event normalizes with str(event_id or "").strip()
    before building its own — a padded --event-id (whitespace the CLI
    passes through verbatim, no type= stripping) made the guard's own
    lookup miss the real entry (cached=None -> outcome=None), fall through
    to the "else" branch, and call forget_event unconditionally — which
    normalizes internally, finds the real entry, and deletes it, silently
    bypassing the non-skipped refusal this function's docstring promises."""
    root = make_vault(tmp_path)
    seenevents.record(root, [{
        "id": "AAMkAGId1", "start_utc": "2026-08-28T14:00:00",
        "outcome": "written", "recording_id": "m365:0123456789abcdef",
    }], NOW)
    seenevents.settle_duplicate(
        root, "m365:aaaa111122223333", "plaud:abc123",
        "28-08-26-weekly-sync")  # no event keys -> nothing new cached
    result = seenevents.unsettle_duplicate(
        root, "m365:aaaa111122223333",
        event_id="AAMkAGId1 ", start_utc="2026-08-28T14:00:00")  # padded
    assert result["forgot"] is False
    assert result["reason"] == "outcome is written, not skipped"
    cache = json.loads(
        (root / seenevents.CACHE_RELPATH).read_text(encoding="utf-8"))
    assert cache["events"]["AAMkAGId1|2026-08-28T14:00:00"]["outcome"] == \
        "written"


def test_settle_and_unsettle_duplicate_agree_on_a_padded_event_id(tmp_path):
    """The normal (non-adversarial) case: settle_duplicate and
    unsettle_duplicate must land on the same cache key regardless of which
    side (if either) receives incidental whitespace in --event-id."""
    root = make_vault(tmp_path)
    seenevents.settle_duplicate(
        root, "m365:aaaa111122223333", "plaud:abc123",
        "28-08-26-weekly-sync",
        event_id=" AAMkAGId1", start_utc="2026-08-28T14:00:00", now_utc=NOW)
    result = seenevents.unsettle_duplicate(
        root, "m365:aaaa111122223333",
        event_id="AAMkAGId1 ", start_utc="2026-08-28T14:00:00")
    assert result["forgot"] is True
    assert result["reason"] is None


def test_unsettle_duplicate_refuses_an_id_not_on_the_skip_list(tmp_path):
    # syncjob.unskip's own refusal propagates unconverted — the same
    # pattern settle_duplicate already uses for syncjob.skip's own errors.
    root = make_vault(tmp_path)
    with pytest.raises(syncjob.SyncError, match="not on the skip list"):
        seenevents.unsettle_duplicate(root, "m365:neverskipped")


def test_unsettle_duplicate_requires_both_event_keys_or_neither(tmp_path):
    root = make_vault(tmp_path)
    seenevents.settle_duplicate(
        root, "m365:aaaa111122223333", "plaud:abc123",
        "28-08-26-weekly-sync")
    with pytest.raises(seenevents.SeenEventsError, match="travel together"):
        seenevents.unsettle_duplicate(
            root, "m365:aaaa111122223333", event_id="AAMkAGId1")
    with pytest.raises(seenevents.SeenEventsError, match="travel together"):
        seenevents.unsettle_duplicate(
            root, "m365:aaaa111122223333", start_utc="2026-08-28T14:00:00")


def test_a_malformed_outcome_without_a_start_still_fails(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(seenevents.SeenEventsError):
        seenevents.record(root, [{"id": "AAMkAGId3", "outcome": "written"}], NOW)
