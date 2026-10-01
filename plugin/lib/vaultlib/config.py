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

from datetime import datetime
from pathlib import Path

import json
import re

from vaultlib import vault

CONFIG_RELPATH = Path("99-workflow-config") / "config.json"
KNOWN_VERSION = 1
CONNECTOR_ADAPTERS = ("plaud", "m365")
ADAPTERS = ("inbox",) + CONNECTOR_ADAPTERS
FEEDBACK_REPO_RE = re.compile(r"\A[\w.-]+/[\w.-]+\Z")
_TOP_LEVEL_KEYS = ("config-version", "timezone", "owner", "adapters",
                   "feedback", "sync", "messages")
MESSAGES_SCOPES = ("teams-chats", "inbox", "sent-items")
EXCLUSION_KINDS = ("person", "domain", "chat", "word")
MESSAGES_DEFAULT = {"enabled": False, "consented-at": None, "scope": [], "exclusions": []}

WRITABLE_FIELDS = (
    "timezone", "owner", "feedback.repo", "sync.start-date",
    "adapters.m365.home_domains",
    "messages.enabled", "messages.consented-at", "messages.scope",
) + tuple(f"adapters.{name}.enabled" for name in ADAPTERS) + tuple(
    f"adapters.{name}.account_hint" for name in CONNECTOR_ADAPTERS)

_BOOL_FIELDS = tuple(f for f in WRITABLE_FIELDS if f.endswith(".enabled"))
_LIST_FIELDS = ("adapters.m365.home_domains", "messages.scope")
_CONSENT_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\Z")


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


def _validate_home_domains(value) -> None:
    """Null, or a non-empty list of casefolded-comparable domain strings.

    Home domains gate the M365 external-organizer filter (seenevents.triage):
    a bare list of domain labels, never emails ("no @") and never blank
    ("at least one .") so a caller cannot pass an account_hint by mistake.
    Duplicates after casefolding are rejected because the config stores the
    casefolded form and a caller that wrote "Acme.com" and "acme.com" would
    silently collapse to one entry on the next read.
    """
    if value is None:
        return
    if not isinstance(value, list) or not value:
        raise ConfigError(
            "adapters.m365.home_domains must be null or a non-empty JSON "
            "list of domain strings")
    seen = set()
    for domain in value:
        if not isinstance(domain, str) or not domain.strip():
            raise ConfigError(
                "adapters.m365.home_domains entries must be non-empty "
                f"strings, got {domain!r}")
        if domain != domain.strip() or any(ch.isspace() for ch in domain):
            raise ConfigError(
                f"adapters.m365.home_domains entry {domain!r} must not "
                "contain whitespace")
        if "@" in domain:
            raise ConfigError(
                f"adapters.m365.home_domains entry {domain!r} looks like "
                "an email address — list the domain only (e.g. example.com)")
        if "." not in domain:
            raise ConfigError(
                f"adapters.m365.home_domains entry {domain!r} must contain "
                "at least one \".\" — it is not a domain")
        folded = domain.casefold()
        if folded in seen:
            raise ConfigError(
                f"adapters.m365.home_domains has a duplicate entry: "
                f"{domain!r}")
        seen.add(folded)


def _validate_messages(messages) -> None:
    if not isinstance(messages, dict) or set(messages) != set(MESSAGES_DEFAULT):
        raise ConfigError(
            f"messages must be an object with exactly {sorted(MESSAGES_DEFAULT)}")
    if not isinstance(messages["enabled"], bool):
        raise ConfigError("messages.enabled must be true or false")
    consented = messages["consented-at"]
    if consented is not None and (not isinstance(consented, str)
                                  or not _CONSENT_RE.match(consented)):
        raise ConfigError("messages.consented-at must be null or YYYY-MM-DDTHH:MM")
    scope = messages["scope"]
    if not isinstance(scope, list) or any(s not in MESSAGES_SCOPES for s in scope):
        raise ConfigError(f"messages.scope must be a list drawn from {list(MESSAGES_SCOPES)}")
    exclusions = messages["exclusions"]
    if not isinstance(exclusions, list):
        raise ConfigError("messages.exclusions must be a list")
    seen = set()
    for entry in exclusions:
        if not isinstance(entry, dict) or set(entry) != {"id", "kind", "value", "label", "added"}:
            raise ConfigError("each messages.exclusions entry needs exactly id, kind, value, label, added")
        if entry["kind"] not in EXCLUSION_KINDS:
            raise ConfigError(f"exclusion kind {entry['kind']!r} must be one of {list(EXCLUSION_KINDS)}")
        if not isinstance(entry["value"], str) or not entry["value"].strip():
            raise ConfigError("an exclusion needs a non-empty value")
        if entry["id"] in seen:
            raise ConfigError(f"duplicate exclusion id {entry['id']!r}")
        seen.add(entry["id"])


