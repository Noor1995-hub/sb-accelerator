"""Deployment config: strict shape validation, honest completeness report.

The config is the deterministic half of 99-workflow-config — a typo'd key
must fail loudly, because a silently-ignored key here disables a safety
guard (account binding) without anyone noticing.
"""
import json

import pytest

from vaultlib import config

from test_vaultlib_vault import make_vault


def write_config(root, payload) -> None:
    path = root / "99-workflow-config" / "config.json"
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")


def valid_config(**overrides) -> dict:
    cfg = {
        "config-version": 1,
        "timezone": "Europe/Brussels",
        "executive": "morgan-ellery",
        "adapters": {
            "inbox": {"enabled": True},
            "plaud": {"enabled": True, "account_hint": "morgan@example.com"},
            "m365": {"enabled": False, "account_hint": None},
        },
    }
    cfg.update(overrides)
    return cfg


def test_read_returns_config_and_empty_missing_when_complete(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    result = config.read(root)
    assert result["config"]["timezone"] == "Europe/Brussels"
    assert result["config"]["executive"] == "morgan-ellery"
    assert result["missing"] == []


def test_read_ignores_underscore_keys(tmp_path):
    root = make_vault(tmp_path)
    cfg = valid_config()
    cfg["_readme"] = ["human explanation"]
    write_config(root, cfg)
    result = config.read(root)
    assert "_readme" not in result["config"]


def test_read_reports_nulls_as_missing_not_errors(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config(timezone=None, executive=None))
    result = config.read(root)
    assert result["missing"] == ["executive", "timezone"]


def test_read_reports_missing_hint_only_for_enabled_connectors(tmp_path):
    root = make_vault(tmp_path)
    cfg = valid_config()
    cfg["adapters"]["plaud"] = {"enabled": True, "account_hint": None}
    cfg["adapters"]["m365"] = {"enabled": False, "account_hint": None}
    write_config(root, cfg)
    result = config.read(root)
    assert result["missing"] == ["adapters.plaud.account_hint"]


def test_read_fails_when_file_is_absent(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(config.ConfigError, match="missing"):
        config.read(root)


def test_read_fails_on_malformed_json(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, "{not json")
    with pytest.raises(config.ConfigError, match="not valid JSON"):
        config.read(root)


def test_read_fails_on_non_object_document(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, "[1, 2]")
    with pytest.raises(config.ConfigError, match="JSON object"):
        config.read(root)


def test_read_fails_on_unknown_version(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config(**{"config-version": 2}))
    with pytest.raises(config.ConfigError, match="config-version"):
        config.read(root)


def test_read_fails_on_unknown_top_level_key(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config(timzeone="oops"))
    with pytest.raises(config.ConfigError, match="timzeone"):
        config.read(root)


def test_read_fails_on_missing_top_level_key(tmp_path):
    root = make_vault(tmp_path)
    cfg = valid_config()
    del cfg["executive"]
    write_config(root, cfg)
    with pytest.raises(config.ConfigError, match="executive"):
        config.read(root)


def test_read_fails_on_wrong_adapter_set(tmp_path):
    root = make_vault(tmp_path)
    cfg = valid_config()
    del cfg["adapters"]["m365"]
    with pytest.raises(config.ConfigError, match="adapters"):
        write_config(root, cfg)
        config.read(root)


def test_read_fails_on_unknown_adapter_key(tmp_path):
    root = make_vault(tmp_path)
    cfg = valid_config()
    cfg["adapters"]["inbox"]["account_hint"] = "x"  # inbox has no account
    write_config(root, cfg)
    with pytest.raises(config.ConfigError, match="inbox"):
        config.read(root)


def test_read_fails_on_non_bool_enabled(tmp_path):
    root = make_vault(tmp_path)
    cfg = valid_config()
    cfg["adapters"]["plaud"]["enabled"] = "yes"
    write_config(root, cfg)
    with pytest.raises(config.ConfigError, match="enabled"):
        config.read(root)


def test_read_fails_on_empty_string_values(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config(timezone="  "))
    with pytest.raises(config.ConfigError, match="timezone"):
        config.read(root)


def test_read_rejects_display_name_shaped_hint(tmp_path):
    # E2E finding: Plaud's whoami carries the nickname as a string scalar,
    # so a display-name hint would false-accept any account with that
    # nickname. Hints must look like identifiers.
    root = make_vault(tmp_path)
    cfg = valid_config()
    cfg["adapters"]["plaud"]["account_hint"] = "Morgan"
    write_config(root, cfg)
    with pytest.raises(config.ConfigError, match="display name"):
        config.read(root)


def test_read_accepts_identifier_shaped_hints(tmp_path):
    # An email, a hex account id, and a synthetic connector address all
    # qualify — anything with an @ or a digit.
    root = make_vault(tmp_path)
    for hint in ("morgan@example.com",
                 "6263672983f3421c8ae7a871410aea2c",
                 "apple-001738.9cef@plaud.ai"):
        cfg = valid_config()
        cfg["adapters"]["plaud"]["account_hint"] = hint
        write_config(root, cfg)
        assert config.read(root)["config"]["adapters"]["plaud"]["account_hint"] == hint


def bound_vault(tmp_path, hint="morgan@example.com", enabled=True):
    root = make_vault(tmp_path)
    cfg = valid_config()
    cfg["adapters"]["plaud"] = {"enabled": enabled, "account_hint": hint}
    write_config(root, cfg)
    return root


def test_verify_account_matches_an_m365_get_me_shaped_payload(tmp_path):
    """The m365 whoami is Graph get_me; its mail field must satisfy an
    email hint bound on the m365 adapter."""
    root = make_vault(tmp_path)
    cfg = valid_config()
    cfg["adapters"]["m365"] = {"enabled": True,
                               "account_hint": "morgan@example.com"}
    write_config(root, cfg)
    payload = {"id": "68531043-31b4-4180-b61b-e32849a582ed",
               "displayName": "Morgan Ellery",
               "userPrincipalName": "morgane@corp.example.net",
               "mail": "Morgan@Example.com", "jobTitle": None}
    result = config.verify_account(root, "m365", payload)
    assert result["match"] is True
    assert result["reason"] == "matched"


def test_verify_account_exact_match_casefolded(tmp_path):
    root = bound_vault(tmp_path, hint="Morgan@Example.com")
    result = config.verify_account(
        root, "plaud", {"user": {"email": "morgan@EXAMPLE.com", "id": 7}})
    assert result["match"] is True
    assert result["reason"] == "matched"
    assert result["values_checked"] == 1  # the id is not a string scalar


def test_verify_account_email_hint_matches_as_substring(tmp_path):
    root = bound_vault(tmp_path)
    payload = {"account": "Morgan Ellery <morgan@example.com>"}
    assert config.verify_account(root, "plaud", payload)["match"] is True


def test_verify_account_non_email_hint_never_substring_matches(tmp_path):
    # "morgan1" appears inside the payload value, but a hint without an @
    # gets exact-match only — substring is reserved for emails.
    root = bound_vault(tmp_path, hint="morgan1")
    payload = {"email": "morgan1@example.com"}
    result = config.verify_account(root, "plaud", payload)
    assert result["match"] is False
    assert result["reason"] == "account-mismatch"


def test_verify_account_scans_nested_lists_and_dicts(tmp_path):
    root = bound_vault(tmp_path)
    payload = {"accounts": [{"aliases": ["other@x.y", "morgan@example.com"]}]}
    assert config.verify_account(root, "plaud", payload)["match"] is True


def test_verify_account_mismatch_reports_without_echoing_values(tmp_path):
    root = bound_vault(tmp_path)
    result = config.verify_account(
        root, "plaud", {"email": "real.client@elsewhere.example"})
    assert result == {
        "match": False, "reason": "account-mismatch", "values_checked": 1,
    }


def test_verify_account_refuses_unbound_enabled_adapter(tmp_path):
    root = bound_vault(tmp_path, hint=None)
    result = config.verify_account(root, "plaud", {"email": "a@b.c"})
    assert result["match"] is False
    assert result["reason"] == "no-account-hint"


def test_verify_account_refuses_disabled_adapter(tmp_path):
    root = bound_vault(tmp_path, enabled=False)
    result = config.verify_account(root, "plaud", {"email": "a@b.c"})
    assert result["match"] is False
    assert result["reason"] == "adapter-disabled"


def test_verify_account_rejects_unknown_adapter(tmp_path):
    root = bound_vault(tmp_path)
    with pytest.raises(config.ConfigError, match="adapter"):
        config.verify_account(root, "inbox", {"email": "a@b.c"})


def test_verify_account_empty_payload_is_an_error_not_a_mismatch(tmp_path):
    root = bound_vault(tmp_path)
    with pytest.raises(config.ConfigError, match="no text"):
        config.verify_account(root, "plaud", {"id": 42, "ok": True})


def test_read_defaults_absent_feedback_to_null_repo(tmp_path):
    # Deployed vaults predate the feedback key; absence must not fail.
    root = make_vault(tmp_path)
    write_config(root, valid_config())          # no "feedback" key at all
    result = config.read(root)
    assert result["config"]["feedback"] == {"repo": None}
    assert "feedback.repo" not in result["missing"]  # optional feature, never "missing"


def test_read_accepts_configured_feedback_repo(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config(feedback={"repo": "delaware-org/sb-client-acme"}))
    assert config.read(root)["config"]["feedback"]["repo"] == "delaware-org/sb-client-acme"


@pytest.mark.parametrize("bad", [
    {"repo": "not-a-slug"},          # no owner/ part
    {"repo": ""},                     # empty string
    {"repo": "a/b/c"},                # too many parts
    {"repo": None, "extra": 1},       # unknown key
    "delaware-org/sb-client-acme",    # not an object
])
def test_read_rejects_malformed_feedback(tmp_path, bad):
    root = make_vault(tmp_path)
    write_config(root, valid_config(feedback=bad))
    with pytest.raises(config.ConfigError):
        config.read(root)


def test_write_sets_field_and_preserves_readme(tmp_path):
    root = make_vault(tmp_path)
    cfg = valid_config(timezone=None)
    cfg["_readme"] = ["keep me"]
    write_config(root, cfg)
    result = config.write(root, "timezone", "Europe/Brussels")
    assert result["config"]["timezone"] == "Europe/Brussels"
    raw = json.loads((root / "99-workflow-config" / "config.json")
                     .read_text(encoding="utf-8"))
    assert raw["_readme"] == ["keep me"]          # commentary survives
    assert raw["timezone"] == "Europe/Brussels"


def test_write_rejects_display_name_hint(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    with pytest.raises(config.ConfigError):
        config.write(root, "adapters.plaud.account_hint", "Morgan")
    # and the file is untouched
    assert config.read(root)["config"]["adapters"]["plaud"]["account_hint"] \
        == "morgan@example.com"


def test_write_null_unsets_nullable_field(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    result = config.write(root, "adapters.plaud.account_hint", None)
    assert result["config"]["adapters"]["plaud"]["account_hint"] is None


def test_write_enabled_requires_bool(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    result = config.write(root, "adapters.m365.enabled", True)
    assert result["config"]["adapters"]["m365"]["enabled"] is True
    with pytest.raises(config.ConfigError):
        config.write(root, "adapters.m365.enabled", None)


def test_write_unknown_field_refused(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    with pytest.raises(config.ConfigError):
        config.write(root, "adapters.plaud.nickname", "x")


def test_write_feedback_repo(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    result = config.write(root, "feedback.repo", "delaware-org/sb-client-acme")
    assert result["config"]["feedback"]["repo"] == "delaware-org/sb-client-acme"


def test_write_rejects_malformed_feedback_repo(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    with pytest.raises(config.ConfigError):
        config.write(root, "feedback.repo", "not-a-slug")
