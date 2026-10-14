"""m365 adapter: id derivation and reassembly of connector JSON.

The shapes here are the lab-verified M365 connector responses (2026-08-25):
a full calendar event read carrying meetingTranscriptUrl, and a transcript
read whose content is VTT-like cue text without speaker attribution (the
tenant toggle), with the attributed <v> form covered for when it flips on.
"""
import json
from urllib.parse import unquote

import pytest
from pathlib import Path

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


def _needs_tz_database():
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("Europe/Paris")
    except Exception:
        pytest.skip("no tz database on host")


# A mailbox with its own time zone set gets every start/end back as a wall
# clock in that zone, labelled with its Windows name — and all of them used
# to be refused, so neither Teams sync nor calendar prep ever ran for it.

def test_a_windows_zone_event_derives_the_same_id_as_its_utc_twin():
    _needs_tz_database()
    local = {**EVENT,
             "start": {"dateTime": "2026-08-25T16:00:00.0000000",
                       "timeZone": "Romance Standard Time"},
             "end": {"dateTime": "2026-08-25T17:00:00.0000000",
                     "timeZone": "Romance Standard Time"}}
    assert m365.derive_id(local) == m365.derive_id(EVENT)
    assert m365.ids([local], timezone="Europe/Brussels")["ids"][0][
        "recorded_local"] == "2026-08-25T16:00"


def test_an_iana_zone_label_converts_across_dst():
    _needs_tz_database()
    winter = {"dateTime": "2026-01-12T09:00:00", "timeZone": "Europe/Brussels"}
    summer = {"dateTime": "2026-08-25T09:00:00", "timeZone": "Europe/Brussels"}
    assert m365.graph_dt_utc(winter, "x").hour == 8
    assert m365.graph_dt_utc(summer, "x").hour == 7


def test_an_explicit_offset_on_the_datetime_wins_over_the_label():
    node = {"dateTime": "2026-08-25T14:00:00Z", "timeZone": "Pacific Standard Time"}
    assert m365.graph_dt_utc(node, "x").hour == 14


def test_an_unresolvable_event_start_zone_is_refused_not_guessed():
    event = {**EVENT, "start": {"dateTime": "2026-08-25T16:00:00",
                                "timeZone": "tzone://Microsoft/Custom"}}
    with pytest.raises(m365.M365Error, match="start.timeZone.*refusing to guess"):
        m365.derive_id(event)


def test_an_unresolvable_event_end_zone_is_refused_not_guessed():
    """end.timeZone must be checked exactly as symmetrically as
    start.timeZone — an end in an unknown zone must never be parsed as if it
    were UTC, which would silently mis-window a recurring series' transcript
    filter and the duration fallbacks derived from the same span."""
    event = {**EVENT, "end": {"dateTime": "2026-08-25T17:00:00",
                              "timeZone": "Not A Zone"}}
    with pytest.raises(m365.M365Error, match="end.timeZone.*refusing to guess"):
        m365.ids([event], utc_offset="+02:00")


def test_an_unresolvable_event_end_zone_is_refused_with_no_timezone_flags_at_all():
    """PR #217 review finding: `_event_end` used to be reachable only
    through `_event_duration_min`, which `ids()` calls only when
    `timezone`/`utc_offset` is supplied — the probe's own `m365 ids` call
    passes neither, so a malformed end passed through silently until a
    Sonnet worker re-derived ids later, after the expensive dispatch this
    PR exists to avoid. Validation must not depend on an optional flag."""
    event = {**EVENT, "end": {"dateTime": "2026-08-25T17:00:00",
                              "timeZone": "Not A Zone"}}
    with pytest.raises(m365.M365Error, match="end.timeZone.*refusing to guess"):
        m365.ids([event])
    with pytest.raises(m365.M365Error, match="end.timeZone.*refusing to guess"):
        m365.derive_id(event)


def test_every_windows_zone_in_the_table_resolves():
    _needs_tz_database()
    from vaultlib import winzones
    for name in winzones.WINDOWS_TO_IANA:
        m365.graph_dt_utc({"dateTime": "2026-08-25T12:00:00", "timeZone": name},
                          name)


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


