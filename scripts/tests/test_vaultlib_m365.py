"""m365 adapter: id derivation and reassembly of connector JSON.

The shapes here are the lab-verified M365 connector responses (2026-08-25):
a full calendar event read carrying meetingTranscriptUrl, and a transcript
read whose content is VTT-like cue text without speaker attribution (the
tenant toggle), with the attributed <v> form covered for when it flips on.
"""
import json
from urllib.parse import unquote

import pytest

from vaultlib import m365

TOKEN = "aHR0cHM6Ly9leGFtcGxl"
URL = f"meeting-transcript:///events/{TOKEN}"
SCOPED_URL = f"{URL}?start=2026-08-25T14%3A00%3A00.0000000Z&end=2026-08-25T15%3A00%3A00.0000000Z"

EVENT = {
    "subject": "Kennismaking & sync AI",
    "organizer": {"name": "Michael B", "address": "m@example.com"},
    "attendees": [{"name": "J T", "address": "j@client.com", "type": "required"}],
    "start": {"dateTime": "2026-08-25T14:00:00.0000000", "timeZone": "UTC"},
    "end": {"dateTime": "2026-08-25T15:00:00.0000000", "timeZone": "UTC"},
    "recurrence": None,
    "meetingTranscriptUrl": SCOPED_URL,
}

CONTENT = (
    "00:01:14.585 --> 00:01:15.265\r\n"
    "Goeiemiddag.\r\n"
    "\r\n"
    "00:01:15.945 --> 00:01:17.225\r\n"
    "Alles goed?\r\n"
    "\r\n"
    "00:02:03.985 --> 00:02:05.625\r\n"
    "Alles goed?\r\n"
    "\r\n"
    "00:45:00.000 --> 00:46:30.500\r\n"
    "Tot de volgende keer.\r\n"
)

TRANSCRIPT = {
    "meeting": {"id": "MSo...", "subject": "Kennismaking & sync AI"},
    "transcripts": [{
        "id": "t-1",
        "createdDateTime": "2026-08-25T14:01:19.9993155Z",
        "endDateTime": "2026-08-25T15:05:01.7993155Z",
        "content": CONTENT,
        "speakerAttribution": False,
    }],
}


