"""m365 adapter: id derivation and reassembly of connector JSON.

The shapes here are the lab-verified M365 connector responses (2026-08-25):
a full calendar event read carrying meetingTranscriptUrl, and a transcript
read whose content is VTT-like cue text without speaker attribution (the
tenant toggle), with the attributed <v> form covered for when it flips on.
"""
import json

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


def test_a_malformed_transcript_url_raises():
    with pytest.raises(m365.M365Error, match="does not start with"):
        m365.derive_id({**EVENT, "meetingTranscriptUrl": "https://graph/x"})


def test_a_non_utc_event_start_is_refused_not_guessed():
    event = {**EVENT, "start": {"dateTime": "2026-08-25T16:00:00",
                                "timeZone": "Romance Standard Time"}}
    with pytest.raises(m365.M365Error, match="is not UTC"):
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
    assert blob.startswith("Kennismaking & sync AI\n\n> Recorded: 2026-08-25 16:00:00\n\n#Transcript\n")
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
    assert result["recorded_local"] == "2026-08-25 16:00:00"


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
    assert result["recorded_local"] == "2026-08-25 16:00:00"


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
    with pytest.raises(m365.M365Error, match="full calendar event read"):
        m365.reassemble(write_json(tmp_path, "e.json", event),
                        write_json(tmp_path, "t.json", TRANSCRIPT),
                        str(tmp_path), utc_offset="+02:00")
