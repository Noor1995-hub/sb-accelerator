"""links: one resolver for every writer, and the identity-link normaliser.

Obsidian resolves [[name]] by file name only, and entities/projects are
folders, so a bare [[acme-industries]] dangles in the app. The normaliser
rewrites identity links to the path form with the vault's display name.
"""
from pathlib import Path

from vaultlib import links

from test_vaultlib_dailynote import make_linkable_vault
from test_vaultlib_vault import make_vault


def test_resolve_bare_entity_project_person_meeting_decision_daily(tmp_path):
    root = make_linkable_vault(tmp_path)
    (root / "60-daily-notes" / "2026-06-12.md").write_text("---\n---\n", encoding="utf-8")
    assert links.resolve(root, "acme-industries")[0] == "entity"
    assert links.resolve(root, "yard-automation")[0] == "project"
    assert links.resolve(root, "taylor-brooks")[0] == "person"
    assert links.resolve(root, "12-06-26-weekly-status")[0] == "meeting"
    assert links.resolve(root, "2026-06-12-phase-1-deferred")[0] == "decision"
    assert links.resolve(root, "2026-06-12")[0] == "daily note"
    assert links.resolve(root, "nope") == (None, None, None)


def test_resolve_accepts_path_targets(tmp_path):
    root = make_linkable_vault(tmp_path)
    kind, path, key = links.resolve(root, "40-entities/acme-industries/dossier")
    assert (kind, key) == ("entity", "entity-name")
    assert path == root / "40-entities" / "acme-industries" / "dossier.md"
    kind, _, key = links.resolve(root, "30-projects/yard-automation/index")
    assert (kind, key) == ("project", "project-name")
    kind, _, _ = links.resolve(root, "30-projects/yard-automation/decisions/2026-06-12-phase-1-deferred")
    assert kind == "decision"
    assert links.resolve(root, "../etc/passwd") == (None, None, None)


def test_normalise_rewrites_identity_links_to_path_form(tmp_path):
    root = make_linkable_vault(tmp_path)
    text, offenders, warnings = links.normalise(
        root, "see [[acme-industries]] and [[yard-automation|Yard Automation Program]] "
              "and [[taylor-brooks]]", "recap")
    assert offenders == [] and warnings == []
    assert text == ("see [[40-entities/acme-industries/dossier|Acme]] and "
                    "[[30-projects/yard-automation/index|Yard Automation Program]] "
                    "and [[50-people/taylor-brooks|Taylor Brooks]]")


def test_normalise_is_idempotent_on_path_form(tmp_path):
    root = make_linkable_vault(tmp_path)
    once, _, _ = links.normalise(root, "[[acme-industries]]", "x")
    twice, offenders, _ = links.normalise(root, once, "x")
    assert twice == once and offenders == []


def test_normalise_leaves_event_links_alone_but_checks_existence(tmp_path):
    root = make_linkable_vault(tmp_path)
    text, offenders, _ = links.normalise(
        root, "[[12-06-26-weekly-status|Friday's status]] [[2026-06-12-phase-1-deferred]]", "x")
    assert text == "[[12-06-26-weekly-status|Friday's status]] [[2026-06-12-phase-1-deferred]]"
    assert offenders == []
    _, offenders, _ = links.normalise(root, "[[no-such-meeting]]", "recap")
    assert len(offenders) == 1 and "[[no-such-meeting]]" in offenders[0]


def test_normalise_refuses_a_wrong_identity_alias(tmp_path):
    root = make_linkable_vault(tmp_path)
    _, offenders, _ = links.normalise(root, "[[acme-industries|ACME Corp]]", "recap")
    assert len(offenders) == 1
    assert "'Acme'" in offenders[0]


def test_normalise_keeps_heading_anchors_and_embeds(tmp_path):
    root = make_linkable_vault(tmp_path)
    text, offenders, _ = links.normalise(
        root, "![[12-06-26-weekly-status#Key Takeaways]] [[acme-industries#Context]]", "x")
    assert offenders == []
    assert "![[12-06-26-weekly-status#Key Takeaways]]" in text
    assert "[[40-entities/acme-industries/dossier#Context|Acme]]" in text


def test_normalise_warns_when_display_name_is_missing(tmp_path):
    root = make_linkable_vault(tmp_path)
    (root / "40-entities" / "acme-industries" / "dossier.md").write_text(
        "---\ntype: entity\nslug: acme-industries\n---\n", encoding="utf-8")
    text, offenders, warnings = links.normalise(root, "[[acme-industries]]", "recap")
    assert offenders == []
    assert len(warnings) == 1 and "entity-name" in warnings[0]
    # falls back to the slug as display so the link still opens the object
    assert text == "[[40-entities/acme-industries/dossier|acme-industries]]"


def test_a_log_resolves_by_stem_and_by_path(tmp_path):
    root = make_vault(tmp_path)
    folder = root / "_messages"
    folder.mkdir()
    (folder / "2026-09-30-messages.md").write_text("---\ntype: message-log\n---\n", encoding="utf-8")
    kind, path, key = links.resolve(root, "2026-09-30-messages")
    assert kind == "message log" and path.name == "2026-09-30-messages.md" and key is None
    kind, _, _ = links.resolve(root, "_messages/2026-09-30-messages")
    assert kind == "message log"


def test_a_daily_note_and_a_log_never_share_a_stem(tmp_path):
    root = make_vault(tmp_path)
    (root / "60-daily-notes").mkdir(exist_ok=True)
    (root / "60-daily-notes" / "2026-09-30.md").write_text("---\n---\n", encoding="utf-8")
    (root / "_messages").mkdir()
    (root / "_messages" / "2026-09-30-messages.md").write_text("---\ntype: message-log\n---\n", encoding="utf-8")
    assert links.resolve(root, "2026-09-30")[0] == "daily note"
    assert links.resolve(root, "2026-09-30-messages")[0] == "message log"


def test_a_session_record_resolves_as_a_session(tmp_path):
    root = make_vault(tmp_path)
    sessions = root / "_messages" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "2026-10-12-x.md").write_text("---\ntype: session\n---\n", encoding="utf-8")
    kind, path, key = links.resolve(root, "_messages/sessions/2026-10-12-x")
    assert kind == "session" and key is None
    kind, _, _ = links.resolve(root, "2026-10-12-x")
    assert kind == "session"