def write_json(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_derive_id_is_stable_when_query_params_change():
    """The connector may add or drop ?start/&end; the id must not care."""
    scoped = m365.derive_id(EVENT)
    unscoped = m365.derive_id({**EVENT, "meetingTranscriptUrl": URL})
    assert scoped["recording_id"] == unscoped["recording_id"]
    prefix, _, tail = scoped["recording_id"].partition(":")
    assert prefix == "m365"
    assert len(tail) == 16 and all(c in "0123456789abcdef" for c in tail)
    # the fetch URL itself stays verbatim — never rebuilt
    assert scoped["transcript_url"] == SCOPED_URL


def test_two_occurrences_of_a_series_get_different_ids():
    other = {**EVENT, "start": {"dateTime": "2026-09-01T14:00:00.0000000",
                                "timeZone": "UTC"}}
    assert m365.derive_id(EVENT)["recording_id"] != m365.derive_id(other)["recording_id"]


def test_ids_batch_skips_events_without_a_transcript_url():
    """Most calendar events have no transcript; that is a skip, not an error."""
    bare = {"subject": "Focus time", "start": EVENT["start"]}
    result = m365.ids([EVENT, bare])
    assert len(result["ids"]) == 1
    assert result["skipped"] == [{"subject": "Focus time",
                                  "reason": "no-transcript-url"}]


def test_ids_rejects_a_non_array_payload():
    with pytest.raises(m365.M365Error, match="JSON array"):
        m365.ids({"value": []})


# --- ids gains optional --timezone/--utc-offset (A3's CLI half): the owner-
# local recorded timestamp and the event's own span, so `sync collide` can
# run before any transcript fetch. Omitted entirely when neither is passed —
# id-only callers (the worker contract's step-2 invocation before this PR)
# see no shape change at all.


def test_ids_omits_recorded_local_and_duration_without_timezone_or_offset():
    result = m365.ids([EVENT])
    assert "recorded_local" not in result["ids"][0]
    assert "event_duration_min" not in result["ids"][0]


def test_ids_adds_recorded_local_and_duration_with_utc_offset():
    result = m365.ids([EVENT], utc_offset="+02:00")
    assert result["ids"][0]["recorded_local"] == "2026-08-25T16:00"
    assert result["ids"][0]["event_duration_min"] == 60


def test_ids_adds_recorded_local_and_duration_with_timezone():
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Brussels")
    except Exception:
        pytest.skip("no tz database on host")
    result = m365.ids([EVENT], timezone="Europe/Brussels")
    assert result["ids"][0]["recorded_local"] == "2026-08-25T16:00"
    assert result["ids"][0]["event_duration_min"] == 60


def test_ids_duration_absent_without_an_event_end():
    event = {k: v for k, v in EVENT.items() if k != "end"}
    result = m365.ids([event], utc_offset="+02:00")
    assert result["ids"][0]["recorded_local"] == "2026-08-25T16:00"
    assert "event_duration_min" not in result["ids"][0]


def test_ids_event_duration_min_rounds_not_floors():
    """Fix round 1, MINOR 3: event_duration_min must share dates.py's
    round()-semantics helper with sync collide's occurrence duration —
    a floor here would silently disagree with collide's own rounding."""
    event = {**EVENT, "end": {"dateTime": "2026-08-25T14:40:31.0000000",
                              "timeZone": "UTC"}}
    result = m365.ids([event], utc_offset="+02:00")
    # 40 min 31 sec = 40.5166... min -> rounds to 41, a floor would say 40.
    assert result["ids"][0]["event_duration_min"] == 41


def test_ids_skipped_entries_are_unaffected_by_timezone():
    bare = {"subject": "Focus time", "start": EVENT["start"]}
    result = m365.ids([EVENT, bare], utc_offset="+02:00")
    assert result["skipped"] == [{"subject": "Focus time",
                                  "reason": "no-transcript-url"}]


def test_a_malformed_transcript_url_raises():
    with pytest.raises(m365.M365Error, match="does not start with"):
        m365.derive_id({**EVENT, "meetingTranscriptUrl": "https://graph/x"})


def test_a_non_utc_event_start_is_refused_not_guessed():
    event = {**EVENT, "start": {"dateTime": "2026-08-25T16:00:00",
                                "timeZone": "Romance Standard Time"}}
    with pytest.raises(m365.M365Error, match="is not UTC"):
        m365.derive_id(event)


def test_a_non_utc_event_end_is_refused_not_guessed():
    """end.timeZone must be checked exactly as symmetrically as
    start.timeZone — a non-UTC end used to be parsed as if it were UTC,
    which would silently mis-window a recurring series' transcript filter
    and the duration fallbacks derived from the same span."""
    event = {**EVENT, "end": {"dateTime": "2026-08-25T17:00:00",
                              "timeZone": "Romance Standard Time"}}
    with pytest.raises(m365.M365Error, match="end.timeZone.*is not UTC"):
        m365.ids([event], utc_offset="+02:00")


def test_a_non_utc_event_end_is_refused_with_no_timezone_flags_at_all():
    """PR #217 review finding: `_event_end` used to be reachable only
    through `_event_duration_min`, which `ids()` calls only when
    `timezone`/`utc_offset` is supplied — the probe's own `m365 ids` call
    passes neither, so a malformed end passed through silently until a
    Sonnet worker re-derived ids later, after the expensive dispatch this
    PR exists to avoid. Validation must not depend on an optional flag."""
    event = {**EVENT, "end": {"dateTime": "2026-08-25T17:00:00",
                              "timeZone": "Romance Standard Time"}}
    with pytest.raises(m365.M365Error, match="end.timeZone.*is not UTC"):
        m365.ids([event])
    with pytest.raises(m365.M365Error, match="end.timeZone.*is not UTC"):
        m365.derive_id(event)


def test_ids_with_no_timezone_flags_still_derives_an_event_with_no_end():
    """The fix for the above must not make `end` a required key — an
    event with no `end` at all (never mind a malformed one) still derives
    an id with no flags supplied."""
    event = {k: v for k, v in EVENT.items() if k != "end"}
    result = m365.ids([event])
    assert result["ids"][0]["recording_id"] == m365.derive_id(event)["recording_id"]
    assert "event_duration_min" not in result["ids"][0]


def test_event_missing_start_datetime_is_refused_plainly():
    event = {k: v for k, v in EVENT.items() if k != "start"}
    with pytest.raises(m365.M365Error, match="missing start.dateTime"):
        m365.derive_id(event)


def test_graph_seven_digit_fractional_seconds_parse():
    """Graph emits 7 fractional digits; 3.10's fromisoformat takes at most 6."""
    parsed = m365._parse_graph_dt("2026-08-25T09:00:00.5558195Z", "x")
    assert parsed.year == 2026 and parsed.microsecond == 555819


def test_reassemble_renders_unattributed_cues_without_invented_speakers(tmp_path):
    """No attribution means bare lines — attendees come from the calendar,
    never from a guessed 'Speaker ?' label."""
    result = m365.reassemble(write_json(tmp_path, "e.json", EVENT),
                             write_json(tmp_path, "t.json", TRANSCRIPT),
                             str(tmp_path), utc_offset="+02:00")
    blob = (tmp_path / f"{result['recording_id'].split(':')[1]}.blob.md").read_text(
        encoding="utf-8")
    assert blob.startswith("Kennismaking & sync AI\n\n> Recorded: 2026-08-25T16:00\n\n#Transcript\n")
    assert "Goeiemiddag.\nAlles goed?" in blob
    assert "Speaker" not in blob
    assert result["has_enrichment"] is False


def test_reassemble_renders_attributed_v_tags_as_speaker_lines(tmp_path):
    attributed = ("00:00:03.000 --> 00:00:05.000\r\n"
                  "<v Michael B>Goeiemiddag.</v>\r\n"
                  "\r\n"
                  "00:00:06.000 --> 00:00:08.000\r\n"
                  "<v J T>Dag Michael.</v>\r\n")
    transcript = {"transcripts": [{**TRANSCRIPT["transcripts"][0],
                                   "content": attributed,
                                   "speakerAttribution": True}]}
    result = m365.reassemble(write_json(tmp_path, "e.json", EVENT),
                             write_json(tmp_path, "t.json", transcript),
                             str(tmp_path), utc_offset="+02:00")
    blob = (tmp_path / f"{result['recording_id'].split(':')[1]}.blob.md").read_text(
        encoding="utf-8")
    assert "Michael B: Goeiemiddag." in blob
    assert "J T: Dag Michael." in blob


def test_crlf_content_and_rolling_duplicate_cues_collapse(tmp_path):
    rolling = ("00:00:01.000 --> 00:00:02.000\r\n"
               "Zelfde zin.\r\n"
               "\r\n"
               "00:00:02.000 --> 00:00:03.000\r\n"
               "Zelfde zin.\r\n")
    cues, _ = m365._parse_vtt(rolling, "t")
    assert cues == [(None, "Zelfde zin.")]


def test_webvtt_header_and_note_blocks_are_ignored():
    content = ("WEBVTT\n\nNOTE confidence low\n\n"
               "00:00:01.000 --> 00:00:02.000\nEcht iets.\n")
    cues, end_ms = m365._parse_vtt(content, "t")
    assert cues == [(None, "Echt iets.")]
    assert end_ms == 2000


def test_multiple_transcripts_concatenate_in_created_order(tmp_path):
    second = {**TRANSCRIPT["transcripts"][0], "id": "t-2",
              "createdDateTime": "2026-08-25T14:40:00Z",
              "content": "00:00:01.000 --> 00:00:02.000\r\nDeel twee.\r\n"}
    first = {**TRANSCRIPT["transcripts"][0], "id": "t-1",
             "createdDateTime": "2026-08-25T14:05:00Z",
             "content": "00:00:01.000 --> 00:00:02.000\r\nDeel een.\r\n"}
    transcript = {"transcripts": [second, first]}
    result = m365.reassemble(write_json(tmp_path, "e.json", EVENT),
                             write_json(tmp_path, "t.json", transcript),
                             str(tmp_path), utc_offset="+02:00")
    blob = (tmp_path / f"{result['recording_id'].split(':')[1]}.blob.md").read_text(
        encoding="utf-8")
    assert blob.index("Deel een.") < blob.index("Deel twee.")


def test_transcripts_from_other_occurrences_are_filtered_out(tmp_path):
    """An unscoped series URL may return last week's transcript alongside
    this occurrence's — filing those here would falsify the note."""
    stale = {**TRANSCRIPT["transcripts"][0], "id": "t-old",
             "createdDateTime": "2026-08-18T14:01:00Z",
             "content": "00:00:01.000 --> 00:00:02.000\r\nVorige week.\r\n"}
    transcript = {"transcripts": [TRANSCRIPT["transcripts"][0], stale]}
    result = m365.reassemble(write_json(tmp_path, "e.json", EVENT),
                             write_json(tmp_path, "t.json", transcript),
                             str(tmp_path), utc_offset="+02:00")
    blob = (tmp_path / f"{result['recording_id'].split(':')[1]}.blob.md").read_text(
        encoding="utf-8")
    assert "Vorige week." not in blob
    assert "Goeiemiddag." in blob


def test_all_transcripts_outside_the_occurrence_is_an_error(tmp_path):
    stale = {**TRANSCRIPT["transcripts"][0], "id": "t-old",
             "createdDateTime": "2026-08-18T14:01:00Z"}
    staler = {**stale, "id": "t-older", "createdDateTime": "2026-08-11T14:01:00Z"}
    transcript = {"transcripts": [stale, staler]}
    with pytest.raises(m365.M365Error, match="other occurrences"):
        m365.reassemble(write_json(tmp_path, "e.json", EVENT),
                        write_json(tmp_path, "t.json", transcript),
                        str(tmp_path), utc_offset="+02:00")


def test_duration_comes_from_cue_ends_with_metadata_and_event_fallbacks(tmp_path):
    # (1) cue ends win: CONTENT's last cue ends at 46m30.5s -> 47 min
    result = m365.reassemble(write_json(tmp_path, "e.json", EVENT),
                             write_json(tmp_path, "t.json", TRANSCRIPT),
                             str(tmp_path), utc_offset="+02:00")
    assert result["duration_min"] == 47
    # (2) no cues cannot happen (no-cue content raises), so metadata is
    # exercised via the event fallback: strip end metadata, zero-length cue
    zero = {**TRANSCRIPT["transcripts"][0], "endDateTime": None,
            "content": "00:00:00.000 --> 00:00:00.000\r\nx\r\n"}
    result = m365.reassemble(write_json(tmp_path, "e2.json", EVENT),
                             write_json(tmp_path, "t2.json", {"transcripts": [zero]}),
                             str(tmp_path), utc_offset="+02:00")
    assert result["duration_min"] == 60  # event span 14:00->15:00


def test_transcript_metadata_span_is_the_second_fallback(tmp_path):
    zero_cue = {**TRANSCRIPT["transcripts"][0],
                "content": "00:00:00.000 --> 00:00:00.000\r\nx\r\n"}
    event = {k: v for k, v in EVENT.items() if k != "end"}
    result = m365.reassemble(write_json(tmp_path, "e.json", event),
                             write_json(tmp_path, "t.json",
                                        {"transcripts": [zero_cue]}),
                             str(tmp_path), utc_offset="+02:00")
    assert result["duration_min"] == 64  # 14:01:19 -> 15:05:01
    assert result["recorded_local"] == "2026-08-25T16:00"


def test_recorded_local_comes_from_the_event_start_not_the_transcript(tmp_path):
    """The calendar is the source of when the meeting was; a transcript can
    start late."""
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Brussels")
    except Exception:
        pytest.skip("no tz database on host")
    result = m365.reassemble(write_json(tmp_path, "e.json", EVENT),
                             write_json(tmp_path, "t.json", TRANSCRIPT),
                             str(tmp_path), timezone="Europe/Brussels")
    assert result["recorded_local"] == "2026-08-25T16:00"


def test_reassemble_id_matches_derive_id_for_the_same_event(tmp_path):
    """The dedup gate keys on ids derived before the fetch; reassemble must
    reproduce them exactly or the ledger silently forks."""
    result = m365.reassemble(write_json(tmp_path, "e.json", EVENT),
                             write_json(tmp_path, "t.json", TRANSCRIPT),
                             str(tmp_path), utc_offset="+02:00")
    assert result["recording_id"] == m365.derive_id(EVENT)["recording_id"]


def test_empty_transcripts_list_raises_with_the_skip_hint(tmp_path):
    with pytest.raises(m365.M365Error, match="skip line"):
        m365.reassemble(write_json(tmp_path, "e.json", EVENT),
                        write_json(tmp_path, "t.json", {"transcripts": []}),
                        str(tmp_path), utc_offset="+02:00")


def test_content_with_no_cues_raises(tmp_path):
    transcript = {"transcripts": [{**TRANSCRIPT["transcripts"][0],
                                   "content": "WEBVTT\n\nNOTE nothing\n"}]}
    with pytest.raises(m365.M365Error, match="no VTT cues"):
        m365.reassemble(write_json(tmp_path, "e.json", EVENT),
                        write_json(tmp_path, "t.json", transcript),
                        str(tmp_path), utc_offset="+02:00")


def test_an_event_missing_its_transcript_url_is_not_reassemblable(tmp_path):
    event = {k: v for k, v in EVENT.items() if k != "meetingTranscriptUrl"}
    with pytest.raises(m365.M365Error, match="missing meetingTranscriptUrl"):
        m365.reassemble(write_json(tmp_path, "e.json", event),
                        write_json(tmp_path, "t.json", TRANSCRIPT),
                        str(tmp_path), utc_offset="+02:00")


def test_an_event_missing_start_datetime_is_not_reassemblable(tmp_path):
    event = {k: v for k, v in EVENT.items() if k != "start"}
    with pytest.raises(m365.M365Error, match="missing start.dateTime"):
        m365.reassemble(write_json(tmp_path, "e.json", event),
                        write_json(tmp_path, "t.json", TRANSCRIPT),
                        str(tmp_path), utc_offset="+02:00")


# --- trimmed event: the scratch event file the probe/worker write now keeps
# only id, subject, start, end, meetingTranscriptUrl, organizer, attendees
# (each name/address/type) — everything else (body, location, recurrence,
# onlineMeeting, webLink, @odata.*, ...) is dropped before it ever reaches
# scratch. ids/reassemble must round-trip on exactly that shape.

TRIMMED_EVENT = {
    "id": "AAMkAGId1",
    "subject": "Kennismaking & sync AI",
    "start": {"dateTime": "2026-08-25T14:00:00.0000000", "timeZone": "UTC"},
    "end": {"dateTime": "2026-08-25T15:00:00.0000000", "timeZone": "UTC"},
    "meetingTranscriptUrl": SCOPED_URL,
    "organizer": {"name": "Michael B", "address": "m@example.com"},
    "attendees": [{"name": "J T", "address": "j@client.com", "type": "required"}],
}


def test_trimmed_event_with_only_the_kept_keys_round_trips(tmp_path):
    assert set(TRIMMED_EVENT) == {
        "id", "subject", "start", "end", "meetingTranscriptUrl",
        "organizer", "attendees"}
    result = m365.reassemble(write_json(tmp_path, "e.json", TRIMMED_EVENT),
                             write_json(tmp_path, "t.json", TRANSCRIPT),
                             str(tmp_path), utc_offset="+02:00")
    assert result["recording_id"] == m365.derive_id(TRIMMED_EVENT)["recording_id"]
    assert result["duration_min"] == 47
    assert result["recorded_local"] == "2026-08-25T16:00"


# --- event_uri: the URI is derived, never retyped -------------------------
#
# The live failure this exists for (issue #205): the orchestrator built
# m365_routing.json's `uri` by reversing the id's URL-safe substitution and
# percent-encoding the result by hand, so every `-` became `%2F`. The
# connector then decoded that back to a raw `/` and spliced it into the Graph
# path unencoded — 400 RequestBroker--ParseUri, every run, for as long as the
# re-encoding kept happening. The ids were copied byte-perfectly at every
# hop; only the value a model had to *transform* came out wrong. So the
# transform moves here.
#
# Outlook's variant is NOT RFC 4648 base64url. Measured against paired
# uri/webLink values from one mailbox, the id's `-` corresponds to `/` and
# its `_` to `+` — the inverse of base64url's substitution. These constants
# carry both characters so a future "correction" to the RFC mapping fails
# here rather than in a client vault.

URLSAFE_ID = "AAkALgAAAAAAHYQDEapmEc2byACqAC-EWg0A0ceR5yDk4k28EdzA-CuLTw_AA"
PADDED_ID = "AAkBOQAICN8ThXOLgAAuAAAAAB2EAxGqZhHNm8gAqgAvxFoNANHHkecg5OA6-ftpYAABA="


def test_event_uri_leaves_a_base64url_id_alone():
    assert m365.event_uri(URLSAFE_ID) == (
        f"calendar:///events/{URLSAFE_ID}")


def test_event_uri_leaves_the_url_safe_substitutes_untouched():
    """The exact regression: `-` and `_` are unreserved, so neither may come
    back as `%2F` or `%2B` however the underlying base64 spells them."""
    uri = m365.event_uri(URLSAFE_ID)
    assert "%2F" not in uri and "%2B" not in uri
    assert uri.count("-") == URLSAFE_ID.count("-") >= 1
    assert uri.count("_") == URLSAFE_ID.count("_") >= 1


def test_event_uri_percent_encodes_the_padding():
    assert m365.event_uri(PADDED_ID) == (
        f"calendar:///events/{PADDED_ID[:-1]}%3D")


def test_event_uri_encodes_a_reserved_character_rather_than_passing_it_raw():
    """Defence in depth: the listing substitutes `/` and `+` away, but if an
    un-substituted id ever arrives, it must come out encoded — a raw `/` is
    exactly what Graph mis-reads as another path segment. Note this means
    `%2F` in a derived URI is not by itself proof of a hand-built one, which
    is why the worker contract keys its diagnostic on Graph's ParseUri code
    instead."""
    assert m365.event_uri("AA/BB+CC=") == (
        "calendar:///events/AA%2FBB%2BCC%3D")


@pytest.mark.parametrize("event_id", [URLSAFE_ID, PADDED_ID, "AA/BB+CC="])
def test_event_uri_round_trips_back_to_the_id(event_id):
    """The one invariant the connector cares about: decoding the path
    segment once returns the id the listing gave, byte for byte."""
    uri = m365.event_uri(event_id)
    assert unquote(uri[len("calendar:///events/"):]) == event_id


def test_event_uri_refuses_an_empty_or_non_string_id():
    for bad in ("", "   ", None, 17):
        with pytest.raises(m365.M365Error, match="event id"):
            m365.event_uri(bad)


# --- agenda: the calendar-prep listing rendered in the owner's local time ---
#
# Regression for the 2026-09-21 daily note: the connector answers every
# start as a UTC wall clock with timeZone "UTC", and the heading time used to
# be hand-copied from it. The agenda step owns filter, sort and conversion.

def _listing_event(subject, start, end=None, **extra):
    event = {
        "uri": f"calendar:///events/{subject[:3]}",
        "id": subject[:3],
        "subject": subject,
        "organizer": "org@example.com",
        "attendees": ["a@example.com"],
        "start": {"dateTime": start, "timeZone": "UTC"},
        "location": None,
        "showAs": "busy",
        "isAllDay": False,
        "isCancelled": False,
        "isOrganizer": False,
    }
    if end is not None:
        event["end"] = {"dateTime": end, "timeZone": "UTC"}
    event.update(extra)
    return event


def test_agenda_renders_local_start_and_end_and_sorts_by_start():
    events = [
        _listing_event("Later  ", "2026-09-21T12:00:00.0000000", "2026-09-21T13:30:00.0000000"),
        _listing_event("Check-in ", "2026-09-21T08:00:00.0000000", "2026-09-21T08:30:00.0000000"),
    ]
    result = m365.agenda(events, utc_offset="+02:00")
    assert [m["time"] for m in result["meetings"]] == ["10:00", "14:00"]
    first = result["meetings"][0]
    assert first["subject"] == "Check-in"
    assert first["end"] == "10:30"
    assert first["start_utc"] == "2026-09-21T08:00:00"
    assert first["start_local"] == "2026-09-21T10:00"
    assert first["organizer"] == "org@example.com"
    assert first["attendees"] == ["a@example.com"]
    assert first["uri"] == "calendar:///events/Che"
    assert result["dropped"] == {"all_day": 0, "cancelled": 0, "other_day": 0, "not_events": 0}


def test_agenda_with_timezone_name():
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Brussels")
    except Exception:
        pytest.skip("no tz database on host")
    events = [_listing_event("Winter", "2026-01-12T08:00:00.0000000"),
              _listing_event("Summer", "2026-09-21T08:00:00.0000000")]
    result = m365.agenda(events, timezone="Europe/Brussels")
    by_subject = {m["subject"]: m for m in result["meetings"]}
    assert by_subject["Winter"]["time"] == "09:00"
    assert by_subject["Summer"]["time"] == "10:00"
    assert by_subject["Winter"]["end"] is None


def test_agenda_drops_all_day_cancelled_and_other_days_with_counts():
    events = [
        _listing_event("Keep", "2026-09-21T08:00:00.0000000"),
        _listing_event("Holiday", "2026-09-21T00:00:00.0000000", isAllDay=True),
        _listing_event("Gone", "2026-09-21T09:00:00.0000000", isCancelled=True),
        # 23:00Z the evening before is 01:00 local on the 21st — kept.
        _listing_event("Late", "2026-09-20T23:00:00.0000000"),
        # 22:30Z on the 21st is 00:30 local on the 22nd — another day.
        _listing_event("Next", "2026-09-21T22:30:00.0000000"),
    ]
    result = m365.agenda(events, utc_offset="+02:00", date="2026-09-21")
    assert [m["subject"] for m in result["meetings"]] == ["Late", "Keep"]
    assert result["dropped"] == {"all_day": 1, "cancelled": 1, "other_day": 1, "not_events": 0}
    assert result["date"] == "2026-09-21"


def test_agenda_refuses_a_non_utc_listing():
    event = _listing_event("Odd", "2026-09-21T10:00:00.0000000")
    event["start"]["timeZone"] = "Romance Standard Time"
    with pytest.raises(m365.M365Error, match="not UTC"):
        m365.agenda([event], utc_offset="+02:00")


def test_agenda_requires_exactly_one_offset_source():
    with pytest.raises(Exception, match="exactly one"):
        m365.agenda([_listing_event("X", "2026-09-21T10:00:00.0000000")])


def test_agenda_rejects_a_bad_date_filter():
    with pytest.raises(m365.M365Error, match="YYYY-MM-DD"):
        m365.agenda([], utc_offset="+02:00", date="21/09/2026")


def test_load_listing_accepts_array_wrapper_and_concatenated_objects():
    a = _listing_event("A", "2026-09-21T08:00:00.0000000")
    b = _listing_event("B", "2026-09-21T09:00:00.0000000")
    marker = {"totalResultCount": 2}
    assert m365.load_listing(json.dumps([a, b])) == [a, b]
    assert m365.load_listing(json.dumps({"value": [a, b]})) == [a, b]
    # The connector's raw output: objects back to back, plus paging markers.
    raw = json.dumps(a) + json.dumps(b) + json.dumps(marker)
    assert m365.load_listing(raw) == [a, b, marker]
    raw_pages = json.dumps([a, marker]) + "\n" + json.dumps([b])
    assert m365.load_listing(raw_pages) == [a, marker, b]


def test_agenda_counts_paging_markers_as_not_events():
    events = [_listing_event("A", "2026-09-21T08:00:00.0000000"),
              {"nextOffset": 25}, {"totalResultCount": 26}]
    result = m365.agenda(events, utc_offset="+02:00")
    assert [m["subject"] for m in result["meetings"]] == ["A"]
    assert result["dropped"]["not_events"] == 2


def test_load_listing_refuses_garbage():
    with pytest.raises(m365.M365Error, match="calendar listing"):
        m365.load_listing("not json at all")
