# Message feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every evening, read the owner's Outlook mail and Teams chats, condense them into one hidden digest per day in `_messages/`, and let that context flow into project state, decisions, person counters and a short *Mail and Teams* block in the daily note.

**Architecture:** A worker agent fetches connector pages into scratch and condenses; deterministic `vaultlib` modules filter, group, route, check, render and keep state; `/sync-messages` orchestrates and runs as stage 3b of `/evening-sync`. Downstream consumers (update queue, stage 4, recap, health) read digests through one module.

**Tech Stack:** Python 3.11 stdlib (`plugin/lib/vaultlib/`), pytest, Markdown skills and agent definitions under `plugin/`, Obsidian template files.

**Spec:** `docs/superpowers/specs/2026-09-30-message-feed-design.md` (decisions §2, clarifications §13). Read it before any task.

## Global Constraints

- Cowork first: everything runs unattended from the one scheduled `/evening-sync`; nothing needs a person at the keyboard (spec §1).
- The model reads; code routes and writes. Every vault write goes through `"$VAULTLIB"` (`plugin/lib/vaultlib/cli.py`); skills never write frontmatter by hand.
- Nothing invented: every condensed point and every morning line passes the token check against the messages it cites; a failing one is dropped, never rewritten (spec §5.3 step 5).
- Not read: Teams channels, full mails, attachments. At most 5 full-message reads per night. Mail is always folder-scoped; the Teams feed never gets a date filter (spec decision 5, §5.3).
- Fixed safety limit: Teams feed 20 pages, mail 8 pages per folder, 5 full reads, at most 40 groups condensed per day (spec §9, §13 C5). Constants, never computed at run time.
- Exclusions are applied before anything is condensed or stored (spec §6.1).
- Digests: `_messages/YYYY-MM-DD-messages.md`, `type: digest`, hidden in the file list and search (spec §8.1, §13 C1).
- Clean room: tests use made-up fixtures only (`acme.example`, `jordan.reyes@acme.example`); never real mail.
- Off by default; the template ships `messages.enabled: false`.
- Each PR touching `plugin/` bumps `plugin/.claude-plugin/plugin.json`; client-visible PRs add a `CHANGELOG.md` line under `Unreleased` ending with the PR number.
- CI: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`. `test_vaultlib_updatequeue.py` has a known intermittent Windows `PermissionError`; if it alone fails, re-run that file.
- UI-impacting files (`ontology.md`, `.obsidian/**`, template `CLAUDE.md`) require `/visual-check` before the PR (root `CLAUDE.md`).

## Review Focus

1. **Graph timestamps in every shape** (`...Z`, 7-digit fractions, no zone): parsed through `m365._parse_graph_dt`, never by hand. Pinned in Task A4.
2. **A subject that normalises to nothing** (`RE: FW:`, empty): grouped as `(no subject)` per sender, never all into one group. Pinned in Task A4.
3. **The owner's own addresses** (primary, UPN, alias): never a participant, never a new person note, never routed as a stranger. Pinned in Tasks A4 and A6.
4. **A digest the owner edited by hand** (data block removed or broken): `messages write` refuses that one digest with a clear error and leaves it untouched; other dates still write. Pinned in Task A8.
5. **Two runs on one night** (manual plus scheduled): message ids never duplicate, the cursor never moves backwards. Pinned in Tasks A7 and A8.

## Packaging

Four plugin PRs, merged serially (each collides on `plugin.json` / `CHANGELOG.md`; rebase each onto the previous squash, never stack):

| PR | Branch | Tasks | plugin.json |
|---|---|---|---|
| A | `feat/messages-core` | A1–A11 | main+1 |
| B | `feat/messages-structure-v4` | B1–B2 | main+2 |
| C | `feat/sync-messages-skill` | C1–C4 | main+3 |
| D | `feat/messages-downstream` | D1–D4 | main+4 |

Then release to dryrun and run the Cowork verification (Task E1). The feature stays off until an owner switches it on, so PRs A–C ship no visible change on their own.

Each PR: tests first, then code, then the three CI commands, then `/code-review`. Implementation teammates: `model: sonnet`.

## File structure

| File | Responsibility |
|---|---|
| `plugin/lib/vaultlib/msgrows.py` (new) | page files in; noise, exclusions, grouping per local day, priority trimming out |
| `plugin/lib/vaultlib/msgroute.py` (new) | people (address book, email enrichment, creation rule) and project routing (entity domains, names, keywords, stakeholders; strong/weak) |
| `plugin/lib/vaultlib/msgstate.py` (new) | cursor, open gaps (7-day horizon), requeue list, keyword proposals shown |
| `plugin/lib/vaultlib/msgdigest.py` (new) | token check, digest data and render, merge, forget, unlink, per-project view, keyword proposals, status lines |
| `plugin/lib/vaultlib/discover.py` | gains public `unsupported_tokens` |
| `plugin/lib/vaultlib/config.py` | `messages` block: validation, defaults, writable fields, exclusions |
| `plugin/lib/vaultlib/person.py` | `ensure(..., email=None)`, `set_email_if_missing`, `address_book` |
| `plugin/lib/vaultlib/project.py` | `keywords_add` / `keywords_remove` / `keywords_list` |
| `plugin/lib/vaultlib/links.py`, `vault.py` | `digest` kind, `MESSAGES_DIR` |
| `plugin/lib/vaultlib/decision.py` | `source` may name a digest |
| `plugin/lib/vaultlib/cli.py` | `messages` group, `project keywords`, new config fields |
| ontology, `schema.json` | Digest object; Person counters; Project `keywords` |
| template + `plugin/migrations/003-structure-version-4/` | `_messages/`, hide settings, structure 4 |
| `plugin/skills/sync-messages/` (new), `plugin/agents/sync-messages-worker.md` (new) | orchestration and the worker contract |
| `evening-sync`, `setup-my-brain`, `health-check` SKILL.md | stage 3b/4/6, switch-on, the health number |
| `updatequeue.py`, `recap.py`, `dailynote.py`, `health.py` | downstream consumers |

---

## PR A — `feat/messages-core`

### Task A1: Public token check in `discover`

**Files:**
- Modify: `plugin/lib/vaultlib/discover.py` (after `_check_claim`, ~line 785)
- Test: `scripts/tests/test_vaultlib_discover.py`

**Interfaces:**
- Produces: `discover.unsupported_tokens(text: str, sources: List[str]) -> List[str]` — the checkable tokens of `text` (emails, domains, quoted strings, numbers, proper-noun runs) that occur in none of `sources`, in order.

- [ ] **Step 1: Write the failing tests**

```python
def test_unsupported_tokens_passes_what_the_sources_hold():
    sources = ['Jordan Reyes: can we move workshop 2 to 14 Oct?', 'ok for me']
    assert discover.unsupported_tokens("Jordan Reyes asks to move workshop 2 to 14 Oct.", sources) == []


def test_unsupported_tokens_names_an_invented_name_and_number():
    sources = ["Jordan Reyes: can we move workshop 2?"]
    missing = discover.unsupported_tokens("Jordan Reyes and Priya Nathan moved workshop 3.", sources)
    assert "Priya Nathan" in missing
    assert "3" in missing
    assert "Jordan Reyes" not in missing


def test_unsupported_tokens_with_no_sources_flags_every_token():
    assert discover.unsupported_tokens("Mail from jordan@acme.example", []) == ["jordan@acme.example"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -k unsupported_tokens -q`
Expected: FAIL with `AttributeError: module 'vaultlib.discover' has no attribute 'unsupported_tokens'`

- [ ] **Step 3: Implement**

```python
def unsupported_tokens(text: str, sources: List[str]) -> List[str]:
    """The checkable tokens of `text` that none of `sources` holds.

    The same rule as a claim's check, for callers whose sources are plain
    strings rather than evidence entries (the message feed's condensed
    points and morning lines). Empty means every token is supported.
    """
    haystack = _norm(" \x00 ".join(str(source) for source in sources))
    return [token for token in _tokens(text) if not _present(token, haystack)]
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m pytest scripts/tests/test_vaultlib_discover.py -q`
Expected: PASS (all discover tests)

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/discover.py scripts/tests/test_vaultlib_discover.py
git commit -m "feat(discover): public unsupported_tokens for plain-string sources (#236)"
```

### Task A2: Ontology, schema, links and decision source for digests

**Files:**
- Modify: `plugin/template/99-workflow-config/reference/ontology.md` (new `### Digest` block after `### Daily note`, Person and Project blocks, Decision `source` prose, relationship graph, line 11 "Six object types")
- Regenerate: `plugin/lib/vaultlib/schema.json` via `python scripts/compile_ontology.py`
- Modify: `plugin/lib/vaultlib/vault.py:27-34`, `plugin/lib/vaultlib/links.py:27-83`, `plugin/lib/vaultlib/decision.py:230-248`
- Test: `scripts/tests/test_vaultlib_links.py`, `scripts/tests/test_vaultlib_decision.py`, `scripts/tests/test_compile_ontology.py` (existing, must stay green)

**Interfaces:**
- Produces: `vault.MESSAGES_DIR = "_messages"`; `links._classify` returns `("digest", None)` for `_messages/<stem>.md`; `links.resolve(root, "<YYYY-MM-DD>-messages")` resolves a digest; `schema.validate("digest", fm)`; `decision._resolve_source` accepts a digest stem.

- [ ] **Step 1: Write the failing tests**

In `scripts/tests/test_vaultlib_links.py`:

```python
def test_a_digest_resolves_by_stem_and_by_path(tmp_path):
    root = make_vault(tmp_path)
    folder = root / "_messages"
    folder.mkdir()
    (folder / "2026-09-30-messages.md").write_text("---\ntype: digest\n---\n", encoding="utf-8")
    kind, path, key = links.resolve(root, "2026-09-30-messages")
    assert kind == "digest" and path.name == "2026-09-30-messages.md" and key is None
    kind, _, _ = links.resolve(root, "_messages/2026-09-30-messages")
    assert kind == "digest"


def test_a_daily_note_and_a_digest_never_share_a_stem(tmp_path):
    root = make_vault(tmp_path)
    (root / "60-daily-notes" / "2026-09-30.md").write_text("---\n---\n", encoding="utf-8")
    (root / "_messages").mkdir()
    (root / "_messages" / "2026-09-30-messages.md").write_text("---\ntype: digest\n---\n", encoding="utf-8")
    assert links.resolve(root, "2026-09-30")[0] == "daily note"
    assert links.resolve(root, "2026-09-30-messages")[0] == "digest"
```

In `scripts/tests/test_vaultlib_decision.py` (reuse the file's existing project fixture helper; if it is named differently, use the one that creates `30-projects/<slug>/index.md`):

```python
def test_source_may_name_a_digest(tmp_path):
    root = vault_with_project(tmp_path, "acme-industries-operating-model")
    (root / "_messages").mkdir()
    (root / "_messages" / "2026-09-30-messages.md").write_text("---\ntype: digest\n---\n", encoding="utf-8")
    assert decision._resolve_source(root, "[[2026-09-30-messages]]") == "2026-09-30-messages"
```

In `scripts/tests/test_vaultlib_schema.py` (create if absent):

```python
from vaultlib import schema

def test_digest_schema_requires_its_core_fields():
    errors = schema.validate("digest", {"type": "digest", "date": "2026-09-30"})
    assert any("updated-at" in e for e in errors)
    assert schema.validate("digest", {
        "type": "digest", "date": "2026-09-30", "updated-at": "2026-09-30T18:52",
        "projects": [], "people": [], "messages-read": 0}) == []

def test_person_and_project_carry_the_new_optional_fields():
    assert "messages-7d" in schema.for_object("person")["optional"]
    assert "keywords" in schema.for_object("project")["optional"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_links.py scripts/tests/test_vaultlib_decision.py scripts/tests/test_vaultlib_schema.py -q`
Expected: FAIL (`digest` unknown; `KeyError` in `schema.for_object("digest")`)

- [ ] **Step 3: Implement**

`vault.py`, next to the other folder constants:

```python
MESSAGES_DIR = "_messages"
```

`links.py` `_classify`, before `return None, None`:

```python
    if parts[0] == vault.MESSAGES_DIR and len(parts) == 2:
        return "digest", None
```

`links.py` `resolve`, append to `candidates` after the daily-note row:

```python
        ("digest", root / vault.MESSAGES_DIR / f"{target}.md", None),
```

`decision.py` `_resolve_source`, replace the lookup:

```python
    stem = canonical_stem(raw, field="source")
    found = _find_note(root / MEETINGS_DIR, stem)
    if found is None:
        found = _find_note(root / vault.MESSAGES_DIR, stem)
    if found is None:
        raise DecisionError(
            f"source {stem!r} matches no meeting note at {MEETINGS_DIR}/{stem}.md "
            f"and no digest at {vault.MESSAGES_DIR}/{stem}.md — omit 'source' and "
            "put the provenance in the 'why' text"
        )
    return found.stem
```

(Import `vault` in `decision.py` if it is not imported yet.)

`ontology.md`:
- Line 11: `Seven object types: **Meeting · Project · Person · Decision · Entity · Daily note · Digest**.`
- Project yaml `optional:` gains `keywords`; prose bullet: "`keywords` — optional list of strings (project codes, nicknames, client terms) the message feed routes on; added by `project keywords add`, never by hand."
- Person yaml `optional:` gains `messages-7d, messages-30d`; prose: "auto-maintained by `sync update-queue` from digests, next to the meeting counters."
- Decision `source` bullet: "`source` names a note in `20-meetings/` or a digest in `_messages/`."
- New block after Daily note:

````markdown
### Digest — `_messages/{YYYY-MM-DD}-messages.md` · no Base

```yaml
object: digest
required: [type, date, updated-at, projects, people, messages-read]
optional: [projects-weak, entities, window-from, window-to, skipped,
           at-limit, gaps]
enums:
  type: [digest]
```

- One per calendar day of mail and Teams chat, written only by
  `messages write`. Machine material: hidden from the file list and search;
  sessions and the evening run read it, the owner meets it only through a
  "from mail" link.
- `projects[]` holds every linked project; `projects-weak[]` the subset that
  never queues a project-state update. `people[]` and `entities[]` follow the
  Meeting pattern.
- The body is rendered from the `%% digest-data … %%` block at its end; never
  edit either by hand.
- **Update-queue exception:** a digest counts as project activity without a
  review tick (strong links only), unlike meetings.
````

- Relationship graph gains: `Digest —projects[]→ Project`, `Digest —people[]→ Person`, `Decision —source→ Digest`.

Then: `python scripts/compile_ontology.py` (regenerates `schema.json`).

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_links.py scripts/tests/test_vaultlib_decision.py scripts/tests/test_vaultlib_schema.py scripts/tests/test_compile_ontology.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/template/99-workflow-config/reference/ontology.md plugin/lib/vaultlib/schema.json plugin/lib/vaultlib/vault.py plugin/lib/vaultlib/links.py plugin/lib/vaultlib/decision.py scripts/tests/
git commit -m "feat(ontology): Digest object, person message counters, project keywords (#236)"
```

### Task A3: `messages` config block and exclusions

**Files:**
- Modify: `plugin/lib/vaultlib/config.py:24-45` (keys, writable fields), `_validate` (~:113-200), add exclusion functions
- Modify: `plugin/template/99-workflow-config/config.json`, `scripts/validate_template.py:85-125`
- Modify: `plugin/lib/vaultlib/cli.py:817-830` (coerce `messages.scope` as a list; `messages.consented-at` as a string)
- Test: `scripts/tests/test_vaultlib_config.py`, `scripts/tests/test_validate_template.py` (existing file for the validator; if named differently, the one that calls `check_config`)

**Interfaces:**
- Produces: `config.MESSAGES_DEFAULT`; `config.messages_settings(root) -> dict` (never raises: `{"enabled": False, ...}` on any config problem, plus `"warning"`); `config.exclusion_add(root, *, kind, value, label, today) -> dict` (returns the new entry with `id`); `config.exclusion_remove(root, exclusion_id) -> dict`; `config.EXCLUSION_KINDS = ("person", "domain", "chat", "word")`. Writable: `messages.enabled`, `messages.consented-at`, `messages.scope`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_deployed_config_without_messages_reads_as_off(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    assert config.read(root)["config"]["messages"] == {
        "enabled": False, "consented-at": None, "scope": [], "exclusions": []}


def test_switching_on_records_consent_and_scope(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    config.write(root, "messages.enabled", True)
    config.write(root, "messages.consented-at", "2026-09-30T20:14")
    config.write(root, "messages.scope", ["teams-chats", "inbox", "sent-items"])
    settings = config.messages_settings(root)
    assert settings["enabled"] is True and settings["scope"] == ["teams-chats", "inbox", "sent-items"]


def test_an_unknown_scope_is_refused(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    with pytest.raises(config.ConfigError, match="scope"):
        config.write(root, "messages.scope", ["teams-channels"])


def test_exclusions_get_stable_ids_and_can_be_removed(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    first = config.exclusion_add(root, kind="person", value="Jordan.Reyes@acme.example",
                                 label="Jordan Reyes", today="2026-09-30")
    second = config.exclusion_add(root, kind="word", value="Salaris", label=None, today="2026-09-30")
    assert (first["id"], first["value"]) == ("x1", "jordan.reyes@acme.example")
    assert (second["id"], second["value"]) == ("x2", "salaris")
    config.exclusion_remove(root, "x1")
    assert [e["id"] for e in config.messages_settings(root)["exclusions"]] == ["x2"]


def test_an_exclusion_kind_outside_the_four_is_refused(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config())
    with pytest.raises(config.ConfigError, match="kind"):
        config.exclusion_add(root, kind="channel", value="x", label=None, today="2026-09-30")


def test_messages_settings_never_raises_on_a_broken_config(tmp_path):
    root = make_vault(tmp_path)
    (root / "99-workflow-config" / "config.json").write_text("{", encoding="utf-8")
    settings = config.messages_settings(root)
    assert settings["enabled"] is False and settings["warning"]
```

Validator test:

```python
def test_template_must_ship_messages_off():
    problems = validate_template.check_config(TEMPLATE_WITH(messages={"enabled": True, "consented-at": None, "scope": [], "exclusions": []}))
    assert any("messages" in p for p in problems)
```

(`TEMPLATE_WITH` is the file's existing helper for a template with one config field overridden; if none exists, write the template config to `tmp_path` with the override and pass that path.)

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_config.py -k "messages or exclusion" -q`
Expected: FAIL (`KeyError: 'messages'`)

- [ ] **Step 3: Implement**

In `config.py`:

```python
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
```

In `_validate`, next to the other `setdefault`s and checks:

```python
    cfg.setdefault("messages", json.loads(json.dumps(MESSAGES_DEFAULT)))
    ...
    _validate_messages(cfg["messages"])
```

New functions:

```python
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
```

`config.write`: `messages.scope` is a list field; it is casefolded like `home_domains`, and the scopes are already lowercase.

Template `config.json`: add after `"sync"`:

```json
  "messages": {"enabled": false, "consented-at": null, "scope": [], "exclusions": []}
```

and two `_readme` lines: `"messages: the nightly mail and Teams feed (/sync-messages). Off until the owner consents; consented-at, scope and exclusions are written by the CLI only."`

`validate_template.check_config`, before `return problems`:

```python
    if cfg.get("messages") != {"enabled": False, "consented-at": None,
                               "scope": [], "exclusions": []}:
        problems.append(
            "template config.json must ship messages off, with no consent, "
            "no scope and no exclusions")
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_config.py scripts/tests/test_validate_template.py -q && python scripts/validate_template.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/config.py plugin/lib/vaultlib/cli.py plugin/template/99-workflow-config/config.json scripts/validate_template.py scripts/tests/
git commit -m "feat(config): messages block with consent, scope and exclusions (#236)"
```

### Task A4: `msgrows` — page files, noise, exclusions, grouping

**Files:**
- Create: `plugin/lib/vaultlib/msgrows.py`
- Test: `scripts/tests/test_vaultlib_msgrows.py`

**Interfaces:**
- Consumes: `m365.load_listing`, `m365._parse_graph_dt`, `dates.utc_to_local`, `discover._subject` (subject normalisation; reuse, do not copy).
- Produces:
  - `MessagesError(Exception)`
  - `PAGE_RE`, `PAGE_CAPS = {"teams": 20, "inbox": 8, "sent": 8}`, `FULL_READS = 5`, `MAX_GROUPS_PER_DAY = 40`, `GROUPS_FILE = "msg_groups.payload.json"`
  - `load(scratch_dir: str) -> Dict[str, dict]` — `{source: {"rows": [...], "capped": bool, "pages": [names], "gap_pages": {gap_id: {"rows", "capped"}}}}` for sources `teams`, `chats`, `inbox`, `sent`
  - `noise_reason(source: str, row: dict) -> Optional[str]`
  - `is_excluded(source: str, row: dict, chat: Optional[dict], exclusions: List[dict]) -> bool`
  - `group(loaded: Dict[str, dict], *, exclusions, owner_addresses: Set[str], timezone, utc_offset) -> Tuple[List[dict], Dict[str, int]]` — groups and counts `{"read", "noise", "excluded"}`
  - Group dict: `{"gid", "key", "date", "kind": "chat"|"mail", "chat_type", "label", "participants": [emails], "names": {email: name}, "messages": [{"id", "at", "from", "text"}], "owner_wrote": bool, "direct": bool, "sources": [..]}`
  - `priority(group: dict) -> int` (0 highest) and `trim(groups, limit=MAX_GROUPS_PER_DAY) -> Tuple[List[dict], Dict[str, int]]` (kept groups, skipped per date)

- [ ] **Step 1: Write the failing tests**

```python
"""Message feed rows. Made-up fixtures only (clean room)."""
import json
import pytest
from vaultlib import msgrows

OWNER = {"morgan.ellery@northwind.example"}


def page(scratch, name, rows, more=False):
    lines = [json.dumps(r) for r in rows] + ([json.dumps({"moreResults": True})] if more else [])
    (scratch / name).write_text("\n".join(lines), encoding="utf-8")


def teams(mid, chat, who, text, at="2026-09-30T08:15:00.0000000Z", **extra):
    return {"id": mid, "chatId": chat, "createdDateTime": at,
            "from": {"displayName": who.split("@")[0].replace(".", " ").title(), "email": who},
            "summary": text, **extra}


def chat(cid, kind, topic, *members):
    return {"id": cid, "chatType": kind, "topic": topic,
            "members": [{"displayName": m.split("@")[0].replace(".", " ").title(), "email": m}
                        for m in members]}


def mail(mid, subject, sender, recipients, at="2026-09-30T09:00:00Z", summary="text"):
    return {"id": mid, "subject": subject, "sender": sender, "recipients": recipients,
            "receivedDateTime": at, "summary": summary}


@pytest.fixture
def scratch(tmp_path):
    d = tmp_path / "scratch"
    d.mkdir()
    return d


def test_pages_are_read_in_numeric_order_and_capped_is_seen(scratch):
    page(scratch, "msg_inbox.p2.payload.json", [mail("m2", "B", "a@acme.example", [])], more=True)
    page(scratch, "msg_inbox.p10.payload.json", [mail("m3", "C", "a@acme.example", [])])
    page(scratch, "msg_inbox.p1.payload.json", [mail("m1", "A", "a@acme.example", [])])
    loaded = msgrows.load(str(scratch))
    assert [r["id"] for r in loaded["inbox"]["rows"]] == ["m1", "m2", "m3"]
    assert loaded["inbox"]["capped"] is False  # only the last page decides
    assert loaded["teams"]["rows"] == []


def test_gap_pages_are_kept_apart(scratch):
    page(scratch, "msg_inbox.gap3.p1.payload.json", [mail("g1", "Old", "a@acme.example", [])], more=True)
    loaded = msgrows.load(str(scratch))
    assert loaded["inbox"]["gap_pages"]["3"]["capped"] is True
    assert loaded["inbox"]["rows"] == []


@pytest.mark.parametrize("source,row,reason", [
    ("teams", teams("t1", "c1", "a@acme.example", "x", channelUri="teams://x"), "channel"),
    ("teams", teams("t2", "c1", "bot@teams.microsoft.com", "x"), "bot"),
    ("teams", teams("t3", "c1", "a@acme.example", "  "), "empty"),
    ("inbox", mail("m1", "Accepted: Weekly", "a@acme.example", []), "meeting-response"),
    ("inbox", mail("m2", "Automatic reply: away", "a@acme.example", []), "meeting-response"),
    ("inbox", mail("m3", "PR #12", "notifications@github.com", []), "notification"),
    ("inbox", mail("m4", "Factuur september", "billing@telco.example", []), "billing"),
    ("inbox", mail("m5", "Workshop 2 agenda", "jordan.reyes@acme.example", []), None),
])
def test_noise_rules(source, row, reason):
    assert msgrows.noise_reason(source, row) == reason


def test_person_exclusion_drops_mail_and_the_one_on_one_but_only_their_lines_in_groups():
    ex = [{"id": "x1", "kind": "person", "value": "jordan.reyes@acme.example", "label": None, "added": "2026-09-30"}]
    one = chat("c1", "oneOnOne", None, "jordan.reyes@acme.example", "morgan.ellery@northwind.example")
    grp = chat("c2", "group", "Rollout", "jordan.reyes@acme.example", "sam.lee@acme.example")
    assert msgrows.is_excluded("inbox", mail("m", "Hi", "jordan.reyes@acme.example", []), None, ex)
    assert msgrows.is_excluded("sent", mail("m", "Hi", "morgan.ellery@northwind.example", ["jordan.reyes@acme.example"]), None, ex)
    assert msgrows.is_excluded("teams", teams("t", "c1", "morgan.ellery@northwind.example", "x"), one, ex)
    assert msgrows.is_excluded("teams", teams("t", "c2", "jordan.reyes@acme.example", "x"), grp, ex)
    assert not msgrows.is_excluded("teams", teams("t", "c2", "sam.lee@acme.example", "x"), grp, ex)


def test_domain_chat_and_word_exclusions():
    ex = [{"id": "x1", "kind": "domain", "value": "hr.example", "label": None, "added": "d"},
          {"id": "x2", "kind": "chat", "value": "c9", "label": "Sollicitaties", "added": "d"},
          {"id": "x3", "kind": "word", "value": "salaris", "label": None, "added": "d"}]
    assert msgrows.is_excluded("inbox", mail("m", "Hi", "a@hr.example", []), None, ex)
    assert msgrows.is_excluded("teams", teams("t", "c9", "a@acme.example", "x"), chat("c9", "group", "x", "a@acme.example"), ex)
    assert msgrows.is_excluded("inbox", mail("m", "Salaris 2027", "a@acme.example", []), None, ex)
    assert msgrows.is_excluded("teams", teams("t", "c3", "a@acme.example", "x"), chat("c3", "group", "Salaris overleg", "a@acme.example"), ex)
    assert not msgrows.is_excluded("inbox", mail("m", "Salarisadministratie", "a@acme.example", []), None, ex)  # word boundary


def test_grouping_per_local_day_threads_inbox_and_sent_and_drops_the_owner(scratch):
    page(scratch, "msg_chats.p1.payload.json", [chat("c1", "oneOnOne", None, "sam.lee@acme.example", "morgan.ellery@northwind.example")])
    page(scratch, "msg_teams.p1.payload.json", [
        teams("t1", "c1", "sam.lee@acme.example", "late one", at="2026-09-30T22:30:00Z"),  # 00:30 local on 1 Oct
        teams("t2", "c1", "morgan.ellery@northwind.example", "morning", at="2026-09-30T07:00:00.1234567Z")])
    page(scratch, "msg_inbox.p1.payload.json", [mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", ["morgan.ellery@northwind.example"])])
    page(scratch, "msg_sent.p1.payload.json", [mail("m2", "RE: Workshop 2 agenda", "morgan.ellery@northwind.example", ["jordan.reyes@acme.example"])])
    groups, counts = msgrows.group(msgrows.load(str(scratch)), exclusions=[], owner_addresses=OWNER,
                                   timezone="Europe/Brussels", utc_offset=None)
    by_key = {(g["key"], g["date"]): g for g in groups}
    assert ("chat:c1", "2026-09-30") in by_key and ("chat:c1", "2026-10-01") in by_key
    thread = by_key[("mail:workshop 2 agenda", "2026-09-30")]
    assert sorted(thread["sources"]) == ["inbox", "sent"] and thread["owner_wrote"] is True
    assert "morgan.ellery@northwind.example" not in thread["participants"]
    assert counts == {"read": 4, "noise": 0, "excluded": 0}


def test_an_empty_subject_groups_per_sender(scratch):
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "RE: FW:", "a@acme.example", []), mail("m2", "", "b@acme.example", [])])
    groups, _ = msgrows.group(msgrows.load(str(scratch)), exclusions=[], owner_addresses=OWNER,
                              timezone="Europe/Brussels", utc_offset=None)
    assert sorted(g["key"] for g in groups) == ["mail:(no subject)|a@acme.example", "mail:(no subject)|b@acme.example"]
    assert all(g["label"] == "(no subject)" for g in groups)


def test_a_group_chat_without_topic_is_labelled_by_its_members(scratch):
    page(scratch, "msg_chats.p1.payload.json", [chat("c2", "group", None, "sam.lee@acme.example", "jordan.reyes@acme.example", "morgan.ellery@northwind.example")])
    page(scratch, "msg_teams.p1.payload.json", [teams("t1", "c2", "sam.lee@acme.example", "hi")])
    groups, _ = msgrows.group(msgrows.load(str(scratch)), exclusions=[], owner_addresses=OWNER,
                              timezone="Europe/Brussels", utc_offset=None)
    assert groups[0]["label"] == "Jordan Reyes, Sam Lee"


def test_priority_order_and_trim_counts_what_was_skipped():
    def g(key, date, **kw):
        base = {"gid": key, "key": key, "date": date, "kind": "mail", "chat_type": None,
                "messages": [{}], "owner_wrote": False, "direct": False, "sources": ["inbox"]}
        base.update(kw)
        return base
    groups = [g("cc", "d1"), g("sent", "d1", sources=["sent"]), g("direct", "d1", direct=True),
              g("one", "d1", kind="chat", chat_type="oneOnOne", sources=["teams"]),
              g("grp", "d1", kind="chat", chat_type="group", sources=["teams"])]
    assert [msgrows.priority(x) for x in groups] == [3, 0, 2, 1, 4]
    kept, skipped = msgrows.trim(groups, limit=3)
    assert [x["key"] for x in kept] == ["sent", "one", "direct"]
    assert skipped == {"d1": 2}
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_msgrows.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vaultlib.msgrows'`

- [ ] **Step 3: Implement `plugin/lib/vaultlib/msgrows.py`**

```python
"""Message feed rows: connector page files in, filtered day groups out.

The worker writes each fetched page verbatim (trimmed to the kept keys) to
scratch as `msg_<source>.p<n>.payload.json`, or `msg_<source>.gap<id>.p<n>`
for a page fetched to fill an open gap. Everything after the fetch is here
and deterministic: noise, the owner's exclusions, grouping per local day,
and the priority order that decides what is condensed on a day that has
more than the safety limit allows.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from . import dates, discover, m365

SOURCES = ("teams", "chats", "inbox", "sent")
PAGE_RE = re.compile(
    r"\Amsg_(?P<source>teams|chats|inbox|sent)(?:\.gap(?P<gap>\d+))?"
    r"\.p(?P<n>\d+)\.payload\.json\Z")
PAGE_CAPS = {"teams": 20, "inbox": 8, "sent": 8}
FULL_READS = 5
MAX_GROUPS_PER_DAY = 40
DIRECT_LIMIT = 5
GROUPS_FILE = "msg_groups.payload.json"
BOT_SUFFIX = "@teams.microsoft.com"
NOTIFICATION_SENDERS = ("azuredevops@microsoft.com", "notifications@github.com")
NOTIFICATION_HINTS = ("deskbird",)
BILLING_WORDS = ("factuur", "invoice")
RESPONSE_PREFIXES = ("accepted:", "declined:", "tentative", "automatic reply:", "following:")
_MARKER_KEYS = {"moreResults", "nextOffset", "totalResultCount", "nextCursor"}


class MessagesError(Exception):
    """A message-feed argument or payload the caller must fix."""


def _address(value) -> Optional[str]:
    if isinstance(value, dict):
        value = value.get("address") or value.get("email") or (
            (value.get("emailAddress") or {}).get("address"))
    text = str(value or "").strip().casefold()
    return text if "@" in text else None


def _domain(address: Optional[str]) -> Optional[str]:
    return address.rsplit("@", 1)[1] if address else None


def _word_in(word: str, text: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text.casefold()))


def _read_page(path: Path) -> Tuple[List[dict], bool]:
    try:
        chunks = m365.load_listing(path.read_text(encoding="utf-8"))
    except (ValueError, m365.M365Error) as exc:
        raise MessagesError(f"{path.name}: {exc}") from exc
    rows = [c for c in chunks if isinstance(c, dict) and not set(c) <= _MARKER_KEYS]
    last = chunks[-1] if chunks else None
    capped = isinstance(last, dict) and set(last) <= _MARKER_KEYS and bool(
        last.get("moreResults") or last.get("nextOffset") or last.get("nextCursor"))
    return rows, capped


def load(scratch_dir: str) -> Dict[str, dict]:
    root = Path(scratch_dir)
    if not root.is_dir():
        raise MessagesError(f"--dir {scratch_dir!r} is not a directory")
    found: Dict[str, Dict[Optional[str], List[Tuple[int, Path]]]] = {
        s: defaultdict(list) for s in SOURCES}
    for path in root.iterdir():
        match = PAGE_RE.match(path.name)
        if match:
            found[match["source"]][match["gap"]].append((int(match["n"]), path))
    out: Dict[str, dict] = {}
    for source in SOURCES:
        entry = {"rows": [], "capped": False, "pages": [], "gap_pages": {}}
        for gap, pages in found[source].items():
            rows, capped = [], False
            for _, path in sorted(pages):
                page_rows, capped = _read_page(path)
                rows.extend(page_rows)
                entry["pages"].append(path.name)
            if gap is None:
                entry["rows"], entry["capped"] = rows, capped
            else:
                entry["gap_pages"][gap] = {"rows": rows, "capped": capped}
        out[source] = entry
    return out


def noise_reason(source: str, row: dict) -> Optional[str]:
    if source == "teams":
        if row.get("channelUri"):
            return "channel"
        sender = _address(row.get("from")) or ""
        if sender.endswith(BOT_SUFFIX):
            return "bot"
        if not str(row.get("summary") or "").strip():
            return "empty"
        return None
    subject = str(row.get("subject") or "").strip().casefold()
    sender = _address(row.get("sender")) or ""
    if subject.startswith(RESPONSE_PREFIXES):
        return "meeting-response"
    if sender in NOTIFICATION_SENDERS or any(h in sender or h in subject for h in NOTIFICATION_HINTS):
        return "notification"
    if any(_word_in(w, subject) for w in BILLING_WORDS):
        return "billing"
    return None


def _mail_addresses(row: dict) -> List[str]:
    found = [_address(row.get("sender"))] + [_address(r) for r in (row.get("recipients") or [])]
    return [a for a in found if a]


def _members(chat: Optional[dict]) -> List[str]:
    return [a for a in (_address(m) for m in (chat or {}).get("members") or []) if a]


def is_excluded(source: str, row: dict, chat: Optional[dict], exclusions: List[dict]) -> bool:
    for ex in exclusions:
        kind, value = ex["kind"], ex["value"]
        if source in ("inbox", "sent"):
            addresses = _mail_addresses(row)
            if kind == "person" and value in addresses:
                return True
            if kind == "domain" and value in {_domain(a) for a in addresses}:
                return True
            if kind == "word" and _word_in(value, str(row.get("subject") or "")):
                return True
        elif source == "teams":
            chat_type = (chat or {}).get("chatType")
            if kind == "chat" and row.get("chatId") == value:
                return True
            if kind == "person":
                if chat_type == "oneOnOne" and value in _members(chat):
                    return True
                if _address(row.get("from")) == value:
                    return True
            if kind == "word" and _word_in(value, str((chat or {}).get("topic") or "")):
                return True
    return False


def _gid(key: str, day: str) -> str:
    return hashlib.sha1(f"{key}|{day}".encode("utf-8")).hexdigest()[:8]


def _local_day(raw: str, label: str, timezone, utc_offset) -> Tuple[str, str]:
    utc = m365._parse_graph_dt(raw, label)
    local, _ = dates.utc_to_local(utc, timezone, utc_offset)
    return local.date().isoformat(), utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _name(row_from: dict) -> Optional[str]:
    if isinstance(row_from, dict):
        shown = str(row_from.get("displayName") or "").strip()
        return shown or None
    return None


def group(loaded: Dict[str, dict], *, exclusions: List[dict], owner_addresses: Set[str],
          timezone, utc_offset) -> Tuple[List[dict], Dict[str, int]]:
    owners = {a.casefold() for a in owner_addresses}
    chats = {c.get("id"): c for c in loaded["chats"]["rows"]}
    counts = {"read": 0, "noise": 0, "excluded": 0}
    groups: Dict[Tuple[str, str], dict] = {}
    seen_ids: Set[str] = set()

    def rows_of(source):
        rows = list(loaded[source]["rows"])
        for gap in loaded[source]["gap_pages"].values():
            rows.extend(gap["rows"])
        return rows

    def bucket(key, day, **init):
        if (key, day) not in groups:
            groups[(key, day)] = {"gid": _gid(key, day), "key": key, "date": day,
                                  "participants": [], "names": {}, "messages": [],
                                  "owner_wrote": False, "direct": False, "sources": [], **init}
        return groups[(key, day)]

    for source in ("teams", "inbox", "sent"):
        for row in rows_of(source):
            row_id = str(row.get("id") or "")
            if not row_id or row_id in seen_ids:
                continue
            seen_ids.add(row_id)
            if noise_reason(source, row):
                counts["noise"] += 1
                continue
            chat = chats.get(row.get("chatId")) if source == "teams" else None
            if is_excluded(source, row, chat, exclusions):
                counts["excluded"] += 1
                continue
            counts["read"] += 1
            if source == "teams":
                day, at = _local_day(row.get("createdDateTime"), "createdDateTime", timezone, utc_offset)
                sender = _address(row.get("from"))
                members = [m for m in (chat or {}).get("members") or []]
                others = sorted({(_name(m) or _address(m)) for m in members
                                 if _address(m) and _address(m) not in owners})
                chat_type = (chat or {}).get("chatType")
                label = (chat or {}).get("topic") or ", ".join(others) or "Teams chat"
                g = bucket(f"chat:{row.get('chatId')}", day, kind="chat",
                           chat_type=chat_type, label=label)
                for m in members:
                    address = _address(m)
                    if address and address not in owners:
                        g["names"].setdefault(address, _name(m))
                        if address not in g["participants"]:
                            g["participants"].append(address)
                g["direct"] = chat_type == "oneOnOne"
                text = str(row.get("summary") or "").strip()
            else:
                day, at = _local_day(row.get("receivedDateTime"), "receivedDateTime", timezone, utc_offset)
                sender = _address(row.get("sender"))
                subject = discover._subject(str(row.get("subject") or ""))
                if subject:
                    key, label = f"mail:{subject.casefold()}", subject
                else:
                    key, label = f"mail:(no subject)|{sender}", "(no subject)"
                g = bucket(key, day, kind="mail", chat_type=None, label=label)
                addresses = _mail_addresses(row)
                for address in addresses:
                    if address not in owners and address not in g["participants"]:
                        g["participants"].append(address)
                if len(addresses) <= DIRECT_LIMIT + 1 and (
                        source == "sent" or owners & set(addresses)):
                    g["direct"] = True
                text = str(row.get("summary") or "").strip()
            if source not in g["sources"]:
                g["sources"].append(source)
            if sender in owners:
                g["owner_wrote"] = True
            if source == "teams" and sender and sender not in owners:
                g["names"].setdefault(sender, _name(row.get("from")))
            g["messages"].append({"id": row_id, "at": at, "from": sender, "text": text})

    out = []
    for g in groups.values():
        g["messages"].sort(key=lambda m: m["at"])
        g["participants"].sort()
        out.append(g)
    out.sort(key=lambda g: (g["date"], g["key"]))
    return out, counts


def priority(g: dict) -> int:
    if "sent" in g["sources"]:
        return 0
    if g["kind"] == "chat" and (g["chat_type"] == "oneOnOne" or g["owner_wrote"]):
        return 1
    if g["kind"] == "mail" and g["direct"]:
        return 2
    if g["kind"] == "mail":
        return 3
    return 4


def trim(groups: List[dict], limit: int = MAX_GROUPS_PER_DAY) -> Tuple[List[dict], Dict[str, int]]:
    by_day: Dict[str, List[dict]] = defaultdict(list)
    for g in groups:
        by_day[g["date"]].append(g)
    kept, skipped = [], {}
    for day in sorted(by_day):
        ranked = sorted(by_day[day], key=lambda g: (priority(g), -len(g["messages"]), g["key"]))
        kept.extend(ranked[:limit])
        if len(ranked) > limit:
            skipped[day] = len(ranked) - limit
    return kept, skipped
```

Note: `discover._subject` is the existing RE:/FW: stripper; if its behaviour on `"RE: FW:"` returns a non-empty string, add `.strip(": ")` handling here rather than changing discover.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_msgrows.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/msgrows.py scripts/tests/test_vaultlib_msgrows.py
git commit -m "feat(messages): rows, noise, exclusions, day groups and priority trim (#236)"
```

### Task A5: People — `person.ensure(email=)`, enrichment, address book

**Files:**
- Modify: `plugin/lib/vaultlib/person.py`
- Modify: `plugin/lib/vaultlib/cli.py` (`person ensure` gains `--email`)
- Test: `scripts/tests/test_vaultlib_person.py`

**Interfaces:**
- Produces: `person.ensure(root, name, today, email: Optional[str] = None) -> dict` (a new note carries the casefolded email; an existing note is never rewritten); `person.set_email_if_missing(root, slug: str, email: str) -> bool`; `person.address_book(root) -> Dict[str, str]` (email → slug).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_new_person_from_the_feed_carries_their_address(tmp_path):
    root = make_vault(tmp_path)
    result = person.ensure(root, "Jordan Reyes", "2026-09-30", email="Jordan.Reyes@acme.example")
    fm, _ = markdown.split_frontmatter((root / result["path"]).read_text(encoding="utf-8"))
    assert fm["email"] == "jordan.reyes@acme.example"


def test_an_existing_person_gets_a_missing_email_once_and_never_overwritten(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Jordan Reyes", "2026-09-30")
    assert person.set_email_if_missing(root, "jordan-reyes", "jordan.reyes@acme.example") is True
    assert person.set_email_if_missing(root, "jordan-reyes", "other@acme.example") is False
    assert person.address_book(root) == {"jordan.reyes@acme.example": "jordan-reyes"}


def test_enrichment_of_an_unknown_slug_is_a_no_op(tmp_path):
    root = make_vault(tmp_path)
    assert person.set_email_if_missing(root, "nobody", "x@acme.example") is False
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_person.py -q`
Expected: FAIL (`unexpected keyword argument 'email'`)

- [ ] **Step 3: Implement**

In `person.py`, change the signature and the new-note frontmatter:

```python
def ensure(root: Path, name: str, today: str, email: Optional[str] = None) -> dict:
    ...
        "email": (email.strip().casefold() if email and "@" in email else None),
```

Add:

```python
def set_email_if_missing(root: Path, slug: str, email: str) -> bool:
    """Fill a person note's empty `email` (the message feed learns addresses
    from Teams chat members). Never overwrites one that is set."""
    found = _existing_note(root, slug)
    address = str(email or "").strip().casefold()
    if found is None or "@" not in address:
        return False
    text = found.read_text(encoding="utf-8")
    frontmatter, _ = markdown.split_frontmatter(text)
    if frontmatter.get("email"):
        return False
    updated = markdown.upsert_scalar_field(text, "email", markdown.emit_scalar(address, quoted=False))
    vault.atomic_write(found, updated)
    return True


def address_book(root: Path) -> Dict[str, str]:
    book: Dict[str, str] = {}
    people = root / PEOPLE_DIR
    for path in sorted(people.glob("*.md")) if people.is_dir() else []:
        try:
            frontmatter, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        address = str(frontmatter.get("email") or "").strip().casefold()
        if "@" in address and frontmatter.get("slug"):
            book.setdefault(address, str(frontmatter["slug"]))
    return book
```

(Imports: `from typing import Dict, Optional`.) In `cli.py` `person ensure`: add `--email` and pass `email=args.email`.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_person.py scripts/tests/test_vaultlib_cli.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/person.py plugin/lib/vaultlib/cli.py scripts/tests/test_vaultlib_person.py
git commit -m "feat(person): email on creation, fill-if-missing, address book (#236)"
```

### Task A6: `msgroute` — entity domains, project routing, people links

**Files:**
- Create: `plugin/lib/vaultlib/msgroute.py`
- Modify: `plugin/lib/vaultlib/project.py` (keywords functions), `plugin/lib/vaultlib/cli.py` (`project keywords add|remove|list`)
- Test: `scripts/tests/test_vaultlib_msgroute.py`, `scripts/tests/test_vaultlib_project.py`

**Interfaces:**
- Consumes: `person.address_book`, `person.ensure`, `person.set_email_if_missing`, `naming.slugify`, group dicts from Task A4.
- Produces:
  - `project.keywords_add(root, *, slug, keyword, today) -> dict`, `project.keywords_remove(root, *, slug, keyword, today) -> dict`, `project.keywords_list(root, *, slug) -> dict` (`{"slug", "keywords": [...]}`)
  - `msgroute.active_projects(root) -> List[dict]` — `{"slug", "name", "entity", "keywords", "people"}` (`people` = stakeholders + key-people slugs)
  - `msgroute.entity_domains(root, home_domains) -> Dict[str, Set[str]]`
  - `msgroute.route(root, groups, *, home_domains, owner_addresses, today) -> dict` — mutates each group, adding `people`, `projects`, `projects_weak`, `entities`; returns `{"created": [slugs], "emails_set": [slugs]}`

- [ ] **Step 1: Write the failing tests**

```python
"""Routing of message groups. Made-up fixtures only."""
from vaultlib import markdown, msgroute, person, project
from test_vaultlib_vault import make_vault

OWNER = {"morgan.ellery@northwind.example"}


def add_project(root, slug, name, entity, stakeholders=(), keywords=()):
    folder = root / "30-projects" / slug
    folder.mkdir(parents=True)
    fm = {"type": "project", "project-name": name, "slug": slug, "status": "active",
          "project-type": "initiative", "entity": entity, "owner": "morgan-ellery",
          "stakeholders": list(stakeholders), "key-people": [], "created": "2026-09-01",
          "last-updated": "2026-09-01"}
    if keywords:
        fm["keywords"] = list(keywords)
    (folder / "index.md").write_text(markdown.emit_frontmatter(fm), encoding="utf-8")


def add_meeting(root, stem, entities, emails):
    fm = {"type": "meeting", "entities": entities, "projects": [], "attendee-emails": emails}
    (root / "20-meetings" / f"{stem}.md").write_text(markdown.emit_frontmatter(fm), encoding="utf-8")


def grp(label, participants, kind="mail", chat_type=None, texts=("hello",), names=None, sources=("inbox",), direct=False):
    return {"gid": label[:8], "key": f"{kind}:{label}", "date": "2026-09-30", "kind": kind,
            "chat_type": chat_type, "label": label, "participants": list(participants),
            "names": names or {}, "messages": [{"id": t, "at": "", "from": None, "text": t} for t in texts],
            "owner_wrote": False, "direct": direct, "sources": list(sources)}


def test_entity_domains_need_two_meetings_and_skip_home_domains(tmp_path):
    root = make_vault(tmp_path)
    add_meeting(root, "01-09-26-a", ["acme-industries"], ["jordan.reyes@acme.example", "morgan.ellery@northwind.example"])
    add_meeting(root, "02-09-26-b", ["acme-industries"], ["sam.lee@acme.example"])
    add_meeting(root, "03-09-26-c", ["acme-industries"], ["once@other.example"])
    assert msgroute.entity_domains(root, ["northwind.example"]) == {"acme-industries": {"acme.example"}}


def test_a_domain_is_strong_only_when_it_names_one_project(tmp_path):
    root = make_vault(tmp_path)
    add_meeting(root, "01-09-26-a", ["acme-industries"], ["a@acme.example"])
    add_meeting(root, "02-09-26-b", ["acme-industries"], ["b@acme.example"])
    add_project(root, "acme-industries-operating-model", "Operating model", "acme-industries")
    g = grp("Quick question", ["jordan.reyes@acme.example"])
    msgroute.route(root, [g], home_domains=["northwind.example"], owner_addresses=OWNER, today="2026-09-30")
    assert g["projects"] == ["acme-industries-operating-model"] and g["projects_weak"] == []
    add_project(root, "acme-industries-rollout", "Rollout", "acme-industries")
    g2 = grp("Quick question", ["jordan.reyes@acme.example"])
    msgroute.route(root, [g2], home_domains=["northwind.example"], owner_addresses=OWNER, today="2026-09-30")
    assert set(g2["projects"]) == set(g2["projects_weak"]) == {"acme-industries-operating-model", "acme-industries-rollout"}


def test_a_keyword_in_the_subject_is_strong_and_in_the_text_is_weak(tmp_path):
    root = make_vault(tmp_path)
    add_project(root, "acme-industries-operating-model", "Operating model", "acme-industries", keywords=["P-2317"])
    strong = grp("Status P-2317", ["x@else.example"])
    weak = grp("Update", ["x@else.example"], texts=("about p-2317 again",))
    none = grp("Update", ["x@else.example"], texts=("about P-23170",))
    msgroute.route(root, [strong, weak, none], home_domains=[], owner_addresses=OWNER, today="2026-09-30")
    assert strong["projects"] == ["acme-industries-operating-model"] and strong["projects_weak"] == []
    assert weak["projects_weak"] == ["acme-industries-operating-model"]
    assert none["projects"] == []


def test_people_creation_rule_and_enrichment(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Sam Lee", "2026-09-01")
    one = grp("Sam Lee", ["sam.lee@acme.example"], kind="chat", chat_type="oneOnOne",
              names={"sam.lee@acme.example": "Sam Lee"}, sources=("teams",), direct=True)
    sent = grp("Proposal", ["priya.nathan@contoso.example"], sources=("sent",), direct=True)
    cc = grp("Newsletter", [f"p{i}@acme.example" for i in range(9)])
    result = msgroute.route(root, [one, sent, cc], home_domains=[], owner_addresses=OWNER, today="2026-09-30")
    assert result["emails_set"] == ["sam-lee"]
    assert result["created"] == ["priya-nathan"]
    assert one["people"] == ["sam-lee"] and sent["people"] == ["priya-nathan"] and cc["people"] == []


def test_the_owner_is_never_routed_or_created(tmp_path):
    root = make_vault(tmp_path)
    g = grp("Hi", ["morgan.ellery@northwind.example"], sources=("sent",), direct=True)
    result = msgroute.route(root, [g], home_domains=[], owner_addresses=OWNER, today="2026-09-30")
    assert result["created"] == [] and g["people"] == []


def test_a_stakeholder_link_is_weak_and_only_for_exactly_one_project(tmp_path):
    root = make_vault(tmp_path)
    person.ensure(root, "Sam Lee", "2026-09-01", email="sam.lee@acme.example")
    add_project(root, "acme-industries-rollout", "Rollout", "acme-industries", stakeholders=["sam-lee"])
    g = grp("Lunch", ["sam.lee@acme.example"])
    msgroute.route(root, [g], home_domains=[], owner_addresses=OWNER, today="2026-09-30")
    assert g["projects_weak"] == ["acme-industries-rollout"]
```

In `test_vaultlib_project.py`:

```python
def test_keywords_add_remove_and_list(tmp_path):
    root = vault_with_entity(tmp_path, "acme-industries")
    project.scaffold(root, name="Operating model", project_type="initiative",
                     entity="acme-industries", owner="morgan-ellery", today="2026-09-30")
    slug = "acme-industries-operating-model"
    project.keywords_add(root, slug=slug, keyword="P-2317", today="2026-09-30")
    project.keywords_add(root, slug=slug, keyword="p-2317", today="2026-09-30")  # dedup, case-insensitive
    assert project.keywords_list(root, slug=slug)["keywords"] == ["P-2317"]
    project.keywords_remove(root, slug=slug, keyword="P-2317", today="2026-09-30")
    assert project.keywords_list(root, slug=slug)["keywords"] == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_msgroute.py scripts/tests/test_vaultlib_project.py -k "keywords or route or domain or people or owner or stakeholder" -q`
Expected: FAIL (`ModuleNotFoundError: vaultlib.msgroute`; `project` has no `keywords_add`)

- [ ] **Step 3: Implement**

`project.py`:

```python
def _keywords_of(frontmatter: dict) -> List[str]:
    raw = frontmatter.get("keywords") or []
    return [str(k) for k in raw] if isinstance(raw, list) else [str(raw)]


def _write_keywords(root: Path, slug: str, keywords: List[str], today: str) -> dict:
    path = root / PROJECTS_DIR / slug / "index.md"
    if not path.is_file():
        raise ProjectError(f"no project {slug!r} at {path.relative_to(root).as_posix()}")
    text = path.read_text(encoding="utf-8")
    rendered = "[{}]".format(", ".join(markdown.emit_scalar(k, quoted=True) for k in keywords))
    updated = markdown.upsert_scalar_field(text, "keywords", rendered)
    frontmatter, _ = markdown.split_frontmatter(updated)
    errors = schema.validate("project", frontmatter)
    if errors:
        raise ProjectError("; ".join(errors))
    if updated != text:
        vault.atomic_write(path, updated)
    return {"slug": slug, "keywords": keywords, "changed": updated != text}


def keywords_list(root: Path, *, slug: str) -> dict:
    data = _load_project(root, slug)
    if data is None:
        raise ProjectError(f"no project {slug!r}")
    return {"slug": slug, "keywords": _keywords_of(data)}


def keywords_add(root: Path, *, slug: str, keyword: str, today: str) -> dict:
    clean = " ".join(str(keyword or "").split())
    if not clean:
        raise ProjectError("a keyword must be a non-empty string")
    current = keywords_list(root, slug=slug)["keywords"]
    if clean.casefold() in {k.casefold() for k in current}:
        return {"slug": slug, "keywords": current, "changed": False}
    return _write_keywords(root, slug, current + [clean], today)


def keywords_remove(root: Path, *, slug: str, keyword: str, today: str) -> dict:
    current = keywords_list(root, slug=slug)["keywords"]
    kept = [k for k in current if k.casefold() != str(keyword).strip().casefold()]
    if len(kept) == len(current):
        raise ProjectError(f"project {slug!r} has no keyword {keyword!r}")
    return _write_keywords(root, slug, kept, today)
```

`plugin/lib/vaultlib/msgroute.py`:

```python
"""Routing message groups to people and projects, from what the vault knows.

No hand-kept table (unlike the colleague's capture): an entity's domains come
from the meetings linked to it, a project's words from its name and its
`keywords`, its people from stakeholders and key people. Strong links queue a
project-state update; weak links only link (spec §7.1, decision 15).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set

from . import markdown, naming, person, vault

MIN_DOMAIN_MEETINGS = 2


def _frontmatter(path: Path) -> dict:
    try:
        data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        return data
    except (ValueError, OSError):
        return {}


def _as_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)] if value else []


def active_projects(root: Path) -> List[dict]:
    out = []
    folder = root / vault.PROJECTS_DIR
    for index in sorted(folder.glob("*/index.md")) if folder.is_dir() else []:
        data = _frontmatter(index)
        if data.get("status") != "active" or not data.get("slug"):
            continue
        out.append({"slug": str(data["slug"]), "name": str(data.get("project-name") or data["slug"]),
                    "entity": str(data.get("entity") or ""),
                    "keywords": _as_list(data.get("keywords")),
                    "people": sorted(set(_as_list(data.get("stakeholders")) + _as_list(data.get("key-people"))))})
    return out


