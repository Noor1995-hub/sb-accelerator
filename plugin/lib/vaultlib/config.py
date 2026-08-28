"""Deployment config: the machine-read half of 99-workflow-config.

Machine decisions — adapter enablement, timezone, owner slug, connector
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
import re

from vaultlib import vault

CONFIG_RELPATH = Path("99-workflow-config") / "config.json"
KNOWN_VERSION = 1
CONNECTOR_ADAPTERS = ("plaud", "m365")
ADAPTERS = ("inbox",) + CONNECTOR_ADAPTERS
FEEDBACK_REPO_RE = re.compile(r"\A[\w.-]+/[\w.-]+\Z")
_TOP_LEVEL_KEYS = ("config-version", "timezone", "owner", "adapters", "feedback")

WRITABLE_FIELDS = (
    "timezone", "owner", "feedback.repo",
) + tuple(f"adapters.{name}.enabled" for name in ADAPTERS) + tuple(
    f"adapters.{name}.account_hint" for name in CONNECTOR_ADAPTERS)

_BOOL_FIELDS = tuple(f for f in WRITABLE_FIELDS if f.endswith(".enabled"))


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
    cfg.setdefault("feedback", {"repo": None})
    unknown = sorted(set(cfg) - set(_TOP_LEVEL_KEYS))
    if unknown:
        raise ConfigError(f"unknown config keys: {unknown}")
    absent = sorted(set(_TOP_LEVEL_KEYS) - set(cfg))
    if absent:
        raise ConfigError(f"config keys missing entirely: {absent}")
    _require_optional_string(cfg, "timezone")
    _require_optional_string(cfg, "owner")
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
            # A display name ("Morgan") false-accepts any account whose
            # whoami carries it as a nickname. Identifiers — emails,
            # account ids, synthetic connector addresses — all carry an @
            # or a digit; names don't.
            if hint is not None and "@" not in hint and not any(
                    ch.isdigit() for ch in hint):
                raise ConfigError(
                    f"adapters.{name}.account_hint looks like a display "
                    "name — copy an account identifier (email or id) "
                    "verbatim from the connector's whoami instead"
                )
    feedback = cfg["feedback"]
    if not isinstance(feedback, dict) or set(feedback) != {"repo"}:
        raise ConfigError('feedback must be an object with exactly the key "repo"')
    repo = feedback["repo"]
    if repo is not None and (
            not isinstance(repo, str) or not FEEDBACK_REPO_RE.match(repo)):
        raise ConfigError(
            'feedback.repo must be null or an "owner/name" GitHub slug')
    return cfg


def read(root: Path) -> dict:
    """Validated config plus the completeness report skills act on."""
    cfg = _validate(_load(root))
    missing = [key for key in ("owner", "timezone") if cfg[key] is None]
    for name in CONNECTOR_ADAPTERS:
        entry = cfg["adapters"][name]
        if entry["enabled"] and entry["account_hint"] is None:
            missing.append(f"adapters.{name}.account_hint")
    return {"config": cfg, "missing": sorted(missing)}


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


def write(root: Path, field: str, value) -> dict:
    """Set one field, re-validate the whole config, write atomically.

    `value` is already typed: bool for .enabled fields, str or None
    elsewhere. The CLI layer does the string->type coercion.
    """
    if field not in WRITABLE_FIELDS:
        raise ConfigError(
            f"field must be one of {sorted(WRITABLE_FIELDS)}, got {field!r}")
    if field in _BOOL_FIELDS:
        if not isinstance(value, bool):
            raise ConfigError(f"{field} takes true or false, not {value!r}")
    elif value is not None and not isinstance(value, str):
        raise ConfigError(f"{field} takes a string or null, not {value!r}")

    path = root / CONFIG_RELPATH
    if not path.is_file():
        raise ConfigError(
            f"{CONFIG_RELPATH} is missing from this vault — the template "
            "ships a default; copy it in or regenerate the vault")
    raw = json.loads(path.read_text(encoding="utf-8"))   # keeps _readme
    node = raw
    parts = field.split(".")
    for key in parts[:-1]:
        node = node.setdefault(key, {})
    node[parts[-1]] = value

    _validate({k: v for k, v in raw.items() if not k.startswith("_")})
    vault.atomic_write(path, json.dumps(raw, indent=2) + "\n")
    return read(root)