def test_agenda_renders_a_windows_zone_listing_in_local_time():
    _needs_tz_database()
    event = _listing_event("Local", "2026-09-21T10:00:00.0000000",
                           "2026-09-21T11:30:00.0000000")
    event["start"]["timeZone"] = "Romance Standard Time"
    event["end"]["timeZone"] = "Romance Standard Time"
    result = m365.agenda([event], timezone="Europe/Brussels", date="2026-09-21")
    meeting = result["meetings"][0]
    assert (meeting["time"], meeting["end"]) == ("10:00", "11:30")
    assert meeting["start_utc"] == "2026-09-21T08:00:00"


def test_agenda_refuses_a_listing_in_an_unresolvable_zone():
    event = _listing_event("Odd", "2026-09-21T10:00:00.0000000")
    event["start"]["timeZone"] = "Not A Zone"
    with pytest.raises(m365.M365Error, match="refusing to guess"):
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


# --- capture: an oversized transcript read the host spilled to a file -------
#
# A transcript read over the host's tool-result cap comes back as an error
# notice naming a tool-results file (live reproduction 2026-10-01: a
# 104,221-character, 72-minute transcript). The file holds the connector's
# JSON byte for byte. Cowork names it by its Windows host path, which the
# sandbox's Bash only sees under /sessions/<name>/mnt/.claude/projects/...


def spill(root, transcript, *, rel="session/abc123/tool-results",
          name="mcp-x-read_resource-1790841626196.txt", bom=False):
    d = root / rel
    d.mkdir(parents=True)
    p = d / name
    data = json.dumps(transcript).encode("utf-8")
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    return p


def test_capture_copies_a_spilled_transcript_verbatim(tmp_path):
    src = spill(tmp_path / "projects", TRANSCRIPT)
    out = tmp_path / "scratch" / "m365_event_1.transcript.json"

    result = m365.capture(str(src), str(out), roots=[tmp_path / "projects"])

    assert out.read_bytes() == src.read_bytes()
    assert result["transcript_path"] == str(out)
    assert result["transcripts"] == 1
    assert result["cues"] == 4
    assert result["last_cue"] == "00:46:30"
    assert result["bytes"] == len(src.read_bytes())
    assert "warnings" not in result


def test_capture_resolves_a_host_path_the_sandbox_cannot_see(tmp_path):
    """Cowork reports the Windows host path; the same file sits under the
    sandbox mount one session-id level below projects/."""
    root = tmp_path / "sessions" / "name" / "mnt" / ".claude" / "projects"
    src = spill(root, TRANSCRIPT)
    host = (r"C:\Users\u\AppData\Roaming\Claude\local-agent-mode-sessions"
            r"\9b\72\x.claude\projects\session\abc123\tool-results"
            r"\mcp-x-read_resource-1790841626196.txt")
    out = tmp_path / "out.json"

    result = m365.capture(host, str(out), roots=[root])

    assert result["source_path"] == str(src)
    assert out.read_bytes() == src.read_bytes()


def test_capture_finds_the_file_by_name_when_the_suffix_differs(tmp_path):
    root = tmp_path / "projects"
    src = spill(root, TRANSCRIPT, rel="proj/sess/subagents/tool-results")
    out = tmp_path / "out.json"

    result = m365.capture(
        "/elsewhere/projects/other/tool-results/mcp-x-read_resource-1790841626196.txt",
        str(out), roots=[root])

    assert result["source_path"] == str(src)


def test_capture_strips_only_a_leading_bom(tmp_path):
    src = spill(tmp_path / "projects", TRANSCRIPT, bom=True)
    out = tmp_path / "out.json"

    m365.capture(str(src), str(out), roots=[tmp_path / "projects"])

    assert out.read_bytes() == src.read_bytes()[3:]


def test_capture_refuses_an_unreachable_file(tmp_path):
    with pytest.raises(m365.M365Error, match="not reachable"):
        m365.capture(r"C:\nowhere\tool-results\mcp-gone-read_resource-1.txt",
                     str(tmp_path / "out.json"), roots=[tmp_path / "projects"])


