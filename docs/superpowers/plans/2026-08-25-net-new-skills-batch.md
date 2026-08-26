# Net-New Skills Batch (#3–#7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the five net-new v0.1 skills — `/setup-my-brain`, `/upgrade-vault`, `/health-check`, `/process-upstream`, `/report-feedback` — plus the vaultlib CLI groups they stand on, in one PR closing #3–#7.

**Architecture:** Skills carry judgment and conversation; every disk write goes through deterministic `vaultlib` subcommands (stdlib-only Python, 3.10 floor, JSON envelope on stdout). This batch adds `config write`, `context write`, a `migrate` group with Python migration modules under `plugin/migrations/`, `health report`, and a `feedback` group whose `send` runs a deterministic scrub lint before posting to the GitHub API.

**Tech Stack:** Python 3.10 stdlib (argparse, json, zipfile, importlib, urllib), pytest, existing `vaultlib` modules (`markdown.py` frontmatter parser, `vault.py` atomic writes).

**Spec:** `docs/superpowers/specs/2026-08-25-net-new-skills-design.md` — read it first; every task argues from it. Also load-bearing: `migrations/README.md` (the exact migration-001 transformations), `docs/superpowers/specs/2026-08-25-deployment-config-design.md` (config shape + binding gate).

## Global Constraints

- **Stdlib only, Python 3.10 syntax floor** in `plugin/lib/` and `plugin/migrations/` — no PyYAML, no 3.11+ constructs (no `except*`, no `Self`). Cowork ships 3.10; CI runs 3.13.
- **Clean-room rule:** nothing under `plugin/` or `template/` may reference delaware clients, Michael, or busdev content. `python scripts/lint_plugin.py` must stay green after every task.
- **CLI envelope:** every subcommand prints exactly one JSON object — `{"ok": true, "result": {...}}` exit 0, or `{"ok": false, "error": "...", "hint": "..."}` exit 1. New errors get an `except` clause in `cli.py:main`.
- **Writes are UTF-8 with `newline="\n"`** — always via `vault.atomic_write` or equivalent.
- **The vault root is always a parameter** (`--vault`), resolved via `vault.resolve()`.
- **Skill frontmatter:** `name` matches the directory, `description` present, `user_invocable: true`. Net-new skills carry `origin: net-new` instead of `upstreamed-from` (Task 10 amends the contract test).
- Every SKILL.md must mention **both "Cowork" and "Claude Code"** (surface-requirement contract test) and must reference at least one real CLI subcommand as `"$VAULTLIB" <group> <action>`.
- **Commit after every task**, message ending with the exact trailer line: `Co-Authored-By: Claude <noreply@anthropic.com>`.
- Run the full gate after each task: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`.
- Tests import via `scripts/tests/conftest.py` path setup: `from vaultlib import <module>` works; template checks use `REPO_ROOT`.

---

### Task 1: `feedback` section in config (read side, template, validators)

The config gains an optional `feedback` object. **Backward compatibility is the point:** a deployed `config.json` without the key must keep validating — absence defaults to `{"repo": null}`. A present key is validated strictly.

**Files:**
- Modify: `plugin/lib/vaultlib/config.py`
- Modify: `template/99-workflow-config/config.json`
- Modify: `scripts/validate_template.py` (the `check_config` function)
- Test: `scripts/tests/test_vaultlib_config.py`, `scripts/tests/test_template_config.py`, `scripts/tests/test_validate_template.py`

**Interfaces:**
- Consumes: existing `config._load`, `config._validate`, `config.read`.
- Produces: `config.read(root)["config"]["feedback"]["repo"]` — always present after read (defaulted), `str "owner/name"` or `None`. `config.FEEDBACK_REPO_RE` for reuse in Task 2's write validation.

- [ ] **Step 1: Write the failing tests** — append to `scripts/tests/test_vaultlib_config.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest scripts/tests/test_vaultlib_config.py -q -k feedback`
Expected: FAIL — `ConfigError: unknown config keys: ['feedback']` (and the absent-key test fails because `feedback` is not in the read result).

- [ ] **Step 3: Implement in `config.py`**

```python
# module level, next to CONNECTOR_ADAPTERS
import re
FEEDBACK_REPO_RE = re.compile(r"\A[\w.-]+/[\w.-]+\Z")
_TOP_LEVEL_KEYS = ("config-version", "timezone", "executive", "adapters", "feedback")
```

In `_validate`, before the unknown/absent checks:

```python
    cfg.setdefault("feedback", {"repo": None})
```

and after the adapters loop:

```python
    feedback = cfg["feedback"]
    if not isinstance(feedback, dict) or set(feedback) != {"repo"}:
        raise ConfigError('feedback must be an object with exactly the key "repo"')
    repo = feedback["repo"]
    if repo is not None and (
            not isinstance(repo, str) or not FEEDBACK_REPO_RE.match(repo)):
        raise ConfigError(
            'feedback.repo must be null or an "owner/name" GitHub slug')
```

`read()` is unchanged — `feedback.repo` never joins `missing` (feedback is an optional feature, not onboarding state).

- [ ] **Step 4: Run the config tests**

Run: `python -m pytest scripts/tests/test_vaultlib_config.py -q`
Expected: PASS (including all pre-existing tests — the default injection must not break the exact-keys assertions).

- [ ] **Step 5: Template + validator.** In `template/99-workflow-config/config.json`, add after the `adapters` object:

```json
  "feedback": {"repo": null}
```

and append a `_readme` line: `"feedback.repo: the delaware-created sb-client-<slug> GitHub repo (owner/name) that /report-feedback files issues on; null until provisioning sets it."`

In `scripts/validate_template.py` `check_config`, add:

```python
    if cfg.get("feedback") != {"repo": None}:
        problems.append('template config.json must ship feedback as {"repo": null}')
```

Extend `scripts/tests/test_template_config.py` (shipped default carries the key) and `scripts/tests/test_validate_template.py` (a template whose config lacks `feedback` or ships a non-null repo is flagged) following each file's existing pattern.

- [ ] **Step 6: Full gate**

Run: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`
Expected: all green.

- [ ] **Step 7: Commit** — `feat: config gains an optional feedback.repo (defaulted, strictly validated)`

---

### Task 2: `config write` subcommand

Field-level sets on `config.json`. The CLI owns the file: `_readme` keys survive, the whole result re-validates before a byte lands, and the display-name hint rule fires at write time.

**Files:**
- Modify: `plugin/lib/vaultlib/config.py`
- Modify: `plugin/lib/vaultlib/cli.py` (parser + dispatch)
- Test: `scripts/tests/test_vaultlib_config.py`, `scripts/tests/test_vaultlib_cli.py`

**Interfaces:**
- Consumes: Task 1's `_validate` (with feedback support), `vault.atomic_write`.
- Produces: `config.write(root, field, value) -> dict` (same shape as `config.read`); CLI `config write --vault V --field F (--value X | --null)`. `config.WRITABLE_FIELDS: tuple[str, ...]`. Callers in later tasks: `/setup-my-brain` (Task 14) writes `timezone`, `executive`, `adapters.*.account_hint`, `adapters.*.enabled`; the runbook writes `feedback.repo`.

- [ ] **Step 1: Write the failing tests** (`test_vaultlib_config.py`):

```python
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
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest scripts/tests/test_vaultlib_config.py -q -k write` → FAIL (`config` has no attribute `write`).

- [ ] **Step 3: Implement `config.write`:**

```python
WRITABLE_FIELDS = (
    "timezone", "executive", "feedback.repo",
) + tuple(f"adapters.{name}.enabled" for name in ADAPTERS) + tuple(
    f"adapters.{name}.account_hint" for name in CONNECTOR_ADAPTERS)

_BOOL_FIELDS = tuple(f for f in WRITABLE_FIELDS if f.endswith(".enabled"))


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
    from vaultlib import vault  # local import avoids a cycle
    vault.atomic_write(path, json.dumps(raw, indent=2) + "\n")
    return read(root)
```

(If `from vaultlib import vault` at module top causes no cycle — `vault.py` does not import `config` — prefer the top-level import.)

- [ ] **Step 4: Run the config tests** — `python -m pytest scripts/tests/test_vaultlib_config.py -q` → PASS.

- [ ] **Step 5: Wire the CLI.** In `build_parser()` after `config_verify`:

```python
    config_write = config_sub.add_parser(
        "write", help="set one config field; the whole file re-validates first")
    _add_vault_argument(config_write)
    config_write.add_argument(
        "--field", required=True, choices=sorted(config.WRITABLE_FIELDS))
    value_group = config_write.add_mutually_exclusive_group(required=True)
    value_group.add_argument("--value", help="the new value (true/false for .enabled)")
    value_group.add_argument("--null", action="store_true",
                             help="unset the field (nullable fields only)")
```

In `_dispatch`, inside `if args.group == "config":` before the verify-account branch:

```python
        if args.action == "write":
            if args.null:
                value = None
            elif args.field.endswith(".enabled"):
                if args.value not in ("true", "false"):
                    raise config.ConfigError(
                        f"{args.field} takes --value true or false")
                value = args.value == "true"
            else:
                value = args.value
            return _ok(config.write(root, args.field, value))
```

Add a CLI envelope test in `test_vaultlib_cli.py` in that file's existing style (invoke `cli.main([...])`, capture stdout JSON): a `config write --field timezone --value Europe/Brussels` run returns `ok: true`, and `--field adapters.plaud.account_hint --value Morgan` returns `ok: false` with the display-name hint in `error`.

- [ ] **Step 6: Full gate** — all green.
- [ ] **Step 7: Commit** — `feat: config write — CLI-owned field sets with whole-file revalidation`

---

