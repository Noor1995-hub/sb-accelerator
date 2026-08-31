# Lessons

Pitfalls agent sessions in this repo have hit. Append entries as they happen
(date, what went wrong, the rule that prevents it). Patterns that recur get
promoted into `CLAUDE.md`.

## 2026-08-23 — a subagent's `git checkout` orphaned the controller's commit

**What went wrong.** During subagent-driven execution of the object-skills
port, a review subagent wanted to run the test suite at the exact commit it
was reviewing, so it ran `git checkout <sha>` in the worktree — the same
worktree the controller session was still committing to. The controller's next
commit was parented on that detached HEAD instead of the branch tip. When HEAD
returned to the branch, the commit became unreachable: present in the object
database and reflog, absent from `git log` on the branch.

It was recovered with `git cherry-pick <sha>` and nothing was lost, but only
because the reviewer noticed the anomaly in its own output and reported it
instead of finishing quietly. A silent version of this loses work to the next
`git gc`.

**Why it bites here specifically.** Parallel agents in one worktree share one
`.git` and one index. Subagents reason locally — "I need the code as it was at
that commit" — and reach for the tool that changes global state. Nothing in the
worktree warns them another writer exists.

**It happened twice.** The second time, a *different* review subagent detached
HEAD to `e344f97` and left it there. No commit was orphaned — the branch ref
was intact and the working tree clean — but the next implementer found its own
target file absent from disk, because the worktree was sitting at a commit
predating the file. It correctly refused to mutate anything, diagnosed the
state read-only, and reported BLOCKED.

**So the prohibition below is necessary but not sufficient.** Two different
subagents violated it despite explicit, prominent instructions. Reviewers
reason locally — "I need the suite as it was at that commit" — and reach for
the tool that changes global state. **Verify controller-side instead of
trusting compliance:** after every subagent returns, run
`git symbolic-ref -q HEAD` and reattach if it comes back empty. That check is
cheap, it is yours, and it does not depend on anyone else behaving. Checking
`git log` is not enough — it looks identical detached.

Also seen in the same session: a `git stash` commit
(`WIP on feat/object-skills-port`, two parents) left dangling by some agent.
Its content was already committed, so nothing was lost, but `stash` belongs on
the prohibited list for the same reason.

**The rule.** Every subagent dispatch, reviewer and implementer alike, carries
an explicit prohibition:

> Do not run `git checkout`, `git switch`, `git reset`, `git stash`, or
> `git rebase` in this worktree. Another session commits here concurrently and
> those commands will orphan its work. To read a file at a specific commit use
> `git show <sha>:<path>`, which needs no working-tree change. To inspect a
> range use `git diff A..B` or `git log`.

`git show` covers essentially every legitimate reviewer need. A reviewer that
genuinely must *execute* code at another commit should copy it out to a
scratch directory rather than move HEAD.

**Also worth knowing:** artifacts under `.superpowers/` (and `.sdd/`) are
gitignored, so a stray checkout does not revert them. Generated briefs stay
valid across this class of accident — but regenerate them anyway after
reconciling, since they may have been produced from a plan file that was
briefly at the wrong revision.

## 2026-08-23 — three backticks cannot fence code that contains vault content