def test_capture_refuses_a_file_outside_tool_results(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text(json.dumps(TRANSCRIPT), encoding="utf-8")
    with pytest.raises(m365.M365Error, match="tool-results"):
        m365.capture(str(p), str(tmp_path / "out.json"), roots=[tmp_path])


def test_capture_refuses_a_cut_off_read(tmp_path):
    root = tmp_path / "projects"
    src = spill(root, TRANSCRIPT)
    src.write_bytes(src.read_bytes()[:-40])
    out = tmp_path / "out.json"
    with pytest.raises(m365.M365Error, match="not a complete transcript read"):
        m365.capture(str(src), str(out), roots=[root])
    assert not out.exists()


def test_capture_refuses_a_spill_that_is_not_a_transcript_read(tmp_path):
    root = tmp_path / "projects"
    src = spill(root, {"meeting": {}, "transcripts": []})
    with pytest.raises(m365.M365Error, match="no transcripts"):
        m365.capture(str(src), str(tmp_path / "out.json"), roots=[root])


def test_capture_warns_when_cues_cover_under_half_the_event(tmp_path):
    root = tmp_path / "projects"
    src = spill(root, TRANSCRIPT)
    long_event = dict(EVENT, end={"dateTime": "2026-08-25T17:00:00.0000000",
                                  "timeZone": "UTC"})
    event = write_json(tmp_path, "event.json", long_event)

    result = m365.capture(str(src), str(tmp_path / "out.json"),
                          event_path=event, roots=[root])

    assert result["warnings"] == [
        "transcript cues end at 00:46:30 of a 180-minute event — "
        "check the transcript is complete"]


def test_capture_does_not_warn_for_a_meeting_that_ended_early(tmp_path):
    root = tmp_path / "projects"
    src = spill(root, TRANSCRIPT)
    event = write_json(tmp_path, "event.json", EVENT)  # 60 min, cues to 46:30

    result = m365.capture(str(src), str(tmp_path / "out.json"),
                          event_path=event, roots=[root])

    assert "warnings" not in result


def test_reassemble_accepts_a_captured_transcript_with_bom_stripped(tmp_path):
    root = tmp_path / "projects"
    src = spill(root, TRANSCRIPT, bom=True)
    out = tmp_path / "scratch" / "t.json"
    m365.capture(str(src), str(out), roots=[root])
    event = write_json(tmp_path, "event.json", EVENT)

    result = m365.reassemble(event, str(out), str(tmp_path / "scratch"),
                             utc_offset="+02:00")

    assert result["blob_lines"] > 0


def test_reassemble_reports_blob_size_for_paged_reading(tmp_path):
    event = write_json(tmp_path, "event.json", EVENT)
    transcript = write_json(tmp_path, "t.json", TRANSCRIPT)

    result = m365.reassemble(event, transcript, str(tmp_path / "out"),
                             utc_offset="+02:00")

    blob = open(result["blob_path"], encoding="utf-8").read()
    assert result["blob_lines"] == blob.count("\n")
    assert result["blob_chars"] == len(blob)


# --- calendar-match: the time-only match (2026-10-09, 11:01 call vs 11:00 weekly) ---

def _weekly(**extra):
    return _listing_event("Leadership enablement - weekly call",
                          "2026-10-09T09:00:00.0000000", "2026-10-09T09:30:00.0000000",
                          **extra)


def test_calendar_match_single_near_start_event_matches_without_word_overlap():
    result = m365.calendar_match([_weekly()], start_local="2026-10-09T11:01",
                                 duration_min=21, utc_offset="+02:00")
    assert result["match"] == "single"
    assert result["event"]["subject"] == "Leadership enablement - weekly call"
    assert result["event"]["attendees"] == ["a@example.com"]
    assert result["event"]["start_offset_min"] == -1
    assert result["event"]["start_local"] == "2026-10-09T11:00"


def test_calendar_match_two_events_in_the_slot_is_ambiguous():
    other = _listing_event("Pipeline sync", "2026-10-09T09:05:00.0000000",
                           "2026-10-09T09:45:00.0000000")
    result = m365.calendar_match([_weekly(), other], start_local="2026-10-09T11:01",
                                 duration_min=21, utc_offset="+02:00")
    assert result["match"] == "ambiguous"
    assert result["slot_size"] == 2
    assert "event" not in result


def test_calendar_match_no_event_is_none():
    result = m365.calendar_match([], start_local="2026-10-09T11:01",
                                 duration_min=21, utc_offset="+02:00")
    assert result == {"slot_size": 0, "tolerance_min": 5, "match": "none"}


def test_calendar_match_overlap_far_from_the_start_is_not_a_match():
    # A recording that began 20 minutes into a meeting says "someone was in
    # a meeting", not which one.
    result = m365.calendar_match([_weekly()], start_local="2026-10-09T11:20",
                                 duration_min=5, utc_offset="+02:00")
    assert result["match"] == "none"
    assert result["slot_size"] == 1


def test_calendar_match_ignores_cancelled_and_all_day_events():
    events = [_weekly(),
              _listing_event("Cancelled", "2026-10-09T09:00:00.0000000",
                             "2026-10-09T09:30:00.0000000", isCancelled=True),
              _listing_event("Holiday", "2026-10-09T00:00:00.0000000",
                             "2026-10-10T00:00:00.0000000", isAllDay=True)]
    result = m365.calendar_match(events, start_local="2026-10-09T11:01",
                                 duration_min=21, utc_offset="+02:00")
    assert result["match"] == "single"


def test_calendar_match_refuses_a_date_only_start():
    with pytest.raises(m365.M365Error):
        m365.calendar_match([], start_local="2026-10-09", utc_offset="+02:00")


def test_calendar_match_resolves_attendee_addresses_through_the_address_book():
    event = _weekly(attendees=["Known@Example.com", "stranger@client.com", "Known@Example.com"])
    result = m365.calendar_match([event], start_local="2026-10-09T11:01",
                                 duration_min=21, utc_offset="+02:00",
                                 address_book={"known@example.com": "kim-known"})
    assert result["known_attendees"] == ["kim-known"]


def test_calendar_match_reads_graph_shaped_attendees():
    event = _weekly(attendees=[{"emailAddress": {"name": "K", "address": "known@example.com"}},
                               {"address": "other@client.com"}])
    result = m365.calendar_match([event], start_local="2026-10-09T11:01",
                                 duration_min=21, utc_offset="+02:00",
                                 address_book={"known@example.com": "kim-known"})
    assert result["known_attendees"] == ["kim-known"]


def test_calendar_match_derives_the_uri_and_never_copies_the_listings():
    event = _weekly(id="AAMk-a_b=", uri="calendar:///events/WRONG")
    result = m365.calendar_match([event], start_local="2026-10-09T11:01",
                                 duration_min=21, utc_offset="+02:00")
    assert result["event"]["uri"] == m365.event_uri("AAMk-a_b=")


def test_calendar_match_ambiguous_lists_candidates_with_derived_uris():
    other = _listing_event("Pipeline sync", "2026-10-09T09:05:00.0000000",
                           "2026-10-09T09:45:00.0000000", id="BBB")
    result = m365.calendar_match([_weekly(id="AAA"), other], start_local="2026-10-09T11:01",
                                 duration_min=21, utc_offset="+02:00")
    assert [c["uri"] for c in result["candidates"]] == [m365.event_uri("AAA"),
                                                         m365.event_uri("BBB")]
    assert [c["start_local"] for c in result["candidates"]] == ["2026-10-09T11:00",
                                                                "2026-10-09T11:05"]


FULL_EVENT = {
    "subject": "Leadership enablement - weekly call",
    "organizer": {"name": "Sam Okafor", "address": "sam@client.example"},
    "attendees": [
        {"name": "Owner Person", "address": "owner@vendor.example", "type": "required"},
        {"name": "Sam Okafor", "address": "sam@client.example", "type": "required"},
        {"name": "Jo Client", "address": "jo@client.example", "type": "optional"},
        {"name": "Room 4.12", "address": "room412@client.example", "type": "resource"},
        {"name": "", "address": "nameless@client.example", "type": "required"},
    ],
}


def test_resolve_attendees_ensures_named_people_and_skips_rooms(tmp_path):
    from test_vaultlib_vault import make_vault
    from vaultlib import person
    root = make_vault(tmp_path)
    person.ensure(root, "Owner Person", "2026-10-01", email="owner@vendor.example")
    result = m365.resolve_attendees(root, FULL_EVENT, owner_slug="owner-person",
                                    today="2026-10-09")
    assert result["attendees"] == ["owner-person", "sam-okafor", "jo-client"]
    assert result["created"] == ["sam-okafor", "jo-client"]
    assert result["new_attendees"] == 2
    assert result["unresolved_emails"] == ["nameless@client.example"]
    assert not (root / "50-people" / "room-4-12.md").exists()
    assert "sam@client.example" in (root / "50-people" / "sam-okafor.md").read_text()


def test_resolve_attendees_matches_by_address_before_name(tmp_path):
    """A display name spelt unlike the note's must not fork a second person."""
    from test_vaultlib_vault import make_vault
    from vaultlib import person
    root = make_vault(tmp_path)
    person.ensure(root, "Owner Person", "2026-10-01", email="owner@vendor.example")
    person.ensure(root, "Jo Client", "2026-10-01", email="jo@client.example")
    event = {"attendees": [{"name": "Person, Owner", "address": "OWNER@vendor.example"},
                           {"name": "Johanna Client", "address": "jo@client.example"}]}
    result = m365.resolve_attendees(root, event, owner_slug="owner-person",
                                    today="2026-10-09")
    assert result["attendees"] == ["owner-person", "jo-client"]
    assert result["created"] == []
    assert sorted(p.name for p in (root / "50-people").glob("*.md")) == [
        "jo-client.md", "owner-person.md"]


# --- capture from the session log: an inline transcript read ---------------
#
# A read under the tool-result cap arrives inline and is in the session log
# the moment it arrives. Re-typing it was the step the output classifier
# stops on claude-sonnet-5-5; the CLI finds it by the event's own
# transcript URL instead. Log lines mirror Claude Code's jsonl shape.

READ_TOOL = "mcp__38771dd3-7d7e-4380-93a7-0a568401598f__read_resource"


def log_read(log, uri, result, *, use_id="toolu_01", is_error=None,
             tool=READ_TOOL):
    """Append one read_resource call and its result to a session log."""
    log.parent.mkdir(parents=True, exist_ok=True)
    content = result if isinstance(result, str) and result.startswith("Error:") \
        else [{"type": "text", "text": result}]
    block = {"tool_use_id": use_id, "type": "tool_result", "content": content}
    if is_error is not None:
        block["is_error"] = is_error
    lines = [
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": use_id, "name": tool,
             "input": {"uri": uri}}]}},
        {"type": "user", "message": {"role": "user", "content": [block]}},
    ]
    with open(log, "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")
    return log