def entity_domains(root: Path, home_domains: Iterable[str]) -> Dict[str, Set[str]]:
    home = {d.casefold() for d in (home_domains or [])}
    project_entity = {p["slug"]: p["entity"] for p in active_projects(root)}
    counts: Dict[str, Counter] = defaultdict(Counter)
    meetings = root / vault.MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        data = _frontmatter(path)
        entities = set(_as_list(data.get("entities")))
        entities |= {project_entity[p] for p in _as_list(data.get("projects")) if project_entity.get(p)}
        domains = {str(e).rsplit("@", 1)[1].casefold() for e in _as_list(data.get("attendee-emails")) if "@" in str(e)}
        for entity in entities:
            for domain in domains - home:
                counts[entity][domain] += 1
    return {entity: {d for d, n in c.items() if n >= MIN_DOMAIN_MEETINGS}
            for entity, c in counts.items() if any(n >= MIN_DOMAIN_MEETINGS for n in c.values())}


def _has_word(word: str, text: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(word.casefold()) + r"(?!\w)", text.casefold()))


def _name_from_address(address: str):
    local = address.split("@", 1)[0]
    parts = [p for p in re.split(r"[._-]", local) if p.isalpha()]
    return " ".join(p.capitalize() for p in parts) if len(parts) >= 2 else None


