"""TDD for plugin/lib/vaultlib/provenance.py — the CLI-owned vault
provenance record (99-workflow-config/provenance.json).

record_provision's "all 45" test copies the plugin's own shipped template
verbatim (the same tree instantiate_vault.instantiate() copies in
production) rather than a synthetic fixture — the count is a property of
the real template, and a synthetic tree would prove nothing about it.
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from vaultlib import provenance, template

from test_vaultlib_vault import make_vault

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_ROOT = REPO_ROOT / "plugin" / "template"


def _versioned_vault(tmp_path, version="2"):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text(f"{version}\n", encoding="utf-8")
    return root


def _symlinks_supported() -> bool:
    """Mirrors test_make_test_vault.py's probe: Windows without Developer
    Mode or elevation refuses os.symlink, which is the default on a CI
    runner, so the symlink-state test must skip there rather than fail."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink("target", Path(tmp) / "probe")
        except (OSError, NotImplementedError, AttributeError):
            return False
    return True


SYMLINKS_SUPPORTED = _symlinks_supported()


# --- digest: CRLF normalisation ---------------------------------------


def test_digest_normalises_crlf_to_lf():
    assert provenance.digest(b"a\r\nb\n") == provenance.digest(b"a\nb\n")


def test_digest_differs_for_different_content():
    assert provenance.digest(b"a\n") != provenance.digest(b"b\n")


# --- template_digest / vault_digest -------------------------------------


def test_template_digest_matches_shipped_bytes():
    rel = "Start here.md"
    expected = provenance.digest((TEMPLATE_ROOT / rel).read_bytes())
    assert provenance.template_digest(rel) == expected


def test_vault_digest_reads_the_vaults_own_copy(tmp_path):
    root = _versioned_vault(tmp_path)
    (root / "CLAUDE.md").write_text("hello\n", encoding="utf-8")
    assert provenance.vault_digest(root, "CLAUDE.md") == provenance.digest(b"hello\n")


def test_vault_digest_raises_for_a_missing_file(tmp_path):
    root = _versioned_vault(tmp_path)
    with pytest.raises(OSError):
        provenance.vault_digest(root, "does-not-exist.md")


# --- read: absent / malformed -------------------------------------------


def test_read_returns_none_when_the_file_is_absent(tmp_path):
    root = _versioned_vault(tmp_path)
    assert provenance.read(root) is None


def test_read_raises_on_invalid_json(tmp_path):
    root = _versioned_vault(tmp_path)
    (root / "99-workflow-config" / "provenance.json").write_text(
        "{not json", encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError):
        provenance.read(root)


def test_read_raises_on_missing_required_keys(tmp_path):
    root = _versioned_vault(tmp_path)
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps({"provenance-version": 1}), encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError):
        provenance.read(root)


def test_read_raises_on_unknown_version(tmp_path):
    root = _versioned_vault(tmp_path)
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps({"provenance-version": 99, "events": [], "template_files": {}}),
        encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError, match="provenance-version"):
        provenance.read(root)


def test_read_returns_the_parsed_dict_when_well_formed(tmp_path):
    root = _versioned_vault(tmp_path)
    payload = {"provenance-version": 1, "events": [], "template_files": {}}
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps(payload), encoding="utf-8")
    assert provenance.read(root) == payload


def test_read_raises_when_an_event_is_not_an_object(tmp_path):
    """Reviewer finding #1: {"events": ["oops"]} passed the old `isinstance(
    events, list)` check, and the first caller to do `event.get("event")`
    (health._provenance_block, cli.py's provenance read) raised AttributeError
    or TypeError instead of the briefed ProvenanceError -> malformed:true."""
    root = _versioned_vault(tmp_path)
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps({"provenance-version": 1, "events": ["oops"],
                    "template_files": {}}),
        encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError, match="events"):
        provenance.read(root)


def test_read_raises_when_a_template_files_value_is_not_a_string(tmp_path):
    root = _versioned_vault(tmp_path)
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps({"provenance-version": 1, "events": [],
                    "template_files": {"CLAUDE.md": 123}}),
        encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError, match="template_files"):
        provenance.read(root)


