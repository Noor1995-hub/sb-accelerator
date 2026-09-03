"""Offline tests for the per-client provisioning script (issue #11).

Every test injects a RecordingRunner (or calls a pure function directly) —
nothing here ever spawns `gh` or touches the network. `provision()` is the
pure orchestration under test; `main()` is exercised only for slug/exit-code
plumbing, still with an injected runner via monkeypatching SubprocessRunner
out of the picture (dry-run always uses RecordingRunner internally).
"""
from datetime import date
from pathlib import Path

import pytest
import yaml

from provision_client import (
    DEFAULT_ORG,
    DuplicateClientError,
    GhCommandError,
    ProvisionOptions,
    RecordingRunner,
    SlugError,
    load_registry,
    provision,
    save_registry,
    token_recipe,
    validate_slug,
)

TODAY = date(2026, 9, 3)


def make_registry(tmp_path: Path, header: str = None) -> Path:
    header = header if header is not None else (
        "# Client deployment registry — one entry per deployed engagement.\n"
        "# v1 is this file; moves to Airtable when client count justifies it (design doc, Phase 2).\n"
        "# Entry shape:\n"
        "#   - client: <client-slug>\n"
        "#     owner: <name or initials>\n"
        "#     plugin_version: <semver deployed>\n"
        "#     structure_version: <template structure-version deployed>\n"
        "#     archetype: commercial-leader\n"
        "#     care_package: active | lapsed | none\n"
        "#     notes: \"\"\n"
    )
    path = tmp_path / "registry.yaml"
    path.write_text(header + "clients: []\n", encoding="utf-8")
    return path


def base_opts(slug="acme", **overrides) -> ProvisionOptions:
    fields = dict(
        slug=slug,
        owner="MB",
        delivery_path="E",
        dist_channel="client",
        archetype="commercial-leader",
        care_package="active",
        notes="",
        register_only=False,
        update=False,
        dry_run=False,
        org=DEFAULT_ORG,
    )
    fields.update(overrides)
    return ProvisionOptions(**fields)


# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slug", ["acme", "acme-industries", "a1", "ab" + "c" * 38])
def test_valid_slugs_pass(slug):
    assert validate_slug(slug) == slug


@pytest.mark.parametrize("slug", [
    "", "a", "Acme", "acme_industries", "-acme", "acme!", "a" * 41, "ACME",
])
def test_invalid_slugs_raise(slug):
    with pytest.raises(SlugError):
        validate_slug(slug)


# ---------------------------------------------------------------------------
# Registry header round-trip
# ---------------------------------------------------------------------------

def test_load_registry_keeps_header_verbatim(tmp_path):
    registry_path = make_registry(tmp_path)
    original_header = registry_path.read_text(encoding="utf-8").split("clients:")[0]
    registry = load_registry(registry_path)
    assert registry["header"] == original_header
    assert registry["clients"] == []


def test_save_registry_round_trips_header_and_appends_entry(tmp_path):
    registry_path = make_registry(tmp_path)
    original_header = registry_path.read_text(encoding="utf-8").split("clients:")[0]
    registry = load_registry(registry_path)
    registry["clients"].append({"client": "acme", "owner": "MB"})
    save_registry(registry_path, registry)

    text = registry_path.read_text(encoding="utf-8")
    assert text.startswith(original_header)
    reloaded = yaml.safe_load(text)
    assert reloaded["clients"] == [{"client": "acme", "owner": "MB"}]


# ---------------------------------------------------------------------------
# provision(): registry bookkeeping
# ---------------------------------------------------------------------------

def test_provision_appends_new_client_with_exact_key_set(tmp_path):
    registry_path = make_registry(tmp_path)
    runner = RecordingRunner()
    result = provision(base_opts(), runner, registry_path, TODAY)

    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert len(registry["clients"]) == 1
    entry = registry["clients"][0]
    assert set(entry.keys()) == {
        "client", "owner", "plugin_version", "structure_version", "archetype",
        "care_package", "delivery_path", "feedback_repo", "dist_channel",
        "provisioned", "notes",
    }
    assert entry["client"] == "acme"
    assert entry["owner"] == "MB"
    assert entry["feedback_repo"] == f"{DEFAULT_ORG}/sb-client-acme"
    assert entry["delivery_path"] == "E"
    assert entry["dist_channel"] == "client"
    assert entry["provisioned"] == "2026-09-03"
    assert result["feedback_repo"] == f"{DEFAULT_ORG}/sb-client-acme"