def route(root: Path, groups: List[dict], *, home_domains, owner_addresses, today: str) -> dict:
    owners = {a.casefold() for a in owner_addresses}
    projects = active_projects(root)
    domains = entity_domains(root, home_domains)
    domain_projects: Dict[str, List[str]] = defaultdict(list)
    for p in projects:
        for domain in domains.get(p["entity"], set()):
            domain_projects[domain].append(p["slug"])
    created, emails_set = [], []

    for g in groups:  # learn addresses first: chat members carry names
        for address, name in g["names"].items():
            if address in owners or not name:
                continue
            slug = naming.slugify(name)
            if person.set_email_if_missing(root, slug, address):
                emails_set.append(slug)
    book = person.address_book(root)

    for g in groups:
        create = []
        if g["kind"] == "chat" and g["chat_type"] == "oneOnOne":
            create = [(a, g["names"].get(a)) for a in g["participants"]]
        elif g["kind"] == "mail" and "sent" in g["sources"] and g["direct"]:
            create = [(a, _name_from_address(a)) for a in g["participants"]]
        for address, name in create:
            if address in owners or address in book or not name:
                continue
            result = person.ensure(root, name, today, email=address)
            if result["created"]:
                created.append(result["slug"])
                book[address] = result["slug"]
        g["people"] = sorted({book[a] for a in g["participants"] if a in book and a not in owners})

        strong, weak = set(), set()
        for address in g["participants"]:
            hits = domain_projects.get(address.rsplit("@", 1)[1], [])
            (strong if len(hits) == 1 else weak).update(hits)
        texts = " \n ".join(m["text"] for m in g["messages"])
        for p in projects:
            words = [p["name"]] + p["keywords"]
            if any(_has_word(w, g["label"]) for w in words):
                strong.add(p["slug"])
            elif any(_has_word(k, texts) for k in p["keywords"]):
                weak.add(p["slug"])
        holders = [p["slug"] for p in projects if set(p["people"]) & set(g["people"])]
        if len(holders) == 1:
            weak.add(holders[0])
        weak -= strong
        g["projects"] = sorted(strong) + sorted(weak)
        g["projects_weak"] = sorted(weak)
        g["entities"] = sorted({p["entity"] for p in projects if p["slug"] in g["projects"] and p["entity"]})
    return {"created": sorted(created), "emails_set": sorted(set(emails_set))}
```

Note on the strong-domain test: with one project the domain maps to one project, so it is strong; with two it is weak for both. `_has_word` on the label uses the project name, so a subject "Operating model" links strongly.

CLI (`cli.py`): `project keywords add|remove|list --vault --slug [--keyword] [--today]`, dispatching to the three functions.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_msgroute.py scripts/tests/test_vaultlib_project.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/msgroute.py plugin/lib/vaultlib/project.py plugin/lib/vaultlib/cli.py scripts/tests/
git commit -m "feat(messages): routing to people and projects, project keywords (#236)"
```

### Task A7: `msgstate` — cursor, gaps, requeue

**Files:**
- Create: `plugin/lib/vaultlib/msgstate.py`
- Test: `scripts/tests/test_vaultlib_msgstate.py`

**Interfaces:**
- Produces:
  - `STATE_RELPATH = Path("99-workflow-config") / "sync-state" / "messages.json"`, `GAP_HORIZON_DAYS = 7`
  - `load(root) -> dict` (never raises; empty state `{"version": 1, "cursor": None, "gaps": [], "requeue": [], "proposed": [], "last_run": None}`), `save(root, state)`
  - `cursor(root, *, now: str, timezone, utc_offset, since: Optional[str] = None) -> dict` — `{"since", "first_run", "gaps": [open gaps within horizon, each {"id", "source", "from", "to"}], "closed": [gaps dropped as too old]}`; `closed` gaps are removed from state and remembered in `state["closed_unread"]` for the status line
  - `advance(root, *, newest: Optional[str], new_gaps: List[dict], filled: List[str], now: str) -> dict` — monotonic cursor, appends gaps with fresh ids, removes filled ids, stamps `last_run`
  - `requeue_add(root, slug, digest)`, `requeue_take(root) -> List[dict]` (returns and clears)

- [ ] **Step 1: Write the failing tests**