**What went wrong.** An implementation plan carried the full source of a Python
module inside a ` ```python ` block. The module builds a project `index.md`,
so its template string contains Dataview query blocks — themselves fenced with
three backticks. The inner block's closing fence terminated the outer one, so
the code block ended two-thirds of the way through the function. Every
renderer, every extraction script, and any agent reading the file sees a
truncated module and the remainder as loose prose.

It surfaced only because the module was extracted and compiled before dispatch:
`SyntaxError: unterminated triple-quoted f-string literal`. Read as prose it
looks complete — the cut lands between two functions.

**Why this repo hits it more than most.** Almost everything here embeds vault
content. Project index bodies carry Dataview blocks; `SKILL.md` files carry
bash and JSON blocks; the ontology carries fenced YAML that is itself the
normative schema. Any doc quoting that content nests fences by default.

**The rule.** A fenced block that contains another fenced block needs **more
backticks than its deepest child** — four outside, three inside. This holds for
plan files, `SKILL.md` bodies, briefs, and PR descriptions alike. To check a
file before trusting it:

```bash
python3 - <<'PY'
import pathlib, re, sys
OPEN = re.compile(r'^(`{3,})([a-zA-Z][a-zA-Z0-9]*)\s*$')
CLOSE = re.compile(r'^(`{3,})\s*$')
for path in sys.argv[1:]:
    lines = pathlib.Path(path).read_text().split("\n")
    i = 0
    while i < len(lines):
        m = OPEN.match(lines[i])
        if not m:
            i += 1
            continue
        ticks, j = m.group(1), i + 1
        while j < len(lines):
            c = CLOSE.match(lines[j])
            if c and len(c.group(1)) >= len(ticks):
                break
            im = OPEN.match(lines[j])
            if im and len(im.group(1)) <= len(ticks) and len(ticks) == 3:
                print(f"{path}:{i+1}: ```{m.group(2)} truncated by ```{im.group(2)} at line {j+1}")
            j += 1
        i = j + 1
PY
```

**A related trap in tooling, not content.** A non-greedy extraction regex
(`` ```python\n(.*?)\n``` ``) silently stops at the first inner fence even when
the outer block is correctly four backticks. Match the fence length with a
backreference instead: `` (`{3,})python\n(.*?)\n\1 ``. Otherwise a correct
document still yields truncated code.

## 2026-08-23 — `checks: read` does not fix the review job's check-runs 403