def test_read_raises_when_a_template_files_key_is_not_a_string_value_pair(tmp_path):
    """Belt-and-suspenders on the same shape: JSON object keys are always
    strings, so this exercises a non-string *value* the way Obsidian's own
    property panel could never produce but a hand-edit could."""
    root = _versioned_vault(tmp_path)
    (root / "99-workflow-config" / "provenance.json").write_text(
        json.dumps({"provenance-version": 1, "events": [],
                    "template_files": {"CLAUDE.md": None}}),
        encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError, match="template_files"):
        provenance.read(root)


# --- record_event ---------------------------------------------------------


def test_record_event_creates_the_file_on_first_call(tmp_path):
    root = _versioned_vault(tmp_path)
    entry = provenance.record_event(root, "provision", at="2026-09-03T09:12:00Z",
                                     structure_version="2")
    assert entry["event"] == "provision"
    assert entry["at"] == "2026-09-03T09:12:00Z"
    assert entry["structure_version"] == "2"
    assert "plugin_version" in entry
    data = provenance.read(root)
    assert data["events"] == [entry]
    assert data["template_files"] == {}


def test_record_event_appends_without_disturbing_earlier_events(tmp_path):
    root = _versioned_vault(tmp_path)
    provenance.record_event(root, "provision", at="2026-09-01T00:00:00Z",
                             structure_version="2")
    provenance.record_event(root, "upgrade", at="2026-09-02T00:00:00Z",
                             structure_version="3", from_structure_version="2")
    data = provenance.read(root)
    assert [e["event"] for e in data["events"]] == ["provision", "upgrade"]
    assert data["events"][1]["from_structure_version"] == "2"


def test_record_event_defaults_at_to_now_when_omitted(tmp_path):
    root = _versioned_vault(tmp_path)
    entry = provenance.record_event(root, "provision", structure_version="2")
    assert entry["at"].endswith("Z")


def test_record_event_is_written_with_sorted_keys_and_indent(tmp_path):
    root = _versioned_vault(tmp_path)
    provenance.record_event(root, "provision", at="2026-09-03T09:12:00Z",
                             structure_version="2")
    raw = (root / "99-workflow-config" / "provenance.json").read_text(encoding="utf-8")
    assert raw == json.dumps(json.loads(raw), indent=2, sort_keys=True) + "\n"


# --- rebaseline -------------------------------------------------------------


def test_rebaseline_records_a_matching_file(tmp_path):
    root = _versioned_vault(tmp_path)
    rel = "CLAUDE.md"
    (root / rel).write_text((TEMPLATE_ROOT / rel).read_text(encoding="utf-8"),
                            encoding="utf-8")
    result = provenance.rebaseline(root, [rel])
    assert result == {"baselined": [rel], "skipped": []}
    data = provenance.read(root)
    assert data["template_files"][rel] == provenance.template_digest(rel)


def test_rebaseline_skips_a_file_that_differs_from_the_template(tmp_path):
    root = _versioned_vault(tmp_path)
    rel = "CLAUDE.md"
    (root / rel).write_text("locally edited\n", encoding="utf-8")
    result = provenance.rebaseline(root, [rel])
    assert result == {"baselined": [], "skipped": [rel]}
    data = provenance.read(root)
    assert rel not in data["template_files"]


def test_rebaseline_skips_a_missing_file(tmp_path):
    root = _versioned_vault(tmp_path)
    result = provenance.rebaseline(root, ["does-not-exist.md"])
    assert result == {"baselined": [], "skipped": ["does-not-exist.md"]}


def test_rebaseline_leaves_earlier_events_and_entries_untouched(tmp_path):
    root = _versioned_vault(tmp_path)
    provenance.record_event(root, "provision", at="2026-09-01T00:00:00Z",
                             structure_version="2")
    rel = "CLAUDE.md"
    (root / rel).write_text((TEMPLATE_ROOT / rel).read_text(encoding="utf-8"),
                            encoding="utf-8")
    provenance.rebaseline(root, [rel])
    data = provenance.read(root)
    assert len(data["events"]) == 1
    assert data["events"][0]["event"] == "provision"


# --- record_provision -------------------------------------------------------


def test_record_provision_records_all_35_shipped_files(tmp_path):
    # len(template.ALL_TIERED) is the single source of truth for this count
    # — #117's shared constant, so this file and test_vaultlib_template.py
    # cannot drift apart on what "the shipped template" contains.
    target = tmp_path / "vault"
    shutil.copytree(TEMPLATE_ROOT, target)
    status = provenance.record_provision(target, TEMPLATE_ROOT,
                                         at="2026-09-03T09:12:00Z")
    assert status == provenance.PROVENANCE_RELPATH.as_posix()
    data = provenance.read(target)
    assert len(data["template_files"]) == len(template.ALL_TIERED)
    for rel, recorded_digest in data["template_files"].items():
        assert recorded_digest == provenance.digest((TEMPLATE_ROOT / rel).read_bytes())
    assert data["events"][-1] == {
        "event": "provision", "at": "2026-09-03T09:12:00Z",
        "plugin_version": data["events"][-1]["plugin_version"],
        "structure_version": "12",
    }


