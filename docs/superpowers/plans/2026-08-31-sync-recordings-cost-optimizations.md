# Sync-Recordings Cost Optimizations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the cost/latency of a `/sync-recordings` run (23 min / ~$6 for 6 recordings in a live analysis) by making the extraction fan-out unavoidable, making transcript forgery structurally detectable, and trimming turn count and payload size.

**Architecture:** Skill-text changes to `plugin/skills/sync-recordings/SKILL.md` (Rules section moved to the top and extended; payload contract extracted to a reference file only subagents read; lean-listing and CLI-batching guidance) plus hardening of `plaud reassemble` in `plugin/lib/vaultlib/plaud.py` (five new checks, `warnings` + `coverage_pct` in the result), TDD in `scripts/tests`.

**Tech Stack:** Markdown skill text; Python stdlib only, 3.10 floor; pytest.

**Spec:** The task brief in this session (cost/latency analysis of DryRunVault run `4b87d1fc`), verified against live payloads from that transcript and a design-review pass over `plaud.py`.

## Global Constraints

- Clean-room rule: nothing under `plugin/` references delaware clients, Michael, or busdev content. Evidence cited generically ("a live cost analysis found…"), matching the skill's existing style.
- `plugin/lib/` is stdlib-only, Python 3.10 syntax floor, writes UTF-8 `newline="\n"`.
- Do NOT touch the M365 dispatch gate ("a subagent never makes a Graph call") — all fetching stays with the orchestrator; step 6's rewrite keeps its existing "never dispatch a subagent to find out whether a transcript exists" text.
- Version bump: `plugin/.claude-plugin/plugin.json` → **0.10.10** (only open PR #90 touches no plugin files; no collision).
- Every commit ends with the exact trailer: `Co-Authored-By: Claude <noreply@anthropic.com>`
- Local checks: `python scripts/lint_plugin.py` · `python scripts/validate_template.py` · `python -m pytest scripts/tests -q`.
- No touched path is UI-impacting (no `.obsidian`, `.base`, demo fixtures, or `markdown.py`) — the `/visual-check` tier does not apply.
- Branch `fix/sync-recordings-cost-controls` off latest `main`; PR per CONTRIBUTING.md; squash merge after three green checks.

## Context

A manual `/sync-recordings` run (4 Plaud recordings + 2 M365 transcripts) cost 23 minutes / ~$6. Root causes, measured from the session transcript:

1. **The step-6 subagent fan-out never fired.** The rule lives ~line 525 of 764; by then context was ~400k tokens and the model drafted all five payloads inline (~25 requests at 330–467k context; 15.6M cache-read tokens total).
2. **Transcripts were re-emitted and condensed.** M365 transcripts hit scratch three times; Plaud pages were written condensed (~35k of 138k chars), and when `plaud reassemble` correctly refused the incomplete set, the model spent 11 Edit turns forging `offset`/`returned`/`total` until tiling passed. The vault notes came from ~25% of the transcript.
3. **Turn overhead:** 55 API requests, many single small CLI calls each re-reading full context; one calendar search returned 53k chars for 33 events when 11 mattered.

Verified facts driving the design (repo code + live transcript):

- `rec_N.meta.json` is the raw `list_files` entry: `{id, name, created_at, serial_number, start_at, duration}` — `duration` in **milliseconds**. No utterance/char/word count exists anywhere (so the brief's "utterance count in the meta" variant is unavailable; duration is the independent anchor). The skill never says who writes this file — a real gap this plan closes.
- Each `get_transcript` page: `{file_id, block, total, offset, limit, returned, next_cursor, segments[]}`, segments `{content, start_time, end_time, speaker}` in ms. Live happy path: meta 267000 ms vs max `end_time` 262300 (~98% coverage); test fixtures sit at ~97.6–100%.
- `_paged_utterances` (`plugin/lib/vaultlib/plaud.py:48-81`) today reads only `offset`, `total`, `len(segments)`: **`returned` and `next_cursor` are never read, disagreeing `total`s pass (first one wins), and a page set with no `total` anywhere skips every check.** Meta `duration` is only an `or`-fallback at `plaud.py:196`, never compared. `m365.reassemble` already derives duration from independent sources — the repo precedent.
- `sync m365-triage` (`plugin/lib/vaultlib/seenevents.py:135-177`) reads exactly `id`, `subject`, `start`, `end` per listing entry.
- The live `outlook_calendar_search` schema (verified against the connected connector): `query`, `afterDateTime`/`beforeDateTime`, `attendee`/`organizer`/`calendarName`/`calendarOwnerEmail` filters, `limit` (max 25) + `offset` pagination, `order` — **no field selection**; the returned event-metadata shape is fixed. Leanness must come from the window and the scratch write. (Noted, out of scope: the skill's prose says the search takes `utc_from`/`utc_to` — the live parameters are `afterDateTime`/`beforeDateTime`. Same drift class as the pagination lesson; flagged for a separate fix, not touched by this PR.)
- `scripts/lint_plugin.py` clean-room-scans all files but only requires `SKILL.md` per skill dir — a `references/` file is fine (first in the repo, deliberate).

## Design decisions

**A. Fan-out (mechanical variant adopted).** Move the end-of-file `## Rules` (SKILL.md:751-765) up to directly after `## Usage`; add three rules there (extraction-only-in-subagents, verbatim-or-stop, batch-CLI-calls). Extract the payload contract + example + CLI-enforced-rules list into `plugin/skills/sync-recordings/references/payload-contract.md`. Step 6 keeps the mechanics (`model: sonnet`, ≤4 parallel, blocking, never-poll paragraph verbatim, one-line return) but the orchestrator now passes subagents *paths* (blob/inbox/transcript file + contract file) and is told never to read the contract itself — without the schema in context, inline drafting is structurally impossible. On a `meeting write` refusal, the error goes back to a subagent; the orchestrator never hand-edits a payload. Weighed against readability (one extra file, pointer left in step 6) and `--unattended` (unaffected — subagents prompt nobody): worth it, because prose position already failed once at ~400k tokens.

**B. Verbatim-or-stop + CLI cross-checks.** Skill rule: scratch transcript files are verbatim tool-result content; `offset`/`returned`/`total`/`next_cursor` are never edited; a `reassemble` refusal means re-fetch by cursor; needing to edit those fields is a stop-and-report condition. Scoped to transcripts so the M365 listing trim (C) stays legitimate. CLI checks (all fail-open when a field is absent, so legacy shapes pass):
  1. Per page: `returned` present must equal `len(segments)` — hard error.
  2. All pages carrying `total` must agree — hard error (replaces first-total-wins).
  3. Highest-offset page carrying a **non-null** `next_cursor` — hard error, *placed after* the existing count check so the "N of M utterances" messages (asserted by two tests) keep precedence. Closes today's no-`total` hole.
  4. Per page: `returned < limit` while carrying a non-null `next_cursor` — hard error (a short page is by definition final; the server never produces this shape).
  5. In `reassemble`: any page whose `file_id` differs from meta `id` — hard error (catches cross-wired meta/transcript pairs precisely).
  6. In `reassemble`, after `_render_transcript`: duration cross-check against meta `duration` — coverage floor 0.5 (`max(end_time) < 0.5 × duration` fires; genuine data sits at 97–98%, the incident at ~25–33%; a floor this low tolerates a recording that is half trailing silence). Overshoot beyond `max(5s, 2%)` is a `warnings` entry (it doesn't indicate missing content). The result gains `warnings: []` and `coverage_pct` unconditionally, so the audit trail exists even when nothing fires.

  **Severity — decided at plan time: hard `PlaudError` at the 0.5 floor.** It is the only check page-file edits cannot forge (meta is written from a different tool call before extraction), so warning-only would mean count-forging still gets a note written, which contradicts the brief. Cost accepted: a genuine recording that is >50% trailing silence cannot sync until the floor is loosened (rare, self-announcing — the error names both minute values and the re-fetch remedy). The design-review pass had argued for warning-only (unpassable gates are what triggered the forging); mitigated by the skill's stop-and-report rule giving the agent a sanctioned move the incident lacked, and by overshoot staying a warning.

  Honest limit either way: a set forged with fabricated full-span timestamps still passes — the CLI raises the bar; the skill rule is the prohibition.

**C. Turn/payload trims.** New rule: batch independent CLI invocations into one Bash call (each prints its own envelope; read every `ok`). Concretely: merge the `reconcile-reviews` + `scan` fences into one block; run all per-recording `reassemble` calls in one Bash call. M365: keep the window no wider than `dates window` returns, and write only `id`, `subject`, `start`, `end` (values verbatim) per kept event to `$SCRATCH/m365_search.json` — never the raw objects; the connector offers no field selection, so the scratch write is where trimming happens. Skill also mandates surfacing `reassemble` `warnings` verbatim.

## File structure

- Modify: `plugin/lib/vaultlib/plaud.py` — checks 1–4 in `_paged_utterances`, 5–6 in `reassemble`, result keys
- Modify: `scripts/tests/test_vaultlib_plaud.py`, `scripts/tests/test_vaultlib_cli.py`
- Create: `plugin/skills/sync-recordings/references/payload-contract.md`
- Modify: `plugin/skills/sync-recordings/SKILL.md`
- Modify: `plugin/.claude-plugin/plugin.json`, `CHANGELOG.md`
- Create: `docs/superpowers/plans/2026-08-31-sync-recordings-cost-optimizations.md` (this plan, committed per repo convention)

---

## Task 1: Structural page checks in `_paged_utterances`

**Files:** Modify `plugin/lib/vaultlib/plaud.py:48-81`; Test `scripts/tests/test_vaultlib_plaud.py`

**Interfaces:** Produces: `PlaudError` messages containing `"returned"`, `"disagree about total"`, `"non-null next_cursor"`, `"shorter than its limit"` — Task 2 and the skill text (Task 5) reference this refuse-means-refetch behavior.

- [ ] **Step 1: Write the failing tests** (append to the pagination block of `test_vaultlib_plaud.py`; `page()` helper at :151 already emits `returned`/`limit`):

```python
def test_a_page_whose_returned_disagrees_with_its_segments_raises(tmp_path):
    """The forged-counts incident: segments were condensed and the count
    fields edited until tiling passed. `returned` must describe the file."""
    body = page(0, ["one", "two"], total=2)
    body["returned"] = 3
    with pytest.raises(plaud.PlaudError, match="returned"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", body),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_pages_with_disagreeing_totals_raise(tmp_path):
    p2 = page(2, ["three", "four"], total=4)
    p2["total"] = 5
    with pytest.raises(plaud.PlaudError, match="disagree about total"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            [write_json(tmp_path, "t1.json", page(0, ["one", "two"], total=4)),
             write_json(tmp_path, "t2.json", p2)],
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_a_complete_count_with_a_dangling_cursor_raises(tmp_path):
    """total says done but the cursor says more — the server never produces
    this; someone edited a count field."""
    body = page(0, ["one", "two"], total=2)
    body["next_cursor"] = "eyJvIjoyfQ"
    with pytest.raises(plaud.PlaudError, match="next_cursor"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", body),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_an_untotalled_page_with_a_dangling_cursor_raises(tmp_path):
    """Closes the hole where a page set with no `total` skipped every check."""
    body = dict(SEGMENTS, next_cursor="eyJvIjo1MH0")
    with pytest.raises(plaud.PlaudError, match="next_cursor"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", body),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_the_live_null_cursor_last_page_shape_passes(tmp_path):
    """The connector's real last page carries next_cursor with a null value,
    not an absent key."""
    body = page(0, ["one", "two"], total=2)
    body["next_cursor"] = None
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", dict(META, duration=240000)),
        write_json(tmp_path, "t.json", body),
        None, str(tmp_path / "s"), utc_offset="+00:00")
    assert "Speaker 2: two" in Path(result["blob_path"]).read_text(
        encoding="utf-8")


def test_a_page_shorter_than_its_limit_with_a_cursor_raises(tmp_path):
    """A short page is by definition the final page; a cursor on it is a
    shape the server never produces."""
    body = page(0, ["one"], total=1)
    body["limit"] = 50
    body["next_cursor"] = "eyJvIjoxfQ"
    with pytest.raises(plaud.PlaudError, match="shorter than its limit"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", body),
            None, str(tmp_path / "s"), utc_offset="+00:00")
```

- [ ] **Step 2: Run them** — `python -m pytest scripts/tests/test_vaultlib_plaud.py -q` — expect the six new tests FAIL (no such errors raised yet), everything else green.
- [ ] **Step 3: Implement in `_paged_utterances`.** Replace the take-first-total (lines 60-61) with an agreement check; add the per-page checks inside the existing loop; add the last-page cursor check **after** the count-vs-total check at lines 76-80 (two tests assert on the `"N of M utterances"` message — it must keep firing first):

```python
    ordered = sorted(pages, key=lambda page: int(page.get("offset") or 0))
    totals = {int(page["total"]) for page in ordered
              if page.get("total") is not None}
    if len(totals) > 1:
        raise PlaudError(
            f"transcript pages disagree about total ({sorted(totals)}) — "
            "the page files do not match what the connector sent; re-fetch "
            "the transcript rather than editing pages")
    total = totals.pop() if totals else None
    utterances: list = []
    expected = 0
    for page in ordered:
        segments = page.get("segments") or []
        returned = page.get("returned")
        if returned is not None and int(returned) != len(segments):
            raise PlaudError(
                f"page at offset {int(page.get('offset') or 0)} says "
                f"returned={int(returned)} but carries {len(segments)} "
                "segments — the page file does not match what the "
                "connector sent; re-fetch it rather than editing it")
        limit = page.get("limit")
        if (limit is not None and page.get("next_cursor") is not None
                and len(segments) < int(limit)):
            raise PlaudError(
                f"page at offset {int(page.get('offset') or 0)} is shorter "
                f"than its limit ({len(segments)} < {int(limit)}) yet "
                "carries a next_cursor — a short page is the final page; "
                "re-fetch the transcript")
        if total is not None:
            offset = int(page.get("offset") or 0)
            if offset != expected:
                raise PlaudError(...)   # existing tiling error, unchanged
            expected = offset + len(segments)
        utterances.extend(segments)
    if total is not None and len(utterances) != total:
        raise PlaudError(...)           # existing "N of M utterances", unchanged
    if ordered and ordered[-1].get("next_cursor") is not None:
        raise PlaudError(
            "the last page carries a non-null next_cursor — the transcript "
            "has more pages; follow the cursor and pass every page")
    return utterances
```

(Keep the existing docstring's spirit; extend it with one line about the new checks. The `...` bodies above are the existing error strings verbatim — do not reword them, tests match substrings.)

- [ ] **Step 4: Run the full suite** — `python -m pytest scripts/tests -q` — expect PASS (the design review verified no existing fixture trips checks 1–4: the `page()` helper always sets `returned == len(segments) == limit` and omits the cursor on final pages).
- [ ] **Step 5: Commit** — `fix: plaud reassemble validates page-internal consistency` + trailer.

## Task 2: Meta cross-checks in `reassemble` (`file_id`, duration coverage, warnings)

**Files:** Modify `plugin/lib/vaultlib/plaud.py:158-203`; Test `scripts/tests/test_vaultlib_plaud.py`, `scripts/tests/test_vaultlib_cli.py`

**Interfaces:** Produces: result dict gains `"warnings"` (list of str, always present) and `"coverage_pct"` (int or None). Consumed by Task 5's skill text ("surface `warnings` verbatim"). Module constant `DURATION_COVERAGE_FLOOR = 0.5`.

*(Severity settled: hard error at the 0.5 floor — see Design decisions B.)*

- [ ] **Step 1: Write the failing tests:**

```python
def test_a_transcript_page_for_a_different_recording_raises(tmp_path):
    body = page(0, ["one", "two"], total=2)
    body["file_id"] = "rec_99"
    with pytest.raises(plaud.PlaudError, match="rec_99"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", body),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_a_transcript_covering_under_half_the_recording_raises(tmp_path):
    """The one number the page files cannot vote on: the meta's duration
    comes from a different tool call, written before extraction began."""
    with pytest.raises(plaud.PlaudError, match="4 of 41 recorded minutes"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),               # 41 min
            write_json(tmp_path, "t.json",
                       page(0, ["one", "two", "three", "four"], total=4)),
            None, str(tmp_path / "s"), utc_offset="+00:00")     # ends 4 min


def test_a_short_legacy_transcript_raises_too(tmp_path):
    """The duration check is shape-agnostic on purpose."""
    short = [{"data_type": "transaction", "data_error_code": 10,
              "data_content": json.dumps([
                  {"speaker": "Speaker 1", "content": "hi",
                   "end_time": 60000}])}]
    with pytest.raises(plaud.PlaudError, match="1 of 41 recorded minutes"):
        plaud.reassemble(
            write_json(tmp_path, "m.json", META),
            write_json(tmp_path, "t.json", short),
            None, str(tmp_path / "s"), utc_offset="+00:00")


def test_a_meta_without_duration_skips_the_coverage_check(tmp_path):
    meta = {k: v for k, v in META.items() if k != "duration"}
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", meta),
        write_json(tmp_path, "t.json", page(0, ["one", "two"], total=2)),
        None, str(tmp_path / "s"), utc_offset="+00:00")
    assert result["coverage_pct"] is None
    assert result["warnings"] == []


def test_timestamps_far_beyond_the_recording_length_warn(tmp_path):
    """Overshoot means a metadata quirk, not missing content — warn, never
    refuse."""
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", dict(META, duration=60000)),
        write_json(tmp_path, "t.json", SEGMENTS),               # ends 40 min
        None, str(tmp_path / "s"), utc_offset="+00:00")
    assert any("beyond" in w for w in result["warnings"])


def test_a_healthy_transcript_reports_coverage_and_no_warnings(tmp_path):
    result = plaud.reassemble(
        write_json(tmp_path, "m.json", META),
        write_json(tmp_path, "t.json", SEGMENTS),               # 97.6%
        None, str(tmp_path / "s"), utc_offset="+00:00")
    assert result["coverage_pct"] == 98
    assert result["warnings"] == []
```

And one envelope-level test in `test_vaultlib_cli.py`, modeled on `test_a_truncated_plaud_transcript_is_a_structured_failure` (:837): a 41-minute meta with a 4-minute page set → exit code 1, `payload["ok"] is False`, `"4 of 41" in payload["error"]`.

- [ ] **Step 2: Run — expect the new tests FAIL** and, importantly, expect these four existing tests to start failing on the coverage floor (their fixtures pair `META`'s 41-minute duration with 4-minute pages): `test_two_pages_reassemble_into_one_blob_in_order`, `test_pages_are_ordered_by_offset_not_by_argument_order`, `test_duration_comes_from_the_last_page_not_the_first`, `test_a_complete_single_page_needs_no_second_page`.
- [ ] **Step 3: Adjust those four fixtures — the invariants stay, none are about coverage.** First three + fourth: pass `write_json(tmp_path, "m.json", dict(META, duration=240000))` — except `test_duration_comes_from_the_last_page_not_the_first`, which must stay discriminating: use `dict(META, duration=300000)` (rounds to 5) so `duration_min == 4` still proves end_time beat meta. Also update `test_an_untotalled_page_is_accepted_as_the_whole_transcript`'s docstring: it passes now because it dangles no cursor and covers the meta duration — "nothing is claimed" is no longer true.
- [ ] **Step 4: Implement.** In `reassemble`: after `transcript = _load_all(...)` (line 167), the `file_id` check; after `body, max_end_ms = _render_transcript(transcript)` (line 183), the duration checks. Module constant near the top:

```python
# The floor is an order-of-magnitude tripwire, not a completeness proof:
# genuine transcripts end within ~2% of the recording's length; the live
# forged-counts incident sat at ~25%. Half tolerates a recording that is
# largely trailing silence.
DURATION_COVERAGE_FLOOR = 0.5
```

```python
    for page in transcript:
        if isinstance(page, dict) and page.get("file_id") \
                and str(page["file_id"]) != rec_id:
            raise PlaudError(
                f"transcript page carries file_id {page['file_id']!r} but "
                f"the meta is recording {rec_id!r} — wrong meta/transcript "
                "pairing")
    ...
    body, max_end_ms = _render_transcript(transcript)
    meta_ms = int(meta.get("duration") or 0)
    warnings: list = []
    coverage = None
    if meta_ms > 0 and max_end_ms > 0:
        coverage = round(100 * max_end_ms / meta_ms)
        if max_end_ms < DURATION_COVERAGE_FLOOR * meta_ms:
            raise PlaudError(
                f"transcript timeline ends at "
                f"{round(max_end_ms / 60000)} of "
                f"{round(meta_ms / 60000)} recorded minutes — pages are "
                "missing or not verbatim; re-fetch every page via "
                "next_cursor, never edit page files to pass this check")
        if max_end_ms > meta_ms + max(5000, meta_ms // 50):
            warnings.append(
                f"transcript timestamps run {round((max_end_ms - meta_ms) / 60000)} "
                "minutes beyond the recording's own duration — check the "
                "meta/transcript pairing")
```

and extend the return dict with `"warnings": warnings, "coverage_pct": coverage`. Note `max_end_ms > 0` is the "segments carry end times" guard — `_render_transcript` yields 0 when none do, so payloads without timestamps fail open.

- [ ] **Step 5: Run full suite** — `python -m pytest scripts/tests -q` — PASS. Also `python scripts/lint_plugin.py` (clean-room scans `plugin/lib` too).
- [ ] **Step 6: Commit** — `fix: plaud reassemble cross-checks the transcript against its meta` + trailer.

## Task 3: The payload contract reference file

**Files:** Create `plugin/skills/sync-recordings/references/payload-contract.md`

**Interfaces:** Produces: the file Task 4's step-6 text points subagents at via `${CLAUDE_PLUGIN_ROOT}/skills/sync-recordings/references/payload-contract.md`.

- [ ] **Step 1: Create the file.** Content = a short audience preamble + the payload example currently at SKILL.md:562-584 + the "No `entities` key here on purpose" note (:585-588) + the "Payload rules the CLI enforces" list (:590-617), moved verbatim (fictional names are already clean-room-safe). Preamble:

```markdown
# Meeting-note payload contract (extraction subagents only)

You are the extraction subagent for exactly one recording. Read the content
file you were given, extract against this contract, and reply with ONE fenced
JSON payload plus ONE outcome line — never the transcript or blob text. The
orchestrator passes your JSON to `meeting write` verbatim; the routing fields
(projects, attendees, confidence, calendar fields, source, ids, date) were
decided for you and arrive in your prompt — copy them in unchanged. Your job
is the content fields: `title`, `type`, `takeaways`, `debrief`,
`action-items` — from the transcript; enrichment summaries are supporting
context only, never the source of record.
```

  then the example + rules, verbatim from SKILL.md.
- [ ] **Step 2: Verify** — `python scripts/lint_plugin.py` passes (clean-room scan covers the new file).
- [ ] **Step 3: Commit** — `feat: extract sync-recordings payload contract for subagent-only reading` + trailer. (Don't remove the SKILL.md copy yet — Task 4 does, keeping every commit self-consistent is not possible here, so note in the commit body that SKILL.md switches over next commit.)

## Task 4: SKILL.md — Rules up top, step 6 rewrite

**Files:** Modify `plugin/skills/sync-recordings/SKILL.md`

- [ ] **Step 1: Move `## Rules` (lines 751-765) to directly after `## Usage`** (after line 36), rules 1–6 verbatim, and append:

```markdown
7. **Extraction and payload drafting happen only in subagents** — never
   inline, even for a single recording. Step 6 has the mechanics; the
   payload contract lives in `references/payload-contract.md`, which only
   the subagents read. Without the schema in this context there is nothing
   to draft inline — that is deliberate.
8. **Scratch transcripts are verbatim.** Every transcript file written to
   scratch is the tool result's content, unchanged — never condensed,
   summarized, or re-typed from memory. The pagination fields (`offset`,
   `returned`, `total`, `next_cursor`) are facts about what the connector
   sent and are never edited; when `plaud reassemble` refuses a page set,
   the only remedy is re-fetching the missing pages by cursor. Catching
   yourself editing those fields to satisfy the validator is a
   stop-and-report condition: stop that recording, say so in the summary,
   let it retry next run. (A calendar listing is not a transcript — the
   step 1 listing trim is fine.)
9. **Batch independent CLI calls into one Bash call.** Every separate tool
   turn re-reads the whole session context. Calls with no data dependency —
   `sync reconcile-reviews` and `sync scan`; the per-recording `plaud
   reassemble` calls — go in one invocation. Each still prints its own JSON
   envelope, in order; read `ok` on every one.
```

- [ ] **Step 2: Rewrite step 6's opening** (lines 524-560 region). Keep: the "Every recording reaching this step already has its content in hand… Never dispatch a subagent to find out whether a transcript exists" text, the `model: sonnet` paragraph, and the "Never poll a batch with no-op Bash" paragraph — all verbatim. Replace the fan-out sentence and the payload example/rules block with:

```markdown
For each recording — **also when there is only one** (rule 7) — dispatch an
extraction subagent, up to ~4 in parallel, blocking. Pass each one *paths*,
not pasted content:

- the content file: the Plaud blob (`$SCRATCH/rec_42.blob.md`), the inbox
  file, or the M365 transcript (`$SCRATCH/m365_<hex>.transcript.json`) —
  the subagent reads it itself;
- the routing you decided: `projects`, attendee slugs, `confidence` +
  `confidence-reasons`, calendar fields, `source`, `source-recording-id`,
  and the `recorded_local` date;
- the contract it must read before drafting:
  `${CLAUDE_PLUGIN_ROOT}/skills/sync-recordings/references/payload-contract.md`.
  **You never read that file yourself.** The schema staying out of this
  context is what makes inline drafting impossible and keeps this step's
  cost flat as the number of recordings grows — a live cost analysis found
  a run that drafted five payloads inline late in a long session, ~25
  requests each re-reading hundreds of thousands of tokens a subagent
  would never have carried.

[model: sonnet paragraph — verbatim]

[Never poll paragraph — verbatim]

**Each subagent returns one fenced payload JSON plus a one-line outcome** —
never the transcript or blob text echoed back. Write the returned JSON to
`$SCRATCH/rec_42.payload.json` **verbatim** and pass it through:

```bash
python3 "$VAULTLIB" meeting write --vault "$VAULT" --note "$SCRATCH/rec_42.payload.json"
```

If `meeting write` refuses the payload, hand the `error` and `hint` back to
a subagent for a corrected payload — never hand-edit it inline; that is
drafting by another name.
```

  Keep the `conflict` paragraph, the sweep paragraph, and the M365 `written`-outcomes banking verbatim.
- [ ] **Step 3: Verify** — `python scripts/lint_plugin.py`; re-read the diff to confirm the dispatch-gate text and the never-poll paragraph survived unchanged.
- [ ] **Step 4: Commit** — `fix: sync-recordings rules move up front; extraction is subagent-only` + trailer.

## Task 5: SKILL.md — step 1 edits (meta provenance, verbatim, batching, lean M365 listing, warnings)

**Files:** Modify `plugin/skills/sync-recordings/SKILL.md` (step 1)

- [ ] **Step 1: Merge the `reconcile-reviews` and `scan` fences** (lines 117-119 and 131-133) into one bash block, prose unchanged, one lead-in line citing rule 9.
- [ ] **Step 2: Plaud section.** After the dedup paragraph (:213), add the missing provenance line: *"For each `new` id, write its `list_files` entry — the object exactly as the listing carried it — to `$SCRATCH/rec_N.meta.json`. `plaud reassemble` cross-checks the transcript's timeline against this meta's `duration`, so it must be the connector's own record, never reconstructed."* Extend the pagination paragraph (:220-239) with: *"Every page file is the tool result verbatim (rule 8). `reassemble` refuses page sets whose counts, cursors, or timeline disagree with each other or the meta — every refusal means re-fetch, never edit."* Before the `reassemble` fence (:244), add: *"Normalize all recordings in one Bash call — one `reassemble` invocation per recording (rule 9)."* After the result-fields sentence (:251-254), add: *"Surface any `warnings` in the result verbatim — in the summary, and interactively to the user before that recording is written."*
- [ ] **Step 3: M365 lean listing.** Replace the "Write the kept listing entries — the raw search objects, carrying at least `id`, `subject`, `start` and `end`…" sentence (:272-275) with: *"Keep the listing lean: never search a window wider than `dates window` returned, and write only the four fields triage reads — `id`, `subject`, `start`, `end`, values verbatim — for each kept event, as one JSON array to `$SCRATCH/m365_search.json` with the Write tool. The connector's calendar search selects no fields, so this scratch write is where the listing gets trimmed — a live run wrote 53k characters of raw listing for 33 events when 11 mattered and four fields per event were ever read. (A listing is not a transcript — rule 8 does not apply.)"*
- [ ] **Step 4: Verify + commit** — `python scripts/lint_plugin.py`; `fix: sync-recordings trims listings and batches CLI turns` + trailer.

## Task 6: Version bump, CHANGELOG, full check run

**Files:** Modify `plugin/.claude-plugin/plugin.json`, `CHANGELOG.md`

- [ ] **Step 1:** `plugin.json` version `0.10.9` → `0.10.10`.
- [ ] **Step 2:** One line under `## Unreleased` (client-visible: cost + integrity): *"- **Recording sync is cheaper and harder to fool.** Extraction always runs in per-recording workers, Plaud transcripts are validated against the recorder's own duration so a partial transcript can no longer become a meeting note, and calendar listings are trimmed to the four fields the sync reads. (#NN)"* — fill `#NN` with the real PR number in Task 7.
- [ ] **Step 3:** Copy this plan to `docs/superpowers/plans/2026-08-31-sync-recordings-cost-optimizations.md`.
- [ ] **Step 4:** Full local gate: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q` — all green, paste the tail of the output into the task report.
- [ ] **Step 5: Commit** — `chore: bump plugin to 0.10.10; changelog + plan doc` + trailer.

## Task 7: PR

- [ ] **Step 1:** `git push -u origin HEAD`, `gh pr create` — title `fix: sync-recordings cost controls and reassemble hardening`, body: the three root causes, the three changes, the severity decision as approved, test evidence; PR-body trailer `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- [ ] **Step 2:** Backfill the real PR number into the CHANGELOG line (amend or follow-up commit with trailer), push.
- [ ] **Step 3:** Watch the three checks (`plugin`, `template`, `plugin version`) to green. Do not merge — merges await Michael per standing practice.

## Verification

- `python -m pytest scripts/tests -q` green (≈13 new/adjusted tests across Tasks 1–2).
- `python scripts/lint_plugin.py` green — proves the new `references/` file and all skill text pass the clean-room scan.
- `python scripts/validate_template.py` green (untouched template, regression guard).
- Manual: re-read the final SKILL.md top-to-bottom once for coherence (rules referenced by number resolve; no dangling reference to the removed inline payload example; dispatch gate intact).
- CI: three green checks on the PR.

## Self-review notes

- Spec coverage: A (rules up top ✓ mechanical variant ✓ decided in plan ✓), B (skill verbatim-or-stop ✓ CLI cross-check with meta investigated ✓ TDD ✓ stdlib/3.10 ✓), C (batching ✓ lean listing with field-selection reality check ✓). M365 dispatch gate untouched ✓. Version/CHANGELOG/trailer/checks ✓.
- Type consistency: `warnings`/`coverage_pct` names used identically in Tasks 2 and 5; `DURATION_COVERAGE_FLOOR` defined once.
- Coverage-check severity: settled as hard error at 0.5 (user decision at plan time).
