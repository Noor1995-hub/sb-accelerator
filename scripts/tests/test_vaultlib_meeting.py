"""meeting write: schema-validated emission of meeting notes.

review_status is not a payload field — every synced meeting lands
needs-review (the auto-confirm gate deliberately did not ship; a fresh vault
has no calibration data)."""
from pathlib import Path
from typing import Optional

import pytest
import yaml

from vaultlib import meeting, syncjob


def make_vault(tmp_path: Path) -> Path:
    (tmp_path / "99-workflow-config").mkdir()
    (tmp_path / "10-inbox").mkdir()
    (tmp_path / "20-meetings").mkdir()
    (tmp_path / "30-projects" / "yard-automation").mkdir(parents=True)
    (tmp_path / "30-projects" / "yard-automation" / "index.md").write_text(
        "---\ntype: project\nslug: yard-automation\n"
        "entity: meridian-freight-holdings\n---\n", encoding="utf-8")
    (tmp_path / "40-entities" / "meridian-freight-holdings").mkdir(parents=True)
    (tmp_path / "40-entities" / "meridian-freight-holdings"
     / "dossier.md").write_text(
        "---\ntype: entity\nslug: meridian-freight-holdings\n---\n",
        encoding="utf-8")
    (tmp_path / "50-people").mkdir()
    for slug in ("priya-nathan", "morgan-ellery"):
        (tmp_path / "50-people" / f"{slug}.md").write_text(
            f"---\nperson-name: X\nslug: {slug}\nrelationship:\n---\n",
            encoding="utf-8")
    return tmp_path


def _add_project(root: Path, slug: str, entity: Optional[str] = None) -> None:
    body = f"---\ntype: project\nslug: {slug}\n"
    if entity is not None:
        body += f"entity: {entity}\n"
    body += "---\n"
    (root / "30-projects" / slug).mkdir(parents=True, exist_ok=True)
    (root / "30-projects" / slug / "index.md").write_text(body, encoding="utf-8")


def _add_entity_dossier(root: Path, slug: str) -> None:
    folder = root / "40-entities" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "dossier.md").write_text(
        f"---\ntype: entity\nslug: {slug}\n---\n", encoding="utf-8")


def payload(**overrides) -> dict:
    base = {
        "title": "vendor strategy brainstorm",
        "date": "2026-05-20T11:00",
        "type": "brainstorm",
        "calendar-subject": "Vendor strategy: working session",
        "calendar_match": False,
        "attendees": ["priya-nathan", "morgan-ellery"],
        "projects": ["yard-automation"],
        "recording-duration": 41,
        "source": "recorder",
        "source-recording-id": "inbox:3f9c2a41d8e07b56",
        "source-filename": "REC-2026-0520-1103.m4a",
        "confidence": "low",
        "confidence-reasons": ["calendar-tool-unavailable",
                               "content-keyword-match", "new-attendees:1"],
        "takeaways": ["Single-vendor consolidation preferred.",
                      "Yard 2 timeline at risk."],
        "debrief": "### Vendor strategy\nDiscussion of consolidation.",
        "action-items": ["**Priya Nathan** — circulate revised schedule"],
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def test_write_happy_path_is_conformant_yaml(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, payload())
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm"
    assert result["review_status"] == "needs-review"
    assert result["conflict"] is None

    text = (root / result["path"]).read_text(encoding="utf-8")
    # PyYAML is the second parser CI trusts; the emitted block must satisfy it.
    block = text.split("---\n")[1]
    data = yaml.safe_load(block)
    assert data["calendar-subject"] == "Vendor strategy: working session"
    assert data["review_status"] == "needs-review"
    assert data["reviewed"] is False and data["archived"] is False
    assert data["processed"] is True
    assert data["confidence-reasons"] == ["calendar-tool-unavailable",
                                          "content-keyword-match",
                                          "new-attendees:1"]
    assert "## Key Takeaways" in text and "## Debrief" in text
    assert "## Action Items" in text


def test_one_to_one_type_survives_pyyaml(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, payload(type="1:1",
                                         title="priya check in"))
    block = (root / result["path"]).read_text(encoding="utf-8").split("---\n")[1]
    assert yaml.safe_load(block)["type"] == "1:1"   # not the integer 61


def test_action_items_section_omitted_when_absent(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, payload(**{"action-items": None}))
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert "## Action Items" not in text


def test_rejects_unknown_project_and_unknown_attendee(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="no-such-project"):
        meeting.write(root, payload(projects=["no-such-project"]))
    with pytest.raises(meeting.MeetingError, match="person ensure"):
        meeting.write(root, payload(attendees=["ghost-attendee"]))


def test_entities_is_derived_from_a_single_project(tmp_path):
    # projects[] is non-empty (yard-automation, entity: meridian-freight-
    # holdings), so entities is machine-derived rather than taken from the
    # payload.
    root = make_vault(tmp_path)
    result = meeting.write(root, payload())
    data = yaml.safe_load(
        (root / result["path"]).read_text(encoding="utf-8").split("---")[1])
    assert data["entities"] == ["meridian-freight-holdings"]


def test_entities_is_derived_from_multiple_projects_and_deduped(tmp_path):
    root = make_vault(tmp_path)
    _add_project(root, "yard-automation-2", "meridian-freight-holdings")
    result = meeting.write(
        root, payload(projects=["yard-automation", "yard-automation-2"]))
    data = yaml.safe_load(
        (root / result["path"]).read_text(encoding="utf-8").split("---")[1])
    # Both projects map to the same entity: one slug, not two.
    assert data["entities"] == ["meridian-freight-holdings"]


def test_entities_derived_from_projects_mapping_to_different_entities(tmp_path):
    root = make_vault(tmp_path)
    _add_entity_dossier(root, "northwind-holdings")
    _add_project(root, "northwind-rollout", "northwind-holdings")
    result = meeting.write(
        root, payload(projects=["yard-automation", "northwind-rollout"]))
    data = yaml.safe_load(
        (root / result["path"]).read_text(encoding="utf-8").split("---")[1])
    assert data["entities"] == ["meridian-freight-holdings", "northwind-holdings"]


def test_refuses_payload_entities_when_projects_non_empty(tmp_path):
    # The skill layer must stop hand-passing entities once a project is
    # assigned — write() derives it, and a payload that tries anyway is
    # refused rather than silently overridden.
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="derived from projects"):
        meeting.write(root, payload(entities=["meridian-freight-holdings"]))


