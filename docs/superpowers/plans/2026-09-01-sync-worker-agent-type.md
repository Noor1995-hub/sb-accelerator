# Dedicated sync-worker agent type — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a plugin-defined `sync-worker` agent type with `model: sonnet` pinned and a trimmed tool surface, and make `/sync-recordings` step 6 dispatch it by name — so per-recording workers stop inheriting the session's full base context and stop silently inheriting a pricier session model.

**Architecture:** One new agent definition at `plugin/agents/sync-worker.md` (auto-discovered — plugin.json declares no component paths), a rewritten dispatch paragraph in `plugin/skills/sync-recordings/SKILL.md` step 6 with a generic-subagent fallback line, a contract test pinning both, plus the release trio (version bump, marketplace-test literal, CHANGELOG). An empirical spike runs *first* because two load-bearing behaviors are undocumented; a measurement task closes the loop with before/after base-context numbers.

**Tech stack:** Claude Code plugin agents (YAML frontmatter markdown), pytest contract tests, `make_test_vault.py` scratch vault + headless `claude -p --plugin-dir` for measurement.

**Spec:** The task brief (this session's opening message). Save this plan to `docs/superpowers/plans/2026-09-01-sync-worker-agent-type.md` as part of Task 6 (repo precedent: `docs/superpowers/plans/2026-08-31-sync-recordings-worker-fetch.md`).

## Context

PR #127 (plugin 0.10.12) moved transcript fetches into per-recording worker subagents. A live DryRunVault run on 2026-09-01 confirmed the design but measured the residual cost: 13 workers cost ~$10.8 vs ~$5 for the main loop, and the dominant driver is that each worker is a **generic** subagent inheriting the session's full base context, re-read on each of its 4–26 requests. The dispatches also silently omitted `model: sonnet` despite the skill mandating it — free that day (session was Sonnet), a real cost bug on any pricier session. A dedicated agent type makes the model mandate structural and slims the per-request base.

## Evidence verified this session (how, and what)

**From the live run's transcripts** (`~/.claude/projects/-Users-bulthem-Documents-DryRunVault/d59003c8…/subagents/*.jsonl`, usage fields via jq):

- All 13 workers ran as `agentType: general-purpose`, model `claude-sonnet-5` — the `model` param was indeed absent on dispatch.
- Worker first-request base ≈ **46k tokens** (24,828 shared cached prefix identical across all workers + ~21.5k worker-specific cache-creation), growing to ~100k+ over a long worker. The briefing itself is only ~2.8k chars (~700 tokens). So the base is the harness system prompt, inherited CLAUDE.md/context/skill-listing, and the core toolset. (The brief's "~85k" figure reads as mid-run context; the honest baseline metric is the first-request base, ~46k. The target below uses "well under half of the measured generic baseline".)
- Workers made 13 ToolSearch calls — **MCP schemas were already deferred** in the live run. So the win comes mostly from replacing the generic subagent's inherited context with a lean agent definition, and the `tools` trim is least-privilege plus insurance for harnesses without deferral.
- Tools workers actually used: Bash, Read, Write, Edit, ToolSearch, `mcp__plaud__get_transcript`, `mcp__plaud__get_note`, `mcp__<uuid>__read_resource` (M365), plus 1 stray Skill call (not needed by the contract — deliberately excluded).

**From current Claude Code docs** (via a claude-code-guide agent; sources: code.claude.com/docs sub-agents, agent-sdk/subagents, agent-sdk/tool-search, plugins-reference):

- Plugin agents are addressed `<plugin-name>:<agent-name>` → **`second-brain:sync-worker`**. The marketplace suffix (`@sb-accelerator-dryrun`) is never part of the address, so the skill text can hard-code it. (Corroborated locally: this session's plugin agents appear as `plugin-dev:agent-creator` etc.)
- Agent `tools:` in .md frontmatter is a comma-separated string; specific MCP tool names (`mcp__plaud__get_transcript`) are valid entries; `mcp__<server>__*` server wildcards are documented. A restricted list **excludes** unlisted MCP tools and **does** keep their schemas out of the agent's context.
- `model: sonnet` in frontmatter pins the model when dispatched via `subagent_type`.
- **Undocumented (spike required, Task 1):** whether ToolSearch inside a tools-restricted agent can load *and call* a tool outside the allowlist, and whether an unanchored `mcp__*` works in an agent allowlist (docs warn it's skipped in permission `allowedTools`). This decides the M365 shape, because the M365 connector's server name is a per-deployment UUID that no static list can name.

**From the repo** (Explore agent + direct reads):

- No `plugin/agents/` exists; plugin.json (name `second-brain`, version 0.10.12) declares no component paths → pure auto-discovery, no manifest change needed.
- Clean-room lint (`scan_cleanroom`) and the slash-command reference scan already rglob all of `plugin/` → a new agents dir is covered with **no linter change**. `lint_skills()` won't validate agent frontmatter — the new contract test covers that instead.
- Version guard triggers on any `^plugin/` diff except `plugin/CLAUDE.md` → bump required. Bump sites: `plugin/.claude-plugin/plugin.json:3` and the literal in `scripts/tests/test_marketplace_manifest.py:65`. Only open PR is #90 (docs-only, no release-trio files) → **0.10.13 is free**.
- Existing tests that must stay green while editing step 6 (`scripts/tests/test_skill_contracts.py:233-284`): keep the `### 6.` heading, "survived triage", `"forbidden"`, `sync m365-record` both before and after `### 6.`, the outcome vocabulary tokens, and the `references/worker-contract.md` mention. New-test precedent: `test_sync_recordings_dispatches_workers_only_after_triage_and_dedup` (L247), helpers `read_skill`/`read_ref` (L142-147), `_normalized()` (L392) for hard-wrapped phrases.
- Scratch vault: `python scripts/make_test_vault.py <target>` (template + demo fixture overlay). Vaults live in the **main checkout's** gitignored `test-vaults/` — never in worktrees or /tmp. Plugin loads via `claude --plugin-dir <worktree>/plugin` from inside the vault.

## Design decisions

**The agent file** — `plugin/agents/sync-worker.md`:

```markdown
---
name: sync-worker
description: Per-recording sync worker dispatched by /sync-recordings step 6 with a full briefing. Not for direct invocation — without a briefing it has nothing to act on.
model: sonnet
color: cyan
tools: Read, Write, Edit, Bash, ToolSearch, mcp__plaud__get_transcript, mcp__plaud__get_note
---

You are the worker for exactly one recording. Your briefing carries the
paths to the worker contract and the payload contract, the vault root,
the scratch directory, the CLI path, the timezone, your recording's
reference, and every routing decision already made.

Read the worker contract file first and follow it exactly — it defines
your fetch mechanics, the reassemble step, the collision check, the
extraction rules, and the outcome table. Your entire reply is one outcome
line from that table: never transcript, blob, or payload text.

If your briefing is missing or names no contract path, reply
`fetch-error: dispatched without a briefing` and stop.
```

Rationale: the description is one short block because agent descriptions load into *every* session of *every* deployment; the body stays minimal because the contract lives in `references/worker-contract.md` (passed by path in the briefing) — no duplication. The stray `Skill` tool the live run used is deliberately excluded; the contract never needs it. **The final `tools:` line depends on the Task-1 spike** (M365 resolution below).

**The M365 UUID problem — decision tree** (settled empirically in Task 1, in this order):

1. If ToolSearch inside the restricted agent can load **and call** a tool outside the allowlist → the list above is final; M365 workers reach `read_resource` via ToolSearch exactly as they do today. (Also note the reverse implication: the tools trim is then advisory, not a hard boundary — record that honestly in the PR.)
2. Else if `mcp__*` (or another accepted pattern) works in the agent allowlist → append it to `tools:`. All MCP schemas stay deferred behind ToolSearch anyway, so this costs ~nothing in context and unblocks the UUID server.
3. Else → **split dispatch in the skill text**: plaud/inbox workers use `second-brain:sync-worker`; M365 workers use a second agent `plugin/agents/sync-worker-m365.md`, identical but with `tools:` omitted entirely (all tools — still wins the pinned model and the lean system prompt). Measure both shapes in Task 5 and report the partial win. Silent failure of the M365 fetch is not acceptable; a broader M365 worker is.

**The dispatch line** — `plugin/skills/sync-recordings/SKILL.md` step 6 (lines 510-519). Replace the opening sentence:

> For each recording that survived step 1 — **also when there is only one** (rule 7) — dispatch a worker, up to ~4 in parallel, blocking, spawned with `model: sonnet`.

with (final wording at implementation, invariants fixed):

> For each recording that survived step 1 — **also when there is only one** (rule 7) — dispatch a worker: `subagent_type: second-brain:sync-worker`, the plugin's own agent type, up to ~4 in parallel, blocking. The agent definition pins `model: sonnet` and the trimmed tool surface, so neither is a per-dispatch decision. On a harness where the plugin agent type is not resolvable, fall back to a generic subagent spawned with `model: sonnet` passed explicitly — the mandate holds either way; a live cost analysis found dispatches that omitted it silently inheriting the session's model.

Keep every phrase the existing tests assert (listed above). The "Never poll a batch" paragraph and the rest of step 6 are untouched.

**Non-goals:** evening-sync's own extraction subagents (`plugin/skills/evening-sync/SKILL.md:136-171`) keep their `model: sonnet` prose dispatch — it runs `/sync-recordings` inline so its recording workers get the new agent type for free; converting its *other* subagents is a separate round. No linter extension for agent frontmatter (the contract test pins what matters). No slimming of worker request count — that was PR #127.

---

## Task 0: Branch

- [ ] From the worktree root: `git fetch origin && git checkout -b claude/sync-worker-agent-type origin/main`. (The worktree's current branch `claude/heuristic-bun-b4f8b5` is a placeholder; do not build on it.)

## Task 1: Spike — verify the undocumented behaviors (no shipped code yet)

**Files:** scratch only (`test-vaults/` in the main checkout + a throwaway agent file added/removed in the worktree plugin, never committed in its probe form).

- [ ] **Create the scratch vault** (main checkout, gitignored):
  `python scripts/make_test_vault.py /Users/bulthem/Documents/Dev/sb-accelerator/test-vaults/2026-09-01-sync-worker-spike`
- [ ] **Write a probe agent** at `plugin/agents/sync-worker.md` with the frontmatter above but body: "Report, as plain text: (1) the names of all tools you can currently call; (2) then use ToolSearch to find `mcp__plaud__get_current_user`, report whether it loads, and attempt one call, reporting the exact error or the result's top-level keys only." (Plaud stands in for the UUID M365 server: same mechanism — an MCP tool *not* in the allowlist. `get_current_user` is read-only whoami.)
- [ ] **Dispatch it headless from the vault:** `cd` to the scratch vault, run `claude -p --plugin-dir <worktree>/plugin --permission-mode acceptEdits "Use the Agent tool with subagent_type 'second-brain:sync-worker' and prompt 'go'. Relay its reply verbatim."` — this simultaneously proves plugin-agent resolvability (`second-brain:sync-worker` resolves) and answers question 1 of the decision tree.
- [ ] **If ToolSearch could not call the unlisted tool:** edit the probe's `tools:` to end with `, mcp__*`, re-dispatch, and check whether the wildcard is honored (decision-tree question 2).
- [ ] **Record outcomes** in the plan doc's margin notes (Task 6) and pick the branch of the decision tree. If `second-brain:sync-worker` itself fails to resolve, STOP — the load-bearing assumption is dead; report to Michael with the exact error and propose the alternative (skill-text-only hardening: explicit `model: sonnet` + a documented tools omission), rather than shipping an agent nothing can address.

## Task 2: Contract test first (TDD), then the agent file

**Files:** Modify: `scripts/tests/test_skill_contracts.py` (after L257); Create: `plugin/agents/sync-worker.md` (+ `sync-worker-m365.md` only on decision-tree branch 3).

- [ ] **Write the failing test** (adjust the `tools` asserts to the spike's outcome):

```python
# Cost round 2: workers run as the plugin's own agent type, which pins the
# model and the tool surface structurally — a live run measured 13 generic
# workers inheriting the session's full base context and, silently, its model.
def test_sync_recordings_dispatch_names_the_worker_agent_type():
    text = read_skill("sync-recordings")
    step6 = text.split("### 6.")[1].split("### 7.")[0]
    step6_flat = re.sub(r"\s+", " ", step6)
    assert "second-brain:sync-worker" in step6_flat, (
        "step 6 must dispatch the plugin's worker agent type by name")
    assert "model: sonnet" in step6_flat, (
        "the generic-subagent fallback must pass the model explicitly")

    agent = (SKILLS_DIR.parent / "agents" / "sync-worker.md").read_text(
        encoding="utf-8")
    front = agent.split("---")[1]
    assert "name: sync-worker" in front
    assert "model: sonnet" in front, "the model mandate must be structural"
    assert "tools:" in front, "the tool surface must be trimmed"
    for tool in ("ToolSearch", "Bash", "Read", "Write",
                 "mcp__plaud__get_transcript"):
        assert tool in front, f"worker tools must include {tool}"
    body = agent.split("---", 2)[2]
    assert "worker contract" in body and "outcome line" in body
    assert "next_cursor" not in agent, (
        "fetch mechanics live in references/worker-contract.md, not the agent")
```

(`SKILLS_DIR` already exists in the file; `re` is already imported for `_normalized`. Verify both at implementation and reuse.)

- [ ] Run: `python -m pytest scripts/tests/test_skill_contracts.py -q -k worker_agent_type` — expect FAIL (no agents dir yet).
- [ ] **Write `plugin/agents/sync-worker.md`** per the Design section + spike outcome. Clean-room voice: "a live cost analysis measured…", no PR numbers, no names.
- [ ] Test still fails (skill text not yet edited) — that's the next task's half.

## Task 3: Skill-text hardening (change B)

**Files:** Modify: `plugin/skills/sync-recordings/SKILL.md:510-519` only.

- [ ] Replace the dispatch sentence per the Design section (adjust for decision-tree branch 3 if taken: one sentence routing plaud/inbox vs m365 to the two agent types).
- [ ] Run: `python -m pytest scripts/tests/test_skill_contracts.py -q` — the new test passes AND all nine existing sync-recordings contract tests stay green (the preserved-phrase list above).
- [ ] Commit (message ends with the exact trailer `Co-Authored-By: Claude <noreply@anthropic.com>`).

## Task 4: Release trio

**Files:** Modify: `plugin/.claude-plugin/plugin.json:3` (`0.10.12` → `0.10.13`), `scripts/tests/test_marketplace_manifest.py:65` (same literal), `CHANGELOG.md` under `## Unreleased`.

- [ ] CHANGELOG bullet (client-visible: sync runs get cheaper), PR number appended once the PR exists:
  `- /sync-recordings workers now run as a dedicated lightweight agent type with the model pinned — each worker starts from a fraction of the session context, so multi-recording syncs cost noticeably less (#NNN)`
- [ ] Run the full local gate: `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q` — all green.
- [ ] Commit.

## Task 5: Measurement — the acceptance evidence

**Files:** none shipped; numbers go in the PR body.

- [ ] Reuse the Task-1 scratch vault. From it, dispatch **one trivial worker of each shape** via `claude -p --plugin-dir <worktree>/plugin`:
  - baseline: generic subagent (`general-purpose`, no model param), briefing: "Reply with exactly: written: probe";
  - new: `second-brain:sync-worker`, same briefing (its body's missing-briefing guard replies `fetch-error: …` — either reply is fine, tokens are the datum);
  - on branch 3: also `second-brain:sync-worker-m365`.
- [ ] Read each dispatch's `subagents/agent-*.jsonl` first request: `jq '.message.usage | {input_tokens, cache_creation_input_tokens, cache_read_input_tokens}'` — base context = their sum. Also confirm `.message.model == "claude-sonnet-5"` for the new agent and, from the probe's tool-listing reply in Task 1, that the restriction held.
- [ ] **Target:** the dedicated worker's first-request base is well under half the generic baseline measured in the same vault (live-run generic baseline: ~46k; the brief's ~85k mid-run figure falls proportionally with the base). If the win is smaller than expected, report the measured numbers honestly and say why (e.g. CLAUDE.md still inherited) — do not shade them.
- [ ] Delete the scratch vault.

## Task 6: Plan doc, PR

- [ ] Copy this plan (with spike outcomes and measured numbers appended) to `docs/superpowers/plans/2026-09-01-sync-worker-agent-type.md`; commit.
- [ ] Push; open PR to `main` titled `feat: dedicated sync-worker agent type pins model and trims worker context`. Body: the two changes, the decision-tree branch taken and why, the before/after table, the local-gate output. Backfill the CHANGELOG `(#NNN)` with the real PR number in the same push if opened with `gh pr create` first, or amend after.
- [ ] **Do not merge** — merges are Michael's. Report PR URL + measured numbers.

## Verification (end-to-end)

1. `python scripts/lint_plugin.py && python scripts/validate_template.py && python -m pytest scripts/tests -q` — the same three checks CI runs, all green.
2. Task-5 measurement table: generic vs dedicated first-request base tokens, model id confirmed `sonnet`, tool restriction confirmed from the probe's own tool listing.
3. Task-1 transcript proves `second-brain:sync-worker` resolves from a vault session with the plugin loaded via `--plugin-dir`.
4. Existing sync-recordings contract tests unchanged and green — the step-6 invariants (triage-gates-dispatch, banking order, outcome vocabulary) survived the edit.

## Execution notes

- Per standing preference: dispatch implementation teammates with `model: sonnet` for the mechanical tasks (2–4); the spike (Task 1) and measurement (Task 5) interpretation stay with the orchestrator.
- Scratch vaults only under the main checkout's `test-vaults/`; never in the worktree or /tmp.
- Every commit message ends with the exact trailer `Co-Authored-By: Claude <noreply@anthropic.com>`.

---

## Spike outcomes & measurements (executed 2026-09-01)

All probes: scratch vault `test-vaults/2026-09-01-sync-worker-spike`, headless
`claude -p --plugin-dir <worktree>/plugin`, usage read from the session's
`subagents/agent-*.jsonl` first request (input + cache_creation + cache_read).

**Decision tree: branch 3 (split dispatch).**

- `second-brain:sync-worker` resolves via `subagent_type` from a vault session
  with the plugin loaded — the load-bearing assumption holds. Meta records
  `agentType: second-brain:sync-worker`; every assistant turn ran
  `claude-sonnet-5` (the frontmatter pin works).
- The `tools:` allowlist is a hard boundary: the probe saw only its five
  built-ins plus the two allowlisted plaud tools as deferred names. ToolSearch
  could NOT load tools outside the allowlist (Airtable and playwright tools —
  both present in the parent session — answered "No matching deferred tools
  found"). Branch 1 dead.
- An unanchored `mcp__*` entry in the allowlist changed nothing (same probe,
  same result) — consistent with the documented warning that unanchored
  wildcards are skipped. Branch 2 dead.
- `disallowedTools:` IS honored in agent .md frontmatter (measured below) —
  used to slim the m365 worker, whose allowlist cannot name a per-deployment
  UUID server.

**Measured first-request base context (same vault, same day):**

| Worker shape | Base tokens | vs generic |
|---|---|---|
| `general-purpose` (the 0.10.12 dispatch) | 42,274 | — |
| `second-brain:sync-worker` (allowlist) | 15,760 | −63% |
| `second-brain:sync-worker-m365`, tools open, no disallow | 42,170 | −0.2% |
| `second-brain:sync-worker-m365` + disallowedTools | 29,165 | −31% |

The lesson under the numbers: the win is the tool surface, not the custom
system prompt — an open-tools agent costs the same base as a generic subagent.
The plaud/inbox worker (the request-heavy shape: paginated transcript fetches,
4–26 requests in the live run) gets the full −63%; the m365 worker (short:
one fetch, one reassemble, one write) keeps every MCP tool and still sheds the
heavyweight built-ins for −31%.

Live-run reference baseline (DryRunVault, 13 generic workers): 46,267 first
request, ~100k+ by end of a long worker, 13.8M cache-read tokens total.