def connector_json(obj):
    """The connector's compact JSON, non-ASCII left as is."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


NAIVE = dict(TRANSCRIPT, meeting={"id": "MSo...", "subject": "Café & sync"})


def test_capture_copies_an_inline_read_from_the_session_log(tmp_path):
    root = tmp_path / "projects"
    text = connector_json(NAIVE)
    log_read(root / "proj" / "sess" / "subagents" / "agent-a1.jsonl",
             SCOPED_URL, text)
    event = write_json(tmp_path, "event.json", EVENT)
    out = tmp_path / "scratch" / "m365_event_1.transcript.json"

    result = m365.capture(None, str(out), event_path=event, roots=[root])

    assert out.read_bytes() == text.encode("utf-8")
    assert result["captured_from"] == "session-log"
    assert result["source_path"] is None
    assert result["transcripts"] == 1
    assert result["cues"] == 4
    assert "Café" not in json.dumps(result)  # counts only, never content


def test_capture_follows_a_spill_notice_found_in_the_session_log(tmp_path):
    root = tmp_path / "projects"
    src = spill(root, TRANSCRIPT, rel="proj/sess/tool-results")
    notice = (f"Error: result (54,154 characters across 1 line) exceeds "
              f"maximum allowed tokens. Output has been saved to {src}.\n"
              f"Format: Plain text\nSearch within the file for specific "
              f"content, and use jq if the content is JSON.")
    log_read(root / "proj" / "sess" / "subagents" / "agent-a1.jsonl",
             SCOPED_URL, notice)
    event = write_json(tmp_path, "event.json", EVENT)
    out = tmp_path / "out.json"

    result = m365.capture(None, str(out), event_path=event, roots=[root])

    assert out.read_bytes() == src.read_bytes()
    assert result["captured_from"] == "spill"
    assert result["source_path"] == str(src)


def test_capture_follows_a_windows_spill_notice_by_name(tmp_path):
    """Cowork's notice names the Windows host path, spaces and all."""
    root = tmp_path / "sessions" / "n" / "mnt" / ".claude" / "projects"
    spill(root, TRANSCRIPT, rel="proj/sess/tool-results",
          name="mcp-x-read_resource-17.txt")
    host = (r"C:\Users\u\AppData\Roaming\Claude\local-agent-mode-sessions"
            r"\9b\x\.claude\projects\proj\sess\tool-results"
            r"\mcp-x-read_resource-17.txt")
    log_read(root / "proj" / "sess.jsonl", SCOPED_URL,
             f"Error: result (61,060 characters across 1 line) exceeds maximum "
             f"allowed tokens. Output has been saved to {host}.\nFormat: Plain text")
    event = write_json(tmp_path, "event.json", EVENT)

    result = m365.capture(None, str(tmp_path / "out.json"), event_path=event,
                          roots=[root])

    assert result["captured_from"] == "spill"