def test_allows_payload_entities_when_projects_empty(tmp_path):
    # A project-less meeting may still concern an entity by hand.
    root = make_vault(tmp_path)
    result = meeting.write(
        root, payload(projects=[], entities=["meridian-freight-holdings"]))
    data = yaml.safe_load(
        (root / result["path"]).read_text(encoding="utf-8").split("---")[1])
    assert data["entities"] == ["meridian-freight-holdings"]


def test_entities_is_omitted_rather_than_written_empty(tmp_path):
    # An entity dossier is the only reader of this field, so `entities: []` on
    # every meeting without one is noise in the properties panel.
    root = make_vault(tmp_path)
    result = meeting.write(root, payload(projects=[]))
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert "entities:" not in text.split("---")[1]


def test_rejects_an_entity_slug_with_no_dossier(tmp_path):
    # The dossier's Meeting Log is a Dataview query over this field: a slug
    # that joins to nothing empties the table with no error anywhere. Only
    # reachable on a project-less meeting now (a project-carrying meeting's
    # entities come from derivation, never the payload).
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="40-entities/typo-co"):
        meeting.write(root, payload(projects=[], entities=["typo-co"]))


def test_all_or_nothing_when_a_project_entity_is_unresolvable(tmp_path):
    # yard-automation resolves fine; the second project has no `entity:`
    # field at all — derivation must refuse the whole note rather than write
    # a partial entities list (migration 001's contract, shared here).
    root = make_vault(tmp_path)
    _add_project(root, "fieldless-project", entity=None)
    with pytest.raises(meeting.MeetingError, match="fieldless-project"):
        meeting.write(
            root, payload(projects=["yard-automation", "fieldless-project"]))
    # Nothing was written — a refused derivation leaves no note behind.
    assert list((root / "20-meetings").glob("*.md")) == []


def test_rejects_incomplete_confidence_stamp(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="travel together"):
        meeting.write(root, payload(**{"confidence-reasons": None}))
    bad = payload(**{"confidence-reasons":
                     ["calendar-match-high", "calendar-match-low",
                      "all-attendees-known"]})
    with pytest.raises(meeting.MeetingError, match="project-link"):
        meeting.write(root, bad)
    bad2 = payload(**{"confidence-reasons":
                      ["calendar-match-high", "no-project-match",
                       "new-attendees:0"]})
    with pytest.raises(meeting.MeetingError, match="new-attendees"):
        meeting.write(root, bad2)