```python
from vaultlib import msgstate
from test_vaultlib_vault import make_vault


def test_first_run_starts_at_local_yesterday_midnight(tmp_path):
    root = make_vault(tmp_path)
    result = msgstate.cursor(root, now="2026-09-30T18:47:00Z", timezone="Europe/Brussels", utc_offset=None)
    assert result == {"since": "2026-09-28T22:00:00Z", "first_run": True, "gaps": [], "closed": []}


def test_the_cursor_never_moves_backwards(tmp_path):
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-09-30T18:40:00Z", new_gaps=[], filled=[], now="2026-09-30T18:50:00Z")
    msgstate.advance(root, newest="2026-09-30T10:00:00Z", new_gaps=[], filled=[], now="2026-09-30T19:10:00Z")
    assert msgstate.cursor(root, now="2026-09-30T19:20:00Z", timezone="UTC", utc_offset=None)["since"] == "2026-09-30T18:40:00Z"


def test_gaps_get_ids_are_filled_and_close_after_seven_days(tmp_path):
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-09-30T18:40:00Z", now="2026-09-30T18:50:00Z", filled=[],
                     new_gaps=[{"source": "inbox", "from": "2026-09-27T00:00:00Z", "to": "2026-09-28T09:00:00Z"},
                               {"source": "teams", "from": "2026-09-20T00:00:00Z", "to": "2026-09-21T00:00:00Z"}])
    open_ = msgstate.cursor(root, now="2026-09-30T19:00:00Z", timezone="UTC", utc_offset=None)
    assert [g["id"] for g in open_["gaps"]] == ["1"]
    assert [g["source"] for g in open_["closed"]] == ["teams"]
    msgstate.advance(root, newest=None, new_gaps=[], filled=["1"], now="2026-10-01T18:50:00Z")
    assert msgstate.cursor(root, now="2026-10-01T19:00:00Z", timezone="UTC", utc_offset=None)["gaps"] == []


def test_requeue_is_taken_once(tmp_path):
    root = make_vault(tmp_path)
    msgstate.requeue_add(root, "acme-industries-operating-model", "2026-09-30-messages")
    assert msgstate.requeue_take(root) == [{"slug": "acme-industries-operating-model", "digest": "2026-09-30-messages"}]
    assert msgstate.requeue_take(root) == []


def test_a_broken_state_file_loads_as_empty(tmp_path):
    root = make_vault(tmp_path)
    path = root / msgstate.STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")
    assert msgstate.load(root)["cursor"] is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_msgstate.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement `plugin/lib/vaultlib/msgstate.py`**

```python
"""Message feed state: the cursor, open gaps, the requeue list.

A cache, not a ledger (like last-sync and seen-events): a missing or broken
file loads as empty. The cursor is the newest message the last successful run
saw (from data, never from the clock), so a missed evening catches itself up.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from . import dates, seenevents, vault

STATE_RELPATH = Path("99-workflow-config") / "sync-state" / "messages.json"
GAP_HORIZON_DAYS = 7
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _empty() -> dict:
    return {"version": 1, "cursor": None, "gaps": [], "requeue": [], "proposed": [],
            "closed_unread": [], "last_run": None, "next_gap": 1}


def load(root: Path) -> dict:
    try:
        state = json.loads((root / STATE_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(state, dict) or state.get("version") != 1:
        return _empty()
    return {**_empty(), **state}


def save(root: Path, state: dict) -> None:
    vault.atomic_write(root / STATE_RELPATH, json.dumps(state, indent=2, sort_keys=True) + "\n")


def _parse(text: str) -> datetime:
    return seenevents.parse_now(text)


def cursor(root: Path, *, now: str, timezone, utc_offset, since: Optional[str] = None) -> dict:
    state = load(root)
    now_dt = _parse(now)
    if since:
        start = _parse(since).strftime(_FMT)
    elif state["cursor"]:
        start = state["cursor"]
    else:
        local_now, _ = dates.utc_to_local(now_dt, timezone, utc_offset)
        midnight = datetime.combine(local_now.date() - timedelta(days=1), datetime.min.time())
        offset, _ = dates.resolve_offset_minutes(midnight, timezone, utc_offset)
        start = (midnight - timedelta(minutes=offset)).strftime(_FMT)
    horizon = now_dt - timedelta(days=GAP_HORIZON_DAYS)
    open_, closed = [], []
    for gap in state["gaps"]:
        (open_ if _parse(gap["to"]) >= horizon else closed).append(gap)
    if closed:
        state["gaps"] = open_
        state["closed_unread"] = state["closed_unread"] + closed
        save(root, state)
    return {"since": start, "first_run": state["cursor"] is None and not since,
            "gaps": open_, "closed": closed}


def advance(root: Path, *, newest: Optional[str], new_gaps: List[dict], filled: List[str], now: str) -> dict:
    state = load(root)
    if newest and (state["cursor"] is None or _parse(newest) > _parse(state["cursor"])):
        state["cursor"] = _parse(newest).strftime(_FMT)
    state["gaps"] = [g for g in state["gaps"] if g["id"] not in set(filled)]
    for gap in new_gaps:
        state["gaps"].append({"id": str(state["next_gap"]), **gap})
        state["next_gap"] += 1
    state["last_run"] = _parse(now).strftime(_FMT)
    save(root, state)
    return {"cursor": state["cursor"], "gaps": state["gaps"]}


def requeue_add(root: Path, slug: str, digest: str) -> None:
    state = load(root)
    entry = {"slug": slug, "digest": digest}
    if entry not in state["requeue"]:
        state["requeue"].append(entry)
        save(root, state)


def requeue_take(root: Path) -> List[dict]:
    state = load(root)
    taken, state["requeue"] = state["requeue"], []
    if taken:
        save(root, state)
    return taken
```

Note: the first-run expectation in the test (Brussels is UTC+2 on 29 Sep, so local midnight 29 Sep = 28 Sep 22:00Z) depends on `dates.resolve_offset_minutes` returning +120; if its sign convention is the opposite, flip the subtraction and keep the test.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_msgstate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/msgstate.py scripts/tests/test_vaultlib_msgstate.py
git commit -m "feat(messages): cursor, gaps with a 7-day horizon, requeue (#236)"
```

### Task A8: `msgdigest` — build, check, write, merge

**Files:**
- Create: `plugin/lib/vaultlib/msgdigest.py`
- Test: `scripts/tests/test_vaultlib_msgdigest.py`

**Interfaces:**
- Consumes: Tasks A1, A4, A6, A7.
- Produces:
  - `CONDENSED_FILE = "msg_condensed.payload.json"`, `CHECKED_FILE = "msg_checked.payload.json"`, `DATA_RE` (the `%% digest-data … %%` block)
  - `build(root, scratch_dir, *, timezone, utc_offset, owner_addresses, home_domains, exclusions, today, since, gap_ids: List[str], consume: bool) -> dict` — writes `GROUPS_FILE`; result `{"groups": n, "by_date": {date: n}, "counts", "skipped": {date: n}, "at_limit": bool, "created": [...], "emails_set": [...], "newest", "new_gaps", "filled", "consumed"}`
  - `check(scratch_dir) -> dict` — reads `GROUPS_FILE` + `CONDENSED_FILE`, writes `CHECKED_FILE`, returns `{"passed": n, "dropped": [{"gid", "text", "reasons"}]}`
  - `write(root, scratch_dir, *, now: str) -> dict` — per date merges into `_messages/<date>-messages.md`, advances the cursor; result `{"written": [stems], "refused": [{"stem", "error"}], "cursor"}`
  - `load_digest(path) -> dict` — `{"frontmatter", "data"}`; raises `MessagesError` when the data block is missing or broken
  - `render(root, data: dict) -> str`

Condensed file format (written by the worker, Task C1):

```json
{"groups": [{"gid": "ab12cd34", "needs_owner": false,
             "points": [{"text": "Jordan asks to move workshop 2 to 14 Oct; you agreed.", "cites": ["m1", "m2"]}]}]}
```

Digest data block (inside `%% digest-data` … `%%`), one JSON object:

```json
{"schema": 1, "date": "2026-09-30", "ids": ["m1", "m2", "t7"],
 "groups": [{"gid": "ab12cd34", "kind": "mail", "label": "Workshop 2 agenda", "chat_type": null,
             "people": ["jordan-reyes"], "names": {"jordan.reyes@acme.example": "Jordan Reyes"},
             "participants": ["jordan.reyes@acme.example"],
             "projects": ["acme-industries-operating-model"], "projects_weak": [],
             "needs_owner": false, "points": [{"text": "...", "cites": ["m1", "m2"]}]}]}
```

- [ ] **Step 1: Write the failing tests**

```python
"""Digest build, check, write. Made-up fixtures only."""
import json
import pytest
from vaultlib import markdown, msgdigest, msgrows, msgstate
from test_vaultlib_vault import make_vault
from test_vaultlib_msgrows import chat, mail, page, teams

OWNER = {"morgan.ellery@northwind.example"}
KW = dict(timezone="Europe/Brussels", utc_offset=None, owner_addresses=OWNER, home_domains=[],
          exclusions=[], today="2026-09-30", since="2026-09-29T22:00:00Z", gap_ids=[])


@pytest.fixture
def env(tmp_path):
    root = make_vault(tmp_path)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", ["morgan.ellery@northwind.example"],
             summary="Can we move workshop 2 to 14 Oct?")])
    page(scratch, "msg_sent.p1.payload.json", [
        mail("m2", "RE: Workshop 2 agenda", "morgan.ellery@northwind.example", ["jordan.reyes@acme.example"],
             at="2026-09-30T10:00:00Z", summary="Fine for me.")])
    return root, scratch


def condense(scratch, points, needs_owner=False):
    groups = json.loads((scratch / msgrows.GROUPS_FILE).read_text(encoding="utf-8"))["groups"]
    payload = {"groups": [{"gid": groups[0]["gid"], "needs_owner": needs_owner, "points": points}]}
    (scratch / msgdigest.CONDENSED_FILE).write_text(json.dumps(payload), encoding="utf-8")


def test_build_writes_groups_and_consumes_pages(env):
    root, scratch = env
    result = msgdigest.build(root, str(scratch), consume=True, **KW)
    assert result["groups"] == 1 and result["by_date"] == {"2026-09-30": 1}
    assert result["newest"] == "2026-09-30T10:00:00Z"
    assert not list(scratch.glob("msg_inbox.p*"))
    assert (scratch / msgrows.GROUPS_FILE).is_file()


def test_check_drops_an_invented_point(env):
    root, scratch = env
    msgdigest.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]},
                       {"text": "Priya Nathan approved the budget.", "cites": ["m1"]}])
    result = msgdigest.check(str(scratch))
    assert result["passed"] == 1
    assert "Priya Nathan" in " ".join(result["dropped"][0]["reasons"])


def test_write_renders_a_hidden_data_block_and_advances_the_cursor(env):
    root, scratch = env
    msgdigest.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    msgdigest.check(str(scratch))
    result = msgdigest.write(root, str(scratch), now="2026-09-30T18:52:00Z")
    assert result["written"] == ["2026-09-30-messages"]
    text = (root / "_messages" / "2026-09-30-messages.md").read_text(encoding="utf-8")
    fm, body = markdown.split_frontmatter(text)
    assert fm["type"] == "digest" and fm["date"] == "2026-09-30" and fm["messages-read"] == 2
    assert "%% digest-data" in body and "Workshop 2 agenda" in body
    assert msgstate.load(root)["cursor"] == "2026-09-30T10:00:00Z"


def test_a_second_run_never_duplicates_a_message(env):
    root, scratch = env
    for _ in range(2):
        msgdigest.build(root, str(scratch), consume=False, **KW)
        condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
        msgdigest.check(str(scratch))
        msgdigest.write(root, str(scratch), now="2026-09-30T18:52:00Z")
    data = msgdigest.load_digest(root / "_messages" / "2026-09-30-messages.md")["data"]
    assert data["ids"] == ["m1", "m2"]
    assert len(data["groups"]) == 1 and len(data["groups"][0]["points"]) == 1


def test_a_hand_edited_digest_is_refused_and_left_alone(env):
    root, scratch = env
    folder = root / "_messages"
    folder.mkdir()
    edited = folder / "2026-09-30-messages.md"
    edited.write_text("---\ntype: digest\n---\nmy own notes\n", encoding="utf-8")
    msgdigest.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    msgdigest.check(str(scratch))
    result = msgdigest.write(root, str(scratch), now="2026-09-30T18:52:00Z")
    assert result["written"] == [] and result["refused"][0]["stem"] == "2026-09-30-messages"
    assert edited.read_text(encoding="utf-8").endswith("my own notes\n")


def test_a_capped_source_inside_the_last_day_is_at_limit_not_a_gap(env):
    root, scratch = env
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", [], at="2026-09-30T09:00:00Z")], more=True)
    result = msgdigest.build(root, str(scratch), consume=False, **{**KW, "since": "2026-09-30T00:00:00Z"})
    assert result["at_limit"] is True and result["new_gaps"] == []


def test_a_capped_source_over_a_missed_evening_records_the_older_part_as_a_gap(env):
    root, scratch = env
    page(scratch, "msg_inbox.p1.payload.json", [
        mail("m1", "Workshop 2 agenda", "jordan.reyes@acme.example", [], at="2026-09-30T09:00:00Z")], more=True)
    result = msgdigest.build(root, str(scratch), consume=False, **{**KW, "since": "2026-09-27T00:00:00Z"})
    assert result["new_gaps"] == [{"source": "inbox", "from": "2026-09-27T00:00:00Z", "to": "2026-09-29T09:00:00Z"}]
```

The last test's expected `to` is "24 hours before the oldest seen item in the capped source, or the oldest seen item, whichever is earlier": the part within the last day is skipped (decision 20), the older part is owed.

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_msgdigest.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement `plugin/lib/vaultlib/msgdigest.py`**

```python
"""Digests: one hidden note per calendar day of mail and Teams chat.

The body is always rendered from the data block at its end, so merge, forget
and unlink edit data and re-render; nothing parses prose. A digest whose data
block is missing or broken was edited by hand and is refused, never rewritten.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

from . import discover, links, markdown, msgroute, msgrows, msgstate, schema, seenevents, vault

CONDENSED_FILE = "msg_condensed.payload.json"
CHECKED_FILE = "msg_checked.payload.json"
DATA_RE = re.compile(r"%% digest-data\n(?P<json>.*?)\n%%\s*\Z", re.S)
MessagesError = msgrows.MessagesError
_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _digest_path(root: Path, day: str) -> Path:
    return root / vault.MESSAGES_DIR / f"{day}-messages.md"


