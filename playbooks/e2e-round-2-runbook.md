# E2E round 2 — DryRun vault tune-up rehearsal (#107)

delaware-side material; never ships. Operator checklist for a delaware
consultant. Steps are marked **[Michael]** where they need the vault owner
personally — see the closing section for why.

This is Wave 2's anchor activity: bring the internal DryRun vault
(`~/Documents/DryRunVault`, structure-version 2, plugin 0.10.6 at time of
writing) to the current plugin via the real tune-up path, rehearse the full
daily loop, run the visual tier, then watch one real week. File findings
against the rubric in Phase 7.

## Phase 0 — Ship the plugin: dist re-cut

Needs push access to `DLW-INT-BTA-BELUX/sb-dist-dryrun` — get explicit
authorization before touching it. Mechanics live in
`playbooks/plugin-distribution.md`; do not duplicate them here. In short:

1. Scratch-clone the dist repo, `rm -rf plugin`, then
   `git archive origin/main plugin | tar -x` from the product repo.
2. Bump the README pin line:
   `Pinned contents: plugin **<X>**, template **structure-version 2**.`
3. Verify with the **real** linter — import `lint_skills` and `scan_cleanroom`
   from the product repo's `scripts/`, with `root=<dist checkout>` and the
   denylist from the product repo. A naive grep false-positives on exempted
   `upstreamed-from:` provenance lines; only the real linter is trustworthy
   here.
4. Commit using the established shape:
   `re-cut: plugin <X> (source main @ <sha>) — <summary>`, then push.
5. Verify via the GitHub API read-back — never the local copy.

**Checkpoint:** pushed `plugin.json` and README pin both read the new
version; linter clean.

## Phase 1 — Local plugin refresh **[Michael's machine]**

```bash
claude plugin marketplace update sb-accelerator-dryrun
claude plugin update second-brain@sb-accelerator-dryrun
```

Restart the session afterward.

**Checkpoint:** plugin list shows the new version.

## Phase 2 — `/upgrade-vault` rehearsal **[Michael's machine, Claude Code/Cowork, never Chat]**

Run `/upgrade-vault` against the DryRun vault. With no migrations beyond 001,
the expected result is `structure_version: 2`, `expected_version: 2`,
`pending: []` reported plainly, then stop.

**That is the pass condition, not a skip** — it rehearses the exact tune-up
path every deployed client hits, including the common "nothing to do" case.

**Checkpoint:** correct versions reported, explicit nothing-pending
statement, no crash, no false pending entry.

## Phase 3 — Base-drift check and hand-apply **[needs Michael's explicit go-ahead]**

Context: template `.base` fixes don't reach deployed vaults — this is issue
#117's mechanism gap, not something this round fixes.

At time of writing the DryRun vault carries the pre-#113 Meetings Triage
order (dead ✓ Reviewed / 🗑 Archive columns at 1440×900 — a live #66-class
defect) and the pre-#115 Projects Active order.

1. Re-run the diffs mechanically: vault copy vs `plugin/template/` for
   `Projects.base`, `Meetings.base`, `Decisions.base`, `Entities.base`,
   `People.base`.
2. Confirm #117 tracks the mechanism gap; comment observations there rather
   than filing duplicates.
3. Tell the vault owner what the hand-copy changes: the Triage column set
   narrows, and their manual column widths (the `columnSize` entries Bases
   wrote back) are dropped — they can re-widen by hand afterward. Get
   explicit go-ahead before touching the vault.
4. Back up, then copy:

```bash
cp ~/Documents/DryRunVault/30-projects/Projects.base ~/Documents/DryRunVault/30-projects/Projects.base.bak-preE2E2
cp ~/Documents/DryRunVault/20-meetings/Meetings.base ~/Documents/DryRunVault/20-meetings/Meetings.base.bak-preE2E2
cp plugin/template/30-projects/Projects.base ~/Documents/DryRunVault/30-projects/Projects.base
cp plugin/template/20-meetings/Meetings.base ~/Documents/DryRunVault/20-meetings/Meetings.base
```

5. Open the vault in Obsidian at 1440×900; confirm Reviewed/Archive render in
   Triage.

**Checkpoint:** order/groupBy shape matches template; controls visible; note
logged on #117.

## Phase 4 — ONE supervised full-loop pass **[Michael's machine, watching; interactive, no `--unattended`]**

Pick a day with real M365 meetings (and ideally a Plaud recording) — the
premise of round 2 is real accumulated state; don't fabricate inputs.

1. `/sync-recordings` — watch the plan-confirmation step (the step the
   scheduled runs bypass with `--unattended`).
2. Review-tick a meeting in Meetings.base → Triage in real Obsidian; confirm
   the fold on the next reconcile pass.
3. `/log-decision --foreground` on something real from that day.
4. `/update-entity` on the entity the meeting was against.
5. `/new-project` only if a genuine new engagement exists that day —
   otherwise record "not exercised this cycle." Don't invent a throwaway
   project in a real vault.