def test_rejects_unknown_payload_key_and_bad_enum(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="unknown payload key"):
        meeting.write(root, payload(review_status="confirmed"))
    with pytest.raises(meeting.MeetingError, match="source"):
        meeting.write(root, payload(source="carrier-pigeon"))


def test_rejects_zero_takeaways_and_too_many(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="takeaways"):
        meeting.write(root, payload(takeaways=[]))
    with pytest.raises(meeting.MeetingError, match="takeaways"):
        meeting.write(root, payload(takeaways=["a", "b", "c", "d", "e", "f"]))


def test_rejects_missing_recording_id(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="source-recording-id"):
        meeting.write(root, payload(**{"source-recording-id": None}))


def test_refuses_when_recording_id_already_in_ledger(tmp_path):
    root = make_vault(tmp_path)
    meeting.write(root, payload())
    with pytest.raises(meeting.MeetingError, match="already synced"):
        meeting.write(root, payload(title="different title entirely"))


def test_confirmed_target_gets_a_flagged_sibling(tmp_path):
    """The sibling is an ordinary needs-review note; the conflicts-with edge
    is what marks it as a duplicate that must not be auto-confirmed."""
    root = make_vault(tmp_path)
    first = meeting.write(root, payload())
    # A human confirms it via triage.
    p = root / first["path"]
    p.write_text(p.read_text(encoding="utf-8").replace(
        "review_status: needs-review", "review_status: confirmed"),
        encoding="utf-8")

    dup = payload(**{"source-recording-id": "inbox:ffff2a41d8e07b56"})
    result = meeting.write(root, dup)
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm-v2"
    assert result["review_status"] == "needs-review"
    assert result["conflict"] == {
        "kind": "confirmed-target",
        "conflicts_with": "20-05-26-vendor-strategy-brainstorm",
    }
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert 'conflicts-with: "[[20-05-26-vendor-strategy-brainstorm]]"' in text
    # The confirmed note was not touched.
    assert "review_status: confirmed" in p.read_text(encoding="utf-8")


def test_second_conflict_takes_v3(tmp_path):
    root = make_vault(tmp_path)
    first = meeting.write(root, payload())
    p = root / first["path"]
    p.write_text(p.read_text(encoding="utf-8").replace(
        "review_status: needs-review", "review_status: confirmed"),
        encoding="utf-8")
    meeting.write(root, payload(**{"source-recording-id": "inbox:aaaa2a41d8e07b56"}))
    third = meeting.write(root, payload(**{"source-recording-id": "inbox:bbbb2a41d8e07b56"}))
    assert third["stem"] == "20-05-26-vendor-strategy-brainstorm-v3"


def test_unconfirmed_stem_collision_suffixes_instead_of_overwriting(tmp_path):
    root = make_vault(tmp_path)
    first = meeting.write(root, payload())
    result = meeting.write(
        root, payload(**{"source-recording-id": "inbox:cccc2a41d8e07b56"}))
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm-2"
    assert result["review_status"] == "needs-review"
    assert result["conflict"]["kind"] == "stem-collision"
    # Both notes exist; nothing was overwritten.
    assert (root / first["path"]).is_file() and (root / result["path"]).is_file()


def test_cross_source_stem_collision_gets_a_flagged_sibling(tmp_path):
    """One conversation captured by two sources in the same run — a Plaud
    recording plus the same meeting's Teams transcript — derives one stem.
    Distinct ids in *different namespaces* at the same stem are a probable
    duplicate, not a coincidence: the sibling carries the conflicts-with
    edge so triage shows it and reconcile-reviews refuses to fold a tick."""
    root = make_vault(tmp_path)
    first = meeting.write(
        root, payload(**{"source-recording-id": "plaud:abc123"}))
    result = meeting.write(
        root, payload(**{"source-recording-id": "m365:def456"}))
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm-v2"
    assert result["review_status"] == "needs-review"
    assert result["conflict"] == {
        "kind": "cross-source-duplicate",
        "conflicts_with": "20-05-26-vendor-strategy-brainstorm",
    }
    text = (root / result["path"]).read_text(encoding="utf-8")
    assert 'conflicts-with: "[[20-05-26-vendor-strategy-brainstorm]]"' in text
    # The first note was not touched.
    assert "plaud:abc123" in (root / first["path"]).read_text(encoding="utf-8")


