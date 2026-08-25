# Deployment Config + Connector↔Vault Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Machine decisions (adapter enablement, timezone, executive slug) move from prose to a CLI-owned `99-workflow-config/config.json`, and every connector adapter deterministically verifies its signed-in account against an `account_hint` before listing any content.

**Architecture:** New `vaultlib/config.py` module (read + verify-account), a new `config` CLI group in `cli.py`, a shipped template default config checked by `validate_template.py`, and rewrites of the three skills that read machine decisions from prose (`sync-recordings`, `evening-sync`, `new-project`). Contract tests pin the new behavior.

**Tech Stack:** Python stdlib only (3.10 floor), pytest, markdown SKILL.md files.

**Spec:** `docs/superpowers/specs/2026-08-25-deployment-config-design.md`

## Global Constraints

- **Stdlib only in `plugin/lib/`** — no PyYAML, no third-party imports. Python 3.10 syntax floor.
- **Clean-room rule:** nothing in `plugin/` or `template/` references delaware clients, Michael, or busdev content. "delaware" as vendor name is fine.
- **CLI envelope:** every run prints exactly one JSON object — `{"ok": true, "result": {...}}` exit 0, `{"ok": false, "error": "...", "hint": "..."}` exit 1.
- **Every commit message ends with the exact trailer:** `Co-Authored-By: Claude <noreply@anthropic.com>`
- **Fences:** a markdown block that contains triple-backtick fences must be wrapped in four backticks (SKILL.md bodies carry bash/json fences).
- **Never echo the connected account's identity values in CLI results** — they are the engagement-sensitive data this feature contains.
- **Do not run `git checkout`, `git switch`, `git reset`, `git stash`, or `git rebase` in this worktree.** Use `git show <sha>:<path>` to read old revisions.
- Run tests as: `python3 -m pytest scripts/tests -q` (or a `-k` subset).

---

### Task 1: `vaultlib/config.py` — `read()`

**Files:**
- Create: `plugin/lib/vaultlib/config.py`
- Create: `scripts/tests/test_vaultlib_config.py`

**Interfaces:**
- Consumes: `vault.py` (nothing new; `root` is an already-resolved `Path`).
- Produces: `config.read(root: Path) -> dict` returning `{"config": <validated dict>, "missing": [<dotted key names>]}`; `config.ConfigError(Exception)`; constants `CONFIG_RELPATH`, `KNOWN_VERSION = 1`, `CONNECTOR_ADAPTERS = ("plaud", "m365")`, `ADAPTERS = ("inbox", "plaud", "m365")`. Task 2 adds `verify_account` to this module; Task 3 wires both into the CLI.

- [ ] **Step 1: Write the failing tests**

