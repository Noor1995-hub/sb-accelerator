"""health.report / health.render: content-free vault metrics.

The invariant these tests exist for: report() and render() have no code
path that can output a note's title, name, or filename — only counts,
rates, ages, dates, and version strings. A consultant should be able to
paste a rendered report into a client channel without a second look.
"""
import json
from datetime import date, timedelta

import pytest

from vaultlib import config, health, provenance, schema, syncjob, template

from test_vaultlib_config import valid_config, write_config
from test_vaultlib_vault import make_vault

TODAY = "2026-08-25"
WINDOW_START = date(2026, 7, 28)  # today - 28 days


def _write_meeting(root, stem, *, meeting_date, review_status="confirmed",
                    projects=(), entities=(), source_recording_id=None,
                    calendar_subject=None):
    lines = ["---", f"date: {meeting_date}", "type: meeting",
              f"review_status: {review_status}"]
    lines.append("projects: [{}]".format(", ".join(projects)))
    lines.append("entities: [{}]".format(", ".join(entities)))
    if source_recording_id:
        lines.append(f"source-recording-id: {source_recording_id}")
    if calendar_subject:
        lines.append(f'calendar-subject: "{calendar_subject}"')
    lines += ["---", "", "- notes", ""]
    (root / "20-meetings" / f"{stem}.md").write_text(
        "\n".join(lines), encoding="utf-8")


def _write_daily_note(root, iso_date, *, with_marker):
    body = ["---", f"date: {iso_date}", "type: daily-note", "---", "",
            f"# {iso_date}", ""]
    if with_marker:
        body += ["## Recap", "<!-- evening-sync:recap:begin -->",
                  "- did things", "<!-- evening-sync:recap:end -->", ""]
    (root / "60-daily-notes" / f"{iso_date}.md").write_text(
        "\n".join(body), encoding="utf-8")


def _write_project(root, slug, *, project_name):
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.md").write_text(
        "\n".join(["---", f'project-name: "{project_name}"', f"slug: {slug}",
                   "status: active", "---", "", f"# {project_name}", ""]),
        encoding="utf-8")
    return folder


def _write_decision(root, project_slug, stem, *, status):
    folder = root / "30-projects" / project_slug / "decisions"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.md").write_text(
        "\n".join(["---", "type: decision", f"project: {project_slug}",
                   "date: 2026-06-01", f"status: {status}",
                   'summary: "x"', "---", "", "**Decision** — x.", ""]),
        encoding="utf-8")


def _write_entity(root, slug, *, entity_name):
    folder = root / "40-entities" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "dossier.md").write_text(
        "\n".join(["---", f'entity-name: "{entity_name}"', f"slug: {slug}",
                   "status: active", "---", "", f"# {entity_name}", ""]),
        encoding="utf-8")


def seeded_vault(tmp_path):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text("2\n", encoding="utf-8")

    # 3 meetings, distinct dates/sources, all in the same ISO week
    # (2026-08-10 is a Monday) and inside the default 28-day window.
    _write_meeting(root, "2026-08-10-northwind-steering",
                    meeting_date="2026-08-10T10:00", review_status="confirmed",
                    projects=["northwind-rollout"], entities=["northwind-holdings"],
                    source_recording_id="plaud:aaa111",
                    calendar_subject="Northwind Steering Call")
    _write_meeting(root, "2026-08-12-northwind-followup",
                    meeting_date="2026-08-12T09:00", review_status="needs-review",
                    projects=["northwind-rollout"], entities=["northwind-holdings"],
                    source_recording_id="m365:bbb222",
                    calendar_subject="Northwind Follow-up")
    _write_meeting(root, "2026-08-14-unfiled-capture",
                    meeting_date="2026-08-14T14:00", review_status="confirmed",
                    projects=[], entities=[],
                    calendar_subject="Unfiled Capture")

    # 2 daily notes: one with a machine region marker, one without. Both
    # weekdays inside the window (2026-08-10 Mon, 2026-08-12 Wed).
    _write_daily_note(root, "2026-08-10", with_marker=True)
    _write_daily_note(root, "2026-08-12", with_marker=False)

    # 2 files + a README in the inbox; the README must not be counted.
    (root / "10-inbox" / "recording.m4a").write_text("x", encoding="utf-8")
    (root / "10-inbox" / "notes.txt").write_text("x", encoding="utf-8")
    (root / "10-inbox" / "README.md").write_text("ignore me", encoding="utf-8")

    # A 2-line skip list.
    skip_dir = root / "99-workflow-config" / "sync-state"
    skip_dir.mkdir(parents=True, exist_ok=True)
    (skip_dir / "skipped-recordings.txt").write_text(
        "plaud:skip-one\tnot a capture\n"
        "plaud:skip-two\tduplicate\n",
        encoding="utf-8")

    # 2 projects: one referenced by a recent meeting, one stale (no
    # referencing meeting within 30 days of today).
    _write_project(root, "northwind-rollout", project_name="Northwind Rollout")
    _write_project(root, "quiet-initiative", project_name="Quiet Initiative")

    # 1 entity, referenced by the recent meetings.
    _write_entity(root, "northwind-holdings", entity_name="Northwind Holdings")

    # 2 decisions with distinct `status` values (the field name confirmed
    # from a real fixture decision note: `status`, not `review_status`).
    _write_decision(root, "northwind-rollout", "2026-06-01-vendor-picked",
                    status="active")
    _write_decision(root, "northwind-rollout", "2026-05-01-old-plan-dropped",
                    status="superseded")

    return root