def _validate(cfg: dict) -> dict:
    version = cfg.get("config-version")
    if version != KNOWN_VERSION:
        raise ConfigError(
            f"config-version {version!r} is not the supported version "
            f"{KNOWN_VERSION} — this plugin cannot read it"
        )
    cfg.setdefault("feedback", {"repo": None})
    # Deployed vaults predate both keys; absence is the honest null state.
    cfg.setdefault("sync", {"start-date": None})
    cfg.setdefault("messages", json.loads(json.dumps(MESSAGES_DEFAULT)))
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
        if name == "m365":
            # Deployed vaults predate this key; absence is the honest
            # unset state (the external-organizer filter is simply off).
            entry.setdefault("home_domains", None)
        allowed = {"enabled"}
        if name in CONNECTOR_ADAPTERS:
            allowed.add("account_hint")
        if name == "m365":
            allowed.add("home_domains")
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
        if name == "m365":
            _validate_home_domains(entry["home_domains"])
    feedback = cfg["feedback"]
    if not isinstance(feedback, dict) or set(feedback) != {"repo"}:
        raise ConfigError('feedback must be an object with exactly the key "repo"')
    repo = feedback["repo"]
    if repo is not None and (
            not isinstance(repo, str) or not FEEDBACK_REPO_RE.match(repo)):
        raise ConfigError(
            'feedback.repo must be null or an "owner/name" GitHub slug')
    sync = cfg["sync"]
    if not isinstance(sync, dict) or set(sync) != {"start-date"}:
        raise ConfigError(
            'sync must be an object with exactly the key "start-date"')
    _validate_start_date(sync["start-date"])
    _validate_messages(cfg["messages"])
    return cfg


def _validate_start_date(value) -> None:
    """Null, or a real ISO calendar date. A date, deliberately not a
    datetime: the vault's horizon is a provisioning day, and anything finer
    would invite timezone arithmetic into a config file."""
    if value is None:
        return
    if not isinstance(value, str) or not re.match(r"\A\d{4}-\d{2}-\d{2}\Z",
                                                  value):
        raise ConfigError(
            f"sync.start-date {value!r} must be null or an ISO date "
            "(YYYY-MM-DD)")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ConfigError(
            f"sync.start-date {value!r} is not a real date") from exc


def read(root: Path) -> dict:
    """Validated config plus the completeness report skills act on."""
    cfg = _validate(_load(root))
    missing = [key for key in ("owner", "timezone") if cfg[key] is None]
    if cfg["sync"]["start-date"] is None:
        # Recommended, not blocking: without it every trailing search can
        # reach back before the vault existed (recurring series expose
        # occurrences years old). Provisioning writes it; a pre-existing
        # vault surfaces it here so an upgrade visit knows to add it.
        missing.append("sync.start-date")
    for name in CONNECTOR_ADAPTERS:
        entry = cfg["adapters"][name]
        if entry["enabled"] and entry["account_hint"] is None:
            missing.append(f"adapters.{name}.account_hint")
    m365 = cfg["adapters"]["m365"]
    if m365["enabled"] and m365["home_domains"] is None:
        # Recommended, not blocking: without it the external-organizer
        # filter is off and every listed occurrence is dispatched.
        missing.append("adapters.m365.home_domains")
    return {"config": cfg, "missing": sorted(missing)}


