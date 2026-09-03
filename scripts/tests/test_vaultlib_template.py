"""TDD for plugin/lib/vaultlib/template.py — managed-file tiers, status,
diff and refresh, built on top of provenance.py (#147/D4a).

The status-matrix tests monkeypatch `template.TEMPLATE_ROOT` to a small
synthetic tree (never the real 34-file template) so each branch of the
matrix is exercised in isolation, the way #147's own tests isolate
`record_provision`'s "all 34" behaviour from every other assertion.
"""
import json
import shutil
from pathlib import Path

import pytest

from vaultlib import provenance, template, vault

from test_vaultlib_vault import make_vault

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_TEMPLATE_ROOT = REPO_ROOT / "plugin" / "template"


def _versioned_vault(tmp_path, version="2"):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text(f"{version}\n", encoding="utf-8")
    return root


# --- tiers partition the real shipped template exactly once ----------------


def test_every_shipped_file_is_classified_exactly_once():
    shipped = {
        path.relative_to(REAL_TEMPLATE_ROOT).as_posix()
        for path in REAL_TEMPLATE_ROOT.rglob("*") if path.is_file()
    }
    assert shipped == template.ALL_TIERED
    tiers = (template.MANAGED_SILENT, template.MANAGED_CONSENT_ALWAYS,
             template.SEEDED_ONCE, template.IGNORED)
    seen = set()
    for tier in tiers:
        overlap = seen & tier
        assert not overlap, f"{overlap} appears in more than one tier"
        seen |= tier


def test_managed_files_all_exist_in_the_shipped_template():
    for rel in template.MANAGED:
        assert (REAL_TEMPLATE_ROOT / rel).is_file(), rel


def test_the_shipped_file_count_matches_the_provenance_all_34_fixture():
    # Single source of truth for the count both test files pin, per the
    # brief's "shared constant" absorb: neither hardcodes 34 independently.
    assert len(template.ALL_TIERED) == 34
    assert len(template.MANAGED) == 26


# --- a synthetic template root for isolated status-matrix tests ------------


def _fake_template(tmp_path, files: dict) -> Path:
    root = tmp_path / "fake-template"
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return root


