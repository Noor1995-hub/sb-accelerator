from pathlib import Path
import json

from validate_template import main


def test_missing_template_dir_fails(tmp_path):
    problems = main(tmp_path)
    assert any("template" in p for p in problems)


def test_empty_template_passes(tmp_path):
    (tmp_path / "plugin" / "template").mkdir(parents=True)
    assert main(tmp_path) == []


def test_lone_readme_is_not_a_bootstrap_state(tmp_path):
    """plugin/template/ ships no README of its own — a root README is not exempt."""
    (tmp_path / "plugin" / "template").mkdir(parents=True)
    (tmp_path / "plugin" / "template" / "README.md").write_text("stub", encoding="utf-8")
    problems = main(tmp_path)
    assert any("CLAUDE.md" in p for p in problems)


def test_populated_template_requires_markers(tmp_path):
    t = tmp_path / "plugin" / "template"
    (t / "10-meetings").mkdir(parents=True)
    problems = main(tmp_path)
    assert any("CLAUDE.md" in p for p in problems)
    assert any("structure-version" in p for p in problems)


def make_populated_template(tmp_path):
    t = tmp_path / "plugin" / "template"
    (t / "10-meetings").mkdir(parents=True)
    (t / "CLAUDE.md").write_text(
        "vault instructions\n\n"
        "## Feedback to delaware\n\n"
        "Report only with the user's explicit approval of the exact draft.\n"
        "delaware uses these reports solely to improve the product.\n"
        "Never read or display files under 99-workflow-config/secrets/.\n",
        encoding="utf-8",
    )
    (t / "structure-version").write_text("6\n", encoding="utf-8")
    secrets = t / "99-workflow-config" / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "README.md").write_text("secrets readme", encoding="utf-8")
    return t


def shipping_config() -> dict:
    return {
        "_readme": ["machine-read deployment config"],
        "config-version": 1,
        "timezone": None,
        "owner": None,
        "adapters": {
            "inbox": {"enabled": True},
            "plaud": {"enabled": False, "account_hint": None},
            "m365": {"enabled": False, "account_hint": None, "home_domains": None},
        },
        "feedback": {"repo": None},
        "sync": {"start-date": None},
        "messages": {"enabled": False, "consented-at": None, "scope": [], "exclusions": []},
    }


def write_template_config(t, cfg) -> None:
    folder = t / "99-workflow-config"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


def test_populated_template_with_markers_passes(tmp_path):
    t = make_populated_template(tmp_path)
    write_template_config(t, shipping_config())
    assert main(tmp_path) == []


def test_stale_structure_version_is_flagged(tmp_path):
    """A migration that lands without bumping the template ships new vaults at
    the old version, so /upgrade-vault immediately proposes a migration that
    has nothing to do — and the mismatch is invisible until a client hits it."""
    t = make_populated_template(tmp_path)
    write_template_config(t, shipping_config())
    (t / "structure-version").write_text("1\n", encoding="utf-8")
    problems = main(tmp_path)
    assert any("structure-version" in p and "6" in p for p in problems)


def test_structure_version_tolerates_no_trailing_newline(tmp_path):
    t = make_populated_template(tmp_path)
    write_template_config(t, shipping_config())
    (t / "structure-version").write_text("6", encoding="utf-8")
    assert main(tmp_path) == []


def test_populated_template_requires_secrets_readme(tmp_path):
    t = make_populated_template(tmp_path)
    write_template_config(t, shipping_config())
    (t / "99-workflow-config" / "secrets" / "README.md").unlink()
    problems = main(tmp_path)
    assert any("secrets" in p for p in problems)


def test_claude_md_missing_solely_to_improve_phrase_is_flagged(tmp_path):
    t = make_populated_template(tmp_path)
    write_template_config(t, shipping_config())
    (t / "CLAUDE.md").write_text(
        "vault instructions\nexplicit approval\n99-workflow-config/secrets\n",
        encoding="utf-8",
    )
    problems = main(tmp_path)
    assert any("solely to improve the product" in p for p in problems)