### Task 3: `context read` / `context write` — the five-file marker machinery

Generalizes the `identity.md` block machinery to all five context-portfolio files. `identity show` stays (skills reference it); `context read --file identity` returns the same block.

**Files:**
- Modify: `plugin/lib/vaultlib/vault.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: `scripts/tests/test_vaultlib_vault.py`, `scripts/tests/test_vaultlib_cli.py`

**Interfaces:**
- Consumes: `vault._BEGIN`/`_END` markers, `vault.atomic_write`.
- Produces: `vault.CONTEXT_FILES: tuple[str, ...]` = the five stems `("identity", "role-and-responsibilities", "communication-style", "preferences-and-constraints", "tools-and-systems")`; `vault.read_context_block(root, stem) -> Optional[str]`; `vault.write_context_block(root, stem, content) -> dict` returning `{"file": "<vault-relative path>", "replaced": bool}`. CLI: `context read --vault V --file STEM`, `context write --vault V --file STEM --content FILE|-`. Task 14's `/setup-my-brain` is the caller.

- [ ] **Step 1: Failing tests** (`test_vaultlib_vault.py` — reuse its `make_vault` helper; it creates `99-workflow-config/`, so the test writes the context file itself):

```python
CONTEXT_TEMPLATE = """# Role

> **Placeholder.** Filled by the onboarding interview (`/setup-my-brain`).

## Interview questions

- What do you own?

## Content

<!-- setup-my-brain:begin -->
<!-- setup-my-brain:end -->
"""


def _write_context(root, stem, text=CONTEXT_TEMPLATE):
    path = root / "99-workflow-config" / "context" / f"{stem}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_write_context_block_replaces_only_the_fenced_region(tmp_path):
    root = make_vault(tmp_path)
    path = _write_context(root, "role-and-responsibilities")
    before = path.read_text(encoding="utf-8")
    result = vault.write_context_block(
        root, "role-and-responsibilities", "Owns commercial strategy.")
    after = path.read_text(encoding="utf-8")
    assert "Owns commercial strategy." in after
    # every byte outside the markers is preserved exactly
    begin, end = "<!-- setup-my-brain:begin -->", "<!-- setup-my-brain:end -->"
    assert after.split(begin)[0] == before.split(begin)[0]
    assert after.split(end)[1] == before.split(end)[1]
    assert vault.read_context_block(root, "role-and-responsibilities") \
        == "Owns commercial strategy."


def test_write_context_block_is_idempotent(tmp_path):
    root = make_vault(tmp_path)
    path = _write_context(root, "identity")
    vault.write_context_block(root, "identity", "Alex Doe, CEO.")
    once = path.read_text(encoding="utf-8")
    vault.write_context_block(root, "identity", "Alex Doe, CEO.")
    assert path.read_text(encoding="utf-8") == once


def test_write_context_block_refuses_marker_in_content(tmp_path):
    root = make_vault(tmp_path)
    _write_context(root, "identity")
    with pytest.raises(vault.VaultError):
        vault.write_context_block(
            root, "identity", "x\n<!-- setup-my-brain:end -->\ny")


