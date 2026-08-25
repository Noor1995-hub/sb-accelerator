from pathlib import Path
import json

from validate_template import main


def test_missing_template_dir_fails(tmp_path):
    problems = main(tmp_path)
    assert any("template" in p for p in problems)


def test_readme_only_template_passes(tmp_path):
    (tmp_path / "template").mkdir()
    (tmp_path / "template" / "README.md").write_text("stub", encoding="utf-8")
    assert main(tmp_path) == []


def test_populated_template_requires_markers(tmp_path):
    t = tmp_path / "template"
    (t / "10-meetings").mkdir(parents=True)
    problems = main(tmp_path)
    assert any("CLAUDE.md" in p for p in problems)
    assert any("structure-version" in p for p in problems)


def make_populated_template(tmp_path):
    t = tmp_path / "template"
    (t / "10-meetings").mkdir(parents=True)
    (t / "CLAUDE.md").write_text("vault instructions", encoding="utf-8")
    (t / "structure-version").write_text("1\n", encoding="utf-8")
    return t


def shipping_config() -> dict:
    return {
        "_readme": ["machine-read deployment config"],
        "config-version": 1,
        "timezone": None,
        "executive": None,
        "adapters": {
            "inbox": {"enabled": True},
            "plaud": {"enabled": False, "account_hint": None},
            "m365": {"enabled": False, "account_hint": None},
        },
    }


def write_template_config(t, cfg) -> None:
    folder = t / "99-workflow-config"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


def test_populated_template_with_markers_passes(tmp_path):
    t = tmp_path / "template"
    (t / "10-meetings").mkdir(parents=True)
    (t / "CLAUDE.md").write_text("vault instructions", encoding="utf-8")
    (t / "structure-version").write_text("1\n", encoding="utf-8")
    write_template_config(t, shipping_config())
    assert main(tmp_path) == []


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