@pytest.fixture
def one_managed_file(tmp_path, monkeypatch):
    """Isolates the status matrix to a single MANAGED_SILENT file, `a.md`,
    with template bytes `template v2\\n`. Returns (vault_root, template_root)."""
    fake_root = _fake_template(tmp_path, {"a.md": "template v2\n"})
    monkeypatch.setattr(template, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(provenance, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(template, "MANAGED_SILENT", frozenset({"a.md"}))
    monkeypatch.setattr(template, "MANAGED_CONSENT_ALWAYS", frozenset())
    monkeypatch.setattr(template, "SEEDED_ONCE", frozenset())
    monkeypatch.setattr(template, "IGNORED", frozenset())
    monkeypatch.setattr(template, "MANAGED", frozenset({"a.md"}))
    vault_root = _versioned_vault(tmp_path)
    return vault_root, fake_root


@pytest.fixture
def one_consent_always_file(tmp_path, monkeypatch):
    fake_root = _fake_template(tmp_path, {"CLAUDE.md": "template v2\n"})
    monkeypatch.setattr(template, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(provenance, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(template, "MANAGED_SILENT", frozenset())
    monkeypatch.setattr(template, "MANAGED_CONSENT_ALWAYS", frozenset({"CLAUDE.md"}))
    monkeypatch.setattr(template, "SEEDED_ONCE", frozenset())
    monkeypatch.setattr(template, "IGNORED", frozenset())
    monkeypatch.setattr(template, "MANAGED", frozenset({"CLAUDE.md"}))
    vault_root = _versioned_vault(tmp_path)
    return vault_root, fake_root


def _entry(status_result, rel):
    matches = [f for f in status_result["files"] if f["relpath"] == rel]
    assert len(matches) == 1
    return matches[0]


# --- status matrix: MANAGED_SILENT tier -------------------------------------


def test_status_missing_when_vault_has_no_copy(one_managed_file):
    root, _ = one_managed_file
    result = template.status(root)
    entry = _entry(result, "a.md")
    assert entry["state"] == "missing"
    assert entry["tier"] == "silent"
    assert result["baseline"] == "unknown"
    assert result["counts"]["missing"] == 1


def test_status_current_when_vault_matches_template_with_no_baseline(one_managed_file):
    root, fake_root = one_managed_file
    (root / "a.md").write_text("template v2\n", encoding="utf-8")
    entry = _entry(template.status(root), "a.md")
    assert entry["state"] == "current"
    assert entry["reason"] == "baseline_stale"


def test_status_current_and_not_stale_once_baselined(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("template v2\n", encoding="utf-8")
    provenance.rebaseline(root, ["a.md"])
    entry = _entry(template.status(root), "a.md")
    assert entry["state"] == "current"
    assert entry["reason"] is None


def test_status_refresh_when_silent_tier_unchanged_since_baseline(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("baselined old content\n", encoding="utf-8")
    provenance.record_event(root, "provision", structure_version="2")
    data = provenance.read(root)
    data["template_files"]["a.md"] = provenance.digest(b"baselined old content\n")
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps(data), encoding="utf-8")
    entry = _entry(template.status(root), "a.md")
    assert entry["state"] == "refresh"
    assert entry["tier"] == "silent"


def test_status_needs_consent_unknown_baseline_when_recorded_is_none(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("hand edited\n", encoding="utf-8")
    entry = _entry(template.status(root), "a.md")
    assert entry["state"] == "needs-consent"
    assert entry["reason"] == "unknown-baseline"
    assert template.status(root)["baseline"] == "unknown"


def test_status_needs_consent_locally_edited_when_vault_differs_from_both(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("baselined old content\n", encoding="utf-8")
    data = provenance._empty()
    data["template_files"]["a.md"] = provenance.digest(b"baselined old content\n")
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps(data), encoding="utf-8")
    (root / "a.md").write_text("hand edited after baseline\n", encoding="utf-8")
    entry = _entry(template.status(root), "a.md")
    assert entry["state"] == "needs-consent"
    assert entry["reason"] == "locally-edited"
    assert entry["lines_added"] >= 1
    assert entry["lines_removed"] >= 1


def test_status_blocked_when_vault_path_is_a_directory(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").mkdir()
    entry = _entry(template.status(root), "a.md")
    assert entry["state"] == "blocked"


def test_status_baseline_is_recorded_once_provenance_exists(one_managed_file):
    root, _ = one_managed_file
    provenance.record_event(root, "provision", structure_version="2")
    assert template.status(root)["baseline"] == "recorded"


# --- status matrix: MANAGED_CONSENT_ALWAYS tier -----------------------------


def test_status_consent_always_when_unchanged_since_baseline_but_template_moved(
        one_consent_always_file):
    root, _ = one_consent_always_file
    (root / "CLAUDE.md").write_text("template v1\n", encoding="utf-8")
    data = provenance._empty()
    data["template_files"]["CLAUDE.md"] = provenance.digest(b"template v1\n")
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps(data), encoding="utf-8")
    entry = _entry(template.status(root), "CLAUDE.md")
    assert entry["state"] == "needs-consent"
    assert entry["reason"] == "consent-always"
    assert entry["tier"] == "consent_always"


# --- resets_column_widths ----------------------------------------------------


def test_resets_column_widths_true_for_a_base_file_containing_columnsize(tmp_path, monkeypatch):
    fake_root = _fake_template(tmp_path, {"x.base": "views: []\n"})
    monkeypatch.setattr(template, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(provenance, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(template, "MANAGED_SILENT", frozenset({"x.base"}))
    monkeypatch.setattr(template, "MANAGED_CONSENT_ALWAYS", frozenset())
    monkeypatch.setattr(template, "SEEDED_ONCE", frozenset())
    monkeypatch.setattr(template, "IGNORED", frozenset())
    monkeypatch.setattr(template, "MANAGED", frozenset({"x.base"}))
    root = _versioned_vault(tmp_path)
    (root / "x.base").write_text(
        "views:\n  - columnSize:\n      note: 200\n", encoding="utf-8")
    entry = _entry(template.status(root), "x.base")
    assert entry["resets_column_widths"] is True


def test_resets_column_widths_false_without_the_key(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("template v2\n", encoding="utf-8")
    entry = _entry(template.status(root), "a.md")
    assert entry["resets_column_widths"] is False


# --- diff --------------------------------------------------------------------


def test_diff_returns_a_unified_diff(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("hand edited\n", encoding="utf-8")
    text = template.diff(root, "a.md")
    assert "-hand edited" in text
    assert "+template v2" in text


def test_diff_against_a_missing_vault_file_diffs_from_empty(one_managed_file):
    root, _ = one_managed_file
    text = template.diff(root, "a.md")
    assert "+template v2" in text


def test_diff_rejects_an_unmanaged_relpath(one_managed_file):
    root, _ = one_managed_file
    with pytest.raises(template.TemplateError):
        template.diff(root, "not-managed.md")


# --- refresh: selection, consent gate, writes -------------------------------


def test_refresh_default_selection_is_silent_refresh_state_only(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("baselined old content\n", encoding="utf-8")
    data = provenance._empty()
    data["template_files"]["a.md"] = provenance.digest(b"baselined old content\n")
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps(data), encoding="utf-8")
    result = template.refresh(root, today="2026-09-03")
    assert result["refreshed"] == ["a.md"]
    assert result["restored"] == []
    assert (root / "a.md").read_text(encoding="utf-8") == "template v2\n"


def test_refresh_needs_consent_without_it_writes_nothing(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("hand edited\n", encoding="utf-8")
    with pytest.raises(template.TemplateError):
        template.refresh(root, files=["a.md"], today="2026-09-03")
    assert (root / "a.md").read_text(encoding="utf-8") == "hand edited\n"


def test_refresh_with_file_and_consent_writes_it(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("hand edited\n", encoding="utf-8")
    result = template.refresh(root, files=["a.md"], consent=True, today="2026-09-03")
    assert result["refreshed"] == ["a.md"]
    assert (root / "a.md").read_text(encoding="utf-8") == "template v2\n"


def test_refresh_restores_a_missing_file_with_consent(one_managed_file):
    root, _ = one_managed_file
    result = template.refresh(root, files=["a.md"], consent=True, today="2026-09-03")
    assert result["restored"] == ["a.md"]
    assert result["refreshed"] == []
    assert (root / "a.md").read_text(encoding="utf-8") == "template v2\n"


def test_refresh_backs_up_the_replaced_file_before_writing(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("hand edited\n", encoding="utf-8")
    result = template.refresh(root, files=["a.md"], consent=True,
                              today="2026-09-03", stamp="2026-09-03-000000")
    backup_path = root / result["backup"] / "a.md"
    assert backup_path.is_file()
    assert backup_path.read_text(encoding="utf-8") == "hand edited\n"


def test_refresh_rebaselines_replaced_and_current_files(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("hand edited\n", encoding="utf-8")
    result = template.refresh(root, files=["a.md"], consent=True, today="2026-09-03")
    assert result["baselined"] == ["a.md"]
    data = provenance.read(root)
    assert data["template_files"]["a.md"] == provenance.template_digest("a.md")


def test_refresh_records_a_template_refresh_event(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("hand edited\n", encoding="utf-8")
    template.refresh(root, files=["a.md"], consent=True, today="2026-09-03")
    data = provenance.read(root)
    last = data["events"][-1]
    assert last["event"] == "template-refresh"
    assert last["refreshed"] == 1
    assert last["restored"] == 0


def test_refresh_writes_one_migration_log_line(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").write_text("hand edited\n", encoding="utf-8")
    template.refresh(root, files=["a.md"], consent=True, today="2026-09-03")
    log_text = (root / "99-workflow-config" / "migration-log.md").read_text(encoding="utf-8")
    assert "template-refresh" in log_text
    assert log_text.count("\n") >= 1


def test_refresh_writes_lf_even_when_the_vault_copy_was_crlf(one_managed_file):
    root, _ = one_managed_file
    with open(root / "a.md", "wb") as handle:
        handle.write(b"hand edited\r\n")
    template.refresh(root, files=["a.md"], consent=True, today="2026-09-03")
    raw = (root / "a.md").read_bytes()
    assert b"\r\n" not in raw
    assert raw == b"template v2\n"


def test_refresh_all_pending_covers_needs_consent_and_missing(tmp_path, monkeypatch):
    fake_root = _fake_template(tmp_path, {"a.md": "template a\n", "b.md": "template b\n"})
    monkeypatch.setattr(template, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(provenance, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(template, "MANAGED_SILENT", frozenset())
    monkeypatch.setattr(template, "MANAGED_CONSENT_ALWAYS", frozenset({"a.md"}))
    monkeypatch.setattr(template, "SEEDED_ONCE", frozenset())
    monkeypatch.setattr(template, "IGNORED", frozenset())
    monkeypatch.setattr(template, "MANAGED", frozenset({"a.md", "b.md"}))
    root = _versioned_vault(tmp_path)
    (root / "a.md").write_text("hand edited\n", encoding="utf-8")
    # b.md left missing entirely.
    result = template.refresh(root, all_pending=True, consent=True, today="2026-09-03")
    assert sorted(result["refreshed"]) == ["a.md"]
    assert sorted(result["restored"]) == ["b.md"]


def test_refresh_first_run_on_an_unknown_baseline_vault_needs_consent_for_everything(
        tmp_path, monkeypatch):
    """A vault that predates provenance: every differing managed file needs
    consent, and --all-pending --consent brings it to a fully recorded
    baseline in one call."""
    fake_root = _fake_template(tmp_path, {"a.md": "template a\n"})
    monkeypatch.setattr(template, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(provenance, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(template, "MANAGED_SILENT", frozenset())
    monkeypatch.setattr(template, "MANAGED_CONSENT_ALWAYS", frozenset({"a.md"}))
    monkeypatch.setattr(template, "SEEDED_ONCE", frozenset())
    monkeypatch.setattr(template, "IGNORED", frozenset())
    monkeypatch.setattr(template, "MANAGED", frozenset({"a.md"}))
    root = _versioned_vault(tmp_path)
    (root / "a.md").write_text("legacy hand-set content\n", encoding="utf-8")
    assert provenance.read(root) is None
    with pytest.raises(template.TemplateError):
        template.refresh(root, all_pending=True, today="2026-09-03")
    result = template.refresh(root, all_pending=True, consent=True, today="2026-09-03")
    assert result["refreshed"] == ["a.md"]
    data = provenance.read(root)
    assert data["template_files"]["a.md"] == provenance.template_digest("a.md")


def test_refresh_rotates_old_backup_dirs_keeping_three_newest(one_managed_file):
    root, _ = one_managed_file
    for stamp in ("2026-09-01-000000", "2026-09-02-000000",
                  "2026-09-03-000000", "2026-09-04-000000"):
        (root / "a.md").write_text("hand edited\n", encoding="utf-8")
        template.refresh(root, files=["a.md"], consent=True, today="2026-09-03", stamp=stamp)
    snapdir = root / "99-workflow-config" / "snapshots"
    remaining = sorted(p.name for p in snapdir.glob("template-refresh-*"))
    assert remaining == [
        "template-refresh-2026-09-02-000000",
        "template-refresh-2026-09-03-000000",
        "template-refresh-2026-09-04-000000",
    ]


def test_refresh_a_seeded_once_file_is_always_refused(tmp_path, monkeypatch):
    fake_root = _fake_template(tmp_path, {"config.json": "{}\n"})
    monkeypatch.setattr(template, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(provenance, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(template, "MANAGED_SILENT", frozenset())
    monkeypatch.setattr(template, "MANAGED_CONSENT_ALWAYS", frozenset())
    monkeypatch.setattr(template, "SEEDED_ONCE", frozenset({"config.json"}))
    monkeypatch.setattr(template, "IGNORED", frozenset())
    monkeypatch.setattr(template, "MANAGED", frozenset({"config.json"}))
    root = _versioned_vault(tmp_path)
    (root / "config.json").write_text('{"edited": true}\n', encoding="utf-8")
    with pytest.raises(template.TemplateError):
        template.refresh(root, files=["config.json"], consent=True, today="2026-09-03")
    assert (root / "config.json").read_text(encoding="utf-8") == '{"edited": true}\n'


def test_refresh_rejects_an_unmanaged_relpath(one_managed_file):
    root, _ = one_managed_file
    with pytest.raises(template.TemplateError):
        template.refresh(root, files=["not-managed.md"], consent=True, today="2026-09-03")


def test_refresh_rejects_a_blocked_selection(one_managed_file):
    root, _ = one_managed_file
    (root / "a.md").mkdir()
    with pytest.raises(template.TemplateError):
        template.refresh(root, files=["a.md"], consent=True, today="2026-09-03")


def test_refresh_a_relpath_missing_from_the_shipped_template_raises(tmp_path, monkeypatch):
    fake_root = _fake_template(tmp_path, {"a.md": "template v2\n"})
    monkeypatch.setattr(template, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(provenance, "TEMPLATE_ROOT", fake_root)
    monkeypatch.setattr(template, "MANAGED_SILENT", frozenset({"a.md", "gone.md"}))
    monkeypatch.setattr(template, "MANAGED_CONSENT_ALWAYS", frozenset())
    monkeypatch.setattr(template, "SEEDED_ONCE", frozenset())
    monkeypatch.setattr(template, "IGNORED", frozenset())
    monkeypatch.setattr(template, "MANAGED", frozenset({"a.md", "gone.md"}))
    root = _versioned_vault(tmp_path)
    with pytest.raises(template.TemplateError):
        template.status(root)