def test_report_meetings_group_has_exact_counts(tmp_path):
    root = seeded_vault(tmp_path)
    data = health.report(root, TODAY)

    assert data["meetings"]["in_window"] == 3
    assert data["meetings"]["per_week"] == [
        {"week_start": "2026-08-10", "count": 3}]
    assert data["meetings"]["by_source"] == {
        "plaud": 1, "m365": 1, "inbox": 0, "unknown": 1}
    assert data["meetings"]["without_projects"] == 1
    assert data["meetings"]["needs_review"] == 1


def test_report_daily_notes_coverage(tmp_path):
    root = seeded_vault(tmp_path)
    data = health.report(root, TODAY)

    working_days = sum(
        1 for offset in range(29)
        if (WINDOW_START + timedelta(days=offset)).weekday() < 5
    )
    assert data["daily_notes"]["working_days"] == working_days
    assert data["daily_notes"]["with_machine_regions"] == 1
    assert data["daily_notes"]["coverage_pct"] == round(1 / working_days * 100)


def test_report_inbox_and_skip_list(tmp_path):
    root = seeded_vault(tmp_path)
    data = health.report(root, TODAY)

    assert data["inbox_pending"] == 2
    assert data["skip_list_size"] == 2
    assert data["skip_list_size"] == len(syncjob.read_skip_records(root))


def test_report_projects_entities_and_decisions(tmp_path):
    root = seeded_vault(tmp_path)
    data = health.report(root, TODAY)

    assert data["projects"] == {"total": 2, "stale_30d": 1}
    assert data["entities"] == {"total": 1, "no_meeting_30d": 0}
    assert data["decisions"] == {
        "active": 1, "superseded": 1, "withdrawn": 0, "unknown": 0}
    assert data["unparsed"] == 0


def test_report_carries_versions_and_window(tmp_path):
    root = seeded_vault(tmp_path)
    data = health.report(root, TODAY)

    assert data["generated"] == TODAY
    assert data["window_days"] == 28
    assert data["structure_version"] == "2"
    assert data["plugin_version"]  # non-empty; exact value is the plugin's


def test_report_counts_unreadable_frontmatter_without_crashing(tmp_path):
    root = seeded_vault(tmp_path)
    # A meeting with no frontmatter delimiter at all.
    (root / "20-meetings" / "broken.md").write_text(
        "not frontmatter at all\n", encoding="utf-8")
    # A decision note with malformed frontmatter (unterminated).
    (root / "30-projects" / "northwind-rollout" / "decisions"
     / "broken-decision.md").write_text(
        "---\nstatus: active\n", encoding="utf-8")

    data = health.report(root, TODAY)

    assert data["unparsed"] == 2
    # Everything readable still counts correctly around the breakage.
    assert data["meetings"]["in_window"] == 3
    assert data["decisions"] == {
        "active": 1, "superseded": 1, "withdrawn": 0, "unknown": 0}


def test_report_rejects_a_non_positive_window(tmp_path):
    root = seeded_vault(tmp_path)
    with pytest.raises(health.HealthError):
        health.report(root, TODAY, window=0)
    with pytest.raises(health.HealthError):
        health.report(root, TODAY, window="not-a-number")