6. `/evening-sync` (interactive) — watch recap tense (today vs yesterday),
   wikilink resolution, calendar-availability line.
7. `/health-check` — record the numbers as the week's baseline. Do **not**
   share to delaware without a separate explicit ask.

**Checkpoint:** each skill ends with its documented final-line format; disk
state verified (note exists, last-updated bumped, recording stem in
`20-meetings/`); decision note has `reviewed: true` and both sides of any
supersession edge. If the Plaud path wasn't exercised, say so in the
write-up.

## Phase 5 — Visual tier (local-only, never CI)

1. Snapshot **excluding secrets** into the main checkout's gitignored
   `test-vaults/`:

```bash
rsync -a --exclude='99-workflow-config/secrets/' --exclude='.DS_Store' \
  ~/Documents/DryRunVault/ test-vaults/$(date +%F)-dryrun-e2e2/
```

   (The vault carries a real scoped GitHub PAT at
   `99-workflow-config/secrets/feedback-token`; the probe never needs it.)

2. `python scripts/obsidian_probe.py doctor`
3. `python scripts/obsidian_probe.py up --vault test-vaults/$(date +%F)-dryrun-e2e2`
4. `python scripts/obsidian_probe.py tour --out .obsidian-probe-out-dryrun-1920`
5. `python scripts/obsidian_probe.py --width 1440 --height 900 tour --out .obsidian-probe-out-dryrun-1440`
6. `python -m pytest scripts/tests -q -m obsidian`, then again with
   `SB_PROBE_OUT=.obsidian-probe-out-dryrun-1440`. Expect the basesim row
   cross-check to self-skip on a non-pristine vault (documented behavior) —
   that skip means the screenshots carry that assertion class, not that it
   passed.
7. Actually read the screenshots — legibility, spacing, empty states, and
   that Reviewed/Archive/Duplicate-of are present at 1440×900. This step
   cannot be automated.
8. `python scripts/obsidian_probe.py down`

**Checkpoint:** no `.bases-error`, no zero-row views, headers match
`displayName`s, evening-sync markers invisible in Live Preview, screenshots
reviewed and noted.

## Phase 6 — One real week of the scheduled loop

The existing scheduled tasks stay untouched — their SKILL.md wrappers are
version-stable by design, resolving `${CLAUDE_PLUGIN_ROOT}` at runtime. Do
not edit them for this round.

- `dryrun-sync-recordings`: every 2h weekdays 08:22–16:22.
- `dryrun-evening-sync`: 18:52 Mon–Fri.

The machine must be awake for the windows; sibling BusDev tasks stay paused
per the wrappers' cross-vault hazard note.

**Daily checkpoint (5 min):** read
`99-workflow-config/logs/routine-runs.log` — each run ends in a documented
final-line shape, no `-INCOMPLETE`; spot-check that `20-meetings/` gained the
claimed stems and the daily note has a fresh mtime.

**End-of-week checkpoint:** `/health-check` diffed against the Phase 4
baseline — counts moved consistently with the actual week, daily-note
coverage 100% of working days, no growth in unparsed decisions.

## Phase 7 — Exit review and filing

1. Re-run `/upgrade-vault` (cheap; confirms nothing regressed mid-week).
2. Compile findings from Phases 2–6 against the rubric:

   **P0 (files against Wave 3):** data loss/corruption of user-authored
   content; silent success (reports complete, disk disagrees); dead control
   on a client-realistic surface at 1440×900; broken first instruction;
   anything forcing manual repair to reach a working state; materially wrong
   client-facing narrative (tense, dates, fabricated content in recaps or
   dossiers).

   **Minor (Unscheduled):** cosmetic/prose drift; virtualized-off-screen
   columns the loop doesn't depend on; anything already tracked (link #117
   rather than duplicating); explicitly predicted one-time transients — e.g.
   #112's "a few projects queue one extra update on the first post-upgrade
   run, then converge" is expected unless it fails to converge by run two;
   DryRun-rig-specific quirks.

   **Tie-break:** "Would this stop a consultant closing a real client's
   tune-up with a clean conscience?" → P0. "Would only a perfectionist
   notice?" → Unscheduled.

3. Write the exit statement mapping #107's three criteria explicitly, and
   state the Phase 3 hand-copy separately: "`/upgrade-vault` required zero
   manual repair to the migration chain; one known, out-of-band, non-lossy
   `.base` hand-copy was applied and is tracked as #117."

## What needs the vault owner personally

- **Phase 0:** authorizing the dist push.
- **Phases 1–6:** their machine, M365, and Plaud.
- **Phase 3:** the go-ahead before the hand-copy.
- Any Restricted-Mode trust click, wherever it lands.
- **Phase 4** is deliberately supervised — never run unattended.