def test_record_provision_only_records_files_that_match_the_vault_copy(tmp_path):
    target = tmp_path / "vault"
    shutil.copytree(TEMPLATE_ROOT, target)
    (target / "CLAUDE.md").write_text("edited before provenance ran\n",
                                      encoding="utf-8")
    provenance.record_provision(target, TEMPLATE_ROOT)
    data = provenance.read(target)
    assert "CLAUDE.md" not in data["template_files"]
    assert len(data["template_files"]) == len(template.ALL_TIERED) - 1


def test_record_provision_never_raises_on_a_bad_root(tmp_path):
    status = provenance.record_provision(tmp_path / "nope", TEMPLATE_ROOT)
    assert status.startswith("failed — ")


# --- compare_versions --------------------------------------------------


@pytest.mark.parametrize("recorded, running, expected", [
    ("0.10.24", "0.10.24", "matches"),
    ("0.10.9", "0.10.24", "behind"),
    ("0.10.24", "0.10.9", "ahead"),
    (None, "0.10.24", "unknown"),
    ("not-a-version", "0.10.24", "unknown"),
    ("0.10.24", "unknown", "unknown"),
])
def test_compare_versions(recorded, running, expected):
    assert provenance.compare_versions(recorded, running) == expected


# --- claude_link_state ---------------------------------------------------


def test_claude_link_state_missing(tmp_path):
    root = _versioned_vault(tmp_path)
    assert provenance.claude_link_state(root) == {"is_symlink": False,
                                                   "state": "missing"}


def test_claude_link_state_directory_the_onedrive_case(tmp_path):
    root = _versioned_vault(tmp_path)
    (root / ".claude").mkdir()
    assert provenance.claude_link_state(root) == {"is_symlink": False,
                                                   "state": "directory"}


def test_claude_link_state_other(tmp_path):
    root = _versioned_vault(tmp_path)
    (root / ".claude").write_text("x", encoding="utf-8")
    assert provenance.claude_link_state(root) == {"is_symlink": False,
                                                   "state": "other"}


@pytest.mark.skipif(
    not SYMLINKS_SUPPORTED,
    reason="platform does not permit symlink creation (Windows without "
           "Developer Mode)",
)
def test_claude_link_state_symlink(tmp_path):
    root = _versioned_vault(tmp_path)
    (root / "claude").mkdir()
    os.symlink("claude", root / ".claude")
    assert provenance.claude_link_state(root) == {"is_symlink": True,
                                                   "state": "symlink"}


# --- drift ---------------------------------------------------------------
# The single helper cli.py's `provenance read` and health._provenance_block
# both call, so the two cannot compute plugin drift differently (#117
# absorb of a Task B review finding).


def test_drift_is_unknown_for_no_provenance_at_all():
    assert provenance.drift(None) == "unknown"


def test_drift_is_unknown_for_an_empty_events_list():
    assert provenance.drift({"events": []}) == "unknown"


def test_drift_is_unknown_when_the_last_event_has_no_plugin_version():
    """Defensive against a hand-edited or partially-written event, the
    same shape a subscript (`events[-1]["plugin_version"]`) would raise
    KeyError on instead of folding to "unknown"."""
    assert provenance.drift({"events": [{"event": "provision"}]}) == "unknown"


def test_drift_matches_reads_the_last_events_plugin_version(monkeypatch):
    monkeypatch.setattr(provenance.vault, "plugin_version", lambda: "0.10.24")
    data = {"events": [{"event": "provision", "plugin_version": "0.10.9"},
                        {"event": "upgrade", "plugin_version": "0.10.24"}]}
    assert provenance.drift(data) == "matches"


def test_drift_behind_when_the_recorded_version_is_older(monkeypatch):
    monkeypatch.setattr(provenance.vault, "plugin_version", lambda: "0.10.24")
    assert provenance.drift(
        {"events": [{"event": "provision", "plugin_version": "0.10.9"}]}
    ) == "behind"