def test_render_contains_no_fixture_name(tmp_path):
    root = seeded_vault(tmp_path)
    data = health.report(root, TODAY)
    rendered = health.render(data)

    lowered = rendered.lower()
    for leaked in ("northwind", "quiet-initiative", "quiet initiative",
                   "steering", "follow-up", "unfiled"):
        assert leaked not in lowered

    # Provenance and claude_link must be just as content-free: no vault-
    # relative paths or filenames, even though this vault has no
    # provenance.json at all yet.
    for leaked in ("99-workflow-config", "provenance.json", ".claude",
                   "Meetings.base"):
        assert leaked not in rendered

    # But the numbers that make the report useful are present.
    assert "2026-08-25" in rendered
    assert "2026-08-10" in rendered  # the per-week bucket date
    assert str(data["meetings"]["in_window"]) in rendered


# --- provenance + claude_link blocks ---------------------------------------


def test_report_folds_an_absent_provenance_file_to_recorded_false(tmp_path):
    root = seeded_vault(tmp_path)
    data = health.report(root, TODAY)
    assert data["provenance"] == {
        "recorded": False, "malformed": False,
        "provisioned_at": None, "provisioned_plugin_version": None,
        "last_event": None, "last_event_at": None,
        "recorded_plugin_version": None, "plugin_drift": "unknown",
    }


def test_report_never_raises_on_malformed_provenance(tmp_path):
    root = seeded_vault(tmp_path)
    (root / "99-workflow-config" / "provenance.json").write_text(
        "{not json", encoding="utf-8")
    data = health.report(root, TODAY)
    assert data["provenance"]["recorded"] is False
    assert data["provenance"]["malformed"] is True


def test_report_never_raises_on_a_non_object_event_entry(tmp_path):
    """Reviewer finding #1's exact reproduction: {"events": ["oops"]} used to
    pass provenance.read()'s isinstance(events, list) check, and health's
    `event.get("event")` on that string raised AttributeError instead of
    folding to malformed:true."""
    root = seeded_vault(tmp_path)
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps({"provenance-version": 1, "events": ["oops"],
                    "template_files": {}}),
        encoding="utf-8")
    data = health.report(root, TODAY)
    assert data["provenance"]["recorded"] is False
    assert data["provenance"]["malformed"] is True


def test_report_reads_provisioned_and_last_event_from_a_real_record(tmp_path):
    root = seeded_vault(tmp_path)
    provenance.record_event(root, "provision", at="2026-07-01T09:00:00Z",
                            structure_version="2")
    provenance.record_event(root, "upgrade", at="2026-08-01T09:00:00Z",
                            structure_version="2", from_structure_version="1")
    data = health.report(root, TODAY)
    block = data["provenance"]
    assert block["recorded"] is True
    assert block["malformed"] is False
    assert block["provisioned_at"] == "2026-07-01T09:00:00Z"
    assert block["last_event"] == "upgrade"
    assert block["last_event_at"] == "2026-08-01T09:00:00Z"
    assert isinstance(block["recorded_plugin_version"], str)
    assert block["plugin_drift"] in ("matches", "behind", "ahead", "unknown")


def test_report_claude_link_reports_the_onedrive_copy_case(tmp_path):
    root = seeded_vault(tmp_path)
    (root / ".claude").mkdir()
    data = health.report(root, TODAY)
    assert data["claude_link"] == {"is_symlink": False, "state": "directory"}


def test_render_of_a_real_provenance_record_leaks_no_paths(tmp_path):
    root = seeded_vault(tmp_path)
    (root / "99-workflow-config" / "provenance.json").write_text(json.dumps({
        "provenance-version": 1,
        "events": [{"event": "provision", "at": "2026-07-01T09:00:00Z",
                     "plugin_version": "0.10.20", "structure_version": "2"}],
        "template_files": {"20-meetings/Meetings.base": "deadbeef"},
    }), encoding="utf-8")
    data = health.report(root, TODAY)
    rendered = health.render(data)
    assert "99-workflow-config" not in rendered
    assert "Meetings.base" not in rendered
    assert "20-meetings" not in rendered
    assert "deadbeef" not in rendered
    assert "## Provenance" in rendered
    assert "0.10.20" in rendered
    assert "2026-07-01T09:00:00Z" in rendered


# --- template block ----------------------------------------------------