def test_capture_takes_the_newest_log_holding_the_url(tmp_path):
    """A probe read the same URL earlier, in a sibling log."""
    import os
    root = tmp_path / "projects"
    probe = log_read(root / "p" / "s" / "subagents" / "agent-probe.jsonl",
                     SCOPED_URL, connector_json(NAIVE))
    own = log_read(root / "p" / "s" / "subagents" / "agent-worker.jsonl",
                   SCOPED_URL, connector_json(TRANSCRIPT))
    os.utime(probe, (1_000_000, 1_000_000))
    os.utime(own, (1_000_100, 1_000_100))
    event = write_json(tmp_path, "event.json", EVENT)
    out = tmp_path / "out.json"

    m365.capture(None, str(out), event_path=event, roots=[root],
                 now=1_000_200)

    assert out.read_text(encoding="utf-8") == connector_json(TRANSCRIPT)


def test_capture_takes_the_last_read_in_a_log(tmp_path):
    """A retried read: the transport error first, the transcript second."""
    root = tmp_path / "projects"
    log = root / "p" / "s.jsonl"
    log_read(log, SCOPED_URL, "Error: connection reset", use_id="toolu_a",
             is_error=True)
    log_read(log, SCOPED_URL, connector_json(TRANSCRIPT), use_id="toolu_b")
    event = write_json(tmp_path, "event.json", EVENT)
    out = tmp_path / "out.json"

    m365.capture(None, str(out), event_path=event, roots=[root])

    assert out.read_text(encoding="utf-8") == connector_json(TRANSCRIPT)