def test_write_context_block_unknown_stem_and_missing_markers(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(vault.VaultError):
        vault.write_context_block(root, "shopping-list", "x")
    _write_context(root, "identity", "# Identity\n\nno markers here\n")
    with pytest.raises(vault.VaultError):
        vault.write_context_block(root, "identity", "x")
```

- [ ] **Step 2: Verify failure** — `python -m pytest scripts/tests/test_vaultlib_vault.py -q -k context` → FAIL (no `write_context_block`).

- [ ] **Step 3: Implement in `vault.py`:**

```python
CONTEXT_DIR = Path("99-workflow-config") / "context"
CONTEXT_FILES = ("identity", "role-and-responsibilities", "communication-style",
                 "preferences-and-constraints", "tools-and-systems")


def _context_path(root: Path, stem: str) -> Path:
    if stem not in CONTEXT_FILES:
        raise VaultError(
            f"context file must be one of {sorted(CONTEXT_FILES)}, got {stem!r}")
    path = root / CONTEXT_DIR / f"{stem}.md"
    if not path.is_file():
        raise VaultError(f"{CONTEXT_DIR / (stem + '.md')} is missing from this vault")
    return path


def read_context_block(root: Path, stem: str) -> Optional[str]:
    text = _context_path(root, stem).read_text(encoding="utf-8")
    start, end = text.find(_BEGIN), text.find(_END)
    if start == -1 or end == -1 or end <= start:
        return None
    block = text[start + len(_BEGIN):end].strip()
    return block or None


def write_context_block(root: Path, stem: str, content: str) -> dict:
    if _BEGIN in content or _END in content:
        raise VaultError(
            "content must not contain the setup-my-brain markers — the CLI "
            "owns them")
    path = _context_path(root, stem)
    text = path.read_text(encoding="utf-8")
    start, end = text.find(_BEGIN), text.find(_END)
    if start == -1 or end == -1 or end <= start:
        raise VaultError(
            f"{path.name} has no intact setup-my-brain marker pair — restore "
            "it from the template before writing")
    replaced = bool(text[start + len(_BEGIN):end].strip())
    new = (text[:start + len(_BEGIN)] + "\n" + content.strip() + "\n"
           + text[end:])
    atomic_write(path, new)
    return {"file": str(CONTEXT_DIR / f"{stem}.md"), "replaced": replaced}
```

Refactor `read_identity_block` to `return read_context_block(root, "identity")` — but keep its missing-file behavior (`None`, not an error): catch `VaultError` and return `None` so the existing `identity show` contract is unchanged.

- [ ] **Step 4: Run vault tests** — `python -m pytest scripts/tests/test_vaultlib_vault.py -q` → PASS (including pre-existing identity tests).

- [ ] **Step 5: Wire the CLI** — new group in `build_parser()`:

```python
    context = top.add_parser("context", help="context portfolio marker blocks")
    context_sub = context.add_subparsers(dest="action", required=True)
    context_read = context_sub.add_parser("read", help="print one file's block")
    _add_vault_argument(context_read)
    context_read.add_argument("--file", required=True,
                              choices=sorted(vault.CONTEXT_FILES))
    context_write = context_sub.add_parser(
        "write", help="replace one file's setup-my-brain block")
    _add_vault_argument(context_write)
    context_write.add_argument("--file", required=True,
                               choices=sorted(vault.CONTEXT_FILES))
    context_write.add_argument("--content", required=True,
                               help="path to a text file, or - to read stdin")
```

Dispatch:

```python
    if args.group == "context":
        if args.action == "read":
            return _ok({"file": args.file,
                        "content": vault.read_context_block(root, args.file)})
        content = (sys.stdin.read() if args.content == "-"
                   else Path(args.content).read_text(encoding="utf-8"))
        return _ok(vault.write_context_block(root, args.file, content))
```

Add a `test_vaultlib_cli.py` envelope test: write then read via `cli.main`, assert round-trip.

- [ ] **Step 6: Full gate.** — all green.
- [ ] **Step 7: Commit** — `feat: context read/write — marker-fenced blocks for all five context files`

---

### Task 4: `feedback` library — token, scrub lint, GitHub send

**Files:**
- Create: `plugin/lib/vaultlib/feedback.py`
- Modify: `plugin/lib/vaultlib/vault.py` (two small helpers), `plugin/lib/vaultlib/cli.py`
- Test: Create `scripts/tests/test_vaultlib_feedback.py`; extend `scripts/tests/test_vaultlib_cli.py`

**Interfaces:**
- Consumes: `config.read` (Task 1: `feedback.repo`), `markdown.split_frontmatter`, `vault` folder constants.
- Produces:
  - `vault.plugin_version() -> str` — reads `plugin/.claude-plugin/plugin.json` relative to `vault.py` (`Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"`), returns `"unknown"` if unreadable (never raises — feedback must work even if packaging broke).
  - `vault.structure_version(root) -> str` — content of the vault-root `structure-version` file, stripped; raises `VaultError` if missing.
  - `feedback.SECRETS_RELPATH = Path("99-workflow-config") / "secrets" / "feedback-token"`
  - `feedback.DISCLOSURE: str` (exact text below — Tasks 5, 10, 11 reuse it verbatim).
  - `feedback.lint(root, text) -> dict` — `{"ok": bool, "blocked": [{"kind": str, "fragment": str}], "terms_checked": int}`.
  - `feedback.send(root, title, body, post=None) -> dict` — `{"issue_url": str, "lint": {...}}`; `post` is injectable for tests.
  - `feedback.FeedbackError`.
  - CLI: `feedback lint --vault V --body-file F|-` and `feedback send --vault V --title T --body-file F|-`.

**The disclosure text (single source of truth, module constant):**

```python
DISCLOSURE = (
    "**What this report contains and how it is used:** this report carries "
    "only the plugin version, the vault structure version, the skill "
    "involved, a generic description of expected vs. actual behavior, and "
    "counts. It contains zero personal or business content: no note text, "
    "no names of people or organizations, no meeting titles. A deterministic "
    "scrub check enforces this before anything is sent. The only identifying "
    "fact is which deployment it came from, which is what makes it "
    "actionable. delaware uses these reports solely to improve the product. "
    "Nothing is ever sent without your explicit approval."
)
```

- [ ] **Step 1: Failing tests** (`test_vaultlib_feedback.py`). Build a small vault inline (reuse `make_vault` from `test_vaultlib_vault`), then create objects the blocklist must catch:

```python
"""Deterministic scrub lint + approval-gated GitHub send.

The lint is the technical control behind the disclosure promise: a draft
that names anything from the vault is refused before a byte leaves the
machine.
"""
import json

import pytest

from vaultlib import config, feedback

from test_vaultlib_vault import make_vault
from test_vaultlib_config import valid_config, write_config


def seeded_vault(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config(
        feedback={"repo": "delaware-org/sb-client-demo"}))
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    (root / "50-people" / "casey-morrow.md").write_text(
        "---\nperson-name: Casey Morrow\n---\n", encoding="utf-8")
    (root / "40-entities" / "northwind-logistics").mkdir(parents=True)
    (root / "40-entities" / "northwind-logistics" / "dossier.md").write_text(
        "---\nentity-name: Northwind Logistics\n---\n", encoding="utf-8")
    (root / "30-projects" / "fleet-renewal").mkdir(parents=True)
    (root / "30-projects" / "fleet-renewal" / "index.md").write_text(
        "---\nproject-name: Fleet Renewal\nentity: northwind-logistics\n---\n",
        encoding="utf-8")
    (root / "20-meetings" / "2026-08-20-northwind-steering.md").write_text(
        "---\ntitle: Northwind steering\n---\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("fragment,kind", [
    ("Casey Morrow told us", "person"),
    ("the casey-morrow note", "person"),
    ("Northwind Logistics renewal", "entity"),
    ("see fleet-renewal", "project"),
    ("in 2026-08-20-northwind-steering", "meeting"),
    ("mail me at casey@northwind.example", "email"),
    ("links like [[anything]]", "wikilink"),
    ("the file 20-meetings/2026-08-20-x.md", "vault-path"),
    ("hint was morgan@example.com", "email"),
])
def test_lint_blocks_vault_data(tmp_path, fragment, kind):
    root = seeded_vault(tmp_path)
    result = feedback.lint(root, f"The sync failed. {fragment}.")
    assert result["ok"] is False
    assert kind in {b["kind"] for b in result["blocked"]}


def test_lint_passes_a_clean_generic_draft(tmp_path):
    root = seeded_vault(tmp_path)
    clean = ("Expected the evening run to write one prep region per "
             "calendar meeting; got a structural-change error on re-run. "
             "3 meetings, 1 daily note.")
    result = feedback.lint(root, clean)
    assert result["ok"] is True and result["blocked"] == []
    assert result["terms_checked"] > 0


def test_send_posts_lint_clean_draft_with_deployment_and_disclosure(tmp_path):
    root = seeded_vault(tmp_path)
    (root / "99-workflow-config" / "secrets").mkdir(parents=True)
    (root / "99-workflow-config" / "secrets" / "feedback-token").write_text(
        "ghp_test123\n", encoding="utf-8")
    calls = {}

    def fake_post(url, token, payload):
        calls.update(url=url, token=token, payload=payload)
        return {"html_url": "https://github.com/delaware-org/sb-client-demo/issues/1"}

    result = feedback.send(root, "Evening sync re-run error",
                           "Generic description.", post=fake_post)
    assert result["issue_url"].endswith("/issues/1")
    assert calls["url"] == ("https://api.github.com/repos/"
                            "delaware-org/sb-client-demo/issues")
    assert calls["token"] == "ghp_test123"
    body = calls["payload"]["body"]
    assert "Generic description." in body
    assert "structure-version 2" in body        # deployment stamp
    assert feedback.DISCLOSURE in body           # promise travels with the issue


def test_send_refuses_blocked_draft_and_missing_channel(tmp_path):
    root = seeded_vault(tmp_path)
    (root / "99-workflow-config" / "secrets").mkdir(parents=True)
    (root / "99-workflow-config" / "secrets" / "feedback-token").write_text(
        "t\n", encoding="utf-8")
    with pytest.raises(feedback.FeedbackError):
        feedback.send(root, "x", "Casey Morrow said so", post=lambda *a: {})
    write_config(root, valid_config())           # feedback.repo back to null
    with pytest.raises(feedback.FeedbackError):
        feedback.send(root, "x", "clean", post=lambda *a: {})
```

Also: a token-file-missing test (repo set, no secrets file → `FeedbackError` naming the path).

- [ ] **Step 2: Verify failure** — `python -m pytest scripts/tests/test_vaultlib_feedback.py -q` → FAIL (module missing).

- [ ] **Step 3: Implement `feedback.py`.** Core logic:

```python
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_WIKILINK_RE = re.compile(r"\[\[")
_VAULT_PATH_RE = re.compile(
    r"\b(?:10-inbox|20-meetings|30-projects|40-entities|50-people|"
    r"60-daily-notes|70-resources|80-thoughts-ideas|90-archive|95-private)/\S+")
_MIN_TERM_LEN = 4   # "Jo" as a substring would block the word "major"


def _blocklist(root):
    """(kind, term) pairs. Deterministic, order-stable, casefolded later."""
    terms = []
    for path in sorted((root / vault.PEOPLE_DIR).glob("*.md")):
        terms.append(("person", path.stem))
        front, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        if front.get("person-name"):
            terms.append(("person", str(front["person-name"])))
    for path in sorted((root / vault.ENTITIES_DIR).glob("*/dossier.md")):
        terms.append(("entity", path.parent.name))
        front, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        if front.get("entity-name"):
            terms.append(("entity", str(front["entity-name"])))
    for path in sorted((root / vault.PROJECTS_DIR).glob("*/index.md")):
        terms.append(("project", path.parent.name))
        front, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        if front.get("project-name"):
            terms.append(("project", str(front["project-name"])))
    for path in sorted((root / vault.MEETINGS_DIR).glob("*.md")):
        terms.append(("meeting", path.stem))
        front, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        if front.get("title"):
            terms.append(("meeting", str(front["title"])))
    cfg = config.read(root)["config"]
    if cfg["executive"]:
        terms.append(("executive", cfg["executive"]))
    for name in config.CONNECTOR_ADAPTERS:
        hint = cfg["adapters"][name]["account_hint"]
        if hint:
            terms.append(("account", hint))
    return [(kind, term) for kind, term in terms
            if len(term.strip()) >= _MIN_TERM_LEN]
```

`lint(root, text)`: casefold `text`; for each `(kind, term)` blocklist entry, substring match on the casefolded term → collect `{"kind": kind, "fragment": term}`; then the three regexes on the raw text (`kind` = `email` / `wikilink` / `vault-path`, fragment = the match). Dedupe on `(kind, fragment)`. `ok` = no blocked entries. Unreadable object files: skip the frontmatter name but keep the stem term (one mangled file must not disable the guard).

`send(root, title, body, post=None)`: read config → `repo = cfg["feedback"]["repo"]`, raise `FeedbackError("feedback.repo is not configured …")` if null; token from `SECRETS_RELPATH` (raise naming the vault-relative path if missing; `.strip()` it); `lint` on `title + "\n" + body` → on block raise `FeedbackError` listing kinds + fragments (local only); assemble:

```python
    full_body = (body.rstrip() + "\n\n---\n"
                 f"**Deployment:** plugin {vault.plugin_version()} · "
                 f"structure-version {vault.structure_version(root)}\n\n"
                 + DISCLOSURE + "\n")
```

`_post(url, token, payload)` (the default when `post is None`) uses `urllib.request.Request` with headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `User-Agent: sb-accelerator`, `Content-Type: application/json`, method POST, `json.dumps(payload).encode()`; parse the JSON response; wrap `urllib.error.URLError`/`HTTPError` in `FeedbackError` **without echoing the token**. Return `{"issue_url": response["html_url"], "lint": lint_result}`.

Add the two `vault.py` helpers (`plugin_version`, `structure_version`) per the Interfaces block.

- [ ] **Step 4: Run** — `python -m pytest scripts/tests/test_vaultlib_feedback.py -q` → PASS.

- [ ] **Step 5: Wire the CLI** (`feedback` group; `lint` takes `--body-file`, `send` takes `--title` + `--body-file`; both accept `-` for stdin; dispatch reads the file then calls the library; add `except feedback.FeedbackError` to `main` with hint `"Fix the named constraint; nothing was sent."`). Envelope tests in `test_vaultlib_cli.py`: lint-clean returns `ok: true`; send without repo returns `ok: false` and the error names `feedback.repo`.

- [ ] **Step 6: Full gate.**
- [ ] **Step 7: Commit** — `feat: feedback lint + send — deterministic scrub gate before any issue leaves the machine`

---

### Task 5: Template — secrets dir, disclosure + nudge + secrets rule in vault CLAUDE.md

**Files:**
- Create: `template/99-workflow-config/secrets/README.md`
- Modify: `template/CLAUDE.md`
- Modify: `scripts/validate_template.py`
- Test: `scripts/tests/test_validate_template.py`

**Interfaces:**
- Consumes: `feedback.DISCLOSURE` text (Task 4) — the CLAUDE.md wording must contain its two load-bearing phrases verbatim: `solely to improve the product` and `explicit approval`.
- Produces: the template contract Tasks 10/11/14 SKILL.mds refer to.

- [ ] **Step 1: Failing validator tests** (`test_validate_template.py`, following its existing make-a-broken-copy pattern): a template copy without `secrets/README.md` is flagged; a copy whose `CLAUDE.md` lacks `solely to improve the product` or lacks `99-workflow-config/secrets` is flagged.

- [ ] **Step 2: Run** — expected FAIL (checks don't exist).

- [ ] **Step 3: Write the template content.**

`template/99-workflow-config/secrets/README.md`:

```markdown
# Secrets

Machine credentials placed here at provisioning. Currently one file:

- `feedback-token` — a fine-grained GitHub token (issues read/write on this
  deployment's own feedback repo, nothing else) used by `/report-feedback`.

These files are read only by the plugin's CLI, which never prints them.
Claude must never read or display files in this folder. If a token needs
replacing, your delaware consultant rotates it at a tune-up.
```

`template/CLAUDE.md` — add a new section before `## Self-Improvement Loop`:

```markdown
## Feedback to delaware

When a skill breaks, a flow is confusing, or the same friction keeps coming
back, offer: "want me to report this to delaware?" On yes, run
`/report-feedback` with a prefilled draft. Never send anything without the
user's explicit approval of the exact draft.

Every report is scrubbed by a deterministic check before sending: it carries
only the plugin version, structure version, the skill involved, expected vs.
actual behavior, and counts — zero personal or business content, no names,
no note text. The only identifying fact is which deployment it came from.
delaware uses these reports solely to improve the product.

Never read or display files under `99-workflow-config/secrets/` — they are
machine credentials, owned by the CLI.
```

- [ ] **Step 4: Extend `validate_template.py`** — in `main` (or a new `check_feedback_contract(template)` called from it):

```python
    if not (template / "99-workflow-config" / "secrets" / "README.md").is_file():
        problems.append("template is missing 99-workflow-config/secrets/README.md")
    claude_md = (template / "CLAUDE.md").read_text(encoding="utf-8")
    for phrase in ("solely to improve the product", "explicit approval",
                   "99-workflow-config/secrets"):
        if phrase not in claude_md:
            problems.append(
                f"template CLAUDE.md is missing the feedback-contract phrase "
                f"{phrase!r}")
```

- [ ] **Step 5: Run the gate** — `python scripts/validate_template.py && python -m pytest scripts/tests -q` → green. Also confirm `python scripts/lint_plugin.py` (template text passes clean-room — "delaware" as vendor name is fine).
- [ ] **Step 6: Commit** — `feat(template): secrets folder + feedback disclosure and nudge rule in vault CLAUDE.md`

---

### Task 6: `migrate` framework — discovery, status, snapshot, run, log

**Files:**
- Create: `plugin/lib/vaultlib/migrate.py`
- Create: `plugin/migrations/README.md` (format contract; the *repo-level* `migrations/README.md` is repointed in Task 8)
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: Create `scripts/tests/test_vaultlib_migrate.py`; extend `test_vaultlib_cli.py`

**Interfaces:**
- Consumes: `vault.atomic_write`, `vault.structure_version` (Task 4), `vault.plugin_version` (Task 4).
- Produces:
  - Migration module contract (what Task 7/8's `migrate.py` implements): module-level `TARGET_VERSION: int`, `LOSSY: str | None`, `apply(root: Path) -> dict`, `verify(root: Path) -> dict`. `apply`/`verify` reports are JSON-serializable dicts; a failed verify **raises** (any exception) rather than returning.
  - `migrate.MIGRATIONS_DIR: Path` — module constant `Path(__file__).resolve().parents[2] / "migrations"`; tests monkeypatch it.
  - `migrate.discover() -> list[dict]` — sorted by number: `{"number": int, "slug": str, "path": Path, "module": module}`; raises `MigrateError` on a malformed dir name (`NNN-slug`) or a module missing the contract.
  - `migrate.status(root) -> dict` — `{"structure_version": int, "expected_version": int, "pending": [{"number", "slug", "target_version", "lossy"}]}`. Pending = migrations with `TARGET_VERSION > structure_version`, in order; also raises if the chain has a gap (a pending migration whose `TARGET_VERSION != previous + 1`).
  - `migrate.run(root, today, stamp=None) -> dict` — `{"snapshot": str | None, "applied": [{"number","slug","target_version","apply","verify"}], "structure_version": int}`; `stamp` overrides the snapshot timestamp for tests (`YYYY-MM-DD-HHMMSS` string; default from `datetime.now()`).
  - `migrate.SNAPSHOT_DIR = Path("99-workflow-config") / "snapshots"`, `migrate.LOG_RELPATH = Path("99-workflow-config") / "migration-log.md"`, `migrate.KEEP_SNAPSHOTS = 3`.
  - CLI: `migrate status --vault V`, `migrate run --vault V [--today D] [--stamp S]`.

- [ ] **Step 1: Failing tests.** Build fake migrations in tmp dirs and monkeypatch `migrate.MIGRATIONS_DIR`:

```python
import textwrap

import pytest

from vaultlib import migrate, vault

from test_vaultlib_vault import make_vault


def write_migration(dirpath, number, slug, target, body_marker, lossy=None,
                    fail_apply=False):
    mdir = dirpath / f"{number:03d}-{slug}"
    mdir.mkdir(parents=True)
    (mdir / "migrate.py").write_text(textwrap.dedent(f"""\
        from pathlib import Path
        TARGET_VERSION = {target}
        LOSSY = {lossy!r}
        def apply(root):
            if {fail_apply}:
                raise RuntimeError("boom")
            (root / "{body_marker}").write_text("done", encoding="utf-8")
            return {{"marker": "{body_marker}"}}
        def verify(root):
            assert (root / "{body_marker}").is_file()
            return {{"checked": 1}}
        """), encoding="utf-8")
    return mdir


@pytest.fixture
def migrations_dir(tmp_path, monkeypatch):
    mdir = tmp_path / "migrations"
    mdir.mkdir()
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", mdir)
    return mdir


def versioned_vault(tmp_path, version="1"):
    root = make_vault(tmp_path)
    (root / "structure-version").write_text(f"{version}\n", encoding="utf-8")
    return root


def test_status_lists_pending_in_order(tmp_path, migrations_dir):
    write_migration(migrations_dir, 1, "first", 2, "m1", lossy="drops a field")
    write_migration(migrations_dir, 2, "second", 3, "m2")
    root = versioned_vault(tmp_path)
    result = migrate.status(root)
    assert result["structure_version"] == 1
    assert result["expected_version"] == 3
    assert [p["slug"] for p in result["pending"]] == ["first", "second"]
    assert result["pending"][0]["lossy"] == "drops a field"


def test_run_applies_pending_snapshots_first_bumps_and_logs(tmp_path,
                                                            migrations_dir):
    write_migration(migrations_dir, 1, "first", 2, "m1")
    root = versioned_vault(tmp_path)
    result = migrate.run(root, "2026-08-25", stamp="2026-08-25-101500")
    assert result["structure_version"] == 2
    assert [a["slug"] for a in result["applied"]] == ["first"]
    assert (root / "99-workflow-config" / "snapshots"
            / "vault-2026-08-25-101500.zip").is_file()
    assert vault.structure_version(root) == "2"
    log = (root / "99-workflow-config" / "migration-log.md") \
        .read_text(encoding="utf-8")
    assert "v1→v2" in log and "vault-2026-08-25-101500.zip" in log
    # re-run: nothing pending, no second snapshot
    again = migrate.run(root, "2026-08-25", stamp="2026-08-25-102000")
    assert again["applied"] == [] and again["snapshot"] is None
    assert not (root / "99-workflow-config" / "snapshots"
                / "vault-2026-08-25-102000.zip").exists()


def test_snapshot_rotation_keeps_three(tmp_path, migrations_dir):
    root = versioned_vault(tmp_path)
    snapdir = root / "99-workflow-config" / "snapshots"
    for stamp in ("2026-08-01-000000", "2026-08-02-000000",
                  "2026-08-03-000000"):
        migrate.snapshot(root, stamp)
    migrate.snapshot(root, "2026-08-04-000000")
    names = sorted(p.name for p in snapdir.glob("*.zip"))
    assert len(names) == 3 and "vault-2026-08-01-000000.zip" not in names


def test_snapshot_excludes_snapshots_dir(tmp_path, migrations_dir):
    import zipfile
    root = versioned_vault(tmp_path)
    migrate.snapshot(root, "2026-08-01-000000")
    path = migrate.snapshot(root, "2026-08-02-000000")
    with zipfile.ZipFile(root / path) as zf:
        assert not any("snapshots/" in n for n in zf.namelist())
        assert any(n.endswith("structure-version") for n in zf.namelist())


def test_failed_apply_stops_chain_and_logs_failure(tmp_path, migrations_dir):
    write_migration(migrations_dir, 1, "first", 2, "m1")
    write_migration(migrations_dir, 2, "boom", 3, "m2", fail_apply=True)
    root = versioned_vault(tmp_path)
    with pytest.raises(migrate.MigrateError):
        migrate.run(root, "2026-08-25", stamp="2026-08-25-101500")
    # first landed, second did not, version reflects the stop point
    assert vault.structure_version(root) == "2"
    log = (root / "99-workflow-config" / "migration-log.md") \
        .read_text(encoding="utf-8")
    assert "FAILED" in log


def test_chain_gap_is_refused(tmp_path, migrations_dir):
    write_migration(migrations_dir, 1, "first", 2, "m1")
    write_migration(migrations_dir, 2, "skips", 4, "m2")
    root = versioned_vault(tmp_path)
    with pytest.raises(migrate.MigrateError):
        migrate.status(root)
```

- [ ] **Step 2: Verify failure** — module missing.

- [ ] **Step 3: Implement `migrate.py`.** Key pieces:

```python
"""Vault structure migrations: snapshot, apply, verify, log.

Migrations ship inside the plugin (plugin/migrations/NNN-<slug>/migrate.py)
so they ride the marketplace update channel — plugin version <-> available
migrations is deterministic. Consultant-run via /upgrade-vault, never
unattended.
"""
import datetime as _datetime
import importlib.util
import json
import re
import zipfile
from pathlib import Path

from vaultlib import vault

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
SNAPSHOT_DIR = Path("99-workflow-config") / "snapshots"
LOG_RELPATH = Path("99-workflow-config") / "migration-log.md"
KEEP_SNAPSHOTS = 3
_DIR_RE = re.compile(r"\A(\d{3})-([a-z0-9-]+)\Z")


class MigrateError(Exception):
    """A migration state or contract problem the caller must fix."""
```

- `discover()`: iterate `sorted(MIGRATIONS_DIR.iterdir())`, skip non-dirs and files (the README); parse `NNN-slug`; `importlib.util.spec_from_file_location(f"sb_migration_{number:03d}", path / "migrate.py")`; assert `isinstance(module.TARGET_VERSION, int)`, `callable(module.apply)`, `callable(module.verify)`, `LOSSY` present (may be `None`) — each violation raises `MigrateError` naming the directory.
- `_current(root)`: `int(vault.structure_version(root))`, `MigrateError` on non-integer.
- `status(root)`: pending = `[m for m in discover() if m TARGET_VERSION > current]`; walk pending asserting consecutive `TARGET_VERSION` starting at `current + 1` (gap → `MigrateError`); `expected_version = max(TARGET_VERSION, default=current)`.
- `snapshot(root, stamp)`: `zipfile.ZipFile(root / SNAPSHOT_DIR / f"vault-{stamp}.zip", "w", zipfile.ZIP_DEFLATED)`; walk `root.rglob("*")`, skip anything under `SNAPSHOT_DIR` and skip directories; arcnames relative to root. Then rotate: delete oldest zips beyond `KEEP_SNAPSHOTS` (sort by name — stamps sort chronologically). Returns the vault-relative path string.
- `_log(root, today, from_v, to_v, snapshot_name, outcome)`: create `LOG_RELPATH` with a two-line header (`# Migration log` + blank) if missing; append `- {today} · v{from_v}→v{to_v} · plugin {vault.plugin_version()} · snapshot {snapshot_name} · {outcome}\n` (plain append via read+`atomic_write`).
- `run(root, today, stamp=None)`: `status` first; empty pending → `{"snapshot": None, "applied": [], "structure_version": current}`. Otherwise `stamp = stamp or _datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")`; snapshot once; for each pending: `apply` → `verify` → `vault.atomic_write(root / "structure-version", f"{target}\n")` → `_log(..., "ok")`. On exception: `_log(..., f"FAILED: {exc}")` then `raise MigrateError(f"migration {number:03d}-{slug} failed after snapshot {name}: {exc}") from exc`.

- [ ] **Step 4: Run** — `python -m pytest scripts/tests/test_vaultlib_migrate.py -q` → PASS.

- [ ] **Step 5: CLI wiring** (`migrate` group per the Interfaces block; `--stamp` help: "snapshot timestamp override (tests)"; add `except migrate.MigrateError` in `main` with hint `"Restore from the named snapshot if needed; fix the cause; re-run."`). Envelope test in `test_vaultlib_cli.py` with a monkeypatched `MIGRATIONS_DIR`. Write `plugin/migrations/README.md` documenting the module contract verbatim (TARGET_VERSION/LOSSY/apply/verify, idempotency requirement, assets convention from Task 7) — client-readable, clean-room.

- [ ] **Step 6: Full gate.**
- [ ] **Step 7: Commit** — `feat: migrate framework — snapshot, ordered apply+verify, migration log`

---

### Task 7: Migration 001, part A — config, decisions, review_status, README/CLAUDE/ontology refresh

Migration `001-structure-version-2` carries **asset files** (canonical copies of template content) so `apply` never needs the template at runtime. A dedicated test pins each asset byte-equal to its template counterpart — the assets cannot drift.

**Files:**
- Create: `plugin/migrations/001-structure-version-2/migrate.py`
- Create: `plugin/migrations/001-structure-version-2/assets/config.json` (copy of `template/99-workflow-config/config.json`)
- Create: `plugin/migrations/001-structure-version-2/assets/10-inbox-README.md` (copy of `template/10-inbox/README.md`)
- Create: `plugin/migrations/001-structure-version-2/assets/90-archive-README.md` (copy of `template/90-archive/README.md`)
- Create: `plugin/migrations/001-structure-version-2/assets/ontology.md` (copy of `template/99-workflow-config/reference/ontology.md`)
- Create: `plugin/migrations/001-structure-version-2/assets/claude-inbox-discipline.md` (the body of `template/CLAUDE.md`'s `## Inbox Discipline` section, heading line included)
- Test: Create `scripts/tests/test_migration_001.py`

**Interfaces:**
- Consumes: Task 6's contract; `markdown.split_frontmatter`, `markdown.upsert_scalar_field`, `markdown.replace_scalar_field`; `vault.atomic_write`.
- Produces: module `TARGET_VERSION = 2`, `LOSSY = "dossier Meeting Log entries: the Attendees, Key outcomes and Follow-ups lines are dropped — that content lives in the meeting notes"`; `apply`/`verify` per contract. Part B (Task 8) **extends this same module** — structure `apply` as an ordered list of step functions (`_step_config`, `_step_decisions`, `_step_review_status`, `_step_readmes`, `_step_claude_md`, `_step_ontology`, and in Task 8 `_step_entities_backfill`, `_step_dossiers`) so Task 8 appends two entries. `apply` returns `{"steps": {name: report}, "needs_human": [...]}`.

**Transformation rules (from `migrations/README.md` — quote them in the module docstring):**
1. `_step_config`: `99-workflow-config/config.json` missing → write `assets/config.json` verbatim. Present → untouched (report `"existed"`).
2. `_step_decisions`: every `30-projects/*/decisions/*.md`: if the frontmatter block contains a `tags:` node, delete the node (the `tags:` line plus any following `  - …` continuation lines — regex on the raw frontmatter block: `re.sub(r"(?m)^tags:.*\n(?:[ \t]+-.*\n)*", "", block)`); if `reviewed` is absent, `markdown.upsert_scalar_field(text, "reviewed", "true")` (pre-existing notes were human-authored — the v0.2.0 semantics). Count changed notes; already-conformant notes untouched (idempotency).
3. `_step_review_status`: every `20-meetings/*.md` whose frontmatter has `review_status: needs-attention` → `markdown.replace_scalar_field(text, "review_status", "needs-review")`.
4. `_step_readmes`: write `assets/10-inbox-README.md` → `10-inbox/README.md` (overwrite), `assets/90-archive-README.md` → `90-archive/README.md` (create parent if needed).
5. `_step_claude_md`: in the vault-root `CLAUDE.md`, replace the section from the line `## Inbox Discipline` up to (excluding) the next `\n## ` heading with the asset text. Section absent → do not guess; append the asset at the end and add `"CLAUDE.md had no Inbox Discipline section — appended; review placement"` to `needs_human`.
6. `_step_ontology`: overwrite `99-workflow-config/reference/ontology.md` with `assets/ontology.md`. Unconditional overwrite **is** the idempotent form.

`verify(root)` (part A): `config.json` parses via `config.read`; no decision note carries `tags:` in frontmatter; no meeting note carries `needs-attention`; both READMEs exist; vault `ontology.md` == asset text; vault `CLAUDE.md` contains the asset's first non-heading line.

- [ ] **Step 1: Failing tests** (`test_migration_001.py`). Load the module the same way `migrate.discover` does (helper at top):

```python
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
M001_DIR = REPO_ROOT / "plugin" / "migrations" / "001-structure-version-2"


def load_m001():
    spec = importlib.util.spec_from_file_location(
        "sb_migration_001", M001_DIR / "migrate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
```

Test cases (build an old-state vault with `make_vault` + hand-written old-format notes):
- `test_assets_match_template`: for each of the four full-file assets, `read_bytes()` equals the template counterpart's bytes; the claude-inbox asset's first line is `## Inbox Discipline` and its body appears verbatim inside `template/CLAUDE.md`.
- `test_config_step_writes_default_only_when_missing`.
- `test_decision_note_drops_tags_and_gains_reviewed`: old note

  ```
  ---
  decision-id: 2026-03-10-x
  tags:
    - decision
  ---
  Body.
  ```

  → after `apply`, frontmatter has no `tags`, has `reviewed: true`, body unchanged; a note already carrying `reviewed: false` keeps `false` (upsert only when absent).
- `test_review_status_rewrite`: `needs-attention` → `needs-review`; a `confirmed` note untouched byte-for-byte.
- `test_claude_md_section_replaced_between_headings`: a CLAUDE.md with `## Inbox Discipline\nold text\n\n## Self-Improvement Loop\nkeep` → asset text present, `keep` still present, `old text` gone.
- `test_apply_twice_is_idempotent`: run `apply` twice; second run reports zero changed notes and the vault bytes are identical after both runs.
- `test_verify_passes_after_apply_and_fails_before`.

- [ ] **Step 2: Verify failure** — directory missing.
- [ ] **Step 3: Create the assets** by copying the current template files (`cp`, then the pin test keeps them honest), extract the Inbox Discipline section into `claude-inbox-discipline.md`, and implement `migrate.py` per the rules above. Assets load via `Path(__file__).parent / "assets" / name`.
- [ ] **Step 4: Run** — `python -m pytest scripts/tests/test_migration_001.py -q` → PASS.
- [ ] **Step 5: Full gate** — note `lint_plugin.py` now scans `plugin/migrations/` content: assets are template copies, already clean.
- [ ] **Step 6: Commit** — `feat: migration 001 part A — config default, decision fields, review_status, doc refresh`

---

### Task 8: Migration 001, part B — entities backfill + dossier restructure; template goes to structure-version 2

**Files:**
- Modify: `plugin/migrations/001-structure-version-2/migrate.py`
- Modify: `template/structure-version` (`1` → `2`)
- Modify: `migrations/README.md` (top-level: becomes a pointer — "Migrations live in `plugin/migrations/` and ship with the plugin; the format contract is `plugin/migrations/README.md`. The pending-candidate list below moved into migration 001." Keep the *not-a-migration* skip-list note.)
- Modify: `scripts/validate_template.py` — assert `structure-version` content equals `2` (read, strip, compare; message names the file).
- Test: `scripts/tests/test_migration_001.py`, `scripts/tests/test_validate_template.py`

**Interfaces:**
- Consumes: Task 7's step-function structure; `markdown.split_frontmatter`.
- Produces: complete migration 001. `/upgrade-vault` (Task 12) and `/setup-my-brain` preflight (Task 14) rely on `migrate.status` reporting `expected_version == 2`.

**Transformation rules (verbatim from `migrations/README.md`):**

7. `_step_entities_backfill`: build `project_slug -> entity_slug` from every `30-projects/*/index.md` frontmatter `entity` field. For each `20-meetings/*.md` **without** an `entities` key: map its `projects` list through the table, dedupe order-stable, and insert `entities: [a, b]` as an inline list **immediately after the `projects` node** in the frontmatter block (locate the `projects:` node with the same line-walking as `markdown._node_end`, or a regex over the block: `(?ms)^projects:.*?(?=^\S|\Z)`; insert the new line after it; rebuild the note text). A meeting whose `projects` is empty or missing gets no write and joins `needs_human` as `"<relpath>: empty projects[] — entities cannot be derived; needs a human read (or is legitimately entity-less)"`. Notes already carrying `entities` are skipped (idempotency).
8. `_step_dossiers`: for each `40-entities/*/dossier.md`, skip if the body already contains a ` ```dataview` fence (idempotency). Otherwise:
   - Ensure the body starts with `# {entity-name}` (from frontmatter `entity-name`); insert as the first body line if absent.
   - `## Context` section: wrap the existing bullets in `> [!info]+ **Standing context**` — the callout line, then every existing non-empty line of the section gains a `> ` prefix. Match on the label **after stripping** any existing `> ` prefix, so a half-converted section still converts cleanly.
   - `## Sensitivities` section: same, with `> [!warning]+ **Handle with care**`.
   - `## Meeting Log` section: collect every `### {date} — {Topic}` block's `**Dynamics:**` line (if present) as `- **{date} — {Topic}:** {dynamics text}`, newest first (sort by the date prefix, descending). Replace the whole section body with:

     ````markdown
     ```dataview
     TABLE WITHOUT ID file.link AS Meeting, date AS Date
     FROM "20-meetings"
     WHERE contains(entities, this.entity)
     SORT date DESC
     ```

     ### Dynamics

     - **{date} — {Topic}:** {dynamics}
     ````

     **Copy the exact Dataview block from `fixtures/demo-vault/40-entities/*/dossier.md` (or the `entity.py` writer if it emits it) rather than from this plan — the shipped query text is the contract.** The Attendees / Key outcomes / Follow-ups lines are dropped (`LOSSY` declares this).

`verify` additions: every meeting with a non-empty `projects` has `entities`; every dossier contains a ` ```dataview` fence and starts its body with `# `.

- [ ] **Step 1: Failing tests** — old-state fixtures written inline:
  - `test_entities_backfill_derives_and_dedupes`: two meetings — one with `projects: [fleet-renewal, ops-review]` where both projects map to `northwind-logistics` → `entities: [northwind-logistics]`; one with empty `projects: []` → untouched + listed in `needs_human`.
  - `test_entities_backfill_skips_notes_that_have_entities`.
  - `test_dossier_restructure_full_shape`: an old-format dossier (flat `## Context` bullets, `## Sensitivities` bullets, `## Meeting Log` with two dated `###` blocks carrying `**Dynamics:**`, Attendees/Key outcomes lines) → after apply: `# {entity-name}` heading, both callouts, Dataview fence, `### Dynamics` list newest-first, Attendees text gone.
  - `test_dossier_half_converted_section_still_converts` (a `## Context` whose bullets already carry `> `).
  - `test_apply_twice_still_idempotent` (extend the Task 7 test to the new steps).
- [ ] **Step 2: Verify failure.**
- [ ] **Step 3: Implement steps 7–8**, append to the step list, extend `verify`.
- [ ] **Step 4: Run** — migration tests PASS.
- [ ] **Step 5: Template bump + validator + README repoint** per the Files block. Check `make_test_vault.py` and any test asserting structure-version content — update if one pins `1`.
- [ ] **Step 6: Full gate.**
- [ ] **Step 7: Commit** — `feat: migration 001 part B — entities backfill + dossier restructure; template structure-version 2`

---

### Task 9: `health report` — content-free metrics

**Files:**
- Create: `plugin/lib/vaultlib/health.py`
- Modify: `plugin/lib/vaultlib/cli.py`
- Test: Create `scripts/tests/test_vaultlib_health.py`; extend `test_vaultlib_cli.py`

**Interfaces:**
- Consumes: `markdown.split_frontmatter`, `vault` constants, `vault.plugin_version`, `vault.structure_version`, `syncjob`'s skip-list path (`99-workflow-config/sync-state/skipped-recordings.txt` — read-only line count; import the relpath constant from `syncjob` if one exists, else define locally with a comment).
- Produces: `health.report(root, today, window=28) -> dict` (shape below); `health.render(data) -> str` (markdown, numbers only); CLI `health report --vault V [--today D] [--window N] [--write]` — with `--write`, renders to `99-workflow-config/health-reports/{today}.md` and adds `"written": "<relpath>"` to the result.

**Report shape (all values counts/rates/versions — no titles, no names, by construction):**

```python
{
  "generated": "2026-08-25", "window_days": 28,
  "plugin_version": "0.7.0", "structure_version": "2",
  "meetings": {
    "in_window": 9,
    "per_week": [{"week_start": "2026-07-28", "count": 2}, ...],  # ISO weeks, oldest first
    "by_source": {"plaud": 4, "m365": 3, "inbox": 2, "unknown": 0},
    "without_projects": 1,          # read-only stand-in for the update-queue warning count
    "needs_review": 5,
  },
  "daily_notes": {"working_days": 20, "with_machine_regions": 17,
                   "coverage_pct": 85},
  "inbox_pending": 2,                # files in 10-inbox/, README excluded
  "skip_list_size": 3,
  "projects": {"total": 4, "stale_30d": 1},   # no meeting referencing the slug in 30 days
  "entities": {"total": 3, "no_meeting_30d": 1},  # via meetings' entities field
  "decisions": {"needs-review": 2, "confirmed": 5, "superseded": 1},
}
```

Notes for the implementer: meeting dates come from frontmatter `date`; `by_source` from the `source-recording-id` prefix before `:` (`unknown` when the field is absent); windows are `[today - window_days, today]`; working days = Mon–Fri in the window; a daily note "has machine regions" when its text contains `<!-- evening-sync:`; decision statuses come from each note's `review_status`-equivalent field — **read one fixture decision note first and count by the actual status field it carries** (`review_status` on decisions vs. meetings may differ; the fixture is the contract). Unreadable frontmatter anywhere: count the file under an `"unparsed"` key rather than crashing. The spec's "update-queue warning count" is replaced by the read-only `meetings.without_projects` (running `sync update-queue` writes metrics into notes — health must be read-only); this deviation is recorded in the spec's testing section by Task 16's spec-conformance pass.

`render(data)`: fixed template, one `##` per group, `| metric | value |` tables. It interpolates **only** numbers/versions/dates from the dict — never a filename or note field.

- [ ] **Step 1: Failing tests** — seeded tmp vault with: 3 meetings (distinct dates/sources, one without `projects`, one `needs-review`), 2 daily notes (one with an `<!-- evening-sync:recap:begin -->` marker, one without), 2 files + README in `10-inbox/`, a 2-line skip list, 2 projects (one stale), 1 entity, 2 decisions. Assert exact numbers, assert `render` output contains no fixture name (`"northwind" not in rendered.lower()` etc.), assert `--write` creates `99-workflow-config/health-reports/2026-08-25.md`.
- [ ] **Step 2: Verify failure.**
- [ ] **Step 3: Implement** (`HealthError` for bad `--window`; wire the CLI + `except` clause).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Full gate.**
- [ ] **Step 6: Commit** — `feat: health report — content-free metrics, optional vault-local write`

---

### Task 10: `/report-feedback` skill + contract-test amendments for net-new skills

**Files:**
- Create: `plugin/skills/report-feedback/SKILL.md`
- Modify: `scripts/tests/test_skill_contracts.py`
- Test: the contract tests themselves + `scripts/lint_plugin.py`

**Interfaces:**
- Consumes: CLI `feedback lint` / `feedback send` (Task 4), `config read` (Task 1), the disclosure contract (Tasks 4/5).
- Produces: the `NET_NEW` frontmatter convention every later skill task follows: frontmatter carries `origin: net-new` instead of `upstreamed-from`.

- [ ] **Step 1: Amend the contract tests first (they gate every skill that follows).** In `test_skill_contracts.py`:

```python
NET_NEW = {"report-feedback", "health-check", "upgrade-vault", "setup-my-brain"}
```

Rewrite `test_skill_records_provenance`:

```python
@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_skill_records_provenance(path):
    head = path.read_text(encoding="utf-8").split("---")[1]
    if path.parent.name in NET_NEW:
        assert "origin: net-new" in head, (
            f"{path.parent.name}: net-new skills declare origin: net-new")
        assert "upstreamed-from" not in head
    else:
        assert "upstreamed-from: busdev@" in head, (
            f"{path.parent.name}: ported skills record upstreamed-from")
```

Extend `test_expected_skills_exist`'s set with `"report-feedback"` (each later skill task adds its own name — the test's comment already says so).

- [ ] **Step 2: Run** — `python -m pytest scripts/tests/test_skill_contracts.py -q` → FAIL (`report-feedback` missing from disk).

- [ ] **Step 3: Write `plugin/skills/report-feedback/SKILL.md`.** Frontmatter:

```yaml
---
name: report-feedback
description: Report a broken skill, confusing flow, or improvement idea to delaware as a scrubbed, approval-gated GitHub issue. Triggers when the user invokes /report-feedback or accepts the report-it nudge.
user_invocable: true
origin: net-new
---
```

Body structure (write real prose, not this outline verbatim — but cover exactly these, in order):
1. **Surface note:** needs Cowork or Claude Code (plugins do not load in Chat).
2. **Setup:** resolve `$VAULTLIB` (the interpreter-resolution rule from `plugin/CLAUDE.md`: try `python3`, `python`, `py -3`); run `"$VAULTLIB" config read --vault "$VAULT"` — remember whether `feedback.repo` is configured.
3. **Gather:** which skill/flow, expected vs. actual, when it started. Keep questions short; the user may be mid-frustration.
4. **Draft rules:** describe behavior generically — no note text, no names of people/organizations, no meeting titles, no file paths, no emails. Counts are fine ("3 of 9 meetings"). The CLI appends the deployment stamp and disclosure — the draft must not duplicate them.
5. **Show the draft plus this disclosure, verbatim** (copy the `DISCLOSURE` text from Task 4 into the SKILL.md so the model shows it without a CLI call), **then ask for explicit approval.** Never send without a clear yes on the exact final text.
6. **Send:** write the approved body to scratch, run `"$VAULTLIB" feedback send --vault "$VAULT" --title "..." --body-file <scratch>`. On `ok: false` with lint fragments: fix the draft (the fragments name what leaked), re-show, re-approve, retry. Never paraphrase-and-send without re-approval.
7. **Unconfigured channel** (`feedback.repo` null or token missing): tell the user the channel is not set up, save the approved draft to `10-inbox/feedback-draft-{YYYY-MM-DD}.md` for the EA/consultant to relay, and say that is what happened. Never a dead end.
8. **Hard rules block:** never read `99-workflow-config/secrets/`; never send without approval; the lint is a backstop, not permission to draft carelessly.

- [ ] **Step 4: Run the gates** — `python scripts/lint_plugin.py && python -m pytest scripts/tests/test_skill_contracts.py -q` → PASS (frontmatter valid, provenance rule satisfied, CLI references real subcommands, "Cowork"/"Claude Code" present).
- [ ] **Step 5: Full gate.**
- [ ] **Step 6: Commit** — `feat: /report-feedback — scrubbed, approval-gated feedback channel (closes half of #7; nudge rule landed in Task 5)`

---

### Task 11: `/health-check` skill

**Files:**
- Create: `plugin/skills/health-check/SKILL.md`
- Modify: `scripts/tests/test_skill_contracts.py` (add `"health-check"` to the expected set)

**Interfaces:**
- Consumes: CLI `health report` (Task 9), `feedback send` (Task 4), disclosure text.

- [ ] **Step 1:** Add `"health-check"` to `test_expected_skills_exist`; run; FAIL.
- [ ] **Step 2: Write the SKILL.md.** Frontmatter: `name: health-check`, `origin: net-new`, `user_invocable: true`, description mentioning hypercare metrics + trigger. Body covers: surface note (Cowork / Claude Code); run `"$VAULTLIB" health report --vault "$VAULT" --write`; present the numbers conversationally (what looks healthy, what looks stale — judgment on top of deterministic numbers, but **quote only the numbers**, never name a stale project); mention the report file path (`99-workflow-config/health-reports/{date}.md`); then *offer* — never auto-run — sharing with delaware: show the disclosure verbatim, on explicit yes send via `"$VAULTLIB" feedback send --vault "$VAULT" --title "Health report {date}" --body-file <the report file>`; unconfigured channel → same inbox fallback as `/report-feedback`. Note for the EA: run this weekly during hypercare (weeks 2–4), and before each tune-up.
- [ ] **Step 3:** Gates green (lint, contracts, full pytest).
- [ ] **Step 4: Commit** — `feat: /health-check — content-free hypercare metrics (closes #5's skill half)`

---

### Task 12: `/upgrade-vault` skill

**Files:**
- Create: `plugin/skills/upgrade-vault/SKILL.md`
- Modify: `scripts/tests/test_skill_contracts.py` (expected set + `"upgrade-vault"`)

**Interfaces:**
- Consumes: CLI `migrate status` / `migrate run` (Task 6), migration 001 (Tasks 7–8).

- [ ] **Step 1:** Expected-set test first; FAIL.
- [ ] **Step 2: Write the SKILL.md.** Frontmatter as convention (`origin: net-new`). Body, in order:
  1. Audience note: **consultant-run at tune-ups**, after `claude plugin update`. Not for the exec/EA to run alone. Surfaces: Cowork or Claude Code.
  2. Run `"$VAULTLIB" migrate status --vault "$VAULT"`. Nothing pending → say so, show current vs. expected version, done.
  3. Present the plan: each pending migration's number, slug, target version, and — prominently — any `lossy` line. State that a full vault snapshot is taken first (`99-workflow-config/snapshots/`, last 3 kept) and where the log lands (`99-workflow-config/migration-log.md`).
  4. **Explicit confirmation gate** — the consultant says go.
  5. Run `"$VAULTLIB" migrate run --vault "$VAULT"`. On `ok: true`: report per-migration apply/verify reports and **read out `needs_human`** items as the consultant's follow-up list. On `ok: false`: the error names the snapshot; walk the consultant through restore (close Obsidian, unzip the snapshot over the vault root, reopen) — do not attempt automatic restore.
  6. Close: recommend the exec/EA restart Obsidian so refreshed config/ontology load.
- [ ] **Step 3:** Gates green.
- [ ] **Step 4: Commit** — `feat: /upgrade-vault — snapshot, migrate, verify, log (closes #4's skill half)`

---

### Task 13: `/process-upstream` repo command

**Files:**
- Create: `.claude/commands/process-upstream.md`

**Interfaces:**
- Consumes: `gh` CLI, the repo's own conventions (CLAUDE.md, CONTRIBUTING.md). Not a plugin skill — no frontmatter contract tests apply; `lint_plugin.py` does not scan `.claude/`.

- [ ] **Step 1: Write the command file** (mirror `visual-check.md`'s format — check its header shape first and match it). Content, in order:
  1. **Usage:** `/process-upstream <issue-number>`. Delaware-internal; runs where `gh` is authenticated and (for upstream proposals) the busdev checkout exists.
  2. Read the issue: `gh issue view <n> --json title,body,labels,comments`. Accept labels `upstream-proposal` and `field-proposal`; anything else → stop and say why.
  3. For `upstream-proposal`: the body records vault files + a busdev sha. Locate the busdev checkout (the issue body or its comments name the path; default `~/Documents/Dev/Vault/BusDev`). Drift check: `git -C <busdev> rev-parse HEAD` vs. the recorded sha; if different, `git -C <busdev> diff <recorded-sha> HEAD -- <files>` and show it — the human decides to proceed against HEAD or the recorded sha.
  4. **Genericization rewrite** — the clean-room rule verbatim: rewrite, never copy-paste-then-trim; strip client names, people names, busdev paths, personal calibrations; replace with archetype-neutral equivalents; the target skill gets `upstreamed-from: busdev@<sha>` frontmatter.
  5. Branch (`git checkout -b upstream/<issue-number>-<slug>` from `main`), implement following repo conventions: plugin version bump if `plugin/` touched, CHANGELOG judgment call, run the three local checks.
  6. Open the PR: `gh pr create` with `Closes #<n>` and a body that names the recorded sha and any drift decision. Commit trailer rule applies.
- [ ] **Step 2: Verify** — `python -m pytest scripts/tests -q` still green (nothing plugin-side changed); manually confirm the file follows `visual-check.md`'s format.
- [ ] **Step 3: Commit** — `feat: /process-upstream — issue-queue to PR, drift-checked, clean-room rewrite (closes #6's build half)`

---

### Task 14: `/setup-my-brain` skill — the onboarding interview

**Files:**
- Create: `plugin/skills/setup-my-brain/SKILL.md`
- Modify: `scripts/tests/test_skill_contracts.py` (expected set + `"setup-my-brain"`)

**Interfaces:**
- Consumes: `config read`/`write` (Tasks 1–2), `context read`/`write` (Task 3), `config verify-account` (existing), `person ensure` / `entity ensure` / `project scaffold` (existing), `migrate status` (Task 6), the `/evening-sync` skill (existing), M365 connector calendar search + `get_me`, Plaud `get_current_user`.
- Produces: the Session-1 onboarding flow. This is the largest SKILL.md in the plugin; write it as numbered phases with explicit CLI calls — the executor model follows it live in front of a client executive.

- [ ] **Step 1:** Expected-set test first; FAIL.
- [ ] **Step 2: Write the SKILL.md.** Frontmatter:

```yaml
---
name: setup-my-brain
description: The Session-1 onboarding interview — fills the context portfolio, binds connector accounts, seeds entities/projects/people, and ends with the executive's first daily note. Triggers when the user invokes /setup-my-brain.
user_invocable: true
origin: net-new
---
```

Body — cover exactly these, as numbered phases:

**Framing paragraph:** runs live in Cowork (or Claude Code) with the delaware consultant and the executive together, ~2 hours. Precondition: a provisioned template vault — this skill **fills, never scaffolds**. Tone guidance: conversational, one topic at a time, the exec's words over polished summaries.

**Phase 0 — preflight.**
- `"$VAULTLIB" config read --vault "$VAULT"`. `ok: false` (no config.json / not a vault) → stop; point at the provisioning runbook; this folder is not a provisioned vault.
- `"$VAULTLIB" migrate status --vault "$VAULT"` — pending migrations → stop and point at `/upgrade-vault` (never interview into a stale structure).
- All-null config (fresh) → first run. Anything filled → **re-run mode**: every phase below shows current values first and offers to revise; every write below is already idempotent (marker replace, config field sets, `ensure` subcommands).

**Phase 1 — interview, five files in fixed order:** `identity`, `role-and-responsibilities`, `communication-style`, `preferences-and-constraints`, `tools-and-systems`. For each: open the vault file's own "Interview questions" section (read the file; the questions live in the vault so archetypes can tune them), ask conversationally one at a time, then draft the content block, **read it back for approval**, then `"$VAULTLIB" context write --vault "$VAULT" --file <stem> --content <scratch-file>`. After the identity file: `"$VAULTLIB" person ensure --vault "$VAULT" --name "<exec full name>"` → take the returned slug → `"$VAULTLIB" config write --vault "$VAULT" --field executive --value <slug>`; confirm timezone (propose from what they said; IANA name) → `config write --field timezone`.

**Phase 2 — binding ceremony** (one subsection per connector; consultant says which apply):
- The rule, stated in the skill: **never ask anyone to type an email address.** Hints are copied verbatim from the connector's whoami; display names are rejected by the CLI.
- Plaud: call `get_current_user` with the exec signed in; save the raw JSON to scratch; show the human-recognizable nickname and ask "is this your account?"; on yes, take `id` or `email` **verbatim from the payload** → `config write --field adapters.plaud.account_hint --value <verbatim>` → `config write --field adapters.plaud.enabled --value true` → confirm the bind with `"$VAULTLIB" config verify-account --vault "$VAULT" --adapter plaud --identity <scratch-file>` (must return `match: true`) → **delete the scratch file immediately**.
- M365: same ceremony with `get_me`; hint from `mail` or `userPrincipalName`; adapter `m365`.
- Connector unavailable/declined → skip with an explicit line; say what still works.

**Phase 3 — seeding, three steps in order:**
- **3a Entities (conversation only):** explain what an entity is (an organization the exec deals with — client, partner, supplier — the thing a dossier is kept on; their own organization counts, as a `business-unit`). Ask the exec to name theirs. For each confirmed: `"$VAULTLIB" entity ensure --vault "$VAULT" --slug <slug> --name "<Name>" --type <client|business-unit|partner|supplier|other> --status active --owner <exec-slug>`. **Entities are never derived from the calendar.**
- **3b Projects (suggested, prudent):** candidates from interview mentions + recurring calendar subjects (if m365 bound: search the next/last 2 weeks). Frame as "areas of responsibility"; **aim for 3–4**, reassure that `/new-project` adds more later, the moment one is missed. For each confirmed: `"$VAULTLIB" project scaffold --vault "$VAULT" --name "<Name>" --type <initiative|area-of-responsibility> --entity <slug> --owner <exec-slug>` (internal areas link to the exec's own organization entity from 3a).
- **3c People (calendar + interview):** if m365 bound, pull attendees from the ±2-week calendar window; merge with interview-mentioned names into **one confirm/reject list**; walk it with the exec; for each confirmed: `"$VAULTLIB" person ensure --vault "$VAULT" --name "<Name>"`. Meeting-rhythm observations feed back into the role/preferences blocks if the exec agrees (re-run `context write`).

**Phase 4 — the first daily note (the close).** Invoke the `/evening-sync` skill now, in this session. It reads config (timezone, executive, m365 binding) and writes tomorrow's daily note with a prep section per real calendar meeting, referencing what was just seeded. Open `60-daily-notes/{tomorrow}.md` on screen and walk through it. This note is what arrives every evening from now on.

**Phase 5 — sweep.** Delete every scratch file this session wrote (whoami payloads, calendar JSON, draft blocks). State the hygiene rule in the skill: raw connector JSON is engagement data; nothing persists except what the exec confirmed into the vault.

**Degradation table** (include it as a table): no m365 → 3b from interview only, 3c from interview only, Phase 4 daily note carries the no-meetings line; no Plaud → skip its bind, `/sync-recordings` inbox adapter still works; no connectors at all → interview + manual seeding still produce a valid vault, say what the EA sets up later.

- [ ] **Step 3:** Gates green (contract tests: CLI subcommand references must all exist — `config read`, `config write`, `context write`, `person ensure`, `entity ensure`, `project scaffold`, `config verify-account`, `migrate status` all do by now).
- [ ] **Step 4: Commit** — `feat: /setup-my-brain — Session-1 onboarding interview (closes #3's build half)`

---

### Task 15: Runbook, version bump, CHANGELOG

**Files:**
- Modify: `playbooks/provisioning-runbook.md`
- Modify: `plugin/.claude-plugin/plugin.json` (`0.6.3` → `0.7.0`)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Runbook additions** (read the file first; add where its structure puts them):
  - Feedback channel step: create `sb-client-<slug>`; mint the token **fine-grained, `issues: read+write` on that repo only, no `contents` scope** (the leak blast-radius rule); place it at `99-workflow-config/secrets/feedback-token` (one line) in the instantiated vault; set the repo: `"$VAULTLIB" config write --vault <vault> --field feedback.repo --value <owner>/sb-client-<slug>`; note the rotation point (any tune-up).
  - Obsidian Sync exclusions step (extend wherever `95-private` exclusion is documented; if it is not yet written down, add both): exclude `95-private/` and `99-workflow-config/snapshots/` — account/device-level Obsidian Sync settings, configured on each machine at provisioning; not shippable files.
  - Data-flow one-pager note: the exec's connector identifier (email/id) is stored in the vault's own `config.json` as the binding hint.
- [ ] **Step 2: Version bump** to `0.7.0`.
- [ ] **Step 3: CHANGELOG** — four lines under `Unreleased`, written for the consultant/exec voice the file's header demands, each ending with the PR number placeholder to fill at PR time (match existing entries' style):
  - `/setup-my-brain`: the Session-1 interview now exists — fills your context, binds your accounts with an on-screen yes, seeds your first entities/projects/people, and ends with tomorrow's note on screen.
  - `/upgrade-vault`: tune-up structure upgrades now snapshot first, verify after, and log what ran; anything lossy is announced before it happens.
  - `/health-check`: a numbers-only health report the EA can run and — only with explicit approval — share with delaware.
  - `/report-feedback`: report a broken or clumsy flow to delaware; a deterministic check guarantees the report carries no names or content, and nothing sends without your approval of the exact text.
  (#6 `/process-upstream` stays out — internal.)
- [ ] **Step 4: Full gate** (version-guard equivalence is CI-side; locally just the three commands).
- [ ] **Step 5: Commit** — `chore: runbook feedback/sync-exclusion steps, plugin 0.7.0, changelog for #3–#5, #7`

---

### Task 16: Final verification + PR

- [ ] **Step 1: Spec-conformance pass.** Re-read `docs/superpowers/specs/2026-08-25-net-new-skills-design.md` top to bottom against the diff (`git diff main --stat`). Every spec section maps to landed code/tests/docs. Record the one known deviation in the spec's Testing section if not already there: health's "update-queue warning count" became the read-only `meetings.without_projects` (reason: `sync update-queue` writes metrics into notes; health is read-only).
- [ ] **Step 2: Full local gate, fresh:**

```bash
python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q
```

Expected: all green, zero warnings about unknown markers.
- [ ] **Step 3: Visual-tier check-the-need:** `git diff main --name-only` — confirm no path under `template/.obsidian/`, no `*.base`/`*.canvas`, no `fixtures/demo-vault/`, no `ontology.md`, no `markdown.py`. If any slipped in, run `/visual-check` and report evidence before proceeding.
- [ ] **Step 4: Exercise once against a real test vault** (dated vault under the main checkout's `test-vaults/`, per `docs/local-setup.md` — create with `make_test_vault.py --with-plugins`): run `migrate status` (expect none pending on a fresh v2 vault), `health report --write`, `feedback lint` on a clean and a dirty draft, `context write` + `config write` round-trip. Paste the outputs into the PR body's testing section.
- [ ] **Step 5: Push + PR.**

```bash
git push -u origin claude/git-issue-3-superpowers-d43d1b
gh pr create --title "Net-new skills: /setup-my-brain, /upgrade-vault, /health-check, /process-upstream, /report-feedback" --body "$(cat <<'EOF'
Implements docs/superpowers/specs/2026-08-25-net-new-skills-design.md — the five
net-new v0.1 skills plus the vaultlib groups they stand on (config write,
context write, migrate + migration 001, health report, feedback lint/send).

Closes #3, closes #4, closes #5, closes #6, closes #7

## Testing
(paste Task 16 step 4 outputs + full gate results here)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Watch the three checks**, fix anything red, report the PR URL and CI status.

---

## Self-review notes (already applied)

- Spec coverage: every spec section has a task — cross-cutting (1–6, 9), privacy controls (4, 5, 10, 11), /setup-my-brain (14), /upgrade-vault + migration 001 (6–8, 12), /health-check (9, 11), /process-upstream (13), /report-feedback (4, 10), testing (in every task), rollout (15–16).
- Known deviation recorded: health's update-queue warning count → `meetings.without_projects` (Task 9 + Task 16 step 1).
- Type consistency: `config.write(root, field, value)` typed values (bool for `.enabled`); `feedback.send(root, title, body, post=None)`; `migrate.run(root, today, stamp=None)`; `vault.write_context_block(root, stem, content)` — SKILL.md tasks reference only these and existing subcommands.
- Dossier Dataview block: Task 8 deliberately pins to the fixture/writer text, not to prose in this plan — the shipped query is the contract.