def test_claude_md_missing_explicit_approval_phrase_is_flagged(tmp_path):
    t = make_populated_template(tmp_path)
    write_template_config(t, shipping_config())
    (t / "CLAUDE.md").write_text(
        "vault instructions\nsolely to improve the product\n99-workflow-config/secrets\n",
        encoding="utf-8",
    )
    problems = main(tmp_path)
    assert any("explicit approval" in p for p in problems)


def test_claude_md_missing_secrets_reference_phrase_is_flagged(tmp_path):
    t = make_populated_template(tmp_path)
    write_template_config(t, shipping_config())
    (t / "CLAUDE.md").write_text(
        "vault instructions\nsolely to improve the product\nexplicit approval\n",
        encoding="utf-8",
    )
    problems = main(tmp_path)
    assert any("99-workflow-config/secrets" in p for p in problems)


def test_populated_template_requires_config_json(tmp_path):
    make_populated_template(tmp_path)
    problems = main(tmp_path)
    assert any("config.json" in p for p in problems)


def test_shipping_default_config_passes(tmp_path):
    t = make_populated_template(tmp_path)
    write_template_config(t, shipping_config())
    assert main(tmp_path) == []


def test_template_config_must_not_ship_bound_or_enabled_connectors(tmp_path):
    t = make_populated_template(tmp_path)
    cfg = shipping_config()
    cfg["adapters"]["plaud"] = {"enabled": True, "account_hint": "a@b.c"}
    write_template_config(t, cfg)
    problems = main(tmp_path)
    assert any("plaud" in p for p in problems)


def test_template_config_must_ship_null_identity_values(tmp_path):
    t = make_populated_template(tmp_path)
    cfg = shipping_config()
    cfg["timezone"] = "Europe/Brussels"
    write_template_config(t, cfg)
    problems = main(tmp_path)
    assert any("timezone" in p for p in problems)


def test_template_config_must_carry_readme_commentary(tmp_path):
    t = make_populated_template(tmp_path)
    cfg = shipping_config()
    del cfg["_readme"]
    write_template_config(t, cfg)
    problems = main(tmp_path)
    assert any("_readme" in p for p in problems)


def test_template_config_invalid_json_is_reported(tmp_path):
    t = make_populated_template(tmp_path)
    folder = t / "99-workflow-config"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text("{oops", encoding="utf-8")
    problems = main(tmp_path)
    assert any("valid JSON" in p for p in problems)


def test_template_config_non_object_top_level_is_reported(tmp_path):
    t = make_populated_template(tmp_path)
    folder = t / "99-workflow-config"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text("[1, 2, 3]", encoding="utf-8")
    problems = main(tmp_path)
    assert any("JSON object" in p for p in problems)


def test_template_config_must_ship_feedback_key(tmp_path):
    t = make_populated_template(tmp_path)
    cfg = shipping_config()
    del cfg["feedback"]
    write_template_config(t, cfg)
    problems = main(tmp_path)
    assert any("feedback" in p for p in problems)


def test_template_config_must_ship_null_feedback_repo(tmp_path):
    t = make_populated_template(tmp_path)
    cfg = shipping_config()
    cfg["feedback"] = {"repo": "delaware-org/sb-client-acme"}
    write_template_config(t, cfg)
    problems = main(tmp_path)
    assert any("feedback" in p for p in problems)


def test_template_must_ship_messages_off(tmp_path):
    t = make_populated_template(tmp_path)
    cfg = shipping_config()
    cfg["messages"] = {"enabled": True, "consented-at": None, "scope": [], "exclusions": []}
    write_template_config(t, cfg)
    problems = main(tmp_path)
    assert any("messages" in p for p in problems)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_template_hides_the_messages_folder():
    template = REPO_ROOT / "plugin" / "template"
    nav = json.loads((template / ".obsidian/plugins/notebook-navigator/data.json").read_text(encoding="utf-8"))
    assert "_messages" in nav["vaultProfiles"][0]["hiddenFolders"]
    app = json.loads((template / ".obsidian/app.json").read_text(encoding="utf-8"))
    assert "_messages/" in app["userIgnoreFilters"]
    assert (template / "_messages" / ".gitkeep").is_file()
    assert (template / "structure-version").read_text(encoding="utf-8").strip() == "6"