**What went wrong.** `abca557` (#30) added `checks: read` to
`claude-code-review.yml`'s `permissions:` block to stop
`gh api repos/{owner}/{repo}/commits/<sha>/check-runs` returning 403. It
did not work. On PR #33 the job token was minted **with** `Checks: read`
(visible in the run log's `GITHUB_TOKEN Permissions` group) and the call
still failed:

```
{"message":"Resource not accessible by integration", "status":"403"}
```

**Why.** `claude-code-action` does not give the agent `GITHUB_TOKEN`. It
mints its own GitHub App installation token — which is why review comments
are authored by `claude[bot]` and not `github-actions[bot]` — and that token
is requested with a hardcoded default scope set:

```
contents: write, pull_requests: write, issues: write
```

(`parseAdditionalPermissions` in `src/github/token.ts`; see
`test/parse-permissions.test.ts` for the defaults.) `checks` is not in it.
The workflow's `permissions:` block governs `GITHUB_TOKEN`, so it cannot
widen a token the agent never uses. The org's `claude` app installation
already carries `checks: write`, so the installation ceiling was never the
constraint — only the action's requested scope was.

The same cause takes out `gh pr view <n> --json ...statusCheckRollup`
(GraphQL: `Resource not accessible by integration`), so the step-1
eligibility guard still cannot see its own prior comments.

**The rule.** For anything the *agent* runs, token scope comes from the
action's `additional_permissions` input, not the workflow `permissions:`
block. Never reason about agent API access from `permissions:` alone. The
fix is on the action:

```yaml
additional_permissions: |
  checks: read
```

Consequence while unfixed: the reviewer cannot read CI outcomes at all. On
#33 it noticed, said so, and ran the suites itself — but a PR with red CI is
otherwise reviewed as though CI did not exist. Prompt constraint 3 currently
instructs a call the token cannot make.

## 2026-08-23 — the inline-comment delivery path works (first proof)

Every prior review run (#25, #28, #30) took the "No issues found" route,
which delivers through `Bash(gh pr comment:*)`. The inline path was
configured but unproven — the exact failure mode that bit the sibling repo
`bta-agents-portal`, where reviews ran but wrote no inline comments.

Exercised deliberately on PR #33 with two planted bugs. It works:
`--comment` + `track_progress: false` +
`mcp__github_inline_comment__create_inline_comment` in `--allowedTools`
produced two comments on `pulls/{n}/comments` (the inline endpoint) anchored
to the exact offending lines, each carrying a `suggestion` block, and zero
issue-comments. Both findings survived the validation subagents, including
a deliberately *silent* one (a guard gutted without any test going red).

Also confirmed: **no orphaned-agent race.** All subagents ran in the
foreground, the run ended `subtype: success`, and the post-action step
logged `No buffered inline comments` — i.e. the MCP tool posted live during
the session rather than leaving work for the cleanup step. The prompt
constraint pinning foreground execution is doing its job; keep it.

Cost of that run: $1.87, 17 turns, 351s — in line with the $1.63 median.

**Method, if this needs re-verifying.** Open a throwaway PR carrying a bug
that clears the plugin's severity bar ("will fail to compile or parse" or
"will definitely produce wrong results regardless of inputs"), do not touch
`claude-code-review.yml` in it (that trips the action's workflow-validation
self-skip and no review runs), then close it unmerged. Do not advertise the
bug as deliberate in the title or body — the orchestrator reads PR context
and may treat it as intentional.

## 2026-08-23 — what actually gets denied in the review job

PR #33's run recorded `permission_denials_count: 6`. None of them were the
entries #30 added. The taxonomy, which is more useful than the count:

- **`python -c` / `python3 -c` — 3 denials.** The allowlist covers
  `-m pytest` and the two named scripts, not arbitrary `-c`. This cost the
  ontology validation agent its empirical proof; it fell back to static
  evidence and flagged the downgrade in its own report. Allowing `-c` means
  allowing arbitrary code execution in the review job — a real tradeoff, not
  an obvious win. Decide it deliberately rather than by omission.
- **Compound commands — 2 denials.** `A; B` and multi-line scripts are
  rejected *whole* if any part is not allowed. One was killed by a trailing
  `echo "exit: $?"`, another by a `git checkout` in the same line as an
  allowed pytest call. Agents batch commands by reflex; each batch is
  all-or-nothing.
- **Backticks inside a quoted pattern — 1 denial.** An agent grepping the
  ontology doc for the yaml fence marker was rejected with
  `Unanalyzable backtick body in double-quoted string gap`:

  ````text
  grep -n "require\|^object:\|```yaml" ontology.md
  ````

  Repo-specific hazard: the ontology's normative schema lives in fenced yaml
  blocks, so grepping for the fence marker is the natural first move here.
  Single-quote the pattern to avoid it.

**Also observed:** plain `grep`, `sed`, `find`, `head`, `wc` and `cat` all
ran fine despite not appearing in `--allowedTools`. So the list is not a
strict whitelist over all of Bash — safe read-only commands pass. What gets
stopped is non-listed interpreters, compound commands, and anything the
safety analyser cannot parse. The comment in `claude-code-review.yml`
("Without an explicit allowlist the action denies these in headless mode")
overstates this.

The three variants added in #30 (`python3 -m pytest`,
`git --no-pager show:*`, `git fetch:*`) went **unused** this run — agents
reached for `python -m pytest`, plain `git show HEAD:<path>`, and
`git log <base>..<head>` (which needs no fetch, since `fetch-depth: 0`
already has the history). Keep them as insurance, but they were not what
was blocking.

## 2026-08-25 — piping `obsidian_probe.py tour` truncates it, and the skip hides that

**What went wrong.** The visual pass for #68 ran
`python3 scripts/obsidian_probe.py tour | tail -3` — the obvious thing to do
with a command that prints one line per surface and a summary at the end. The
tour stopped partway (6 of 17 surfaces on one run, 12 on the next), so it never
reached the line that writes `summary.json`. Then
`python -m pytest scripts/tests -q -m obsidian` reported **8 skipped**, not 8
failures, because `test_obsidian_render.py`'s module-scoped `tour` fixture skips
when `summary.json` is absent. Skips scroll past as green. The run read as
"visual verification done" while nothing had been verified — a silent false
pass, which is the one outcome this harness exists to prevent.

The mechanism is not pinned down: `tail` reads to EOF, so this is not a plain
SIGPIPE. But it reproduced across runs and stopped the moment the pipe became a
redirect.

**Why the skip cannot save you.** It is deliberate and correct — it is what
CI's Ubuntu runners see — but it cannot tell "no Obsidian on this machine" from
"the tour you just ran died". A broken capture and an unattempted one look
identical.

**The rule.** Never pipe `tour`. Redirect, then read the file:

```bash
python3 scripts/obsidian_probe.py tour > /tmp/tour.log 2>&1; tail -3 /tmp/tour.log
```

And check the capture before trusting the pytest result: the tour's own last
line must read `17 surfaces -> …`, and `summary.json` must exist. A green
`-m obsidian` run showing `8 skipped` is not evidence; only `8 passed` is.

A truncated tour also leaves the instance wedged — the next `tour` dies with
`The CLI is unable to find Obsidian`. See the wedged-instance entry below.

## 2026-08-25 — Dataview is not initialised on a vault's very first open

**What went wrong.** The first `tour` after
`make_test_vault.py test-vaults/<name> --with-plugins` reported
`dataviewTables: 0, dataviewErrors: 0` on *every* note surface, and
`test_project_indexes_render_dataview_tables` failed. Nothing was wrong with
the vault: a `down` / `up` / `tour` cycle against the same, already-opened
vault rendered 2 tables and the test passed.

**The tell.** Zero tables *and* zero errors is the signature of "the plugin
never ran", not of a broken query — a Dataview block that fails renders
`.dataview-error`, which the tour counts separately. Tables with zero errors is
a pass; zero of both is a capture problem, and chasing it as a rendering bug
wastes the session.

**Why.** On a vault's first open the app is still settling community plugins —
trust, plugin load, Dataview's own index build — and the tour drives surfaces
faster than that finishes. The fixed `PROBE_VAULT_ID` means the Restricted Mode
dialog is usually not *shown* again, but inheriting the trust is not the same as
having the plugin loaded and indexed.

**The rule.** A first-open capture is not a trustworthy baseline. Build the
vault, `up`, then `down` / `up` / `tour` and capture on the second open. Cheap,
and it removes a whole class of phantom failure.

## 2026-08-25 — `--width`/`--height` are global options, not `up` options

**What went wrong.** Two things, in order.

`obsidian_probe.py up --vault test-vaults/<name> --height 2400` fails with
`unrecognized arguments: --height 2400`. Both options live on the top-level
parser, not on `up` or `tour`, so they have to precede the subcommand:

```bash
python3 scripts/obsidian_probe.py --height 2400 --width 1500 \
    up --vault test-vaults/<name>
```

Placed correctly, that brought the instance up — `up` printed
`probe instance driving <path>` — and then every subsequent CDP call failed
with `The CLI is unable to find Obsidian`. Reverting to the default 1920×1200
fixed it immediately.

**The rule.** Leave the geometry alone. The default is pinned for a reason —
Bases virtualises columns by width, so captures are only reproducible at a known
width — and on this machine a non-default size appears to break the instance
outright rather than merely change the frame. If you ever do need another size,
confirm a CDP call answers before trusting the instance — `up` applied the
resize and reported success, and the instance was still dead.

## 2026-08-25 — a wedged probe instance is the normal failure mode

Roughly one tour in three during the #68 pass died mid-run with one of:

```text
unparseable CDP reply for …
TypeError: Cannot read properties of undefined (reading 'selectView')
The CLI is unable to find Obsidian
```

All three are transient, and none of them meant anything was wrong with the
vault. The fix was the same every time: `down`, then `up`, then `tour` again.
The `selectView` one is the Bases view switcher reaching for a controller on a
leaf that is not yet the view it expected — a timing loss, not a broken `.base`.

**The rule.** Budget for retries, and treat a failed tour as a failed tour
rather than as a finding: get one clean end-to-end run before concluding a
surface is broken. The converse also holds — do not paper over a *reproducible*
failure with retries. If the same surface dies at the same point three times,
that is a bug.

## 2026-08-25 — two sessions cannot share the visual-verification probe

**What went wrong.** Mid-way through the visual pass for #60 items 4–5, the
probe stopped answering for the vault it had been launched on. `obsidian_probe
up --vault test-vaults/2026-08-25-entity` printed the entity vault, and ~15
seconds later `doctor` reported a *different* vault — three different ones
across successive attempts, one of them a directory that had not existed when
the run started. A `dev:screenshot` taken in between captured a vault that was
not under test at all: confidently wrong evidence.

The cause was another agent session running its own visual pass concurrently — the #68 pass whose retry advice is the entry above. Those
same three errors are what contention looks like from the inside, so "budget for retries" is right but incomplete: a retry loop that does not
check *which* vault came back re-points at the wrong one and keeps going.
Both used the default profile `~/.sb-probe`, and the probe registers every
vault under one fixed id (`PROBE_VAULT_ID`, so the Restricted Mode click
survives fresh vaults). So the two runs shared one profile, one CLI socket at
`$HOME/.obsidian-cli.sock`, and one registry entry — each `up` overwrote the
other's, and Obsidian persisted whichever window closed last. Killing the
probe processes and pinning `obsidian.json` by hand did not hold: the other
session simply claimed it again seconds later.

**Why the guard does not catch it.** The guard resolves
`app.vault.adapter.basePath` and refuses anything outside `test-vaults/` —
which is exactly what it promises, and no help here. Both vaults were under
`test-vaults/`, so it reported `ok` for the wrong one. It defends against
touching a real vault, not against touching the wrong test vault.

**The rule.** The probe is a single-tenant resource. Before starting a visual
pass, check whether one is already running:

```bash
pgrep -f 'user-data-dir=.*sb-probe' >/dev/null && echo "probe in use — wait"
cat ~/.sb-probe/userdata/obsidian.json   # whose vault is registered?
```

If it is in use, wait rather than launching — and never `pkill` it, which
destroys the other run's instance mid-tour. `--home` starts an independent
profile, but a fresh one needs the one-time Restricted Mode click, so it is
not a fix an agent can apply alone: without trust, Dataview never loads and
every Dataview assertion passes against an unrendered block.

**Verify the vault after the fact, not just before.** `tour` writes the
guarded path into `.obsidian-probe-out/summary.json`. Read it before trusting
any capture — that field is what confirmed the 17 surfaces in this run were
genuinely the intended vault, and it is the only durable record of which vault
answered. Ad-hoc `dev:screenshot` calls outside `tour` carry no such record,
which is why the wrong-vault capture was believable.

## 2026-08-25 — `--home` *is* usable alone, if the capture vault has no plugins

**Context.** The entry above concludes that `--home` is "not a fix an agent can
apply alone", because a fresh profile needs the one-time Restricted Mode click
and an agent cannot click it. That is right about the modal and wrong about the
conclusion: the modal only appears for a vault that *has* community plugins.

**What worked.** During the #56/#57 pass the shared profile was already taken
(the #60 items 4–5 run), so rather than wait or fight for it:

```bash
python scripts/make_test_vault.py <vault>          # note: no --with-plugins
rm -f <vault>/.obsidian/community-plugins.json
rm -rf <vault>/.obsidian/plugins
python scripts/obsidian_probe.py --home ~/.sbp2 up --vault <vault>
```

No modal, no contention, and the other session's instance was never touched.
`doctor` confirmed the right vault, and `down` with the same `--home` stopped
only that instance.

**What it costs, and what it does not.** CSS snippets, callouts, marker hiding
and core markdown all still render — `.obsidian/snippets/` and
`appearance.json` ship in `template/` and are core Obsidian features. What is
absent is the Minimal theme (so heading colours are the default), Notebook
Navigator (the sidebar shows "Plugin no longer active") and Dataview.

The Dataview loss is safe rather than silent, which is the important part:
`test_obsidian_render.py` asserts `dom["dataviewTables"]` truthily, so a vault
with no Dataview plugin makes those tests **fail loudly** at zero tables — it
does not pass them against an unrendered block. The hazard the entry above
warns about belongs to a trusted-but-uninitialised profile, not to this.

**The rule.** For a question about core rendering — a callout, a snippet,
marker visibility, markdown structure, **or a `.base` view** — a plugin-free
vault on a private `--home` is a legitimate way to get an answer without
queueing behind another session. Only Dataview and the navigator need the
shared profile and its accepted trust. Either way, state in the report which
plugins were absent rather than implying full fidelity.

`.base` belongs on the first list, not the second: **Bases is a core plugin**,
enabled by `"bases": true` in `template/.obsidian/core-plugins.json`, and it
appears in neither `community-plugins.json` nor `scripts/plugin-pins.json`.
Restricted Mode gates community plugins, so it never gated Bases. The first
version of this entry put `.base` on the wrong side — an inference from "the
tour's base captures came from the plugin-complete vault", never measured,
which is precisely the mistake the next entry is about.

## 2026-08-25 — "no template surfaces touched" does not mean "skip the visual tier"

**What went wrong — nearly.** The merge queue's read of #56/#57 was that it
needed no visual pass, because its diff touches no `.base` file and nothing
under `template/`. That heuristic is reasonable and it has a hole. The change
added an attribute to a marker the CLI writes *into* a daily note
(`<!-- evening-sync:recap:begin inputs=<16 hex> -->`), and the vault's shipped
CSS snippet hides marker lines by matching a shape:

```css
.markdown-source-view.mod-cm6 .cm-line:has(> .cm-comment:only-child) { display: none; }
```

`:only-child` is the fragile part. Had `inputs=a1b2…` caused CodeMirror to
tokenise the comment into more than one span, the selector would have stopped
matching and every stamped note would have shown machine bookkeeping in Live
Preview — the view the exec types in. It does still match, verified live
(`markerLines: 4`, `markerLinesHidden: true`), but that was a measurement, not
a deduction.

**Why the shipped test does not catch it.** `test_evening_sync_markers_are_hidden_in_live_preview`
runs against the daily note the tour picks, and `surfaces()` takes the **first**
sorted `60-daily-notes/*.md` containing `evening-sync` and then breaks — which
in the demo vault is `2026-06-01.md`, not the packed `2026-06-15.md`. That
fixture ships unstamped, so the assertion exists, passes, and never sees the
stamped form.

**And that gap is cheap to close** — the first version of this entry said
otherwise, wrongly. It claimed stamping a fixture would break
`test_fresh_fixture_is_exactly_what_daily_note_write_renders`; that test pins
`2026-06-15.md`, not the captured `2026-06-01.md`, and nothing in the suite
pins `2026-06-01.md` byte-for-byte. A placeholder attribute
(`inputs=0000000000000000`) parses under the marker grammar and would put the
stamped shape in front of the CSS assertion.

A placeholder is also the *right* value, rather than merely a convenient one. A
real digest is a hash over the fixture vault, so committing one bakes in a
value that every later fixture edit falsifies — churn in the diff, and a
committed number that means nothing to a reader. It is not a hazard at runtime:
the skip fires only on a stamp that **matches** the freshly computed
fingerprint, so a stale stamp fails the equality, falls through to the
regeneration branch, and gets restamped. Measured, not reasoned:

```text
write 1  (fresh note)                     inputs=1f5e8f3933f59593  skipped=False
write 2  (unchanged inputs, stamp matches)                         skipped=True   changed=False
write 3  (stamp tampered to a stale value)                         skipped=False  changed=True
```

The dangerous stamp is the *matching* one, which is why `daily-note write`
**strips** the attribute when it rewrites a recap with no `recap_window` rather
than leaving it: a stamp left standing over prose whose inputs nobody verified
could later match and skip.

The lesson inside the lesson: three errors went into these two entries — `.base`
on the wrong side of the rule, the wrong test named, and the skip condition
stated backwards — and all three were deductions presented as findings, inside
an entry whose own rule is that a measurement is not a deduction. Each was
caught by the automated review on the PR, not by me. Before writing a mechanism
into a lessons entry, check the file, check the test name, and if the claim is
about behaviour, **run it** — the three-line script above took under a minute
and would have caught the third error before it shipped.

**The rule.** Ask what the change makes appear in a note, not only which files
it edits. A diff confined to `plugin/lib/` can still alter what template CSS
has to match, and the pinned render assertions only cover the shapes the
fixtures happen to contain. When a change alters *written* content, either
capture it live or say plainly that it went unverified.

These seven entries are about the probe. Traps about what the vault renders —
column virtualisation, occluded windows returning stale frames, non-pristine
vaults poisoning the row cross-check — live in `docs/visual-verification.md`
under "Traps worth knowing".

## 2026-08-26 — an MCP tool grew pagination and the skill kept calling it once

**What went wrong.** `/sync-recordings` fetched a Plaud transcript with one
`mcp__plaud__get_transcript` call and passed the result to `plaud reassemble`.
At some point the tool became paginated: it now answers `limit` utterances at
a time (50 by default) with `total`, `offset` and `next_cursor`. Verified live
while fixing issue #82 — a 32-minute meeting reports `total: 142`. So the
skill was writing meeting notes from the first 50 utterances of every long
recording, and `duration_min` (computed from the last segment's `end_time`)
reported roughly a third of the meeting's real length.

Nothing failed. The 50 segments were well-formed, `_render_transcript` took
its normal dict branch, the blob rendered, the note was written and the
recording was marked synced in the ledger — so it never retried. The only
symptom was meeting notes that felt thin, which reads as a weak transcript.

**Why it bites here specifically.** A skill's contract with an MCP tool is
prose in a `SKILL.md`; nothing versions it and no test exercises it, because
the tool is not in the repo. Our own CLI is fully covered — `plaud.py` had 20
tests — and every one of them fed it a payload *we* wrote. The tests agreed
with the code and both were describing a response shape the connector no
longer sent alone.

**The rule.** When a skill hands an external tool's raw output to the CLI, the
CLI must be able to tell whether it got all of it, and must refuse rather than
render a partial. `plaud reassemble` now takes one path per page, orders them
by each page's own `offset`, and checks the accumulated count against the
page's `total` — a missing page is an error naming both numbers. Where the
payload carries no such self-description, say so in the skill and treat the
absence as the risk it is. And when a fix touches an MCP call, spend one live
call reading the envelope before trusting the shape written down last time.

**Second instance (2026-08-31).** `outlook_calendar_search`: three skills
described a window as `utc_from`/`utc_to` parameters, but the live connector's
schema (read against a connected instance) takes `afterDateTime`/
`beforeDateTime` — and caps at 25 events per call, paging via the response's
`nextOffset`, which no skill mentioned. Same failure shape: nothing errors, a
busy window just syncs its first page. The closing rule above is the fix both
times — read the envelope live before trusting the prose.

## 2026-08-26 — three regexes for one timestamp, agreeing with nobody

**What went wrong.** `plaud.reassemble` and `m365.reassemble` returned
`recorded_local` as `%Y-%m-%d %H:%M:%S`. Both consumers rejected it:
`meeting.write` matches `\A\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?\Z` and
`sync collide` matches `\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\Z`. Every recording in
the first live Session 1 cost a rejection round trip, and `SKILL.md` papered
over it with an instruction to "swap the space for `T`, drop the seconds" —
an agent-side transformation of a value the CLI had just produced.

**The rule.** A value one CLI subcommand emits for another to consume is an
internal interface: assert it against the *consumer's* real validator, not
against a string literal. The test that now guards this imports
`meeting._DATETIME_RE` and `syncjob._COLLIDE_START_RE` and matches the live
output against both, so the three cannot drift apart again. A skill
instruction that reformats one CLI's output for another CLI is the smell —
fix the producer instead.