def m365_home_domains(root: Path) -> tuple:
    """The configured home-domain list, or (None, warning) — never raises.

    A caller that wants to filter by organizer domain (seenevents.triage)
    needs a value it can trust even when config.json is missing, unreadable,
    or the field was never set; this is the one place that turns all three
    into the same honest "unset" shape instead of three different failure
    paths for every caller to handle.
    """
    try:
        cfg = read(root)["config"]
    except ConfigError as exc:
        return None, str(exc)
    domains = cfg["adapters"]["m365"]["home_domains"]
    if domains is None:
        return None, (
            "adapters.m365.home_domains is unset — the external-organizer "
            "filter is off and every listed occurrence is fetched; set it "
            "with: config write --field adapters.m365.home_domains --value "
            '"<domain>[,<domain>]"')
    return domains, None


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

    `value` is already typed: bool for .enabled fields, a list (or None) for
    the list fields, str or None elsewhere. The CLI layer does the
    string->type coercion.
    """
    if field not in WRITABLE_FIELDS:
        raise ConfigError(
            f"field must be one of {sorted(WRITABLE_FIELDS)}, got {field!r}")
    if field in _BOOL_FIELDS:
        if not isinstance(value, bool):
            raise ConfigError(f"{field} takes true or false, not {value!r}")
    elif field in _LIST_FIELDS:
        if value is not None and not isinstance(value, list):
            raise ConfigError(
                f"{field} takes a JSON list of strings or null, not {value!r}")
        # Stored casefolded so a later read/compare never has to fold it
        # again — every consumer (seenevents.triage) compares casefolded.
        if value is not None:
            value = [v.casefold() if isinstance(v, str) else v for v in value]
    elif value is not None and not isinstance(value, str):
        raise ConfigError(f"{field} takes a string or null, not {value!r}")

    path = root / CONFIG_RELPATH
    if not path.is_file():
        raise ConfigError(
            f"{CONFIG_RELPATH} is missing from this vault — the template "
            "ships a default; copy it in or regenerate the vault")
    raw = json.loads(path.read_text(encoding="utf-8"))   # keeps _readme
    node = raw
    if field.startswith("messages."):
        # Deployed vaults predate the block; seed it so a single-field write
        # lands in a complete object.
        raw.setdefault("messages", json.loads(json.dumps(MESSAGES_DEFAULT)))
    parts = field.split(".")
    for key in parts[:-1]:
        node = node.setdefault(key, {})
    node[parts[-1]] = value

    _validate({k: v for k, v in raw.items() if not k.startswith("_")})
    vault.atomic_write(path, json.dumps(raw, indent=2) + "\n")
    return read(root)


def messages_settings(root: Path) -> dict:
    """The feed's settings, or the off state with a warning. Never raises:
    a broken config must switch the feed off, not crash the evening."""
    try:
        return dict(read(root)["config"]["messages"])
    except (ConfigError, OSError) as exc:
        return {**json.loads(json.dumps(MESSAGES_DEFAULT)), "warning": str(exc)}


def _edit_exclusions(root: Path, change) -> dict:
    path = root / CONFIG_RELPATH
    raw = json.loads(path.read_text(encoding="utf-8"))
    messages = raw.setdefault("messages", json.loads(json.dumps(MESSAGES_DEFAULT)))
    result = change(messages["exclusions"])
    _validate({k: v for k, v in raw.items() if not k.startswith("_")})
    vault.atomic_write(path, json.dumps(raw, indent=2) + "\n")
    return result


def exclusion_add(root: Path, *, kind: str, value: str, label, today: str) -> dict:
    if kind not in EXCLUSION_KINDS:
        raise ConfigError(f"exclusion kind {kind!r} must be one of {list(EXCLUSION_KINDS)}")
    clean = str(value or "").strip()
    if kind in ("person", "domain", "word"):
        clean = clean.casefold()
    if not clean:
        raise ConfigError("an exclusion needs a non-empty value")

    def add(entries):
        numbers = [int(e["id"][1:]) for e in entries if str(e.get("id", "")).startswith("x")
                   and str(e["id"])[1:].isdigit()]
        entry = {"id": f"x{max(numbers, default=0) + 1}", "kind": kind, "value": clean,
                 "label": label, "added": today}
        entries.append(entry)
        return entry
    return _edit_exclusions(root, add)


def exclusion_remove(root: Path, exclusion_id: str) -> dict:
    def remove(entries):
        kept = [e for e in entries if e["id"] != exclusion_id]
        if len(kept) == len(entries):
            raise ConfigError(f"no exclusion with id {exclusion_id!r}")
        entries[:] = kept
        return {"removed": exclusion_id}
    return _edit_exclusions(root, remove)
