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

import provision_client
from provision_client import (
    DEFAULT_ORG,
    DuplicateClientError,
    GhCommandError,
    MissingOwnerError,
    ProvisionOptions,
    RecordingRunner,
    SlugError,
    UnknownClientError,
    load_registry,
    provision,
    resolve_token_minted,
    save_registry,
    token_recipe,
    validate_slug,
)

TODAY = date(2026, 9, 3)
# A later tune-up: far enough from TODAY that a re-stamped date is unmistakable.
LATER = date(2027, 3, 14)


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


def update_opts(slug="acme", **overrides) -> ProvisionOptions:
    """What a consultant actually types at a tune-up: the slug, `--update`,
    and only the fields that changed. Every other field stays `None`, so a
    test built on this helper fails the moment an unstated field is
    overwritten with a default instead of the registered value."""
    fields = dict(slug=slug, update=True, register_only=True)
    fields.update(overrides)
    return ProvisionOptions(**fields)


def only_client(registry_path: Path) -> dict:
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    assert len(registry["clients"]) == 1
    return registry["clients"][0]


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
        "provisioned", "token_minted", "notes",
    }
    assert entry["client"] == "acme"
    assert entry["owner"] == "MB"
    assert entry["feedback_repo"] == f"{DEFAULT_ORG}/sb-client-acme"
    assert entry["delivery_path"] == "E"
    assert entry["dist_channel"] == "client"
    assert entry["provisioned"] == "2026-09-03"
    # Setup day is token day: the two dates only diverge at a later rotation.
    assert entry["token_minted"] == "2026-09-03"
    assert result["feedback_repo"] == f"{DEFAULT_ORG}/sb-client-acme"


def test_create_uses_defaults_for_flags_left_off(tmp_path):
    registry_path = make_registry(tmp_path)
    provision(ProvisionOptions(slug="acme", owner="MB", register_only=True),
              RecordingRunner(), registry_path, TODAY)

    entry = only_client(registry_path)
    assert entry["delivery_path"] == "E"
    assert entry["dist_channel"] == "client"
    assert entry["archetype"] == "commercial-leader"
    assert entry["care_package"] == "active"
    assert entry["notes"] == ""


def test_create_without_owner_raises(tmp_path):
    registry_path = make_registry(tmp_path)

    with pytest.raises(MissingOwnerError):
        provision(ProvisionOptions(slug="acme", register_only=True),
                  RecordingRunner(), registry_path, TODAY)


def test_duplicate_slug_refused_without_update(tmp_path):
    registry_path = make_registry(tmp_path)
    runner = RecordingRunner()
    provision(base_opts(), runner, registry_path, TODAY)

    with pytest.raises(DuplicateClientError):
        provision(base_opts(), RecordingRunner(), registry_path, TODAY)


def test_update_applies_the_fields_given(tmp_path):
    registry_path = make_registry(tmp_path)
    provision(base_opts(notes="first"), RecordingRunner(), registry_path, TODAY)

    provision(update_opts(notes="second", care_package="lapsed"),
              RecordingRunner(), registry_path, LATER)

    entry = only_client(registry_path)
    assert entry["notes"] == "second"
    assert entry["care_package"] == "lapsed"


def test_update_never_moves_the_provisioned_date(tmp_path):
    """The deployment's birth date. Recording a version bump at a later
    tune-up must not claim the client was stood up that day."""
    registry_path = make_registry(tmp_path)
    provision(base_opts(), RecordingRunner(), registry_path, TODAY)

    provision(update_opts(), RecordingRunner(), registry_path, LATER)

    assert only_client(registry_path)["provisioned"] == "2026-09-03"


def test_update_keeps_fields_not_given_on_the_command_line(tmp_path):
    registry_path = make_registry(tmp_path)
    provision(base_opts(owner="AB", delivery_path="A", dist_channel="dryrun",
                        archetype="trial", care_package="lapsed", notes="exco pilot"),
              RecordingRunner(), registry_path, TODAY)

    provision(update_opts(), RecordingRunner(), registry_path, LATER)

    entry = only_client(registry_path)
    assert entry["owner"] == "AB"
    assert entry["delivery_path"] == "A"
    assert entry["dist_channel"] == "dryrun"
    assert entry["archetype"] == "trial"
    assert entry["care_package"] == "lapsed"
    assert entry["notes"] == "exco pilot"


def test_update_refreshes_the_version_stamps(tmp_path, monkeypatch):
    """The one thing a bare `--update` is *for*: restamping what's deployed
    from the plugin manifest in this checkout."""
    registry_path = make_registry(tmp_path)
    provision(base_opts(), RecordingRunner(), registry_path, TODAY)

    monkeypatch.setattr(provision_client, "_plugin_version", lambda: "9.9.9")
    monkeypatch.setattr(provision_client, "_structure_version", lambda: "7")
    provision(update_opts(), RecordingRunner(), registry_path, LATER)

    entry = only_client(registry_path)
    assert entry["plugin_version"] == "9.9.9"
    assert entry["structure_version"] == "7"