def test_duplicate_slug_refused_without_update(tmp_path):
    registry_path = make_registry(tmp_path)
    runner = RecordingRunner()
    provision(base_opts(), runner, registry_path, TODAY)

    with pytest.raises(DuplicateClientError):
        provision(base_opts(), RecordingRunner(), registry_path, TODAY)


def test_update_replaces_existing_entry(tmp_path):
    registry_path = make_registry(tmp_path)
    provision(base_opts(notes="first"), RecordingRunner(), registry_path, TODAY)

    provision(base_opts(notes="second", update=True), RecordingRunner(), registry_path,
              date(2026, 9, 10))

    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert len(registry["clients"]) == 1
    assert registry["clients"][0]["notes"] == "second"
    assert registry["clients"][0]["provisioned"] == "2026-09-10"


# ---------------------------------------------------------------------------
# provision(): gh call ordering and idempotence
# ---------------------------------------------------------------------------

def test_dry_run_records_ordered_gh_calls_with_no_subprocess(tmp_path):
    registry_path = make_registry(tmp_path)
    runner = RecordingRunner()
    result = provision(base_opts(dry_run=True), runner, registry_path, TODAY)

    call_shapes = [tuple(c["args"][:2]) for c in runner.calls]
    assert call_shapes[0] == ("repo", "view")
    assert call_shapes[1] == ("repo", "create")
    # Two seed files, each a GET then a PUT.
    api_calls = [c["args"] for c in runner.calls if c["args"][0] == "api"]
    assert len(api_calls) == 4
    assert api_calls[0][:2] == ["api", f"repos/{DEFAULT_ORG}/sb-client-acme/contents/README.md"]
    assert api_calls[1][:3] == ["api", "-X", "PUT"]
    assert api_calls[2][:2] == [
        "api", f"repos/{DEFAULT_ORG}/sb-client-acme/contents/.github/ISSUE_TEMPLATE/feedback.md"]
    assert api_calls[3][:3] == ["api", "-X", "PUT"]
    label_calls = [c["args"] for c in runner.calls if c["args"][0] == "label"]
    assert len(label_calls) == 6

    # dry-run must not touch registry.yaml at all.
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert registry["clients"] == []
    assert result["registered"] is False


def test_existing_repo_skips_create(tmp_path):
    registry_path = make_registry(tmp_path)
    runner = RecordingRunner(existing_repo=True)
    provision(base_opts(dry_run=True), runner, registry_path, TODAY)

    kinds = [tuple(c["args"][:2]) for c in runner.calls]
    assert ("repo", "create") not in kinds
    assert ("repo", "view") in kinds


def test_existing_readme_skips_put_but_still_seeds_other_file(tmp_path):
    registry_path = make_registry(tmp_path)
    runner = RecordingRunner(existing_paths=["README.md"])
    provision(base_opts(dry_run=True), runner, registry_path, TODAY)

    put_targets = [c["args"][3] for c in runner.calls
                   if c["args"][0] == "api" and "-X" in c["args"]]
    assert not any(t.endswith("contents/README.md") for t in put_targets)
    assert any(t.endswith("contents/.github/ISSUE_TEMPLATE/feedback.md") for t in put_targets)


def test_register_only_makes_zero_gh_calls(tmp_path):
    registry_path = make_registry(tmp_path)
    runner = RecordingRunner()
    result = provision(base_opts(register_only=True), runner, registry_path, TODAY)

    assert runner.calls == []
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert len(registry["clients"]) == 1
    assert result["registered"] is True


def test_gh_command_error_propagates(tmp_path):
    registry_path = make_registry(tmp_path)

    class FailingRunner:
        def run(self, args, input=None):
            raise GhCommandError(args, 1, "boom")

    with pytest.raises(GhCommandError):
        provision(base_opts(), FailingRunner(), registry_path, TODAY)


# ---------------------------------------------------------------------------
# Token recipe text
# ---------------------------------------------------------------------------

def test_recipe_names_repo_scopes_and_secrets_path():
    text = token_recipe(f"{DEFAULT_ORG}/sb-client-acme", "acme", DEFAULT_ORG)
    assert f"{DEFAULT_ORG}/sb-client-acme" in text or "sb-client-acme" in text
    assert "Issues" in text
    assert "no Contents" in text
    assert "1 year" in text or "1-year" in text
    assert "99-workflow-config/secrets/feedback-token" in text
    assert "feedback.repo" in text