def test_report_template_block_is_counts_only(tmp_path):
    root = seeded_vault(tmp_path)
    data = health.report(root, TODAY)
    block = data["template"]
    assert block["baseline"] == "unknown"
    assert block["managed"] == len(template.MANAGED)
    assert (block["current"] + block["refresh"] + block["needs_consent"]
            + block["missing"] + block["blocked"]) == block["managed"]
    # seeded_vault predates the feature and never wrote the shipped
    # .obsidian/.base tree, so nothing is "current" or silently refreshable.
    assert block["current"] == 0
    assert block["refresh"] == 0


def test_report_template_block_on_a_freshly_provisioned_vault_is_all_current(tmp_path):
    import instantiate_vault
    target = tmp_path / "vault"
    instantiate_vault.instantiate(target)

    data = health.report(target, TODAY)
    block = data["template"]
    assert block["baseline"] == "recorded"
    assert block["managed"] == len(template.MANAGED)
    assert block["current"] == len(template.MANAGED)
    assert block["needs_consent"] == 0
    assert block["missing"] == 0
    assert block["blocked"] == 0


def test_report_template_block_never_raises_on_malformed_provenance(tmp_path):
    root = seeded_vault(tmp_path)
    (root / "99-workflow-config" / "provenance.json").write_text(
        "{not json", encoding="utf-8")
    data = health.report(root, TODAY)
    assert data["template"] == {
        "managed": 0, "current": 0, "refresh": 0, "needs_consent": 0,
        "missing": 0, "blocked": 0, "baseline": "unknown",
    }


def test_render_includes_template_files_section_with_no_paths(tmp_path):
    root = seeded_vault(tmp_path)
    data = health.report(root, TODAY)
    rendered = health.render(data)
    assert "## Template files" in rendered
    for leaked in ("Meetings.base", "20-meetings", "CLAUDE.md",
                   "99-workflow-config"):
        assert leaked not in rendered
    assert str(data["template"]["managed"]) in rendered


def test_write_creates_the_dated_report_file(tmp_path):
    root = seeded_vault(tmp_path)
    data = health.report(root, TODAY)
    relpath = health.write_report(root, data)

    assert relpath == "99-workflow-config/health-reports/2026-08-25.md"
    written = (root / relpath).read_text(encoding="utf-8")
    assert written == health.render(data)
    assert "northwind" not in written.lower()


# --- security: enum allow-lists on hand-editable frontmatter --------------
#
# The write path enforces `source-recording-id` namespaces and decision
# `status` through argparse/CLI validation, but Obsidian's property panel
# writes frontmatter directly and has no such gate. These tests seed exactly
# that bypass — a value no writer in this codebase would ever produce — and
# assert the offending string never becomes a dict key or reaches render().

def test_by_source_folds_an_out_of_enum_prefix_to_unknown(tmp_path):
    root = seeded_vault(tmp_path)
    # Hand-edited frontmatter, as if typed into Obsidian's property panel:
    # not one of syncjob.NAMESPACES.
    _write_meeting(root, "2026-08-13-off-book-capture",
                    meeting_date="2026-08-13T10:00", review_status="confirmed",
                    projects=["northwind-rollout"],
                    entities=["northwind-holdings"],
                    source_recording_id="acme-secret-project:xyz")

    data = health.report(root, TODAY)

    assert "acme-secret-project" not in data["meetings"]["by_source"]
    # The pre-existing unfiled capture (absent field) plus this one
    # (out-of-enum prefix) both fold into "unknown".
    assert data["meetings"]["by_source"]["unknown"] == 2
    assert data["meetings"]["in_window"] == 4

    rendered = health.render(data)
    assert "acme-secret-project" not in rendered
    assert "acme-secret-project" not in rendered.lower()


def test_decisions_fold_an_out_of_enum_status_to_unknown(tmp_path):
    root = seeded_vault(tmp_path)
    allowed = schema.enum_values("decision", "status")
    # Hand-edited frontmatter: not one of the ontology's decision statuses.
    _write_decision(root, "northwind-rollout", "2026-06-02-secret-signoff",
                    status="blocked-pending-acme-corp-signoff")

    data = health.report(root, TODAY)

    assert "blocked-pending-acme-corp-signoff" not in data["decisions"]
    assert data["decisions"]["unknown"] == 1
    # The full allow-list is always present (zero-filled), so render()'s
    # table has a stable shape regardless of which statuses occur.
    for status in allowed:
        assert status in data["decisions"]

    rendered = health.render(data)
    assert "blocked-pending-acme-corp-signoff" not in rendered
    assert "acme-corp" not in rendered.lower()