def test_capture_ignores_reads_of_other_urls(tmp_path):
    """A sibling worker's read — or this worker's own, rebuilt URL — is
    never this event's transcript."""
    root = tmp_path / "projects"
    log = root / "p" / "s.jsonl"
    log_read(log, URL, connector_json(TRANSCRIPT))  # unscoped: rebuilt
    log_read(log, SCOPED_URL, connector_json(TRANSCRIPT),
             tool="mcp__other__get_thing")
    event = write_json(tmp_path, "event.json", EVENT)

    with pytest.raises(m365.M365Error, match="no read_resource result"):
        m365.capture(None, str(tmp_path / "out.json"), event_path=event,
                     roots=[root])


def test_capture_ignores_logs_outside_the_window(tmp_path):
    import os
    root = tmp_path / "projects"
    log = log_read(root / "p" / "s.jsonl", SCOPED_URL,
                   connector_json(TRANSCRIPT))
    os.utime(log, (1_000_000, 1_000_000))
    event = write_json(tmp_path, "event.json", EVENT)

    with pytest.raises(m365.M365Error, match="no read_resource result"):
        m365.capture(None, str(tmp_path / "out.json"), event_path=event,
                     roots=[root], now=1_000_000 + m365.LOG_WINDOW_S + 1)


def test_capture_refuses_a_newest_read_that_is_not_a_transcript(tmp_path):
    root = tmp_path / "projects"
    log_read(root / "p" / "s.jsonl", SCOPED_URL, connector_json(
        {"note": "Microsoft Graph returned no transcripts for this meeting",
         "meeting": {"id": "MSo..."}, "transcripts": []}))
    event = write_json(tmp_path, "event.json", EVENT)
    out = tmp_path / "out.json"

    with pytest.raises(m365.M365Error, match="no transcripts"):
        m365.capture(None, str(out), event_path=event, roots=[root])
    assert not out.exists()