def _read_json(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MessagesError(f"{label} is missing from scratch — run the previous step first") from exc
    except ValueError as exc:
        raise MessagesError(f"{label} is not valid JSON: {exc}") from exc


def build(root: Path, scratch_dir: str, *, timezone, utc_offset, owner_addresses, home_domains,
          exclusions, today: str, since: str, gap_ids: List[str], consume: bool) -> dict:
    loaded = msgrows.load(scratch_dir)
    groups, counts = msgrows.group(loaded, exclusions=exclusions, owner_addresses=set(owner_addresses),
                                   timezone=timezone, utc_offset=utc_offset)
    groups, skipped = msgrows.trim(groups)
    routed = msgroute.route(root, groups, home_domains=home_domains,
                            owner_addresses=set(owner_addresses), today=today)
    since_dt = seenevents.parse_now(since)
    new_gaps, at_limit = [], bool(skipped)
    for source in ("teams", "inbox", "sent"):
        entry = loaded[source]
        if not entry["capped"] or not entry["rows"]:
            continue
        stamps = [r.get("createdDateTime") or r.get("receivedDateTime") for r in entry["rows"]]
        oldest = min(seenevents.parse_now(s) for s in stamps if s)
        owed_until = oldest - timedelta(hours=24)
        at_limit = True
        if owed_until > since_dt:
            new_gaps.append({"source": source, "from": since_dt.strftime(_FMT),
                             "to": owed_until.strftime(_FMT)})
    filled = [gid for gid in gap_ids
              if not any(loaded[s]["gap_pages"].get(gid, {}).get("capped") for s in ("teams", "inbox", "sent"))]
    newest = max((m["at"] for g in groups for m in g["messages"]), default=None)
    by_date: Dict[str, int] = {}
    for g in groups:
        by_date[g["date"]] = by_date.get(g["date"], 0) + 1
    payload = {"groups": groups, "skipped": skipped, "at_limit": at_limit,
               "counts": counts, "newest": newest, "new_gaps": new_gaps, "filled": filled}
    (Path(scratch_dir) / msgrows.GROUPS_FILE).write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    consumed = []
    if consume:
        for source in msgrows.SOURCES:
            for name in loaded[source]["pages"]:
                (Path(scratch_dir) / name).unlink()
                consumed.append(name)
    return {"groups": len(groups), "by_date": by_date, "counts": counts, "skipped": skipped,
            "at_limit": at_limit, "newest": newest, "new_gaps": new_gaps, "filled": filled,
            "consumed": sorted(consumed), **routed}


def check(scratch_dir: str) -> dict:
    scratch = Path(scratch_dir)
    groups = {g["gid"]: g for g in _read_json(scratch / msgrows.GROUPS_FILE, msgrows.GROUPS_FILE)["groups"]}
    condensed = _read_json(scratch / CONDENSED_FILE, CONDENSED_FILE)
    checked, dropped, passed = [], [], 0
    for item in condensed.get("groups", []):
        g = groups.get(item.get("gid"))
        if g is None:
            dropped.append({"gid": item.get("gid"), "text": None, "reasons": ["unknown group"]})
            continue
        by_id = {m["id"]: m for m in g["messages"]}
        keep = []
        for point in item.get("points", []):
            cites = [c for c in point.get("cites", []) if c in by_id]
            if not cites:
                dropped.append({"gid": g["gid"], "text": point.get("text"), "reasons": ["cites no message of this group"]})
                continue
            sources = [by_id[c]["text"] for c in cites] + [g["label"]] + [n for n in g["names"].values() if n]
            missing = discover.unsupported_tokens(str(point.get("text") or ""), sources)
            if missing:
                dropped.append({"gid": g["gid"], "text": point.get("text"),
                                "reasons": [f"{t!r} is not in the cited messages" for t in missing]})
                continue
            keep.append({"text": point["text"].strip(), "cites": cites})
            passed += 1
        if keep:
            checked.append({"gid": g["gid"], "needs_owner": bool(item.get("needs_owner")), "points": keep})
    (scratch / CHECKED_FILE).write_text(json.dumps({"groups": checked}, ensure_ascii=False), encoding="utf-8")
    return {"passed": passed, "dropped": dropped}


def load_digest(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = markdown.split_frontmatter(text)
    match = DATA_RE.search(body)
    if not match:
        raise MessagesError(f"{path.name} has no digest-data block — it was edited by hand; "
                            "leave it, or move it out of _messages/ to let the feed write that day again")
    try:
        data = json.loads(match["json"])
    except ValueError as exc:
        raise MessagesError(f"{path.name}: the digest-data block is not valid JSON ({exc})") from exc
    return {"frontmatter": frontmatter, "data": data}


def _person_link(root: Path, slug: str) -> str:
    kind, path, key = links.resolve(root, slug)
    if kind != "person":
        return slug
    return f"[[{links.path_target(root, path)}|{links.display_name(path, key) or slug}]]"


def _project_heading(root: Path, slug: str) -> str:
    kind, path, key = links.resolve(root, slug)
    if kind != "project":
        return slug
    return f"[[{links.path_target(root, path)}|{links.display_name(path, key) or slug}]]"


def render(root: Path, data: dict, frontmatter: dict) -> str:
    sections: Dict[str, List[str]] = {}
    for g in data["groups"]:
        if not g["points"]:
            continue
        head = g["projects"][0] if g["projects"] else ""
        what = (f'Mail "{g["label"]}"' if g["kind"] == "mail"
                else ("Teams 1:1" if g["chat_type"] == "oneOnOne" else f'Teams "{g["label"]}"'))
        who = " · ".join(_person_link(root, s) for s in g["people"])
        flag = "**Needs you** · " if g.get("needs_owner") else ""
        lines = [f"- {flag}**{what}**" + (f" · {who}" if who else "") + f" <!-- {g['gid']} -->"]
        lines += [f"  - {p['text']}" for p in g["points"]]
        sections.setdefault(head, []).extend(lines)
    parts = [f"# Mail and Teams · {data['date']}"]
    for head in sorted(k for k in sections if k):
        parts.append(f"## {_project_heading(root, head)}\n" + "\n".join(sections[head]))
    if "" in sections:
        parts.append("## Not linked to a project\n" + "\n".join(sections[""]))
    block = "%% digest-data\n" + json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n%%"
    return markdown.emit_frontmatter(frontmatter) + "\n" + "\n\n".join(parts) + "\n\n" + block + "\n"


def _frontmatter_for(data: dict, *, updated_at: str, read: int, skipped: int, at_limit: bool) -> dict:
    projects = sorted({p for g in data["groups"] for p in g["projects"]})
    strong = {p for g in data["groups"] for p in g["projects"] if p not in g["projects_weak"]}
    return {"type": "digest", "date": data["date"], "updated-at": updated_at,
            "projects": projects, "projects-weak": sorted(set(projects) - strong),
            "people": sorted({p for g in data["groups"] for p in g["people"]}),
            "entities": sorted({e for g in data["groups"] for e in g.get("entities", [])}),
            "messages-read": read, "skipped": skipped, "at-limit": at_limit}


def save_digest(root: Path, data: dict, frontmatter: dict) -> None:
    errors = schema.validate("digest", frontmatter)
    if errors:
        raise MessagesError("; ".join(errors))
    vault.atomic_write(_digest_path(root, data["date"]), render(root, data, frontmatter))


def write(root: Path, scratch_dir: str, *, now: str) -> dict:
    scratch = Path(scratch_dir)
    built = _read_json(scratch / msgrows.GROUPS_FILE, msgrows.GROUPS_FILE)
    checked = {g["gid"]: g for g in _read_json(scratch / CHECKED_FILE, CHECKED_FILE)["groups"]}
    updated_at = seenevents.parse_now(now).strftime("%Y-%m-%dT%H:%M")
    days: Dict[str, List[dict]] = {}
    for g in built["groups"]:
        days.setdefault(g["date"], []).append(g)
    written, refused = [], []
    for day, groups in sorted(days.items()):
        path = _digest_path(root, day)
        if path.is_file():
            try:
                existing = load_digest(path)
            except (MessagesError, ValueError) as exc:
                refused.append({"stem": path.stem, "error": str(exc)})
                continue
            data, previous = existing["data"], existing["frontmatter"]
        else:
            data, previous = {"schema": 1, "date": day, "ids": [], "groups": []}, {}
        known_ids = set(data["ids"])
        by_gid = {g["gid"]: g for g in data["groups"]}
        new_messages = 0
        for g in groups:
            fresh = [m["id"] for m in g["messages"] if m["id"] not in known_ids]
            if not fresh:
                continue
            new_messages += len(fresh)
            data["ids"].extend(fresh)
            known_ids.update(fresh)
            points = [p for p in checked.get(g["gid"], {}).get("points", [])
                      if any(c in fresh for c in p["cites"])]
            target = by_gid.get(g["gid"])
            if target is None:
                target = {k: g[k] for k in ("gid", "kind", "label", "chat_type", "people", "names",
                                            "participants", "projects", "projects_weak", "entities")}
                target.update({"needs_owner": False, "points": []})
                data["groups"].append(target)
                by_gid[g["gid"]] = target
            target["points"].extend(points)
            target["needs_owner"] = target["needs_owner"] or bool(checked.get(g["gid"], {}).get("needs_owner"))
        if new_messages == 0 and path.is_file():
            continue
        read = int(previous.get("messages-read") or 0) + new_messages
        skipped = int(previous.get("skipped") or 0) + int(built["skipped"].get(day, 0))
        frontmatter = _frontmatter_for(data, updated_at=updated_at, read=read, skipped=skipped,
                                       at_limit=bool(previous.get("at-limit")) or bool(built["at_limit"]))
        save_digest(root, data, frontmatter)
        written.append(path.stem)
    state = msgstate.advance(root, newest=built["newest"], new_gaps=built["new_gaps"],
                             filled=built["filled"], now=now)
    return {"written": written, "refused": refused, "cursor": state["cursor"]}
```

Note: `markdown.emit_frontmatter` renders lists inline and bools as `true`/`false`; if it refuses an empty list for `projects-weak`, render `[]`. `schema.validate` checks `required` non-empty: `projects` and `people` may be empty lists — if `validate` treats `[]` as "empty required", move `projects` and `people` to `keys_present` in the ontology block (Task A2) instead of `required`, and adjust that test.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_msgdigest.py scripts/tests/test_vaultlib_msgrows.py scripts/tests/test_vaultlib_msgstate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/msgdigest.py scripts/tests/test_vaultlib_msgdigest.py
git commit -m "feat(messages): build, check and write hidden day digests (#236)"
```

### Task A9: Forget, unlink, per-project view

**Files:**
- Modify: `plugin/lib/vaultlib/msgdigest.py`
- Test: `scripts/tests/test_vaultlib_msgdigest.py`

**Interfaces:**
- Produces:
  - `forget_find(root, *, text: Optional[str] = None, exclusion: Optional[dict] = None) -> List[dict]` — matches `{"ref": "<stem>:<gid>:<i>", "digest", "label", "text"}`; `text` matches a point (casefold substring), an exclusion matches whole groups by participant address, domain, chat key or word in label
  - `forget_apply(root, refs: List[str]) -> dict` — removes those points (a group left without points is removed), re-renders, requeues the group's strong projects; `forget_all(root) -> dict` deletes every digest and requeues every project they linked
  - `unlink(root, *, digest: str, gid: str, project: str) -> dict` — removes one project link, re-renders, requeues the project
  - `for_project(root, *, slug: str, digests: List[str]) -> List[dict]` — the strongly linked groups of those digests: `{"digest", "gid", "label", "kind", "people", "points", "link": "[[_messages/<stem>|<d Mon>]]"}`

- [ ] **Step 1: Write the failing tests**

```python
def written_digest(env):
    root, scratch = env
    msgdigest.build(root, str(scratch), consume=False, **KW)
    condense(scratch, [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}])
    msgdigest.check(str(scratch))
    msgdigest.write(root, str(scratch), now="2026-09-30T18:52:00Z")
    return root


def test_forget_finds_then_removes_only_confirmed_points_and_requeues(env):
    root = written_digest(env)
    found = msgdigest.forget_find(root, text="workshop 2")
    assert [f["ref"].split(":")[0] for f in found] == ["2026-09-30-messages"]
    msgdigest.forget_apply(root, [found[0]["ref"]])
    after = msgdigest.load_digest(root / "_messages" / "2026-09-30-messages.md")["data"]
    assert after["groups"] == []
    assert after["ids"] == ["m1", "m2"]  # ids stay, so the message is never fetched back in


def test_forget_by_exclusion_matches_the_person(env):
    root = written_digest(env)
    found = msgdigest.forget_find(root, exclusion={"kind": "person", "value": "jordan.reyes@acme.example"})
    assert len(found) == 1


def test_unlink_removes_one_project_and_requeues_it(env, monkeypatch):
    root = written_digest(env)
    path = root / "_messages" / "2026-09-30-messages.md"
    loaded = msgdigest.load_digest(path)
    loaded["data"]["groups"][0]["projects"] = ["acme-industries-operating-model"]
    msgdigest.save_digest(root, loaded["data"], {**loaded["frontmatter"], "projects": ["acme-industries-operating-model"]})
    gid = loaded["data"]["groups"][0]["gid"]
    msgdigest.unlink(root, digest="2026-09-30-messages", gid=gid, project="acme-industries-operating-model")
    assert msgdigest.load_digest(path)["data"]["groups"][0]["projects"] == []
    assert msgstate.requeue_take(root) == [{"slug": "acme-industries-operating-model", "digest": "2026-09-30-messages"}]


def test_for_project_returns_only_strong_groups(env):
    root = written_digest(env)
    path = root / "_messages" / "2026-09-30-messages.md"
    loaded = msgdigest.load_digest(path)
    loaded["data"]["groups"][0]["projects"] = ["p-strong", "p-weak"]
    loaded["data"]["groups"][0]["projects_weak"] = ["p-weak"]
    msgdigest.save_digest(root, loaded["data"], loaded["frontmatter"])
    assert len(msgdigest.for_project(root, slug="p-strong", digests=["2026-09-30-messages"])) == 1
    assert msgdigest.for_project(root, slug="p-weak", digests=["2026-09-30-messages"]) == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_msgdigest.py -k "forget or unlink or for_project" -q`
Expected: FAIL (`AttributeError`)

- [ ] **Step 3: Implement (append to `msgdigest.py`)**

```python
def _digests(root: Path) -> List[Path]:
    folder = root / vault.MESSAGES_DIR
    return sorted(folder.glob("*-messages.md")) if folder.is_dir() else []


def _resave(root: Path, path: Path, data: dict, frontmatter: dict) -> None:
    fm = {**frontmatter, **{k: v for k, v in _frontmatter_for(
        data, updated_at=frontmatter.get("updated-at") or "", read=int(frontmatter.get("messages-read") or 0),
        skipped=int(frontmatter.get("skipped") or 0), at_limit=bool(frontmatter.get("at-limit"))).items()
        if k in ("projects", "projects-weak", "people", "entities")}}
    save_digest(root, data, fm)


def _matches(group: dict, exclusion: dict) -> bool:
    kind, value = exclusion["kind"], exclusion["value"]
    if kind == "person":
        return value in group["participants"]
    if kind == "domain":
        return any(a.endswith("@" + value) for a in group["participants"])
    if kind == "chat":
        return group.get("key") == f"chat:{value}" or group["gid"] == value
    if kind == "word":
        return bool(re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", group["label"].casefold()))
    return False


def forget_find(root: Path, *, text: Optional[str] = None, exclusion: Optional[dict] = None) -> List[dict]:
    if not text and not exclusion:
        raise MessagesError("forget needs --text or --exclusion")
    needle = str(text or "").casefold().strip()
    found = []
    for path in _digests(root):
        try:
            data = load_digest(path)["data"]
        except MessagesError:
            continue
        for g in data["groups"]:
            whole = exclusion is not None and _matches(g, exclusion)
            for i, point in enumerate(g["points"]):
                if whole or (needle and needle in point["text"].casefold()):
                    found.append({"ref": f"{path.stem}:{g['gid']}:{i}", "digest": path.stem,
                                  "label": g["label"], "text": point["text"]})
    return found


def forget_apply(root: Path, refs: List[str]) -> dict:
    wanted: Dict[str, Dict[str, set]] = {}
    for ref in refs:
        stem, gid, index = ref.split(":")
        wanted.setdefault(stem, {}).setdefault(gid, set()).add(int(index))
    removed = 0
    for stem, by_gid in wanted.items():
        path = root / vault.MESSAGES_DIR / f"{stem}.md"
        loaded = load_digest(path)
        data = loaded["data"]
        for g in data["groups"]:
            drop = by_gid.get(g["gid"], set())
            if drop:
                for slug in g["projects"]:
                    if slug not in g["projects_weak"]:
                        msgstate.requeue_add(root, slug, stem)
                g["points"] = [p for i, p in enumerate(g["points"]) if i not in drop]
                removed += len(drop)
        data["groups"] = [g for g in data["groups"] if g["points"]]
        _resave(root, path, data, loaded["frontmatter"])
    return {"removed": removed}


def forget_all(root: Path) -> dict:
    deleted = []
    for path in _digests(root):
        try:
            data = load_digest(path)["data"]
            for g in data["groups"]:
                for slug in set(g["projects"]) - set(g["projects_weak"]):
                    msgstate.requeue_add(root, slug, path.stem)
        except MessagesError:
            pass
        path.unlink()
        deleted.append(path.stem)
    return {"deleted": deleted}


def unlink(root: Path, *, digest: str, gid: str, project: str) -> dict:
    path = root / vault.MESSAGES_DIR / f"{digest}.md"
    loaded = load_digest(path)
    for g in loaded["data"]["groups"]:
        if g["gid"] == gid and project in g["projects"]:
            g["projects"] = [p for p in g["projects"] if p != project]
            g["projects_weak"] = [p for p in g["projects_weak"] if p != project]
            _resave(root, path, loaded["data"], loaded["frontmatter"])
            msgstate.requeue_add(root, project, digest)
            return {"unlinked": True}
    raise MessagesError(f"no group {gid!r} linked to {project!r} in {digest}")


def for_project(root: Path, *, slug: str, digests: List[str]) -> List[dict]:
    out = []
    for stem in digests:
        path = root / vault.MESSAGES_DIR / f"{stem}.md"
        try:
            data = load_digest(path)["data"]
        except (MessagesError, OSError):
            continue
        for g in data["groups"]:
            if slug in g["projects"] and slug not in g["projects_weak"] and g["points"]:
                out.append({"digest": stem, "gid": g["gid"], "label": g["label"], "kind": g["kind"],
                            "people": g["people"], "points": [p["text"] for p in g["points"]],
                            "link": f"[[{vault.MESSAGES_DIR}/{stem}|{data['date']}]]"})
    return out
```

In `write`, keep `key` on stored groups (add `"key"` to the copied fields) so `_matches` can use chat keys.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_msgdigest.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/msgdigest.py scripts/tests/test_vaultlib_msgdigest.py
git commit -m "feat(messages): forget, unlink and the per-project view (#236)"
```

### Task A10: Keyword proposals, morning-line check, status lines

**Files:**
- Modify: `plugin/lib/vaultlib/msgdigest.py`
- Test: `scripts/tests/test_vaultlib_msgdigest.py`

**Interfaces:**
- Produces:
  - `keywords_propose(root, *, today: str) -> Optional[dict]` — `{"keyword", "project", "count"}` or None; at most one per 7 days (recorded in `msgstate` `proposed`); a word or code recurring in ≥3 unlinked groups' labels over the last 7 digests, co-occurring with exactly one active project's people or entity domain in ≥2 of them, not already a keyword or the name of that project
  - `check_lines(root, lines_path: str) -> dict` — input `{"lines": [{"kind": "needs-you"|"context", "text", "cites": ["<stem>#<gid>"]}]}`; checks each text against the cited groups' points, labels and names; returns `{"passed": [...], "dropped": [...]}`
  - `status(root, *, now: str, first_run_since: Optional[str]) -> List[str]` — CLI-made plain lines: first morning ("From today, this note also covers your mail and Teams."), behind ("I'm N days behind on your mail; I'll catch up tonight." when an open gap is older than 2 nights), closed ("I couldn't catch up on your mail from 3 to 5 October." once per closed gap, then cleared)

- [ ] **Step 1: Write the failing tests**

```python
def test_status_says_behind_only_after_two_nights_and_closed_gaps_once(tmp_path):
    root = make_vault(tmp_path)
    msgstate.advance(root, newest="2026-09-30T18:00:00Z", filled=[], now="2026-09-30T18:50:00Z",
                     new_gaps=[{"source": "inbox", "from": "2026-09-27T00:00:00Z", "to": "2026-09-27T20:00:00Z"}])
    assert msgdigest.status(root, now="2026-09-28T19:00:00Z", first_run_since=None) == []
    lines = msgdigest.status(root, now="2026-09-30T19:00:00Z", first_run_since=None)
    assert lines == ["I'm 3 days behind on your mail; I'll catch up tonight."]
    msgstate.cursor(root, now="2026-10-06T19:00:00Z", timezone="UTC", utc_offset=None)  # closes it
    assert msgdigest.status(root, now="2026-10-06T19:00:00Z", first_run_since=None) == [
        "I couldn't catch up on your mail from 27 September to 27 September."]
    assert msgdigest.status(root, now="2026-10-07T19:00:00Z", first_run_since=None) == []


def test_status_first_morning_line(tmp_path):
    root = make_vault(tmp_path)
    assert msgdigest.status(root, now="2026-09-30T19:00:00Z", first_run_since="2026-09-28T22:00:00Z") == [
        "From today, this note also covers your mail and Teams."]


def test_check_lines_drops_an_unsupported_line(env, tmp_path):
    root = written_digest(env)
    gid = msgdigest.load_digest(root / "_messages" / "2026-09-30-messages.md")["data"]["groups"][0]["gid"]
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps({"lines": [
        {"kind": "context", "text": "Jordan Reyes asks to move workshop 2 to 14 Oct.", "cites": [f"2026-09-30-messages#{gid}"]},
        {"kind": "needs-you", "text": "Priya Nathan waits on you.", "cites": [f"2026-09-30-messages#{gid}"]}]}), encoding="utf-8")
    result = msgdigest.check_lines(root, str(lines))
    assert [l["kind"] for l in result["passed"]] == ["context"]
    assert result["dropped"][0]["text"].startswith("Priya")
```

Keyword proposal test (fixture builds three unlinked digests whose labels carry `P-2317` and whose people are stakeholders of one project):

```python
def test_a_recurring_code_with_one_projects_people_is_proposed_once_a_week(tmp_path):
    root = make_vault(tmp_path)
    from test_vaultlib_msgroute import add_project
    from vaultlib import person
    person.ensure(root, "Sam Lee", "2026-09-01", email="sam.lee@acme.example")
    add_project(root, "acme-industries-rollout", "Rollout", "acme-industries", stakeholders=["sam-lee"])
    for day in ("2026-09-28", "2026-09-29", "2026-09-30"):
        data = {"schema": 1, "date": day, "ids": [day], "groups": [{
            "gid": day[-2:], "key": "mail:x", "kind": "mail", "label": f"Status P-2317 {day}", "chat_type": None,
            "people": ["sam-lee"], "names": {}, "participants": ["sam.lee@acme.example"],
            "projects": [], "projects_weak": [], "entities": [], "needs_owner": False,
            "points": [{"text": "x", "cites": [day]}]}]}
        msgdigest.save_digest(root, data, {"type": "digest", "date": day, "updated-at": f"{day}T18:00",
                                           "projects": [], "people": ["sam-lee"], "messages-read": 1})
    assert msgdigest.keywords_propose(root, today="2026-09-30") == {
        "keyword": "P-2317", "project": "acme-industries-rollout", "count": 3}
    assert msgdigest.keywords_propose(root, today="2026-10-02") is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_msgdigest.py -k "status or check_lines or proposed" -q`
Expected: FAIL (`AttributeError`)

- [ ] **Step 3: Implement (append to `msgdigest.py`)**

```python
_CODE_RE = re.compile(r"\b(?:[A-Z]{1,5}-?\d{2,}|\d{2,}-[A-Z]{1,5})\b")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _day_label(text: str) -> str:
    dt = seenevents.parse_now(text)
    return f"{dt.day} {_MONTHS[dt.month - 1]}"


def status(root: Path, *, now: str, first_run_since: Optional[str]) -> List[str]:
    state = msgstate.load(root)
    now_dt = seenevents.parse_now(now)
    lines = []
    if first_run_since:
        lines.append("From today, this note also covers your mail and Teams.")
    behind = [g for g in state["gaps"] if (now_dt - seenevents.parse_now(g["from"])).days > 2]
    if behind:
        days = max((now_dt - seenevents.parse_now(g["from"])).days for g in behind)
        lines.append(f"I'm {days} days behind on your mail; I'll catch up tonight.")
    for gap in state["closed_unread"]:
        lines.append(f"I couldn't catch up on your mail from {_day_label(gap['from'])} to {_day_label(gap['to'])}.")
    if state["closed_unread"]:
        state["closed_unread"] = []
        msgstate.save(root, state)
    return lines


def check_lines(root: Path, lines_path: str) -> dict:
    payload = _read_json(Path(lines_path), "lines file")
    cache: Dict[str, dict] = {}
    passed, dropped = [], []
    for line in payload.get("lines", []):
        sources = []
        for cite in line.get("cites", []):
            stem, _, gid = str(cite).partition("#")
            if stem not in cache:
                try:
                    cache[stem] = load_digest(root / vault.MESSAGES_DIR / f"{stem}.md")["data"]
                except (MessagesError, OSError):
                    cache[stem] = {"groups": []}
            for g in cache[stem]["groups"]:
                if g["gid"] == gid:
                    sources += [p["text"] for p in g["points"]] + [g["label"]] + [n for n in g["names"].values() if n]
        if line.get("kind") not in ("needs-you", "context") or not sources:
            dropped.append({**line, "reasons": ["cites no digest group"]})
            continue
        missing = discover.unsupported_tokens(str(line.get("text") or ""), sources)
        (dropped.append({**line, "reasons": [f"{t!r} is not in the cited digest" for t in missing]})
         if missing else passed.append({"kind": line["kind"], "text": line["text"].strip()}))
    return {"passed": passed, "dropped": dropped}


def keywords_propose(root: Path, *, today: str) -> Optional[dict]:
    state = msgstate.load(root)
    today_dt = seenevents.parse_now(f"{today}T00:00:00Z")
    if any((today_dt - seenevents.parse_now(f"{p['date']}T00:00:00Z")).days < 7 for p in state["proposed"]):
        return None
    projects = msgroute.active_projects(root)
    taken = {(p["slug"], k.casefold()) for p in projects for k in p["keywords"] + [p["name"]]}
    counts: Dict[str, Dict[str, int]] = {}
    for path in _digests(root)[-7:]:
        try:
            data = load_digest(path)["data"]
        except MessagesError:
            continue
        for g in data["groups"]:
            if g["projects"]:
                continue
            holders = [p["slug"] for p in projects if set(p["people"]) & set(g["people"])]
            for code in set(_CODE_RE.findall(g["label"])):
                bucket = counts.setdefault(code, {"_total": 0})
                bucket["_total"] += 1
                if len(holders) == 1:
                    bucket[holders[0]] = bucket.get(holders[0], 0) + 1
    best = None
    for code, bucket in counts.items():
        total = bucket.pop("_total")
        for slug, hits in bucket.items():
            if total >= 3 and hits >= 2 and (slug, code.casefold()) not in taken:
                if best is None or total > best["count"]:
                    best = {"keyword": code, "project": slug, "count": total}
    if best:
        state["proposed"].append({"keyword": best["keyword"], "project": best["project"], "date": today})
        msgstate.save(root, state)
    return best
```

(The proposal uses codes only, the `_CODE_RE` shape like `P-2317`; ordinary words are left out in v1 to keep proposals precise.)

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_msgdigest.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/msgdigest.py scripts/tests/test_vaultlib_msgdigest.py
git commit -m "feat(messages): status lines, morning-line check, keyword proposals (#236)"
```

### Task A11: CLI group `messages`, version, changelog

**Files:**
- Modify: `plugin/lib/vaultlib/cli.py` (import line ~35; `build_parser`; `_dispatch`; `main` error mapping)
- Modify: `plugin/.claude-plugin/plugin.json` (main+1)
- Test: `scripts/tests/test_vaultlib_cli.py`

**Interfaces:**
- Produces (all with the usual envelope):
  - `messages cursor --vault --now --timezone|--utc-offset [--since]`
  - `messages build --vault --dir --now --timezone|--utc-offset --owner-address A [--owner-address B ...] --since S [--gap ID ...] [--consume]` (exclusions and home domains read from config inside the CLI; `--today` defaults from `--now`)
  - `messages check --dir`
  - `messages write --vault --dir --now`
  - `messages exclude add --vault --kind --value [--label] [--today]` / `remove --vault --id` / `list --vault`
  - `messages forget --vault (--text T | --exclusion ID | --all) [--apply REF ...]` (without `--apply` it only finds; with `--apply` it removes those refs; `--all` deletes every digest)
  - `messages unlink --vault --digest --gid --project`
  - `messages for-project --vault --slug --digests a,b`
  - `messages keywords-propose --vault [--today]`
  - `messages check-lines --vault --lines FILE`
  - `messages status --vault --now [--first-run-since S]`

- [ ] **Step 1: Write the failing CLI tests**

```python
def test_messages_round_trip_through_the_cli(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root, {"timezone": "Europe/Brussels"})
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "msg_inbox.p1.payload.json").write_text(json.dumps({
        "id": "m1", "subject": "Workshop 2 agenda", "sender": "jordan.reyes@acme.example",
        "recipients": ["morgan.ellery@northwind.example"], "receivedDateTime": "2026-09-30T09:00:00Z",
        "summary": "Can we move workshop 2 to 14 Oct?"}), encoding="utf-8")
    code, payload = run(capsys, ["messages", "build", "--vault", str(root), "--dir", str(scratch),
                                 "--now", "2026-09-30T18:47:00Z", "--timezone", "Europe/Brussels",
                                 "--owner-address", "morgan.ellery@northwind.example",
                                 "--since", "2026-09-29T22:00:00Z", "--consume"])
    assert code == 0 and payload["result"]["groups"] == 1
    gid = json.loads((scratch / "msg_groups.payload.json").read_text(encoding="utf-8"))["groups"][0]["gid"]
    (scratch / "msg_condensed.payload.json").write_text(json.dumps({"groups": [{"gid": gid, "needs_owner": False,
        "points": [{"text": "Jordan asks to move workshop 2 to 14 Oct.", "cites": ["m1"]}]}]}), encoding="utf-8")
    assert run(capsys, ["messages", "check", "--dir", str(scratch)])[1]["result"]["passed"] == 1
    code, payload = run(capsys, ["messages", "write", "--vault", str(root), "--dir", str(scratch),
                                 "--now", "2026-09-30T18:52:00Z"])
    assert code == 0 and payload["result"]["written"] == ["2026-09-30-messages"]


def test_messages_errors_stay_inside_the_envelope(capsys, tmp_path):
    root = make_vault(tmp_path)
    code, payload = run(capsys, ["messages", "check", "--dir", str(tmp_path)])
    assert code == 1 and payload["ok"] is False and "msg_groups" in payload["error"] and payload["hint"]


def test_messages_exclude_add_list_remove(capsys, tmp_path):
    root = make_vault(tmp_path)
    write_vault_config(root)
    code, payload = run(capsys, ["messages", "exclude", "add", "--vault", str(root), "--kind", "word",
                                 "--value", "salaris", "--today", "2026-09-30"])
    assert code == 0 and payload["result"]["id"] == "x1"
    assert run(capsys, ["messages", "exclude", "list", "--vault", str(root)])[1]["result"]["exclusions"][0]["value"] == "salaris"
    assert run(capsys, ["messages", "exclude", "remove", "--vault", str(root), "--id", "x1"])[0] == 0
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_cli.py -k messages -q`
Expected: FAIL (argparse `invalid choice: 'messages'`, exit 2)

- [ ] **Step 3: Implement**

Add `msgdigest, msgrows, msgstate` to the `from vaultlib import ...` line. In `build_parser()`:

```python
    messages_group = top.add_parser("messages", help="the nightly mail and Teams feed")
    messages_sub = messages_group.add_subparsers(dest="action", required=True)

    def _tz(parser):
        parser.add_argument("--timezone", help="IANA timezone name")
        parser.add_argument("--utc-offset", dest="utc_offset", help="explicit offset like +02:00")

    m_cursor = messages_sub.add_parser("cursor", help="where tonight's read starts, and open gaps")
    _add_vault_argument(m_cursor)
    m_cursor.add_argument("--now", required=True)
    m_cursor.add_argument("--since", help="an explicit start the owner asked for")
    _tz(m_cursor)

    m_build = messages_sub.add_parser("build", help="page files in --dir into day groups")
    _add_vault_argument(m_build)
    m_build.add_argument("--dir", required=True, help="the session scratch directory (never the vault)")
    m_build.add_argument("--now", required=True)
    m_build.add_argument("--since", required=True)
    m_build.add_argument("--owner-address", dest="owner_address", action="append", required=True)
    m_build.add_argument("--gap", action="append", default=[])
    m_build.add_argument("--consume", action="store_true")
    _tz(m_build)

    m_check = messages_sub.add_parser("check", help="drop condensed points the cited messages do not hold")
    m_check.add_argument("--dir", required=True)

    m_write = messages_sub.add_parser("write", help="merge checked groups into _messages/ and advance the cursor")
    _add_vault_argument(m_write)
    m_write.add_argument("--dir", required=True)
    m_write.add_argument("--now", required=True)

    m_exclude = messages_sub.add_parser("exclude", help="what the feed never reads")
    m_exclude_sub = m_exclude.add_subparsers(dest="exclude_action", required=True)
    m_ex_add = m_exclude_sub.add_parser("add")
    _add_vault_argument(m_ex_add)
    m_ex_add.add_argument("--kind", required=True, choices=list(config.EXCLUSION_KINDS))
    m_ex_add.add_argument("--value", required=True)
    m_ex_add.add_argument("--label")
    m_ex_add.add_argument("--today")
    m_ex_remove = m_exclude_sub.add_parser("remove")
    _add_vault_argument(m_ex_remove)
    m_ex_remove.add_argument("--id", required=True)
    m_ex_list = m_exclude_sub.add_parser("list")
    _add_vault_argument(m_ex_list)

    m_forget = messages_sub.add_parser("forget", help="find, then remove, saved lines")
    _add_vault_argument(m_forget)
    m_forget_target = m_forget.add_mutually_exclusive_group(required=True)
    m_forget_target.add_argument("--text")
    m_forget_target.add_argument("--exclusion", help="an exclusion id")
    m_forget_target.add_argument("--all", action="store_true")
    m_forget.add_argument("--apply", action="append", default=[], help="a ref from the find step")

    m_unlink = messages_sub.add_parser("unlink", help="remove one project link from one group")
    _add_vault_argument(m_unlink)
    for flag in ("--digest", "--gid", "--project"):
        m_unlink.add_argument(flag, required=True)

    m_for_project = messages_sub.add_parser("for-project", help="a project's strongly linked groups")
    _add_vault_argument(m_for_project)
    m_for_project.add_argument("--slug", required=True)
    m_for_project.add_argument("--digests", required=True, help="comma-separated digest stems")

    m_propose = messages_sub.add_parser("keywords-propose", help="at most one keyword proposal a week")
    _add_vault_argument(m_propose)
    m_propose.add_argument("--today")

    m_lines = messages_sub.add_parser("check-lines", help="check the morning block's lines")
    _add_vault_argument(m_lines)
    m_lines.add_argument("--lines", required=True)

    m_status = messages_sub.add_parser("status", help="plain status lines for the morning block")
    _add_vault_argument(m_status)
    m_status.add_argument("--now", required=True)
    m_status.add_argument("--first-run-since", dest="first_run_since")
```

In `_dispatch`:

```python
    if args.group == "messages":
        if args.action == "cursor":
            return _ok(msgstate.cursor(root, now=args.now, timezone=args.timezone,
                                       utc_offset=args.utc_offset, since=args.since))
        if args.action == "build":
            settings = config.messages_settings(root)
            home_domains, _warning = config.m365_home_domains(root)
            return _ok(msgdigest.build(
                root, args.dir, timezone=args.timezone, utc_offset=args.utc_offset,
                owner_addresses=args.owner_address, home_domains=home_domains or [],
                exclusions=settings["exclusions"], today=args.now[:10], since=args.since,
                gap_ids=args.gap, consume=args.consume))
        if args.action == "check":
            return _ok(msgdigest.check(args.dir))
        if args.action == "write":
            return _ok(msgdigest.write(root, args.dir, now=args.now))
        if args.action == "exclude":
            if args.exclude_action == "add":
                return _ok(config.exclusion_add(root, kind=args.kind, value=args.value,
                                                label=args.label, today=vault.today_iso(args.today)))
            if args.exclude_action == "remove":
                return _ok(config.exclusion_remove(root, args.id))
            return _ok({"exclusions": config.messages_settings(root)["exclusions"]})
        if args.action == "forget":
            if args.all:
                return _ok(msgdigest.forget_all(root))
            if args.apply:
                return _ok(msgdigest.forget_apply(root, args.apply))
            exclusion = None
            if args.exclusion:
                matches = [e for e in config.messages_settings(root)["exclusions"] if e["id"] == args.exclusion]
                if not matches:
                    return _fail(f"no exclusion {args.exclusion!r}", "List them with messages exclude list.")
                exclusion = matches[0]
            return _ok({"found": msgdigest.forget_find(root, text=args.text, exclusion=exclusion)})
        if args.action == "unlink":
            return _ok(msgdigest.unlink(root, digest=args.digest, gid=args.gid, project=args.project))
        if args.action == "for-project":
            stems = [s.strip() for s in args.digests.split(",") if s.strip()]
            return _ok({"groups": msgdigest.for_project(root, slug=args.slug, digests=stems)})
        if args.action == "keywords-propose":
            return _ok({"proposal": msgdigest.keywords_propose(root, today=vault.today_iso(args.today))})
        if args.action == "check-lines":
            return _ok(msgdigest.check_lines(root, args.lines))
        if args.action == "status":
            return _ok({"lines": msgdigest.status(root, now=args.now, first_run_since=args.first_run_since)})
```

In `main`, before the `ValueError` backstop:

```python
    except msgrows.MessagesError as exc:
        return _fail(str(exc), "Fix the named file or argument and retry; nothing was written for that step.")
```

`plugin.json`: bump to main+1. No CHANGELOG line (nothing client-visible yet).

- [ ] **Step 4: Run all CI checks**

Run: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`
Expected: PASS

- [ ] **Step 5: Commit, review, PR**

```bash
git add plugin/lib/vaultlib/cli.py plugin/.claude-plugin/plugin.json scripts/tests/test_vaultlib_cli.py
git commit -m "feat(cli): messages group for the nightly feed (#236)"
```

Run `/code-review`, fix findings, open PR A (`feat/messages-core`).

---

## PR B — `feat/messages-structure-v4`

### Task B1: Template — `_messages/`, hide settings, structure 4

**Files:**
- Create: `plugin/template/_messages/.gitkeep`
- Modify: `plugin/template/.obsidian/plugins/notebook-navigator/data.json` (`vaultProfiles[0].hiddenFolders`), `plugin/template/.obsidian/app.json`, `plugin/template/CLAUDE.md:24-38` and its object-model line, `plugin/template/structure-version`, `scripts/validate_template.py:27`
- Test: `scripts/tests/test_validate_template.py` (or the existing template test file)

- [ ] **Step 1: Write the failing test**

```python
def test_template_hides_the_messages_folder():
    template = REPO_ROOT / "plugin" / "template"
    nav = json.loads((template / ".obsidian/plugins/notebook-navigator/data.json").read_text(encoding="utf-8"))
    assert "_messages" in nav["vaultProfiles"][0]["hiddenFolders"]
    app = json.loads((template / ".obsidian/app.json").read_text(encoding="utf-8"))
    assert "_messages/" in app["userIgnoreFilters"]
    assert (template / "_messages" / ".gitkeep").is_file()
    assert (template / "structure-version").read_text(encoding="utf-8").strip() == "4"
```

- [ ] **Step 2: Run it to see it fail**

Run: `python -m pytest scripts/tests/test_validate_template.py -k messages -q`
Expected: FAIL (`KeyError: 'userIgnoreFilters'`)

- [ ] **Step 3: Implement**

- `notebook-navigator/data.json`: `"hiddenFolders": ["_messages"]`.
- `app.json`: `{"attachmentFolderPath": "70-resources/attachments", "alwaysUpdateLinks": true, "userIgnoreFilters": ["_messages/"]}`.
- Template `CLAUDE.md` folder table, after the `_heavy-assets/` row: `` | `_messages/` | Mail and Teams digests — machine material for Claude, hidden; you never need to open them | ``. Object-model line: "Seven object types: **Meeting · Project · Person · Decision · Entity · Daily note · Digest**."
- `structure-version`: `4`. `validate_template.py`: `EXPECTED_STRUCTURE_VERSION = "4"`.

- [ ] **Step 4: Run CI checks and `/visual-check`**

Run: `python scripts/validate_template.py && python -m pytest scripts/tests -q`
Expected: PASS. Then run `/visual-check` on a scratch vault built from the template: `_messages/` must not show in the file list or in search; a link to a digest must open.

- [ ] **Step 5: Commit**

```bash
git add plugin/template scripts/validate_template.py scripts/tests/
git commit -m "feat(template): hidden _messages/ folder, structure-version 4 (#236)"
```

### Task B2: Migration `003-structure-version-4`

**Files:**
- Create: `plugin/migrations/003-structure-version-4/migrate.py`
- Test: `scripts/tests/test_migration_003.py`
- Modify: `plugin/.claude-plugin/plugin.json` (main+2)

**Interfaces:**
- Produces: `TARGET_VERSION = 4`, `LOSSY = None`, `apply(root) -> {"created": bool, "nav": bool, "app": bool}`, `verify(root) -> {"checked": 3}` (raises `RuntimeError` when the folder or either hide entry is missing).

- [ ] **Step 1: Write the failing tests**

```python
"""Migration 003: the hidden _messages/ folder. Made-up vaults only."""
import importlib.util, json
from pathlib import Path
import pytest
from vaultlib import migrate
from test_vaultlib_vault import make_vault

REPO_ROOT = Path(__file__).resolve().parents[2]
M003 = REPO_ROOT / "plugin" / "migrations" / "003-structure-version-4" / "migrate.py"


def load():
    spec = importlib.util.spec_from_file_location("m003", M003)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def obsidian(root, nav_hidden, app_extra):
    nav = root / ".obsidian" / "plugins" / "notebook-navigator" / "data.json"
    nav.parent.mkdir(parents=True)
    nav.write_text(json.dumps({"vaultProfiles": [{"hiddenFolders": nav_hidden}]}), encoding="utf-8")
    (root / ".obsidian" / "app.json").write_text(json.dumps({"alwaysUpdateLinks": True, **app_extra}), encoding="utf-8")


def test_module_contract():
    module = load()
    assert module.TARGET_VERSION == 4 and module.LOSSY is None


def test_apply_merges_into_what_the_owner_already_hid_and_is_idempotent(tmp_path):
    root = make_vault(tmp_path)
    obsidian(root, ["95-private"], {"userIgnoreFilters": ["70-resources/old/"]})
    module = load()
    module.apply(root)
    module.apply(root)
    nav = json.loads((root / ".obsidian/plugins/notebook-navigator/data.json").read_text(encoding="utf-8"))
    app = json.loads((root / ".obsidian/app.json").read_text(encoding="utf-8"))
    assert nav["vaultProfiles"][0]["hiddenFolders"] == ["95-private", "_messages"]
    assert app["userIgnoreFilters"] == ["70-resources/old/", "_messages/"]
    assert (root / "_messages").is_dir()
    assert module.verify(root) == {"checked": 3}


def test_verify_fails_when_the_folder_is_missing(tmp_path):
    root = make_vault(tmp_path)
    obsidian(root, [], {})
    with pytest.raises(RuntimeError):
        load().verify(root)


def test_discover_chains_through_003():
    found = migrate.discover()
    assert [m["module"].TARGET_VERSION for m in found][:3] == [2, 3, 4]
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_migration_003.py -q`
Expected: FAIL (file not found)

- [ ] **Step 3: Implement `plugin/migrations/003-structure-version-4/migrate.py`**

```python
"""Structure version 4: the hidden `_messages/` folder for mail and Teams digests.

Creates `_messages/` and hides it in the file list (Notebook Navigator's
`hiddenFolders`) and in search, graph and quick switcher (Obsidian's
`userIgnoreFilters`). Each list is merged into, never replaced: whatever the
owner already hid stays hidden. Moves nothing, lossless.

Touches two template-managed files (`.obsidian/app.json`,
`.obsidian/plugins/notebook-navigator/data.json`). A later template refresh
ships the same entries, so consenting to it keeps them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from vaultlib import vault  # noqa: E402

TARGET_VERSION = 4
LOSSY = None
_NAV = Path(".obsidian") / "plugins" / "notebook-navigator" / "data.json"
_APP = Path(".obsidian") / "app.json"


def _merge_list(path: Path, getter, entry: str) -> bool:
    if not path.is_file():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    target = getter(data)
    if target is None or entry in target:
        return False
    target.append(entry)
    vault.atomic_write(path, json.dumps(data, indent=2) + "\n")
    return True


def _nav_list(data):
    profiles = data.get("vaultProfiles") or []
    if not profiles:
        return None
    return profiles[0].setdefault("hiddenFolders", [])


def _app_list(data):
    return data.setdefault("userIgnoreFilters", [])


def apply(root: Path) -> dict:
    folder = root / vault.MESSAGES_DIR
    created = not folder.is_dir()
    folder.mkdir(exist_ok=True)
    return {"created": created,
            "nav": _merge_list(root / _NAV, _nav_list, vault.MESSAGES_DIR),
            "app": _merge_list(root / _APP, _app_list, f"{vault.MESSAGES_DIR}/")}


def verify(root: Path) -> dict:
    if not (root / vault.MESSAGES_DIR).is_dir():
        raise RuntimeError(f"{vault.MESSAGES_DIR}/ was not created")
    if (root / _NAV).is_file():
        nav = json.loads((root / _NAV).read_text(encoding="utf-8"))
        if vault.MESSAGES_DIR not in (_nav_list(nav) or []):
            raise RuntimeError("_messages is not hidden in Notebook Navigator")
    if (root / _APP).is_file():
        app = json.loads((root / _APP).read_text(encoding="utf-8"))
        if f"{vault.MESSAGES_DIR}/" not in app.get("userIgnoreFilters", []):
            raise RuntimeError("_messages/ is not excluded from search")
    return {"checked": 3}
```

`plugin.json`: main+2.

- [ ] **Step 4: Run CI checks**

Run: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`
Expected: PASS

- [ ] **Step 5: Commit, review, PR**

```bash
git add plugin/migrations/003-structure-version-4 scripts/tests/test_migration_003.py plugin/.claude-plugin/plugin.json
git commit -m "feat(migrations): 003 creates and hides _messages/ (#236)"
```

`/code-review`, then open PR B.

---

## PR C — `feat/sync-messages-skill`

### Task C1: Worker agent and its contract

**Files:**
- Create: `plugin/agents/sync-messages-worker.md`, `plugin/skills/sync-messages/references/messages-contract.md`
- Test: `scripts/tests/test_skill_contracts.py`

- [ ] **Step 1: Write the failing contract tests**

```python
def read_contract():
    return (REPO_ROOT / "plugin/skills/sync-messages/references/messages-contract.md").read_text(encoding="utf-8")


def test_messages_contract_pins_the_tool_rules():
    text = re.sub(r"\s+", " ", read_contract())
    assert 'chat_message_search' in text and 'query: "*"' in text
    assert "Never pass a date filter to `chat_message_search`" in text
    assert '`folderName` `"Inbox"`' in text and '`folderName` `"Sent Items"`' in text
    assert "Never search mail without `folderName`" in text
    assert "never call `read_resource` on a mail" in text
    assert "at most 5" in text
    assert "20 pages" in text and "8 pages" in text


def test_messages_contract_orders_build_check_write():
    text = read_contract()
    assert text.index("messages build") < text.index("messages check") < text.index("messages write")


def test_messages_worker_agent_definition():
    text = (REPO_ROOT / "plugin/agents/sync-messages-worker.md").read_text(encoding="utf-8")
    front = text.split("---")[1]
    assert "name: sync-messages-worker" in front and "model: sonnet" in front
    assert "tools:" not in front
    disallowed = re.search(r"disallowedTools: (.*)", front).group(1)
    assert {t.strip() for t in disallowed.split(",")} == M365_WORKER_DISALLOWED_TOOLS_SET
    assert "messages contract" in text and "outcome line" in text
```

(`M365_WORKER_DISALLOWED_TOOLS_SET` = the set form of the existing `M365_WORKER_DISALLOWED_TOOLS` constant at `test_skill_contracts.py:31-35`; add it next to that constant.)

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -k messages -q`
Expected: FAIL (files missing)

- [ ] **Step 3: Write the files**

`plugin/agents/sync-messages-worker.md`:

```markdown
---
name: sync-messages-worker
description: Nightly mail and Teams worker, dispatched by /sync-messages with a full briefing. Not for direct invocation — without a briefing it has nothing to act on.
model: sonnet
color: cyan
disallowedTools: Agent, Workflow, WebFetch, WebSearch, NotebookEdit, Skill, SlashCommand, TodoWrite, Artifact, ListAgents, ReportFindings, ShareOnboardingGuide, Monitor, SendMessage, PushNotification, RemoteTrigger, TaskStop, CronCreate, CronDelete, CronList
---

You are the worker for one night of the owner's mail and Teams chat. Your briefing carries the messages contract path, the vault and scratch paths, the CLI path, the timezone, the owner's addresses, where to start reading, and any open gaps to fill.

Read the messages contract file first and follow it exactly. You fetch, the CLI filters and writes; you condense. Never write into the vault yourself. Your entire reply is one outcome line, as the contract defines it — never message content.

Your tool surface stays open because the Microsoft 365 connector's tool names differ per deployment. That is not license to roam: call only the tools the contract names.

If your briefing is missing or names no contract path, reply `fetch-error: dispatched without a briefing` and stop.
```

`plugin/skills/sync-messages/references/messages-contract.md`:

````markdown
# Messages contract

You are dispatched by `/sync-messages` for one night. Inputs in your briefing:
`$VAULT`, `$SCRATCH`, `$VAULTLIB`, `TIMEZONE` (IANA name), `OWNER_ADDRESSES`
(one or more), `SINCE` (UTC ISO), `NOW` (UTC ISO), `GAPS` (a list of
`{id, source, from, to}`, possibly empty).

Every file you write goes to `$SCRATCH` and matches `msg_*.payload.json`; the
skill sweeps them at the end.

## 1. Fetch

Fetch newest first. After each page, write it straight away to scratch, one
JSON object per line, keeping only these keys, values verbatim:

| Source | File | Keys kept |
|---|---|---|
| Teams feed | `msg_teams.p<n>.payload.json` | `id`, `chatId`, `createdDateTime`, `from` (`displayName`, `email`), `summary`, `channelUri` |
| Chat list | `msg_chats.p<n>.payload.json` | `id`, `chatType`, `topic`, `members` (`displayName`, `email`) |
| Inbox | `msg_inbox.p<n>.payload.json` | `id`, `subject`, `sender`, `recipients`, `receivedDateTime`, `summary` |
| Sent Items | `msg_sent.p<n>.payload.json` | the same as Inbox |

`<n>` counts from 1 per source. When you stop a source at its page limit while
the connector still reported more, append one line `{"moreResults": true}` to
that source's last page.

**Teams.** Call `chat_message_search` with `query: "*"`, `limit: 25`, starting at
`offset: 0`, then the returned `nextOffset`. Never pass a date filter to
`chat_message_search`: with one it scans chat by chat and is throttled. Keep
paging while every result on the page is newer than `SINCE`; stop at the first
result at or before `SINCE`, keeping only the newer ones. At most 20 pages.
Then call `teams_list_chats` with `limit: 25`, and page with `nextCursor` until
every `chatId` you saw is resolved or 4 pages are read.

**Mail.** Call `outlook_email_search` with `folderName` `"Inbox"`,
`afterDateTime` = `SINCE`, `order` `"newest"`, `limit: 25`, then the same with
`folderName` `"Sent Items"`. Page with `nextOffset`, at most 8 pages per
folder. Never search mail without `folderName`: the sender degrades and the
recipients disappear. Never call `read_resource` on a mail; the `summary` is
enough.

**Long chat messages.** A Teams `summary` ending in `...` was cut off. For at
most 5 of those per night, the longest first, call `read_resource` on
`teams:///chats/{chatId}/messages/{messageId}` and put the full text in that
row's `summary` before writing the page.

**Gaps.** For each gap in `GAPS`, after the normal fetch: for mail, call the same
search with `afterDateTime` = gap `from` and `beforeDateTime` = gap `to`; for
Teams, keep paging the feed past `SINCE` until you reach the gap's interval,
and only while `offset` stays below 1000. Write these pages as
`msg_<source>.gap<id>.p<n>.payload.json`. The page limits above are shared:
stop a gap when its source's limit is reached.

A tool error: retry once with the same arguments; then leave that source and go
on with the others. Note the source in your outcome line.

## 2. Build

```bash
python3 "$VAULTLIB" messages build --vault "$VAULT" --dir "$SCRATCH" \
  --now "$NOW" --timezone "$TIMEZONE" --since "$SINCE" --consume \
  --owner-address <each address> [--gap <id> ...]
```

Read `ok`. On failure, reply `fetch-error: build: <error>` and stop.

## 3. Condense

Read `$SCRATCH/msg_groups.payload.json`. For each group in `groups`, write 1 to 4
points: what was said, asked, agreed or decided, in the owner's note language,
each a short sentence, "you" meaning the owner. Every point cites the ids of
the messages it rests on. Use only names, numbers, dates and titles that appear
in those messages; write numbers as digits. Set `needs_owner: true` only when a
message asks the owner for something or is waiting on them.

Write `$SCRATCH/msg_condensed.payload.json`:

```json
{"groups": [{"gid": "<gid>", "needs_owner": false,
             "points": [{"text": "<sentence>", "cites": ["<message id>"]}]}]}
```

## 4. Check, then write

```bash
python3 "$VAULTLIB" messages check --dir "$SCRATCH"
python3 "$VAULTLIB" messages write --vault "$VAULT" --dir "$SCRATCH" --now "$NOW"
```

Never rewrite a dropped point to make it pass. A digest in `refused` was edited
by hand: leave it, and name it in your outcome line.

## 5. The outcome line (your entire reply)

| Line | When |
|---|---|
| `written: <n> digests, <m> groups, <d> dropped points[, at-limit][, refused: <stems>][, failed: <sources>]` | `messages write` returned `ok` |
| `nothing-new` | the build found no messages |
| `fetch-error: <what>` | a step failed and nothing was written |
| `auth-error` | the connector refused the account |

Never include message content, names or subjects in the outcome line.
````

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -k messages -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/agents/sync-messages-worker.md plugin/skills/sync-messages/references/messages-contract.md scripts/tests/test_skill_contracts.py
git commit -m "feat(sync-messages): worker agent and messages contract (#236)"
```

### Task C2: The `/sync-messages` skill

**Files:**
- Create: `plugin/skills/sync-messages/SKILL.md`
- Modify: `scripts/tests/test_skill_contracts.py` (`NET_NEW` gains `"sync-messages"`; `test_expected_skills_exist` set gains it; new tests)

- [ ] **Step 1: Write the failing tests**

```python
def test_sync_messages_asks_consent_with_the_honest_text():
    text = re.sub(r"\s+", " ", read_skill("sync-messages"))
    assert "save short notes on what was said" in text
    assert "they include what other people wrote to you" in text
    assert "stop and delete everything" in text


def test_sync_messages_checks_everything_before_dispatch():
    text = read_skill("sync-messages")
    dispatch = text.index("second-brain:sync-messages-worker")
    assert text.index("config verify-account --adapter m365") < dispatch
    assert text.index("messages cursor") < dispatch


def test_sync_messages_never_writes_without_the_owner_on_removals():
    flat = re.sub(r"\s+", " ", read_skill("sync-messages"))
    assert "messages forget" in flat and "--apply" in flat
    assert "Shall I keep what I saved so far, or delete it?" in flat


def test_sync_messages_unattended_mode_never_asks():
    unattended = read_skill("sync-messages").split("## Unattended mode")[1]
    assert "never ask" in unattended.lower()
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -k sync_messages -q`
Expected: FAIL (skill missing)

- [ ] **Step 3: Write `plugin/skills/sync-messages/SKILL.md`**

````markdown
---
name: sync-messages
description: Read the owner's Outlook mail and Teams chats into hidden day digests, and handle switching the feed on or off, exclusions, forgetting and corrections. Triggers when /evening-sync runs its stage 3b, when the user invokes /sync-messages, or asks to start or stop reading their mail and Teams, to skip or forget someone or something, to link a code to a project, or to catch up on mail.
user_invocable: true
origin: net-new
---

# Sync Messages

Keeps the second brain aware of what happens in mail and Teams chat, so a
session already knows. The owner reads mail in Outlook and chat in Teams; they
meet the result, not the digests (`_messages/`, hidden).

## Requirements

Writing to the vault needs a shell, so this skill runs in **Cowork** or
**Claude Code**. It cannot run in Chat.

```bash
VAULTLIB="${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py"
```

Read `ok` on every call; on failure surface `error` and `hint`.

## Speaking to the owner

Plain words, no internal terms: "your mail and Teams", "what I saved", never
"digest", "group", "cursor" or "exclusion". Read back every change in one
sentence.

## Switching on

Only with Microsoft 365 connected and its account proven
(`config verify-account --adapter m365` returns `match: true`).

1. Ask, verbatim: *"Each evening I can look through your inbox, your sent mail
   and your Teams chats (not Teams channels, not attachments). I read the
   opening lines of each mail and your chat messages, and save short notes on
   what was said in your second brain, which only you can see. I keep them like
   your meeting notes; they include what other people wrote to you. You can
   tell me at any time to skip a person, a company or a topic, or to stop and
   delete everything. Shall I start?"* No is a complete answer: change nothing
   and do not ask again this session.
2. On yes:
   ```bash
   python3 "$VAULTLIB" config write --vault "$VAULT" --field messages.enabled --value true
   python3 "$VAULTLIB" config write --vault "$VAULT" --field messages.consented-at --value "<now, YYYY-MM-DDTHH:MM local>"
   python3 "$VAULTLIB" config write --vault "$VAULT" --field messages.scope --value "teams-chats,inbox,sent-items"
   ```
3. Ask: *"Is there anyone or anything I should never read? For example HR
   matters or a private chat. You can also tell me later."* For each answer,
   add an exclusion (below). No answer means none.
4. Read back: *"From tonight I'll read your mail and Teams, starting with
   today's messages."* plus one sentence per exclusion.

## Switching off

Ask: *"Shall I keep what I saved so far, or delete it?"* Then:

```bash
python3 "$VAULTLIB" config write --vault "$VAULT" --field messages.enabled --value false
python3 "$VAULTLIB" messages forget --vault "$VAULT" --all   # only if they said delete
```

Read back what happened.

## What the owner can ask

| They say | Do |
|---|---|
| "don't read X anymore" | `messages exclude add --kind person\|domain\|chat\|word --value … --label …`; read back what is skipped (a person: their mail and your 1:1 chat; in group chats only their own messages). Then `messages forget --exclusion <id>` and offer what it found: *"I found N older notes about X. Shall I remove those lines?"* Only on yes: `messages forget --apply <ref> …` |
| "forget what you saved about X" | `messages forget --text "X"`; show the found lines in plain words; on yes `--apply` exactly those refs |
| "link P-2317 to <project>", or yes to the weekly proposal | `project keywords add --slug <slug> --keyword "P-2317"`; read back |
| "that mail isn't about <project>" | find the group with `messages for-project --slug <slug> --digests <recent stems>`; `messages unlink --digest … --gid … --project <slug>`; read back that tonight's update drops it |
| "catch up on my mail from last week" | run the workflow below with `--since <start>` on `messages cursor` |
| about mail from before switching on, or from someone excluded | say plainly you have not read it and why; offer a live search in Outlook |
| "what don't you read?" | `messages exclude list`, plus the fixed scope: channels and attachments are never read |

## Workflow (one run)

1. **Preflight.** `config read`: stop with one line if `messages.enabled` is
   false, M365 is disabled, or `timezone`/`owner` are missing. Run
   `config verify-account --adapter m365`; stop on anything but `match: true`.
   Collect the owner's addresses: the m365 `account_hint`, and from `get_me`
   its `mail` and `userPrincipalName`.
2. **Where to start.**
   ```bash
   python3 "$VAULTLIB" messages cursor --vault "$VAULT" --now "<now UTC>" --timezone "<timezone>" [--since "<owner's start>"]
   ```
   Keep `since`, `first_run` and `gaps`.
3. **Dispatch the worker**, blocking, one call:
   `subagent_type: second-brain:sync-messages-worker`. Pass paths and values,
   never content: the contract path
   `${CLAUDE_PLUGIN_ROOT}/skills/sync-messages/references/messages-contract.md`,
   `$VAULT`, `$SCRATCH`, `$VAULTLIB`, `TIMEZONE`, `OWNER_ADDRESSES`, `SINCE`,
   `NOW`, `GAPS`. You read neither the contract nor the worker's files yourself.
4. **Record the outcome line** for the evening summary. Under `/evening-sync`,
   hand back: the outcome line and, when `first_run` was true, `since` (stage 6
   passes it to `messages status --first-run-since`).
5. **Scratch hygiene.** `scratch sweep --dir "$SCRATCH"`.

## Unattended mode

Under `/evening-sync` unattended: never ask a question, never switch on or
off, never add or remove an exclusion, never forget anything. Run the workflow
and report. A failed run moves nothing: the next run starts from the same
place.

## Hard rules

1. Nothing is read before the owner's yes to the consent question.
2. Every vault write goes through `$VAULTLIB`.
3. Nothing is removed without the owner's yes to the exact lines found.
4. Message content never appears in the main conversation, the run log or a
   summary line.
````

- [ ] **Step 4: Run lint and tests**

Run: `python scripts/lint_plugin.py && python -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: PASS (the lint checks frontmatter and that every backticked `/command` exists; `test_every_cli_invocation_named_by_a_skill_exists` checks every `"$VAULTLIB" <group> <action>`)

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/sync-messages/SKILL.md scripts/tests/test_skill_contracts.py
git commit -m "feat(sync-messages): the skill — consent, requests, one run (#236)"
```

### Task C3: `/evening-sync` stage 3b

**Files:**
- Modify: `plugin/skills/evening-sync/SKILL.md` (after the Refresh paragraph of Stage 3, ~line 156; summary template ~510-520; scratch hygiene ~524-531)
- Test: `scripts/tests/test_skill_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_evening_sync_runs_messages_between_sync_and_project_updates():
    text = read_skill("evening-sync")
    stage3, stage4 = text.index("## Stage 3"), text.index("## Stage 4")
    marker = text.index("### Stage 3b — Mail and Teams")
    assert stage3 < marker < stage4
    assert text.index("skills/sync-messages/SKILL.md") > stage3
    assert text.index("sync update-queue") > marker, "the queue must see tonight's digests"
```

- [ ] **Step 2: Run it to see it fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -k evening_sync_runs_messages -q`
Expected: FAIL (`ValueError: substring not found`)

- [ ] **Step 3: Edit the skill**

Move the **Refresh** paragraph (`sync reconcile-reviews` + `sync update-queue`) to after the new subsection, and insert before it:

```markdown
### Stage 3b — Mail and Teams

When `messages.enabled` is true in `config read`: run the `/sync-messages`
workflow (follow `${CLAUDE_PLUGIN_ROOT}/skills/sync-messages/SKILL.md`),
unattended when this run is unattended. Record its outcome line for the
summary, and `since` when it reports a first run (stage 6 needs it). It runs
before the refresh below so tonight's update queue sees tonight's digests. A
failed stage 3b is recorded and the evening continues. Off, or no M365: skip
with one line in the summary.
```

Summary template gains `- Mail and Teams: <outcome line, or "off">`. Scratch hygiene: `msg_*.payload.json` is already covered by `*.payload.json`; add it to the prose list.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/evening-sync/SKILL.md scripts/tests/test_skill_contracts.py
git commit -m "feat(evening-sync): stage 3b runs the mail and Teams feed (#236)"
```

### Task C4: Switching on in `/setup-my-brain`

**Files:**
- Modify: `plugin/skills/setup-my-brain/SKILL.md` (new `### Mail and Teams every evening` at the end of Step 1, after the M365 account proof ~line 244; hard rule 9 ~line 628)
- Modify: `plugin/.claude-plugin/plugin.json` (main+3), `CHANGELOG.md`
- Test: `scripts/tests/test_skill_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_setup_offers_the_feed_after_the_account_proof_and_scopes_rule_9():
    text = read_skill("setup-my-brain")
    proof = text.index("config verify-account --adapter m365")
    offer = text.index("### Mail and Teams every evening")
    assert proof < offer < text.index("## Step 2")
    assert "skills/sync-messages/SKILL.md" in text[offer:text.index("## Step 2")]
    rules = text.split("## Hard rules")[1]
    assert "During the step-3 read" in rules
```

- [ ] **Step 2: Run it to see it fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -k setup_offers_the_feed -q`
Expected: FAIL

- [ ] **Step 3: Edit the skill**

At the end of Step 1, after the Microsoft 365 account proof:

```markdown
### Mail and Teams every evening

Only when Microsoft 365 is connected and proven. Follow **Switching on** in
`${CLAUDE_PLUGIN_ROOT}/skills/sync-messages/SKILL.md` exactly: its consent
question, its one exclusions question, its read-back. This is separate from the
5-minute read of step 3, which has its own consent. A no changes nothing here.
```

Hard rule 9 becomes: "**During the step-3 read**, chat message text is never read, and neither is the Inbox. The nightly mail and Teams feed is a separate feature with its own consent (step 1)."

`plugin.json`: main+3. `CHANGELOG.md` under `## Unreleased`:

```markdown
- Your second brain can now keep up with your mail and Teams chats. Switch it on during setup or by asking ("start reading my mail and Teams"): each evening it saves short notes on what was said, so your projects and sessions already know. Channels and attachments are never read, you can tell it to skip anyone or anything, and you can stop and delete everything at any time. (#PR)
```

- [ ] **Step 4: Run CI checks**

Run: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`
Expected: PASS

- [ ] **Step 5: Commit, review, PR**

```bash
git add plugin/skills/setup-my-brain/SKILL.md plugin/.claude-plugin/plugin.json CHANGELOG.md scripts/tests/test_skill_contracts.py
git commit -m "feat(setup-my-brain): offer the mail and Teams feed after the account proof (#236)"
```

`/code-review`, then open PR C.

---

## PR D — `feat/messages-downstream`

### Task D1: Update queue — digests as activity, requeue, person counters

**Files:**
- Modify: `plugin/lib/vaultlib/updatequeue.py` (`run`, ~:234-381; new `_index_digests`)
- Test: `scripts/tests/test_vaultlib_updatequeue.py`

**Interfaces:**
- Consumes: `msgdigest.load_digest`, `msgstate.requeue_take`.
- Produces: queue entries gain `newDigests: [stems]` and `removedSources: [stems]`; a project with only digest activity is queued; `newCount` counts meetings plus digests; people gain `messages-7d` / `messages-30d` (groups the person is linked in, digests dated after d7 / d30).

- [ ] **Step 1: Write the failing tests**

```python
def digest(root, day, groups, updated_at):
    from vaultlib import msgdigest
    data = {"schema": 1, "date": day, "ids": [g["gid"] for g in groups], "groups": groups}
    projects = sorted({p for g in groups for p in g["projects"]})
    weak = sorted({p for g in groups for p in g["projects_weak"]})
    msgdigest.save_digest(root, data, {"type": "digest", "date": day, "updated-at": updated_at,
        "projects": projects, "projects-weak": weak,
        "people": sorted({p for g in groups for p in g["people"]}), "messages-read": len(groups)})


def g(gid, projects=(), weak=(), people=()):
    return {"gid": gid, "key": f"mail:{gid}", "kind": "mail", "label": gid, "chat_type": None,
            "people": list(people), "names": {}, "participants": [], "projects": list(projects),
            "projects_weak": list(weak), "entities": [], "needs_owner": False,
            "points": [{"text": "x", "cites": [gid]}]}


def test_a_strong_digest_after_state_updated_queues_the_project(tmp_path):
    root = vault_with_project_and_owner(tmp_path, slug="acme-industries-rollout", state_updated="2026-09-29T19:00")
    digest(root, "2026-09-30", [g("a1", projects=["acme-industries-rollout"])], "2026-09-30T18:52")
    queue = updatequeue.run(root, "2026-09-30", "morgan-ellery")["projectsNeedingUpdate"]
    assert queue[0]["slug"] == "acme-industries-rollout" and queue[0]["newDigests"] == ["2026-09-30-messages"]


def test_a_weak_digest_never_queues(tmp_path):
    root = vault_with_project_and_owner(tmp_path, slug="acme-industries-rollout", state_updated="2026-09-29T19:00")
    digest(root, "2026-09-30", [g("a1", projects=["acme-industries-rollout"], weak=["acme-industries-rollout"])], "2026-09-30T18:52")
    assert updatequeue.run(root, "2026-09-30", "morgan-ellery")["projectsNeedingUpdate"] == []


def test_a_requeued_project_carries_the_removed_source_once(tmp_path):
    from vaultlib import msgstate
    root = vault_with_project_and_owner(tmp_path, slug="acme-industries-rollout", state_updated="2026-10-01T19:00")
    msgstate.requeue_add(root, "acme-industries-rollout", "2026-09-30-messages")
    first = updatequeue.run(root, "2026-10-01", "morgan-ellery")["projectsNeedingUpdate"]
    assert first[0]["removedSources"] == ["2026-09-30-messages"]
    assert updatequeue.run(root, "2026-10-01", "morgan-ellery")["projectsNeedingUpdate"] == []


def test_people_get_message_counters(tmp_path):
    root = vault_with_project_and_owner(tmp_path, slug="acme-industries-rollout", state_updated="2026-09-29T19:00")
    person.ensure(root, "Sam Lee", "2026-09-01")
    digest(root, "2026-09-30", [g("a1", people=["sam-lee"]), g("a2", people=["sam-lee"])], "2026-09-30T18:52")
    digest(root, "2026-09-10", [g("b1", people=["sam-lee"])], "2026-09-10T18:52")
    updatequeue.run(root, "2026-09-30", "morgan-ellery")
    fm, _ = markdown.split_frontmatter((root / "50-people" / "sam-lee.md").read_text(encoding="utf-8"))
    assert (fm["messages-7d"], fm["messages-30d"]) == (2, 3)
```

(`vault_with_project_and_owner` is a helper to add to this test file: `make_vault`, an owner person note `morgan-ellery`, one active project with the given `state-updated`. Reuse the file's existing builders where they cover this.)

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_updatequeue.py -k "digest or requeue or message_counters" -q`
Expected: FAIL (`KeyError: 'newDigests'`)

- [ ] **Step 3: Implement**

Add to `updatequeue.py`:

```python
from . import msgdigest, msgstate


def _index_digests(root: Path) -> Tuple[List[dict], List[str]]:
    out, warnings = [], []
    folder = root / vault.MESSAGES_DIR
    for path in sorted(folder.glob("*-messages.md")) if folder.is_dir() else []:
        try:
            loaded = msgdigest.load_digest(path)
        except (msgdigest.MessagesError, ValueError, OSError) as exc:
            warnings.append(f"{vault.MESSAGES_DIR}/{path.name}: {exc}")
            continue
        fm, data = loaded["frontmatter"], loaded["data"]
        strong = [p for p in _slug_list(fm.get("projects"), "projects", path.name, warnings)
                  if p not in _slug_list(fm.get("projects-weak"), "projects-weak", path.name, warnings)]
        out.append({"stem": path.stem, "date": _parse_first_iso_date(fm.get("date")),
                    "updated": _parse_iso_datetime(fm.get("updated-at")), "strong": strong,
                    "people_groups": [p for g in data["groups"] for p in g["people"]]})
    return out, warnings
```

In `run`, after `meetings, warnings = _index_meetings(root)`:

```python
    digests, digest_warnings = _index_digests(root)
    warnings.extend(digest_warnings)
    requeued: Dict[str, List[str]] = {}
    for entry in msgstate.requeue_take(root):
        requeued.setdefault(entry["slug"], []).append(entry["digest"])
```

In the per-project loop, replace the `new_meetings` / append block with:

```python
        new_meetings = [m for m in for_project if _activity(m) >= threshold]
        new_digests = [d["stem"] for d in digests
                       if slug in d["strong"] and d["updated"] is not None and d["updated"] >= threshold]
        removed = requeued.get(slug, [])
        if new_meetings or new_digests or removed:
            queue.append({
                ...existing keys...,
                "newCount": len(new_meetings) + len(new_digests),
                "newFiles": [m["file"] for m in new_meetings],
                "newDigests": new_digests,
                "removedSources": removed,
            })
```

In the people loop, add:

```python
        msg7 = sum(d["people_groups"].count(slug) for d in digests if d["date"] and d["date"] > d7)
        msg30 = sum(d["people_groups"].count(slug) for d in digests if d["date"] and d["date"] > d30)
        updated = _upsert_all(text, {"meetings-7d": str(m7), "meetings-30d": str(m30),
                                     "messages-7d": str(msg7), "messages-30d": str(msg30)})
```

The self-check stays meetings-only.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_updatequeue.py -q`
Expected: PASS (re-run once if the known Windows `PermissionError` flake appears)

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/updatequeue.py scripts/tests/test_vaultlib_updatequeue.py
git commit -m "feat(update-queue): strong digests queue projects; person message counters (#236)"
```

### Task D2: Stage 4 reads digests and captures their decisions

**Files:**
- Modify: `plugin/skills/evening-sync/SKILL.md` (Stage 4 instructions, ~:192-246)
- Test: `scripts/tests/test_skill_contracts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_stage4_reads_digests_marks_their_items_and_captures_decisions():
    stage4 = read_skill("evening-sync").split("## Stage 4")[1].split("## Stage 5")[0]
    flat = re.sub(r"\s+", " ", stage4)
    assert "messages for-project" in flat and "newDigests" in flat
    assert "(mail ·" in flat or "(chat ·" in flat
    assert "removedSources" in flat
    assert flat.index("messages for-project") < flat.index("log-decision")
```

- [ ] **Step 2: Run it to see it fail**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -k stage4_reads_digests -q`
Expected: FAIL

- [ ] **Step 3: Edit the Stage 4 instructions**

Step 1 of the subagent instructions gains:

```markdown
   When the entry has `newDigests`, also run
   `python3 "$VAULTLIB" messages for-project --vault "$VAULT" --slug <slug> --digests <comma-separated newDigests>`
   and read the returned groups as input next to the meetings. Every state item
   you take from one (a Hot potato, an Owe, an Awaiting, a closed action) ends
   with its source marker, `(mail · <link>)` or `(chat · <link>)`, where
   `<link>` is the group's `link` verbatim. When the entry has
   `removedSources`, drop every current item whose marker links one of those
   digests unless a meeting or a remaining group still supports it.
```

Step 4 (decision capture) becomes: "extract candidates from the new meetings, the harvest jottings AND the digest groups read in step 1, then follow `…/log-decision/SKILL.md` in **background mode** … A decision from a digest group carries `source: <digest stem>`." The rest of step 4 is unchanged.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_skill_contracts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/evening-sync/SKILL.md scripts/tests/test_skill_contracts.py
git commit -m "feat(evening-sync): stage 4 reads digests, marks sources, captures decisions (#236)"
```

### Task D3: The *Mail and Teams* block in the daily note

**Files:**
- Modify: `plugin/lib/vaultlib/recap.py` (`_ALLOWED`, `validate`, `render`), `plugin/lib/vaultlib/dailynote.py` (`_fingerprint_inputs`)
- Modify: `plugin/skills/evening-sync/SKILL.md` (Stage 6 field list ~:397-416 and example ~:438-466)
- Test: `scripts/tests/test_vaultlib_recap.py`, `scripts/tests/test_vaultlib_dailynote.py`, `scripts/tests/test_skill_contracts.py`

**Interfaces:**
- Produces: recap field `messages`: `{"items": [{"kind": "needs-you"|"context", "text"}], "status": [lines], "decisions_to_confirm": int, "keyword_proposal": {"keyword", "project"} | null}`; at most 5 items (≤30 words each), at most 3 status lines (≤40 words). Rendered as `> [!info] Mail and Teams` right after *At a glance*, needs-you first.

- [ ] **Step 1: Write the failing tests**

```python
def test_messages_block_renders_needs_you_first_with_the_pointers(tmp_path):
    root = make_vault(tmp_path)
    clean, offenders, _ = recap.validate(root, {**MINIMAL_RECAP, "messages": {
        "items": [{"kind": "context", "text": "Operating model: workshop 2 moves to 14 Oct."},
                  {"kind": "needs-you", "text": "Sam is waiting for your budget figures."}],
        "status": ["From today, this note also covers your mail and Teams."],
        "decisions_to_confirm": 1, "keyword_proposal": None}})
    assert offenders == []
    out = recap.render(root, clean, meetings=0, window_label="today")
    block = out.split("> [!info] Mail and Teams")[1].split("\n\n")[0]
    lines = [l for l in block.splitlines() if l.startswith("> - ")]
    assert lines[0] == "> - **Needs you:** Sam is waiting for your budget figures."
    assert lines[1] == "> - Operating model: workshop 2 moves to 14 Oct."
    assert "1 decision from mail to confirm" in block
    assert out.index("At a glance") < out.index("Mail and Teams") < out.index("Themes")


def test_messages_block_refuses_more_than_five_items(tmp_path):
    root = make_vault(tmp_path)
    with pytest.raises(recap.RecapError, match="messages.items"):
        recap.validate(root, {**MINIMAL_RECAP, "messages": {
            "items": [{"kind": "context", "text": "x"}] * 6, "status": [],
            "decisions_to_confirm": 0, "keyword_proposal": None}})


def test_no_messages_field_renders_no_block(tmp_path):
    root = make_vault(tmp_path)
    clean, _, _ = recap.validate(root, MINIMAL_RECAP)
    assert "Mail and Teams" not in recap.render(root, clean, meetings=0, window_label="today")
```

(`MINIMAL_RECAP` = the smallest valid v2 recap already used in `test_vaultlib_recap.py`; reuse its fixture.)

In `test_vaultlib_dailynote.py`:

```python
def test_a_digest_in_the_window_feeds_the_fingerprint(tmp_path):
    root = make_vault(tmp_path)
    (root / "_messages").mkdir()
    (root / "_messages" / "2026-09-30-messages.md").write_text("---\ntype: digest\n---\n", encoding="utf-8")
    names = [n for n, _ in dailynote._fingerprint_inputs(root, date(2026, 9, 30), date(2026, 9, 30))]
    assert "_messages/2026-09-30-messages.md" in names
```

- [ ] **Step 2: Run them to see them fail**

Run: `python -m pytest scripts/tests/test_vaultlib_recap.py scripts/tests/test_vaultlib_dailynote.py -k "messages or digest" -q`
Expected: FAIL (`recap: unknown key(s) ['messages']`)

- [ ] **Step 3: Implement**

`recap.py`: add `"messages"` to `_ALLOWED`. In `validate`, before building `clean`:

```python
    messages_raw = raw.get("messages")
    messages = None
    if messages_raw is not None:
        if not isinstance(messages_raw, dict) or set(messages_raw) != {
                "items", "status", "decisions_to_confirm", "keyword_proposal"}:
            raise RecapError("recap.messages needs exactly items, status, decisions_to_confirm, keyword_proposal")
        items = messages_raw["items"]
        if not isinstance(items, list) or len(items) > 5:
            raise RecapError("recap.messages.items: at most 5")
        clean_items = []
        for i, item in enumerate(items):
            if not isinstance(item, dict) or set(item) != {"kind", "text"} or item["kind"] not in ("needs-you", "context"):
                raise RecapError(f"recap.messages.items[{i}] needs kind (needs-you|context) and text")
            text = _one_line(item["text"], f"recap.messages.items[{i}].text", 30)
            clean_items.append({"kind": item["kind"],
                                "text": _norm(root, text, f"recap.messages.items[{i}]", offenders, warnings)})
        status_lines = _lines(messages_raw["status"], "recap.messages.status")
        if len(status_lines) > 3:
            raise RecapError("recap.messages.status: at most 3")
        count = messages_raw["decisions_to_confirm"]
        if not isinstance(count, int) or count < 0:
            raise RecapError("recap.messages.decisions_to_confirm must be a non-negative integer")
        proposal = messages_raw["keyword_proposal"]
        if proposal is not None:
            if not isinstance(proposal, dict) or set(proposal) != {"keyword", "project"}:
                raise RecapError("recap.messages.keyword_proposal needs keyword and project")
            link = _identity_link(root, "project", str(proposal["project"]),
                                  "recap.messages.keyword_proposal", offenders, warnings)
            proposal = {"keyword": _one_line(proposal["keyword"], "keyword", 3), "project": link}
        clean_items.sort(key=lambda it: it["kind"] != "needs-you")
        messages = {"items": clean_items, "status": status_lines,
                    "decisions_to_confirm": count, "keyword_proposal": proposal}
```

Add `"messages": messages` to `clean`. In `render`, right after the glance part:

```python
    if clean.get("messages") and (clean["messages"]["items"] or clean["messages"]["status"]
                                  or clean["messages"]["decisions_to_confirm"]
                                  or clean["messages"]["keyword_proposal"]):
        m = clean["messages"]
        lines = ["> [!info] Mail and Teams"]
        lines += [f"> - **Needs you:** {it['text']}" if it["kind"] == "needs-you" else f"> - {it['text']}"
                  for it in m["items"]]
        if m["decisions_to_confirm"]:
            noun = _plural(m["decisions_to_confirm"], "decision")
            lines.append(f"> - **{noun} from mail to confirm** → [[Decisions.base#Needs review]]")
        if m["keyword_proposal"] and m["keyword_proposal"]["project"]:
            p = m["keyword_proposal"]
            lines.append(f"> - Mails about '{p['keyword']}' seem to be about {p['project']}. "
                         f"Say 'link {p['keyword']}' to me and I'll link them from now on.")
        lines += [f"> - {line}" for line in m["status"]]
        parts.append("\n".join(lines))
```

`dailynote._fingerprint_inputs`, before `return found`:

```python
    digests = root / vault.MESSAGES_DIR
    for path in sorted(digests.glob("*-messages.md")) if digests.is_dir() else []:
        noted = _iso_prefix_date(path.stem)
        if noted is not None and start <= noted <= end:
            found.append((f"{vault.MESSAGES_DIR}/{path.name}", path))
```

Stage 6 prose (field list), add:

```markdown
- `messages` — only when stage 3b ran. Build it in this order:
  1. `python3 "$VAULTLIB" messages status --vault "$VAULT" --now <now UTC> [--first-run-since <since from stage 3b>]` → `status` (use the lines verbatim).
  2. `python3 "$VAULTLIB" messages keywords-propose --vault "$VAULT" --today <today>` → `keyword_proposal` (the result's `proposal` without `count`, or null).
  3. `decisions_to_confirm` — the number of decisions stage 4 wrote with a digest `source`.
  4. `items` — at most 5 lines from tonight's digests: first what needs the owner (groups with **Needs you**), each with one concrete action; then one context line per project. Write them to `$SCRATCH/msg_lines.payload.json` as `{"lines": [{"kind", "text", "cites": ["<digest stem>#<gid>"]}]}`, run `python3 "$VAULTLIB" messages check-lines --vault "$VAULT" --lines "$SCRATCH/msg_lines.payload.json"`, and use only `passed`. No counts, no internal terms.
```

and add the field to the payload example.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest scripts/tests/test_vaultlib_recap.py scripts/tests/test_vaultlib_dailynote.py scripts/tests/test_skill_contracts.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add plugin/lib/vaultlib/recap.py plugin/lib/vaultlib/dailynote.py plugin/skills/evening-sync/SKILL.md scripts/tests/
git commit -m "feat(daily-note): the Mail and Teams block (#236)"
```

### Task D4: Health — days that hit the limit

**Files:**
- Modify: `plugin/lib/vaultlib/health.py` (`report`, `render`), `plugin/skills/health-check/SKILL.md` (§2)
- Modify: `plugin/.claude-plugin/plugin.json` (main+4), `CHANGELOG.md`
- Test: `scripts/tests/test_vaultlib_health.py`

- [ ] **Step 1: Write the failing test**

```python
def test_health_counts_digests_and_days_at_the_limit(tmp_path):
    root = make_vault(tmp_path)
    folder = root / "_messages"
    folder.mkdir()
    for day, limit in (("2026-09-29", "false"), ("2026-09-30", "true"), ("2026-08-01", "true")):
        (folder / f"{day}-messages.md").write_text(
            f"---\ntype: digest\ndate: {day}\nat-limit: {limit}\n---\n", encoding="utf-8")
    block = health.report(root, "2026-09-30", window=28)["messages"]
    assert block["digests_in_window"] == 2 and block["days_at_limit"] == 1
    assert "days at the limit" in health.render(health.report(root, "2026-09-30", window=28))
```

- [ ] **Step 2: Run it to see it fail**

Run: `python -m pytest scripts/tests/test_vaultlib_health.py -k days_at_the_limit -q`
Expected: FAIL (`KeyError: 'messages'`)

- [ ] **Step 3: Implement**

```python
def _messages_block(root: Path, start: date, end: date, unparsed) -> dict:
    enabled = bool(config.messages_settings(root).get("enabled"))
    in_window, at_limit = 0, 0
    folder = root / vault.MESSAGES_DIR
    for path in sorted(folder.glob("*-messages.md")) if folder.is_dir() else []:
        try:
            fm, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
            day = date.fromisoformat(str(fm.get("date")))
        except (ValueError, OSError):
            unparsed.add()
            continue
        if start <= day <= end:
            in_window += 1
            at_limit += 1 if fm.get("at-limit") is True else 0
    return {"enabled": enabled, "digests_in_window": in_window, "days_at_limit": at_limit}
```

Add `"messages": _messages_block(root, window_start, today_date, unparsed)` to `result` (use the module's existing `_Counter` method name for `unparsed`; if it is not `add()`, call the one the other blocks use). In `render`, a section `## Mail and Teams` with rows `("feed on", …)`, `("digests in window", …)`, `("days at the limit", …)`. Health-check SKILL §2: read out "days at the limit" when the feed is on; one line: "Days at the limit means a day had more mail and chat than the safety limit; a few are fine, many mean the limit should be raised."

`plugin.json`: main+4. `CHANGELOG.md` under `Unreleased`: "Your daily note now has a short *Mail and Teams* block when the feed is on: what needs you first, then what moved per project. (#PR)"

- [ ] **Step 4: Run CI checks**

Run: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q`
Expected: PASS

- [ ] **Step 5: Commit, review, PR**

```bash
git add plugin/lib/vaultlib/health.py plugin/skills/health-check/SKILL.md plugin/.claude-plugin/plugin.json CHANGELOG.md scripts/tests/test_vaultlib_health.py
git commit -m "feat(health): days the mail and Teams feed hit its limit (#236)"
```

`/code-review`, then open PR D.

---

## Task E1: Release to dryrun and verify in Cowork

- [ ] **Step 1:** After D merges, cut a dryrun release (tag push, per root `CLAUDE.md`), `claude plugin update` in the DryRunVault, run `/upgrade-vault` (structure 3 → 4, lossless).
- [ ] **Step 2:** In Cowork, on Matthias's own account: switch the feed on by asking, add one word exclusion, then run `/evening-sync` once interactively.
- [ ] **Step 3:** Check, by looking only at the vault, never at message content in chat:
  - `_messages/<today>-messages.md` exists and is hidden in the file list and in search;
  - the daily note has the *Mail and Teams* block, at most 5 lines, no counts;
  - any project with a strong link has "from mail" or "from chat" markers that open the digest;
  - excluded subjects appear nowhere in `_messages/`;
  - `/health-check` shows the feed's numbers.
- [ ] **Step 4:** Export the session (`mcp__ccd_session_mgmt__export_transcript`) and run `python scripts/cost_report.py <export.zip>`; record tokens and list price for stage 3b in issue #236.
- [ ] **Step 5:** Run a second `/evening-sync` the same evening; confirm no duplicates in the digest and the cursor did not move backwards.