# --- 30-day staleness boundary ---------------------------------------------

def test_project_staleness_boundary_is_inclusive_at_exactly_30_days(tmp_path):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    _write_project(root, "edge-case-project", project_name="Edge Case Project")

    # A meeting exactly 30 days before "today" (2026-08-25 - 30d ==
    # 2026-07-26, the cutoff itself) counts as recent, matching this
    # module's inclusive window semantics elsewhere.
    _write_meeting(root, "2026-07-26-touchpoint",
                    meeting_date="2026-07-26T10:00", review_status="confirmed",
                    projects=["edge-case-project"], entities=[])
    data = health.report(root, TODAY)
    assert data["projects"]["stale_30d"] == 0

    # One day older (31 days before "today") falls outside the window and
    # the project is stale.
    (root / "20-meetings" / "2026-07-26-touchpoint.md").unlink()
    _write_meeting(root, "2026-07-25-touchpoint",
                    meeting_date="2026-07-25T10:00", review_status="confirmed",
                    projects=["edge-case-project"], entities=[])
    data = health.report(root, TODAY)
    assert data["projects"]["stale_30d"] == 1


def test_entity_staleness_boundary_is_inclusive_at_exactly_30_days(tmp_path):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    _write_entity(root, "edge-case-entity", entity_name="Edge Case Entity")

    _write_meeting(root, "2026-07-26-touchpoint",
                    meeting_date="2026-07-26T10:00", review_status="confirmed",
                    projects=[], entities=["edge-case-entity"])
    data = health.report(root, TODAY)
    assert data["entities"]["no_meeting_30d"] == 0

    (root / "20-meetings" / "2026-07-26-touchpoint.md").unlink()
    _write_meeting(root, "2026-07-25-touchpoint",
                    meeting_date="2026-07-25T10:00", review_status="confirmed",
                    projects=[], entities=["edge-case-entity"])
    data = health.report(root, TODAY)
    assert data["entities"]["no_meeting_30d"] == 1


def test_health_counts_logs_and_days_at_the_limit(tmp_path):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    folder = root / "_messages"
    folder.mkdir()
    for day, limit in (("2026-09-29", "false"), ("2026-09-30", "true"), ("2026-08-01", "true")):
        (folder / f"{day}-messages.md").write_text(
            f"---\ntype: message-log\ndate: {day}\nat-limit: {limit}\n---\n", encoding="utf-8")
    block = health.report(root, "2026-09-30", window=28)["messages"]
    assert block["logs_in_window"] == 2 and block["days_at_limit"] == 1
    assert "days at the limit" in health.render(health.report(root, "2026-09-30", window=28))


def _messages_vault(tmp_path):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    (root / "_messages").mkdir()
    return root


def test_damaged_logs_never_raise_and_are_counted_as_unparsed(tmp_path):
    root = _messages_vault(tmp_path)
    before = health.report(root, "2026-09-30")["unparsed"]
    (root / "_messages" / "2026-09-28-messages.md").write_text("no frontmatter here", encoding="utf-8")
    (root / "_messages" / "2026-09-29-messages.md").write_text(
        "---\ntype: message-log\ndate: notadate\n---\n", encoding="utf-8")
    data = health.report(root, "2026-09-30")
    assert data["unparsed"] == before + 2
    assert data["messages"]["logs_in_window"] == 0


def test_a_misnamed_log_is_not_counted_in_the_window_but_is_unparsed(tmp_path):
    root = _messages_vault(tmp_path)
    (root / "_messages" / "2026-09-30-messages.md").write_text(
        "---\ntype: message-log\ndate: 2026-09-29\nat-limit: true\n---\n", encoding="utf-8")
    data = health.report(root, "2026-09-30")
    assert data["messages"]["logs_in_window"] == 0
    assert data["messages"]["days_at_limit"] == 0
    assert data["unparsed"] == 1


def test_messages_block_reflects_config_and_renders_its_rows(tmp_path):
    root = _messages_vault(tmp_path)
    assert health.report(root, "2026-09-30")["messages"]["enabled"] is False
    write_config(root, valid_config())
    config.write(root, "messages.enabled", True)
    data = health.report(root, "2026-09-30")
    assert data["messages"]["enabled"] is True
    text = health.render(data)
    assert "## Mail and Teams" in text
    for row in ("| feed on | True |", "| logs in window | 0 |", "| days at the limit | 0 |"):
        assert row in text