def test_lost_write_race_lands_on_a_sibling_never_a_clobber(
        tmp_path, monkeypatch):
    """Two concurrent workers can both see a free stem before either writes —
    the lookup in _resolve_target is a snapshot. Simulate the loser: its
    first stem lookup answers None even though the winner's note exists by
    then; the exclusive create must refuse, and the retry must re-resolve to
    the flagged sibling instead of replacing the winner's note."""
    root = make_vault(tmp_path)
    first = meeting.write(
        root, payload(**{"source-recording-id": "plaud:abc123"}))
    first_text = (root / first["path"]).read_text(encoding="utf-8")

    real_find = meeting._find_stem
    calls = {"n": 0}

    def stale_once(folder, stem):
        calls["n"] += 1
        if calls["n"] == 1:
            return None   # the loser's pre-write snapshot: nothing there yet
        return real_find(folder, stem)

    monkeypatch.setattr(meeting, "_find_stem", stale_once)
    result = meeting.write(
        root, payload(**{"source-recording-id": "m365:def456"}))
    assert result["stem"] == "20-05-26-vendor-strategy-brainstorm-v2"
    assert result["conflict"]["kind"] == "cross-source-duplicate"
    # The winner's note is byte-identical — never last-write-wins clobbered.
    assert (root / first["path"]).read_text(encoding="utf-8") == first_text


def note_payload(**overrides) -> dict:
    """A forwarded email: a capture, not a meeting. No calendar was ever
    consulted and nothing was recorded — but it is still filed under its
    own subject line, because a required field may not be empty."""
    base = payload(
        title="meridian renewal terms heads up",
        type="note",
        **{"calendar-subject": "Renewal terms — heads up before next steerco"},
    )
    base["calendar_match"] = False
    base["recording-duration"] = 0
    base["source"] = "email"
    base["confidence-reasons"] = ["calendar-not-applicable",
                                  "content-keyword-match",
                                  "all-attendees-known"]
    base.pop("source-filename", None)
    base.update(overrides)
    return base


def test_note_type_is_written_like_any_other_capture(tmp_path):
    root = make_vault(tmp_path)
    result = meeting.write(root, note_payload())
    assert result["stem"] == "20-05-26-meridian-renewal-terms-heads-up"
    assert result["review_status"] == "needs-review"
    written = (root / result["path"]).read_text(encoding="utf-8")
    data = yaml.safe_load(written.split("---")[1])
    assert data["type"] == "note"
    assert data["calendar-subject"] == "Renewal terms — heads up before next steerco"
    assert data["recording-duration"] == 0
    assert data["source"] == "email"


def test_note_may_carry_no_attendees(tmp_path):
    """A voice memo musing names nobody. Every other type still must."""
    root = make_vault(tmp_path)
    result = meeting.write(root, note_payload(attendees=[]))
    written = (root / result["path"]).read_text(encoding="utf-8")
    data = yaml.safe_load(written.split("---")[1])
    assert data["attendees"] == []