def test_capture_refuses_a_failed_newest_read(tmp_path):
    root = tmp_path / "projects"
    log_read(root / "p" / "s.jsonl", SCOPED_URL, "Error: 403 Forbidden",
             is_error=True)
    event = write_json(tmp_path, "event.json", EVENT)

    with pytest.raises(m365.M365Error, match="failed"):
        m365.capture(None, str(tmp_path / "out.json"), event_path=event,
                     roots=[root])


def test_capture_needs_a_spill_path_or_an_event(tmp_path):
    with pytest.raises(m365.M365Error, match="--from .* or --event"):
        m365.capture(None, str(tmp_path / "out.json"), roots=[tmp_path])


def test_reassemble_accepts_a_transcript_captured_from_the_log(tmp_path):
    root = tmp_path / "projects"
    log_read(root / "p" / "s.jsonl", SCOPED_URL, connector_json(NAIVE))
    event = write_json(tmp_path, "event.json", EVENT)
    out = tmp_path / "scratch" / "t.json"
    m365.capture(None, str(out), event_path=event, roots=[root])

    result = m365.reassemble(event, str(out), str(tmp_path / "scratch"),
                             utc_offset="+02:00")

    assert result["blob_lines"] > 0


# --- hosts that deliver results as MCP text parts, paths past the OS limit --
#
# Live 2026-10-14 (Plaud, Claude Desktop): a result spilled to a file is a
# list of MCP text parts, not the bare JSON, and a project folder nested past
# the Windows path limit made the log scan's stat() raise. Teams shares both.

def test_capture_from_a_spill_that_is_a_list_of_text_parts(tmp_path):
    root = tmp_path / "projects"
    text = connector_json(NAIVE)
    src = spill(root, TRANSCRIPT, rel="proj/sess/tool-results")
    src.write_text(json.dumps([{"type": "text", "text": text}]), encoding="utf-8")
    out = tmp_path / "out.json"

    result = m365.capture(str(src), str(out), roots=[root])

    assert out.read_bytes() == text.encode("utf-8")
    assert result["transcripts"] == 1


def test_capture_follows_a_notice_to_a_text_part_spill(tmp_path):
    root = tmp_path / "projects"
    text = connector_json(NAIVE)
    src = spill(root, TRANSCRIPT, rel="proj/sess/tool-results")
    src.write_text(json.dumps([{"type": "text", "text": text}]), encoding="utf-8")
    log_read(root / "p" / "s.jsonl", SCOPED_URL,
             f"Error: result (54,154 characters across 1 line) exceeds maximum "
             f"allowed tokens. Output has been saved to {src}.\nFormat: Plain text")
    event = write_json(tmp_path, "event.json", EVENT)
    out = tmp_path / "out.json"

    m365.capture(None, str(out), event_path=event, roots=[root])

    assert out.read_bytes() == text.encode("utf-8")


def test_capture_skips_a_log_it_cannot_stat(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    log_read(root / "p" / "s.jsonl", SCOPED_URL, connector_json(TRANSCRIPT))
    bad = log_read(root / "p" / "unreachable.jsonl", SCOPED_URL,
                   connector_json(NAIVE))
    real_stat = Path.stat

    def stat(self, *a, **kw):
        if self.name == bad.name:
            raise FileNotFoundError(str(self))
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", stat)
    event = write_json(tmp_path, "event.json", EVENT)
    out = tmp_path / "out.json"

    m365.capture(None, str(out), event_path=event, roots=[root])

    assert out.read_text(encoding="utf-8") == connector_json(TRANSCRIPT)