Create `scripts/tests/test_vaultlib_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_config.py -q`
Expected: collection error — `ImportError: cannot import name 'config'` (module does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `plugin/lib/vaultlib/config.py`:

```python
"""Deployment config: the machine-read half of 99-workflow-config.

Machine decisions — adapter enablement, timezone, executive slug, connector
account binding — live in config.json, a CLI-owned JSON file. Deliberately
not markdown frontmatter: this file must never be editable from Obsidian's
property panel. Style and narrative stay prose in context/*.md; this module
never reads those.

Validation is strict: a typo'd key here silently disables a safety guard
(account binding), so unknown keys fail loudly instead of being ignored.
Null values are the honest pre-onboarding state and are reported, not
rejected.
"""
from __future__ import annotations

from pathlib import Path

import json

CONFIG_RELPATH = Path("99-workflow-config") / "config.json"
KNOWN_VERSION = 1
CONNECTOR_ADAPTERS = ("plaud", "m365")
ADAPTERS = ("inbox",) + CONNECTOR_ADAPTERS
_TOP_LEVEL_KEYS = ("config-version", "timezone", "executive", "adapters")


class ConfigError(Exception):
    """A missing or malformed config the caller must fix."""


def _load(root: Path) -> dict:
    path = root / CONFIG_RELPATH
    if not path.is_file():
        raise ConfigError(
            f"{CONFIG_RELPATH} is missing from this vault — the template "
            "ships a default; copy it in or regenerate the vault"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{CONFIG_RELPATH} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{CONFIG_RELPATH} must hold a JSON object")
    # Keys starting with "_" are human commentary (JSON has no comments).
    return {key: value for key, value in raw.items() if not key.startswith("_")}


def _require_optional_string(cfg: dict, key: str) -> None:
    value = cfg[key]
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a non-empty string or null")


def _validate(cfg: dict) -> dict:
    version = cfg.get("config-version")
    if version != KNOWN_VERSION:
        raise ConfigError(
            f"config-version {version!r} is not the supported version "
            f"{KNOWN_VERSION} — this plugin cannot read it"
        )
    unknown = sorted(set(cfg) - set(_TOP_LEVEL_KEYS))
    if unknown:
        raise ConfigError(f"unknown config keys: {unknown}")
    absent = sorted(set(_TOP_LEVEL_KEYS) - set(cfg))
    if absent:
        raise ConfigError(f"config keys missing entirely: {absent}")
    _require_optional_string(cfg, "timezone")
    _require_optional_string(cfg, "executive")
    adapters = cfg["adapters"]
    if not isinstance(adapters, dict) or set(adapters) != set(ADAPTERS):
        raise ConfigError(
            f"adapters must be an object with exactly {sorted(ADAPTERS)}"
        )
    for name in ADAPTERS:
        entry = adapters[name]
        if not isinstance(entry, dict):
            raise ConfigError(f"adapters.{name} must be an object")
        allowed = {"enabled"}
        if name in CONNECTOR_ADAPTERS:
            allowed.add("account_hint")
        stray = sorted(set(entry) - allowed)
        if stray:
            raise ConfigError(f"unknown keys on adapters.{name}: {stray}")
        if not isinstance(entry.get("enabled"), bool):
            raise ConfigError(f"adapters.{name}.enabled must be true or false")
        if name in CONNECTOR_ADAPTERS:
            if "account_hint" not in entry:
                raise ConfigError(f"adapters.{name} is missing account_hint")
            hint = entry["account_hint"]
            if hint is not None and (not isinstance(hint, str) or not hint.strip()):
                raise ConfigError(
                    f"adapters.{name}.account_hint must be a non-empty "
                    "string or null"
                )
    return cfg


def read(root: Path) -> dict:
    """Validated config plus the completeness report skills act on."""
    cfg = _validate(_load(root))
    missing = [key for key in ("executive", "timezone") if cfg[key] is None]
    for name in CONNECTOR_ADAPTERS:
        entry = cfg["adapters"][name]
        if entry["enabled"] and entry["account_hint"] is None:
            missing.append(f"adapters.{name}.account_hint")
    return {"config": cfg, "missing": sorted(missing)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_config.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/config.py scripts/tests/test_vaultlib_config.py
git commit -m "feat: vaultlib config module — strict read of 99-workflow-config/config.json (#54)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: `vaultlib/config.py` — `verify_account()`

**Files:**
- Modify: `plugin/lib/vaultlib/config.py` (append)
- Modify: `scripts/tests/test_vaultlib_config.py` (append)

**Interfaces:**
- Consumes: `config.read`/`_validate`/`_load` from Task 1.
- Produces: `config.verify_account(root: Path, adapter: str, identity_payload) -> dict` returning `{"match": bool, "reason": str, "values_checked": int}` with `reason` ∈ `matched | account-mismatch | no-account-hint | adapter-disabled`. Task 3 wires it as `config verify-account`.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_config.py`:

```python
def bound_vault(tmp_path, hint="morgan@example.com", enabled=True):
    root = make_vault(tmp_path)
    cfg = valid_config()
    cfg["adapters"]["plaud"] = {"enabled": enabled, "account_hint": hint}
    write_config(root, cfg)
    return root


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


def test_verify_account_bare_name_hint_never_substring_matches(tmp_path):
    root = bound_vault(tmp_path, hint="mo")
    payload = {"email": "morgan@example.com"}
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_config.py -q`
Expected: the new tests FAIL with `AttributeError: ... has no attribute 'verify_account'`; Task 1 tests still pass.

- [ ] **Step 3: Write the implementation**

Append to `plugin/lib/vaultlib/config.py`:

```python
def _string_scalars(node) -> list:
    """Every string scalar in the payload, recursively, order-stable.

    Shape-agnostic on purpose: neither connector's whoami response shape is
    a contract this plugin owns.
    """
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in _string_scalars(value)]
    if isinstance(node, list):
        return [s for value in node for s in _string_scalars(value)]
    return []


def verify_account(root: Path, adapter: str, identity_payload) -> dict:
    """The deterministic binding gate: does the signed-in account match?

    Only match=True lets a skill list connector content. The result never
    echoes the payload's values — the connected account's identity is
    exactly the engagement-sensitive data this gate exists to contain.
    """
    if adapter not in CONNECTOR_ADAPTERS:
        raise ConfigError(
            f"adapter must be one of {sorted(CONNECTOR_ADAPTERS)}, "
            f"got {adapter!r}"
        )
    entry = read(root)["config"]["adapters"][adapter]
    if not entry["enabled"]:
        return {"match": False, "reason": "adapter-disabled",
                "values_checked": 0}
    hint = entry["account_hint"]
    if hint is None:
        return {"match": False, "reason": "no-account-hint",
                "values_checked": 0}
    values = [v.strip().casefold() for v in _string_scalars(identity_payload)]
    values = [v for v in values if v]
    if not values:
        raise ConfigError(
            "identity payload carries no text to check — the whoami call "
            "likely failed; treat this as unchecked, not as a mismatch"
        )
    needle = hint.strip().casefold()
    # An email is specific enough for substring matching (aliases, display
    # forms like "Name <email>"); a bare name is not, so it gets exact only.
    matched = needle in values or (
        "@" in needle and any(needle in value for value in values)
    )
    return {
        "match": matched,
        "reason": "matched" if matched else "account-mismatch",
        "values_checked": len(values),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_config.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/config.py scripts/tests/test_vaultlib_config.py
git commit -m "feat: deterministic connector account verification against account_hint (#54)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: CLI `config` group + plugin CLAUDE.md section

**Files:**
- Modify: `plugin/lib/vaultlib/cli.py`
- Modify: `plugin/CLAUDE.md`
- Modify: `scripts/tests/test_vaultlib_cli.py` (append)

**Interfaces:**
- Consumes: `config.read(root)`, `config.verify_account(root, adapter, payload)`, `config.ConfigError` from Tasks 1–2.
- Produces: CLI subcommands `config read --vault V` and `config verify-account --vault V --adapter {plaud,m365} --identity FILE|-`, both inside the standard JSON envelope. Tasks 5–6 write SKILL.md instructions that call them (the contract test derives known subcommands from `cli.build_parser()`, so they become "known" here).

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_vaultlib_cli.py` (it already imports `json`, `cli`, `make_vault`, and defines `run(capsys, argv)`):

```python
def write_vault_config(root, extra=None):
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
    if extra:
        cfg.update(extra)
    path = root / "99-workflow-config" / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")


def test_config_read_returns_config_and_missing(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root, extra={"timezone": None})
    code, payload = run(capsys, ["config", "read", "--vault", str(root)])
    assert code == 0
    assert payload["result"]["config"]["executive"] == "morgan-ellery"
    assert payload["result"]["missing"] == ["timezone"]


def test_config_read_missing_file_is_a_structured_error(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, ["config", "read", "--vault", str(root)])
    assert code == 1
    assert payload["ok"] is False
    assert "config.json" in payload["error"]
    assert payload["hint"]


def test_config_verify_account_matches_from_identity_file(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root)
    identity = tmp_path / "whoami.json"
    identity.write_text(
        json.dumps({"user": {"email": "morgan@example.com"}}),
        encoding="utf-8")
    code, payload = run(capsys, [
        "config", "verify-account", "--vault", str(root),
        "--adapter", "plaud", "--identity", str(identity),
    ])
    assert code == 0
    assert payload["result"]["match"] is True


def test_config_verify_account_mismatch_is_ok_false_free(capsys, tmp_path):
    # A mismatch is a *result* (the gate worked), not an envelope error.
    root = make_vault(tmp_path)
    write_vault_config(root)
    identity = tmp_path / "whoami.json"
    identity.write_text(
        json.dumps({"user": {"email": "someone.else@client.example"}}),
        encoding="utf-8")
    code, payload = run(capsys, [
        "config", "verify-account", "--vault", str(root),
        "--adapter", "plaud", "--identity", str(identity),
    ])
    assert code == 0
    assert payload["result"] == {
        "match": False, "reason": "account-mismatch", "values_checked": 1,
    }
    assert "someone.else" not in json.dumps(payload)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_vaultlib_cli.py -q`
Expected: the four new tests FAIL (argparse: `invalid choice: 'config'` → `SystemExit`); existing tests pass.

- [ ] **Step 3: Wire the CLI**

In `plugin/lib/vaultlib/cli.py`:

1. Add `config` to the vaultlib import line (line 34), keeping it alphabetical:

```python
from vaultlib import config, dailynote, dates, decision, entity, meeting, person, plaud, project, schema, syncjob, updatequeue, vault  # noqa: E402
```

2. In `build_parser()`, directly after the `identity` group (after line 66), add:

```python
    config_group = top.add_parser(
        "config", help="deployment config — the machine-read half of 99-workflow-config")
    config_sub = config_group.add_subparsers(dest="action", required=True)
    config_read = config_sub.add_parser(
        "read", help="read and validate 99-workflow-config/config.json")
    _add_vault_argument(config_read)
    config_verify = config_sub.add_parser(
        "verify-account",
        help="check a connector's signed-in account against its account_hint")
    _add_vault_argument(config_verify)
    config_verify.add_argument(
        "--adapter", required=True, choices=sorted(config.CONNECTOR_ADAPTERS),
        help="which connector adapter's binding to check")
    config_verify.add_argument(
        "--identity", required=True,
        help="path to the raw whoami JSON the connector returned (or - for stdin)")
```

3. In `_dispatch()`, directly after the `identity` branch (after line 251), add:

```python
    if args.group == "config":
        if args.action == "read":
            return _ok(config.read(root))
        payload = (json.load(sys.stdin) if args.identity == "-"
                   else json.loads(Path(args.identity).read_text(encoding="utf-8")))
        return _ok(config.verify_account(root, args.adapter, payload))
```

4. In `main()`'s except chain, directly after the `vault.VaultError` handler, add:

```python
    except config.ConfigError as exc:
        return _fail(str(exc),
                     "Fix 99-workflow-config/config.json (see the template "
                     "default) and retry.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest scripts/tests/test_vaultlib_cli.py scripts/tests/test_vaultlib_config.py scripts/tests/test_skill_contracts.py -q`
Expected: all PASS (the contract test's `known_subcommands()` now includes `("config", "read")` and `("config", "verify-account")`).

- [ ] **Step 5: Document the config surface in `plugin/CLAUDE.md`**

Insert this section into `plugin/CLAUDE.md` directly before the `## Interpreter resolution` heading:

```markdown
## Deployment config is CLI-owned JSON

Machine decisions — adapter enablement, timezone, the executive's person
slug, connector account binding — live in `99-workflow-config/config.json`,
read via `config read`. It is deliberately JSON and deliberately not
frontmatter: nothing about it should be editable from Obsidian's property
panel. Keys starting with `_` are human commentary and are ignored. Null
values are the honest pre-onboarding state and come back in `missing`
rather than failing the read.

`config verify-account` is the binding gate: it takes the raw whoami JSON a
connector returned (Plaud `get_current_user`, M365 `get_me`) and reports
whether the signed-in account matches the adapter's `account_hint`. Only
`match: true` may proceed to listing content. The result never echoes the
connected account's values — a mismatch means those values belong to an
unrelated engagement, and they must not propagate further than the raw
scratch file, which the skill deletes.

Style and narrative (language, recap depth, identity prose) stay in
`99-workflow-config/context/*.md` — judgment, not machine config.
```

- [ ] **Step 6: Commit**

```bash
git add plugin/lib/vaultlib/cli.py plugin/CLAUDE.md scripts/tests/test_vaultlib_cli.py
git commit -m "feat: config read / config verify-account CLI subcommands (#54)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Template default config + validator + migration note

**Files:**
- Create: `template/99-workflow-config/config.json`
- Modify: `scripts/validate_template.py`
- Modify: `scripts/tests/test_validate_template.py` (append)
- Modify: `migrations/README.md`

**Interfaces:**
- Consumes: nothing from other tasks (validator stays standalone stdlib — it must run as `python scripts/validate_template.py` without `plugin/lib` on the path).
- Produces: the shipped default config file Tasks 5–6's skills assume exists in a template-derived vault; `validate_template.main(root)` gains config problems in its returned list.

- [ ] **Step 1: Write the failing tests**

Append to `scripts/tests/test_validate_template.py`:

```python
import json


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest scripts/tests/test_validate_template.py -q`
Expected: the new tests FAIL (`main` reports no config problems yet). NOTE: `test_populated_template_with_markers_passes` (existing) will also start failing once the check lands — that is expected and Step 3 updates it.

- [ ] **Step 3: Implement the validator check**

In `scripts/validate_template.py`, add `import json` next to `import sys`, and replace the body of `main()` after the `problems = []` line so it reads:

```python
    problems = []
    if not (template / "CLAUDE.md").is_file():
        problems.append("populated template/ is missing CLAUDE.md")
    if not (template / "structure-version").is_file():
        problems.append("populated template/ is missing the structure-version marker")
    problems.extend(check_config(template))
    return problems
```

Then add below `main()`:

```python
def check_config(template: Path) -> list[str]:
    """The shipped default must be valid AND in the safe shipping state:
    identity values null, connector adapters disabled and unbound. A template
    that ships a binding would silently wire every new vault to it."""
    path = template / "99-workflow-config" / "config.json"
    if not path.is_file():
        return ["populated template/ is missing 99-workflow-config/config.json"]
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"template config.json is not valid JSON: {exc}"]
    problems = []
    if not cfg.get("_readme"):
        problems.append("template config.json must carry a _readme explaining the file")
    if cfg.get("config-version") != 1:
        problems.append("template config.json must declare config-version 1")
    for key in ("timezone", "executive"):
        if key not in cfg or cfg[key] is not None:
            problems.append(f"template config.json must ship {key} as null")
    adapters = cfg.get("adapters")
    if not isinstance(adapters, dict) or set(adapters) != {"inbox", "plaud", "m365"}:
        problems.append("template config.json adapters must be exactly inbox, plaud, m365")
        return problems
    if adapters["inbox"] != {"enabled": True}:
        problems.append("template config.json must ship adapters.inbox as {\"enabled\": true}")
    for name in ("plaud", "m365"):
        if adapters[name] != {"enabled": False, "account_hint": None}:
            problems.append(
                f"template config.json must ship adapters.{name} disabled with a null account_hint"
            )
    return problems
```

Update the module docstring's second paragraph to mention the third marker, replacing the sentence that names the two markers with:

```text
The moment anything else exists (the template-extraction issue), the template
must carry its markers: CLAUDE.md (vault instructions), structure-version
(consumed by /upgrade-vault), and 99-workflow-config/config.json in the safe
shipping state (identity values null, connector adapters disabled, unbound).
```

Finally, update the existing test `test_populated_template_with_markers_passes` to also write the shipping config (reuse the new helpers) so it still passes:

```python
def test_populated_template_with_markers_passes(tmp_path):
    t = tmp_path / "template"
    (t / "10-meetings").mkdir(parents=True)
    (t / "CLAUDE.md").write_text("vault instructions", encoding="utf-8")
    (t / "structure-version").write_text("1\n", encoding="utf-8")
    write_template_config(t, shipping_config())
    assert main(tmp_path) == []
```

- [ ] **Step 4: Create the shipped default**

Create `template/99-workflow-config/config.json` (2-space indent, trailing newline):

```json
{
  "_readme": [
    "Machine-read deployment config — owned by the CLI and /setup-my-brain.",
    "Edit as text (never via Obsidian's property panel; this is not frontmatter).",
    "timezone: the executive's IANA timezone name, e.g. Europe/Brussels.",
    "executive: the executive's person slug in 50-people/, the join key for metrics.",
    "account_hint: an identifier (email preferred) of the connector account that",
    "IS this vault's account. A connector whose signed-in account does not match",
    "its hint is refused before any content is listed. Binding a vault to an",
    "account is a conscious act: write the hint here, explicitly."
  ],
  "config-version": 1,
  "timezone": null,
  "executive": null,
  "adapters": {
    "inbox": {"enabled": true},
    "plaud": {"enabled": false, "account_hint": null},
    "m365": {"enabled": false, "account_hint": null}
  }
}
```

- [ ] **Step 5: Record the migration candidate**

In `migrations/README.md`, extend the pending-migration paragraph. Replace the final paragraph with:

```text
Pending migration (structure-version 2 candidate): decision notes — drop
`tags`, add `reviewed: true` to existing notes (v0.2.0 removed tags and made
the reviewed key mandatory). Also: add `99-workflow-config/config.json`
(template default, then fill timezone/executive/adapters from the vault's
prose context — #54 moved machine decisions out of prose).
```

- [ ] **Step 6: Run the validator and tests**

Run: `python3 scripts/validate_template.py && python3 -m pytest scripts/tests/test_validate_template.py scripts/tests/test_template_config.py -q`
Expected: validator exits 0 silently; all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add template/99-workflow-config/config.json scripts/validate_template.py scripts/tests/test_validate_template.py migrations/README.md
git commit -m "feat: template ships a default deployment config; validator pins the safe shipping state (#54)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: `/sync-recordings` — config-driven adapters, binding gate, scratch hygiene

**Files:**
- Modify: `plugin/skills/sync-recordings/SKILL.md`

**Interfaces:**
- Consumes: CLI `config read` and `config verify-account` (Task 3 signatures).
- Produces: the SKILL.md text Task 7's contract tests grep for: it must contain `config read`, `verify-account`, and a `## Scratch hygiene` heading, and must not contain `identity.md` or `tools-and-systems.md`.

- [ ] **Step 1: Replace the adapter-declaration section**

In `plugin/skills/sync-recordings/SKILL.md`, replace the `## The three adapters` section (heading plus the paragraph and table under it, up to but not including `## Workflow`) with:

````markdown
## The three adapters

Read the deployment config first — it, not prose, says which adapters this
vault uses:

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
```

Adapters with `enabled: false` are skipped with an explicit line in the
summary. For an enabled adapter, verify the tools actually exist before
running it — declared but unavailable is also **an explicit skip line,
never a silent zero**. Anything in `missing` that blocks a step below is
reported the same way.

| Adapter | Discovery | Availability check |
|---|---|---|
| `inbox` | `sync scan` over `10-inbox/` | always available |
| `plaud` | Plaud MCP `list_files` | ToolSearch finds `mcp__plaud__list_files` |
| `m365` | — | **not yet supported** — the retrieval path is pending verification; say so if enabled |

### Account binding — before anything is listed

A connector adapter runs against whatever account is signed in at the *user*
level, which may not be this vault's account. The config's `account_hint`
binds them, and the check is deterministic, not judgment:

1. Call the connector's whoami tool (`mcp__plaud__get_current_user`; for
   M365 calendar enrichment, `get_me`). Write the raw JSON to scratch with
   the Write tool.
2. Run the gate:

```bash
python3 "$VAULTLIB" config verify-account --vault "$VAULT" \
  --adapter plaud --identity "$SCRATCH/plaud.whoami.json"
```

3. Only `match: true` proceeds. On `match: false` the adapter is **refused,
   in both modes** — nothing is listed, nothing is synced. Delete the whoami
   scratch file immediately. Interactively, tell the user the `reason` and
   that binding the account means writing its identifier into
   `adapters.<name>.account_hint` in `99-workflow-config/config.json` — a
   conscious act, not something you do for them. Under `--unattended`, write
   a refuse-and-alert line in the summary (see below) and move on to the
   other adapters.

The reasons: `account-mismatch` (wrong account signed in — the S1 this gate
exists for), `no-account-hint` (enabled but never bound — same refusal), and
`adapter-disabled`. A whoami tool that is missing or errors means the
adapter is *unavailable* (skip line), not unbound — do not guess either way.
````

- [ ] **Step 2: Point the Plaud step and timezone at the config**

In the `### 1. Scan and dedup` section, change the Plaud paragraph's opening from `**Plaud** (when available): call` to:

```text
**Plaud** (when enabled, available, and account-verified): call
```

Then replace the timezone paragraph (the one beginning `The executive's timezone is prose in`) with:

```text
The executive's timezone is `timezone` from `config read` — pass the IANA
name. If it is in `missing`, the plaud adapter and calendar enrichment
cannot run: skip them with an explicit line. If the host cannot resolve
timezone names, the error's hint says to pass `--utc-offset` instead.
```

- [ ] **Step 3: Gate calendar enrichment on the m365 binding**

In `### 2. Calendar enrichment (optional, honest about absence)`, replace the opening sentence (`If the Microsoft 365 calendar tool is available (ToolSearch outlook_calendar_search), match each recording to a calendar event.`) with:

```text
Calendar enrichment uses the M365 connector, so it is gated like an adapter:
it runs only when `adapters.m365.enabled` is true, the calendar tool exists
(ToolSearch `outlook_calendar_search`), and `config verify-account
--adapter m365` (whoami: `get_me`) returns `match: true`. Disabled, missing
tool, or a refused account all stamp `calendar-tool-unavailable` — the
calendar was never consulted — and the summary says which one happened.
When the gate passes, match each recording to a calendar event.
```

- [ ] **Step 4: Add the refusal line to the summary block and a scratch-hygiene section**

In the `### 7. Summarize` fenced summary template, replace the `**Adapters:**` line with:

```text
**Adapters:** inbox ok · plaud ok | REFUSED (account-mismatch | no-account-hint) | disabled | unavailable · m365 disabled | not yet supported
```

Then add this section directly before `## Unattended mode`:

````markdown
## Scratch hygiene

Raw connector JSON — whoami payloads, `list_files` listings, transcripts —
is engagement data that must not outlive the run. It lands only in the
session scratch directory, never the vault. At the end of the run, success
or refusal, delete the raw connector files this run wrote:

```bash
rm -f "$SCRATCH"/plaud.whoami.json "$SCRATCH"/m365.whoami.json "$SCRATCH"/rec_*.json "$SCRATCH"/plaud.list.json
```

On an account-mismatch refusal, delete the whoami payload immediately —
before writing the summary. (The gate runs before listing, so on a refusal
no listing ever reaches disk.)
````

- [ ] **Step 5: Add the unattended rule**

In `## Unattended mode`, after rule 2, add:

```text
3. **A refused account binding is an alert, not a fallback.** The summary
   carries the refuse-and-alert line; the adapter synced nothing, and no
   judgment call overrides the gate.
```

- [ ] **Step 6: Verify the skill text**

Run: `python3 scripts/lint_plugin.py && python3 -m pytest scripts/tests/test_skill_contracts.py -q && ! grep -n "identity.md\|tools-and-systems" plugin/skills/sync-recordings/SKILL.md`
Expected: lint clean, contract tests pass (the CLI already knows both subcommands), grep finds nothing (inverted: exits 0).

- [ ] **Step 7: Commit**

```bash
git add plugin/skills/sync-recordings/SKILL.md
git commit -m "feat: /sync-recordings reads deployment config and refuses unbound or mismatched connector accounts (#54)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: `/evening-sync` + `/new-project` — config consumption

**Files:**
- Modify: `plugin/skills/evening-sync/SKILL.md`
- Modify: `plugin/skills/new-project/SKILL.md`

**Interfaces:**
- Consumes: CLI `config read` / `config verify-account` (Task 3).
- Produces: SKILL.md text satisfying Task 7's contract tests (`config read` present in both; `verify-account` present in evening-sync; no `identity.md`/`tools-and-systems.md` references).

- [ ] **Step 1: Rewrite evening-sync Stage 1**

In `plugin/skills/evening-sync/SKILL.md`, replace the `## Stage 1 — Dates (authoritative, never re-derived)` section's first paragraph and command (the text from `Read the executive's timezone` through the fenced `dates plan` block) with:

````markdown
Read the deployment config, then plan the dates:

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
python3 "$VAULTLIB" dates plan --vault "$VAULT" --timezone <config.timezone>
```

If `timezone` or `executive` is in `missing`, the pipeline cannot run
deterministically: stop, and say which key to fill in
`99-workflow-config/config.json` (interactive), or write the alert as the
run's only output (unattended).
````

And replace the section's final paragraph (the one beginning `Also resolve the executive's **person slug**`) with:

```text
The executive's **person slug** is `executive` from the config — a slug,
used as-is. Stage 3 needs it.
```

- [ ] **Step 2: Gate Stage 5's calendar pull**

In `## Stage 5 — Tomorrow's calendar and prep`, replace the opening sentence (`If the Microsoft 365 calendar tool is available (ToolSearch outlook_calendar_search), pull next_business_day's events; compute the query window deterministically:`) with:

````markdown
The calendar pull uses the M365 connector, so it is gated like an adapter:
it runs only when `adapters.m365.enabled` is true, the calendar tool exists
(ToolSearch `outlook_calendar_search`), and the account binding verifies —
call `get_me`, write the raw JSON to scratch, then:

```bash
python3 "$VAULTLIB" config verify-account --vault "$VAULT" \
  --adapter m365 --identity "$SCRATCH/m365.whoami.json"
```

Only `match: true` pulls events. A refusal (`account-mismatch`,
`no-account-hint`) or a disabled adapter takes the calendar-unavailable
path below, and the summary names the cause — a signed-in account from the
wrong engagement must never prep this vault's meetings. Delete the whoami
scratch file immediately on a refusal, and in any case before the run ends.
When the gate passes, pull `next_business_day`'s events; compute the query
window deterministically:
````

- [ ] **Step 3: Extend evening-sync's summary and rules**

In the `## Stage 7` summary template, replace the `**Tomorrow's note:**` line's trailing alternatives so the line reads:

```text
**Tomorrow's note:** `60-daily-notes/{date}.md` ({DayName}) — {N} meetings prepped | calendar unavailable | calendar REFUSED (account-mismatch | no-account-hint) | m365 disabled
```

In `## Rules`, replace rule 7 with:

```text
7. **Calendar unavailable, refused, or disabled still writes the note** —
   with the explicit line naming which, never a silent empty section.
```

And append rule 9:

```text
9. **Machine decisions come from `config read`** — timezone, executive
   slug, adapter enablement. Prose context files carry style and narrative,
   never these.
```

- [ ] **Step 4: Rewrite new-project's owner resolution**

In `plugin/skills/new-project/SKILL.md`, section `### 3. Resolve the owner`, replace the text from `The owner is a person slug` through the paragraph after the `identity show` block (the one beginning `Read the executive's name out of the returned`) with:

````markdown
The owner is a person slug, and it must resolve to a real person note.
Default to the executive:

```bash
python3 "$VAULTLIB" config read --vault "$VAULT"
```

`executive` in the result is the executive's person slug — use it as
`--owner` directly. If it is in `missing`, ask the user who owns this
project (never guess), then make sure the note exists:
````

Keep the existing `person ensure` block and adjust the sentence after it to:

```text
Use the returned `slug` as `--owner`.
```

Check the tail of that section: if the old text mentions `identity` coming back `null`, fold that case into the `missing` branch above (the config replaces the identity-block read here; `identity show` remains a CLI command but this skill no longer calls it).

- [ ] **Step 5: Verify**

Run: `python3 scripts/lint_plugin.py && python3 -m pytest scripts/tests/test_skill_contracts.py -q && ! grep -rn "identity.md\|tools-and-systems" plugin/skills/*/SKILL.md`
Expected: all clean. (`test_every_cli_invocation_named_by_a_skill_exists` covers the new `config` invocations; the inverted grep exits 0.)

- [ ] **Step 6: Commit**

```bash
git add plugin/skills/evening-sync/SKILL.md plugin/skills/new-project/SKILL.md
git commit -m "feat: /evening-sync and /new-project consume deployment config; calendar pull gated on account binding (#54)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Contract tests, template prose note, version bump, changelog

**Files:**
- Modify: `scripts/tests/test_skill_contracts.py` (append)
- Modify: `template/99-workflow-config/context/tools-and-systems.md`
- Modify: `plugin/.claude-plugin/plugin.json`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: the SKILL.md texts from Tasks 5–6 and the CLI from Task 3.
- Produces: the CI-pinned contract; version `0.5.0`.

- [ ] **Step 1: Write the contract tests (they should pass immediately — they pin Tasks 5–6)**

Append to `scripts/tests/test_skill_contracts.py`:

```python
def read_skill(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")


def test_sync_skills_gate_connectors_through_config():
    """#54: adapter enablement and account binding are deterministic —
    both sync skills must read the config and run the verify gate."""
    for name in ("sync-recordings", "evening-sync"):
        text = read_skill(name)
        assert "config read" in text, f"{name} must read the deployment config"
        assert "verify-account" in text, f"{name} must run the binding gate"


def test_sync_recordings_states_the_scratch_hygiene_rule():
    assert "## Scratch hygiene" in read_skill("sync-recordings")


def test_new_project_resolves_owner_from_config():
    assert "config read" in read_skill("new-project")


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_no_skill_reads_machine_decisions_from_prose(path):
    """#54 acceptance: timezone, exec slug, and adapter enablement come from
    config.json. The prose context files carry style and narrative only, so
    no skill may name the two files that used to hold machine decisions."""
    text = path.read_text(encoding="utf-8")
    assert "identity.md" not in text, f"{path.parent.name} reads prose config"
    assert "tools-and-systems" not in text, f"{path.parent.name} reads prose config"
```

- [ ] **Step 2: Run the full suite**

Run: `python3 -m pytest scripts/tests -q`
Expected: all PASS. If a contract test fails, the corresponding Task 5/6 edit is incomplete — fix the SKILL.md, not the test.

- [ ] **Step 3: Point the template prose at the config**

In `template/99-workflow-config/context/tools-and-systems.md`, replace the `## Purpose` paragraph with:

```text
The systems around the vault, as narrative — what they are, who runs them,
where things land. Machine decisions (which adapters sync, account binding,
timezone) live in `99-workflow-config/config.json`, not here: skills read
that file, and this one stays human context.
```

- [ ] **Step 4: Bump the plugin version**

In `plugin/.claude-plugin/plugin.json`, change `"version": "0.4.2"` to `"version": "0.5.0"` (new feature surface: config group + binding gate).

- [ ] **Step 5: Changelog entry**

In `CHANGELOG.md`, add as the first bullet under `## Unreleased`:

```markdown
- **Connectors are now bound to the vault, and refuse to sync anyone else's
  account.** Each vault carries a deployment config
  (`99-workflow-config/config.json`) naming its timezone, its executive, and
  which capture channels are on. A connector (Plaud, Microsoft 365) only
  lists content after the signed-in account matches the account written in
  the config — a mismatch is refused outright, and an unattended run raises
  an alert instead of syncing. Raw connector data is wiped from the work
  area at the end of every run. (#54)
```

- [ ] **Step 6: Full verification**

Run: `python3 scripts/lint_plugin.py && python3 scripts/validate_template.py && python3 -m pytest scripts/tests -q && bash scripts/check-plugin-version.sh 2>/dev/null || true`
Expected: lint and validator silent-clean, full suite green. (The version-guard script may need a base ref in CI; locally the pytest + lint + validator trio is the gate.)

- [ ] **Step 7: Commit**

```bash
git add scripts/tests/test_skill_contracts.py template/99-workflow-config/context/tools-and-systems.md plugin/.claude-plugin/plugin.json CHANGELOG.md
git commit -m "feat: contract tests pin config-driven skills; bump plugin to 0.5.0 (#54)

Co-Authored-By: Claude <noreply@anthropic.com>"
```