def test_empty_attendees_still_refused_for_every_other_type(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(meeting.MeetingError, match="non-empty"):
        meeting.write(root, payload(attendees=[]))


def test_date_from_stem_is_the_inverse_of_the_date_prefix():
    from datetime import date
    # meeting._date_prefix renders 2026-06-01 as 01-06-26; this reads it back.
    assert meeting.date_from_stem(
        "01-06-26-commercial-ops-status-update") == date(2026, 6, 1)
    # A conflict variant keeps its prefix.
    assert meeting.date_from_stem("12-06-26-jordan-1on1-v2") == date(2026, 6, 12)


def test_date_from_stem_returns_none_for_a_non_conforming_stem():
    # An ISO-prefixed stem is a decision note, not a meeting note.
    assert meeting.date_from_stem("2026-06-12-phase-1-deferred") is None
    assert meeting.date_from_stem("notes-from-the-call") is None
    assert meeting.date_from_stem("") is None
    # A real-looking but impossible date.
    assert meeting.date_from_stem("32-06-26-nope") is None


def test_date_prefix_round_trips_through_date_from_stem():
    stem = f"{meeting._date_prefix('2026-05-20T11:00')}-vendor-strategy"
    assert meeting.date_from_stem(stem).isoformat() == "2026-05-20"


def test_write_refuses_the_other_plaud_id_form_of_a_synced_recording(tmp_path):
    """Regression for the 2026-09-15 duplicates: one recording written once as
    plaud:<hex> and once as plaud:of_<hex>, because the ledger compared the
    literal strings."""
    root = make_vault(tmp_path)
    hex_id = "0123456789abcdef0123456789abcdef"
    meeting.write(root, payload(**{"source-recording-id": f"plaud:{hex_id}"}))
    with pytest.raises(meeting.MeetingError, match="already synced"):
        meeting.write(root, payload(
            title="same meeting, second listing",
            **{"source-recording-id": f"plaud:of_{hex_id}"}))


def test_write_stores_the_plaud_id_in_canonical_form(tmp_path):
    from vaultlib import markdown
    root = make_vault(tmp_path)
    hex_id = "0123456789abcdef0123456789abcdef"
    result = meeting.write(
        root, payload(**{"source-recording-id": f"plaud:of_{hex_id}"}))
    assert result["recording_id"] == f"plaud:{hex_id}"
    data, _ = markdown.split_frontmatter(
        (root / result["path"]).read_text(encoding="utf-8"))
    assert data["source-recording-id"] == f"plaud:{hex_id}"


# ---------------------------------------------------------------------------
# A1: a stem-independent cross-adapter collision check. The existing
# cross-source-duplicate guard above only catches two sources that derive
# the *same* title-based stem; a Plaud recording named after a generic
# recorder filename and its own meeting's Teams transcript often do not, so
# two separate notes land for one conversation with no conflict anywhere.
# This scans every meeting note's time window instead of one stem's, and is
# the correctness net for the intra-run race worker-contract.md's collide
# check cannot always close by itself (its own pre-write check can run
# before a sibling worker's note exists).


def test_cross_adapter_collision_at_a_different_stem_refuses(tmp_path):
    root = make_vault(tmp_path)
    meeting.write(root, payload(**{"source-recording-id": "plaud:abc123"}))
    with pytest.raises(meeting.MeetingError, match="cross-adapter-duplicate"):
        meeting.write(root, payload(
            title="teams recording of the same meeting",
            **{"source-recording-id": "m365:def456"}))
    # nothing was written for the refused attempt
    assert len(list((root / "20-meetings").glob("*.md"))) == 1


def test_cross_adapter_collision_message_carries_no_repr_quotes(tmp_path):
    """Fix wave 2: a worker parses this message's stem/id verbatim for its
    outcome line and, from there, sync settle-duplicate's --existing value
    — repr quotes (from `!r`) would leak into both."""
    root = make_vault(tmp_path)
    meeting.write(root, payload(**{"source-recording-id": "plaud:abc123"}))
    with pytest.raises(meeting.MeetingError) as excinfo:
        meeting.write(root, payload(
            title="teams recording of the same meeting",
            **{"source-recording-id": "m365:def456"}))
    message = str(excinfo.value)
    assert "'20-05-26-vendor-strategy-brainstorm'" not in message
    assert "'plaud:abc123'" not in message
    assert "20-05-26-vendor-strategy-brainstorm" in message
    assert "plaud:abc123" in message


def test_cross_adapter_collision_same_namespace_writes_normally(tmp_path):
    root = make_vault(tmp_path)
    meeting.write(root, payload(**{"source-recording-id": "plaud:abc123"}))
    result = meeting.write(root, payload(
        title="a second plaud capture in the same overlapping slot",
        **{"source-recording-id": "plaud:def456"}))
    assert result["conflict"] is None
    assert result["warnings"] == []


def test_cross_adapter_collision_imprecise_match_is_a_warning_not_a_refusal(
        tmp_path):
    root = make_vault(tmp_path)
    meeting.write(root, payload(
        title="date-only capture", date="2026-05-20",
        **{"source-recording-id": "plaud:abc123"}))
    result = meeting.write(root, payload(
        title="teams recording of the same meeting",
        **{"source-recording-id": "m365:def456"}))
    assert result["conflict"] is None
    assert result["warnings"]
    assert "imprecise" in result["warnings"][0].lower() \
        or "date-only" in result["warnings"][0].lower()


def test_accept_collision_writes_a_precise_cross_adapter_match_anyway(
        tmp_path):
    root = make_vault(tmp_path)
    meeting.write(root, payload(**{"source-recording-id": "plaud:abc123"}))
    result = meeting.write(
        root, payload(
            title="teams recording of the same meeting",
            **{"source-recording-id": "m365:def456"}),
        accept_collision=True)
    assert result["conflict"] is None
    assert (root / result["path"]).is_file()


def test_accept_collision_leaves_a_trace_in_the_result_warnings(tmp_path):
    """MINOR 1: --accept-collision used to bypass the refusal silently,
    leaving no record on the written note or its result of a collision
    having been overridden."""
    root = make_vault(tmp_path)
    meeting.write(root, payload(**{"source-recording-id": "plaud:abc123"}))
    result = meeting.write(
        root, payload(
            title="teams recording of the same meeting",
            **{"source-recording-id": "m365:def456"}),
        accept_collision=True)
    assert any(
        w.startswith("collision-accepted: ")
        and "20-05-26-vendor-strategy-brainstorm" in w
        for w in result["warnings"]
    ), result["warnings"]


def test_zero_duration_payload_skips_the_collision_scan(tmp_path):
    root = make_vault(tmp_path)
    meeting.write(root, payload(**{"source-recording-id": "plaud:abc123"}))
    result = meeting.write(root, note_payload(
        title="teams recording of the same meeting",
        **{"source-recording-id": "m365:def456"}))
    assert result["conflict"] is None
    assert result["warnings"] == []


# ---------------------------------------------------------------------------
# Fix round 1, CRITICAL: a merely-adjacent meeting is a "precise" match under
# collide's 15-minute grace, but has zero real overlap — must never be
# refused or skipped, only warned about, same as an imprecise match.


def test_cross_adapter_collision_non_strong_match_is_a_warning_not_a_refusal(
        tmp_path):
    root = make_vault(tmp_path)
    meeting.write(root, payload(**{"source-recording-id": "plaud:abc123"}))
    # Back-to-back: the first meeting is 11:00-11:41; this one starts right
    # as it ends. Different namespace, different stem, zero real overlap.
    result = meeting.write(root, payload(
        title="an unrelated meeting right after the first one",
        date="2026-05-20T11:41",
        **{"source-recording-id": "m365:def456"}))
    assert result["conflict"] is None
    assert result["warnings"]
    assert "20-05-26-vendor-strategy-brainstorm" in result["warnings"][0]


# ---------------------------------------------------------------------------
# Fix round 1, SPEC GAP: the write-time collision scan used to run only on
# the fully-free-stem path — a payload landing on the stem-collision branch
# (same title, same namespace, unconfirmed note already there) never got the
# stem-independent scan at all, so a *different*, strongly-overlapping,
# cross-adapter note elsewhere in the vault went uncaught.


def test_cross_adapter_collision_also_runs_on_the_stem_collision_path(
        tmp_path):
    root = make_vault(tmp_path)
    # A: same title/date/duration as the payload under test, same namespace
    # (plaud) -> C will land on the stem-collision path against A.
    meeting.write(root, payload(**{"source-recording-id": "plaud:aaa111"}))
    # B: a different stem entirely, different namespace, identical window —
    # a strong cross-adapter match the stem-collision path must still catch.
    # (Written with accept_collision=True: on its own write B also overlaps
    # A strongly, cross-namespace, which is exactly the scenario under test
    # — a human/re-dispatch already confirmed these are two real meetings.)
    meeting.write(root, payload(
        title="an entirely different capture of the same slot",
        **{"source-recording-id": "m365:bbb222"}), accept_collision=True)
    with pytest.raises(meeting.MeetingError, match="cross-adapter-duplicate"):
        meeting.write(root, payload(**{"source-recording-id": "plaud:ccc333"}))


def test_stem_collision_path_excludes_its_own_stem_from_the_scan(tmp_path):
    """The note already sitting at the colliding stem (same namespace) must
    not also get reported back as an imprecise/non-strong warning — that
    would just be noisy double-reporting of the stem-collision conflict the
    caller already sees."""
    root = make_vault(tmp_path)
    meeting.write(root, payload(**{"source-recording-id": "inbox:aaaa000011112222"}))
    result = meeting.write(
        root, payload(**{"source-recording-id": "inbox:bbbb000011112222"}))
    assert result["conflict"]["kind"] == "stem-collision"
    assert result["warnings"] == []