def test_update_on_unknown_slug_raises(tmp_path):
    """--update is for an entry that exists; a typo'd slug must not quietly
    create a half-empty row now that --owner is optional."""
    registry_path = make_registry(tmp_path)
    provision(base_opts(), RecordingRunner(), registry_path, TODAY)

    with pytest.raises(UnknownClientError):
        provision(update_opts(slug="acmee"), RecordingRunner(), registry_path, LATER)

    assert only_client(registry_path)["client"] == "acme"


def test_update_keeps_the_registered_org(tmp_path):
    """`--org` is an entry field like any other: a deployment registered in a
    non-default org must not have `feedback_repo` rewritten to the default
    one by a bare --update — and the gh calls must target the same repo."""
    registry_path = make_registry(tmp_path)
    provision(base_opts(org="ACME-CORP"), RecordingRunner(), registry_path, TODAY)

    runner = RecordingRunner(existing_repo=True)
    result = provision(update_opts(register_only=False), runner, registry_path, LATER)

    assert only_client(registry_path)["feedback_repo"] == "ACME-CORP/sb-client-acme"
    assert result["feedback_repo"] == "ACME-CORP/sb-client-acme"
    assert "ACME-CORP" in result["recipe"]
    assert all("DLW-INT-BTA-BELUX" not in " ".join(c["args"]) for c in runner.calls)


def test_update_can_still_move_a_deployment_to_another_org(tmp_path):
    registry_path = make_registry(tmp_path)
    provision(base_opts(org="ACME-CORP"), RecordingRunner(), registry_path, TODAY)

    provision(update_opts(org="NEW-CORP"), RecordingRunner(), registry_path, LATER)

    assert only_client(registry_path)["feedback_repo"] == "NEW-CORP/sb-client-acme"


def test_update_of_a_row_with_no_feedback_repo_falls_back_to_the_default_org(tmp_path):
    registry_path = make_registry(tmp_path)
    registry = load_registry(registry_path)
    registry["clients"].append({"client": "acme", "owner": "MB"})
    save_registry(registry_path, registry)

    provision(update_opts(), RecordingRunner(), registry_path, LATER)

    assert only_client(registry_path)["feedback_repo"] == f"{DEFAULT_ORG}/sb-client-acme"


# ---------------------------------------------------------------------------
# provision(): the token clock
# ---------------------------------------------------------------------------

def test_token_minted_flag_moves_only_the_token_date(tmp_path):
    registry_path = make_registry(tmp_path)
    provision(base_opts(), RecordingRunner(), registry_path, TODAY)

    provision(update_opts(token_minted=LATER), RecordingRunner(), registry_path, LATER)

    entry = only_client(registry_path)
    assert entry["token_minted"] == "2027-03-14"
    assert entry["provisioned"] == "2026-09-03"


def test_update_leaves_the_token_date_alone_by_default(tmp_path):
    registry_path = make_registry(tmp_path)
    provision(base_opts(), RecordingRunner(), registry_path, TODAY)

    provision(update_opts(), RecordingRunner(), registry_path, LATER)

    assert only_client(registry_path)["token_minted"] == "2026-09-03"


def test_update_backfills_token_minted_on_a_row_that_predates_the_field(tmp_path):
    """A row written before `token_minted` existed. Its best-known clock
    start is the provisioning date, which is what the old single field meant."""
    registry_path = make_registry(tmp_path)
    registry = load_registry(registry_path)
    registry["clients"].append({
        "client": "acme", "owner": "MB", "plugin_version": "0.1.0",
        "structure_version": "2", "archetype": "commercial-leader",
        "care_package": "active", "delivery_path": "E",
        "feedback_repo": f"{DEFAULT_ORG}/sb-client-acme",
        "dist_channel": "client", "provisioned": "2026-01-05", "notes": "",
    })
    save_registry(registry_path, registry)

    provision(update_opts(), RecordingRunner(), registry_path, LATER)

    entry = only_client(registry_path)
    assert entry["token_minted"] == "2026-01-05"
    assert entry["provisioned"] == "2026-01-05"


def test_update_of_a_row_missing_provisioned_stamps_today(tmp_path):
    """Defensive: a hand-edited row with no birth date at all gets one
    rather than serialising `None` into the registry."""
    registry_path = make_registry(tmp_path)
    registry = load_registry(registry_path)
    registry["clients"].append({"client": "acme", "owner": "MB"})
    save_registry(registry_path, registry)

    provision(update_opts(), RecordingRunner(), registry_path, LATER)

    entry = only_client(registry_path)
    assert entry["provisioned"] == "2027-03-14"
    assert entry["token_minted"] == "2027-03-14"


@pytest.mark.parametrize("raw,expected", [
    (None, None),
    ("today", LATER),
    ("2026-12-01", date(2026, 12, 1)),
])
def test_resolve_token_minted(raw, expected):
    assert resolve_token_minted(raw, LATER) == expected


def test_resolve_token_minted_rejects_a_malformed_date():
    with pytest.raises(ValueError):
        resolve_token_minted("14/03/2027", LATER)


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
