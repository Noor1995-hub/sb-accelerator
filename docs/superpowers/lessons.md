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

> *Obsolete in part (2026-10-12):* Notebook Navigator was removed in #263
> (0.13.7); the sidebar is now Obsidian's core Bookmarks menu, so a
> plugin-free vault shows the real sidebar. Only Dataview and the theme are
> still lost.

The Dataview loss is safe rather than silent, which is the important part:
`test_obsidian_render.py` asserts `dom["dataviewTables"]` truthily, so a vault
with no Dataview plugin makes those tests **fail loudly** at zero tables — it
does not pass them against an unrendered block. The hazard the entry above
warns about belongs to a trusted-but-uninitialised profile, not to this.

**The rule.** For a question about core rendering — a callout, a snippet,
marker visibility, markdown structure, **or a `.base` view** — a plugin-free
vault on a private `--home` is a legitimate way to get an answer without
queueing behind another session. Only Dataview and the navigator need the
shared profile and its accepted trust. (Navigator: obsolete since #263, see
the note above.) Either way, state in the report which
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

## 2026-09-02 — a fresh probe profile silently boots in Restricted Mode

**What went wrong.** In a new worktree (new per-worktree probe home), the
first `up` printed the fresh-profile notice and everything *looked* fine:
doctor green, tours captured, Bases rendered. But both Dataview render tests
failed with `dataviewTables: 0, dataviewErrors: 0` — the block wasn't
erroring, it wasn't being processed at all. The known first-open lesson
(down/up, capture on the second open) didn't fix it, because the cause was
upstream: the Restricted Mode consent was never given in this profile, so
community plugins never *load* even though `community-plugins.json` lists
them as enabled. The cloaked window meant nobody ever saw the trust dialog.

**How to tell.** Over CDP, `Object.keys(app.plugins.plugins)` is empty while
`app.plugins.manifests` is populated, and
`localStorage.getItem('enable-plugin-' + app.appId)` is null. That triple is
Restricted Mode, not an indexing delay.

**The remedy.** `eval_js("app.plugins.setEnable(true); 'ok'")` — the same
state transition as clicking *trust author and enable plugins*, performed by
the operator in the throwaway probe profile. This does not soften the design
rule: consent still cannot ship as files, and nothing in the repo pre-grants
it; it is the one click per probe home, made scriptable when no human is at
the keyboard.

> *Obsolete (2026-10-12):* the paragraph below is about Notebook Navigator,
> removed in #263 (0.13.7). It no longer ships, so there is no modal to
> dismiss. The Restricted Mode remedy above still holds.

**The photobomb that follows.** The moment plugins first load, Notebook
Navigator pops its "What's new" release-notes modal, which then sits in front
of *every* surface the tour captures (the DOM assertions still pass — only
the PNGs are ruined). Dismiss it once via its own button so it persists:
`(() => { const c = document.querySelector('.modal-container'); const b =
c && (c.querySelector('button.mod-cta') || c.querySelector('button'));
if (b) b.click(); })()` — then recapture.

## 2026-09-03 — hard-wrapped prose renders as hard line breaks in the vault

**What went wrong.** Decision notes and `Start here.md` looked "too narrow"
next to meeting and daily notes, and the first instinct was the Minimal
theme's line width. The theme was fine: those files were the only ones with
source hard-wrapped at ~76 columns (`textwrap.fill` in `decision.py`, hand
wrapping in the template prose). Obsidian ships with *strict line breaks*
off, so a single newline renders as `<br>` in Reading view, and Live Preview
shows source lines regardless. Every note the CLI writes as one long line per
paragraph soft-wraps to the theme width; every hard-wrapped one stops at
column 76.

**Rule.** Vault-facing markdown — emitted by `vaultlib` or shipped in
`plugin/template/` — is one source line per paragraph. Wrap the repo's docs
and code comments; never the notes. When a rendered note looks narrow, diff
its line lengths against a note that looks right before touching the theme.

## 2026-09-03 — "properties collapsed by default" is a CSS inversion, and needs one `!important`

**What went wrong.** Obsidian has no default-fold setting for properties.
The snippet inverts app.css's `.metadata-container.is-collapsed
.metadata-property { display: none }`. Three things bit in turn, each only
visible over CDP in the probe:

1. `display: none` on the rows made the "Add file property" command type
   into an invisible input — a display:none element cannot take focus, so a
   `:focus-within` reveal never fired. Clip instead (`max-height: 0;
   overflow: hidden` on `.metadata-properties`); clipped elements focus.
2. Clicking the heading also writes an inline `display: none` on
   `.metadata-content` from JS, not from app.css. An inline style beats every
   stylesheet rule except an `!important` one, so the expanded state needs
   `display: block !important` there — the first computed-style check said
   the rows were `flex` while their parent was `none`, and a screenshot with
   the chevron down and no rows is what finally showed it.
3. Fold state persists per file, so the memory is inverted too: a file the
   user expanded reopens expanded. Acceptable, and documented in the snippet.

**Rule.** For any CSS that fights Obsidian's own state, verify in the probe
with computed heights (`getBoundingClientRect().height`), not `display` of
the innermost element, and read the inline `style` attribute of every
ancestor in both states.

## 2026-09-03 — the review plugin's model pins are prose, and the action ignores them

**What went wrong.** Nothing visibly. The code review worked well for two
weeks — 80 findings across 41 PRs, none of them a false positive — while
running on a model the plugin never asked for. Across the 85 billed runs from
2026-08-22 to 2026-09-03 it cost **$371.00: mean $4.36, median $3.49, max
$11.88**, and the console Cost page grouped by Model put roughly **85% of it
on Opus**, 13% on Sonnet, 2% on Haiku.

That split is the inverse of the design. The `code-review` plugin's own
command file pins a model per step in prose: "use a Haiku agent" for steps
1, 2, 3, 5 and 7, and "launch 5 parallel **Sonnet** agents" for step 4 — the
five reviewers that do all the actual reading. It asks for Opus nowhere.

**Why the pins lose.** They are instructions to the orchestrator, not
configuration. With no `--model` in `claude_args`, `claude-code-action`
starts the session on its default (Opus) and the `Task` subagents inherit
the session model, so the prose is honoured only as far as the orchestrator
happens to pass a `model` override — which, measurably, is not far.

**Where per-run cost actually lives: in the run log.** The action writes
`claude-execution-output.json` and echoes it into the step, carrying
`total_cost_usd`, `num_turns` and `permission_denials_count` for that run:

```
gh run view <id> --log | grep -oE '"total_cost_usd": [0-9.]+'
```

Do not do what the first draft of this entry did and derive cost by
correlating daily console totals against billed run-minutes. That estimate
landed within about 8% here ($4.04 mean against the real $4.36), but it is
unnecessary work and it cannot attribute a single run. Read the field.

`permission_denials_count` from the same JSON is a free health signal worth
watching — 14 on the first Sonnet run — because a denied agent silently
downgrades to reading the code instead of running the tests (see the
2026-08-23 denials entry). The log carries the count only, never which tool.

**The remedy, and what it actually bought.** `--model claude-sonnet-5` in
`claude_args` (#156) — the plugin's own intended model, not a downgrade.
First pinned run (#157): **$2.84 over 11.8 min, one valid finding
delivered**, against the Opus mean of $4.36 and median $3.49. Real, but well
short of the 2.5x the per-token prices imply (Opus 5 $5/$25 per MTok against
Sonnet 5 $2/$10), because much of a run's bill is the orchestrator's own
turns and the Haiku steps, not the five reviewers. One run is one run; read
`total_cost_usd` across the next several before quoting a monthly figure.

**Do not trust a ported workflow's cost comments.** Ours quoted a $1.63
median that came from bta-agents-portal and cited PR numbers that do not
exist in this repo — 2.2x optimistic for us. Re-measure per repo.

## 2026-09-03 — a change to the review workflow cannot be tested from its own PR

**What went wrong.** PR #156 added a delivery assertion to the review job.
Its first run red-X'd, and the action step above it had "succeeded" in two
seconds having posted nothing:

> Skipping action due to workflow validation: Workflow validation failed.
> The workflow file must exist and have identical content to the version on
> the repository's default branch.

`claude-code-action` refuses to run when its own workflow file differs from
the copy on the default branch. The guard is sound — otherwise a PR could
rewrite the reviewer's config and walk off with `ANTHROPIC_API_KEY` — but it
exits with `outcome: success`, so from the outside it is indistinguishable
from a review that ran and found nothing.

**What it means.** Any edit to `claude-code-review.yml` takes effect on the
**first PR opened after merge**, never on the PR that makes it. Plan the
verification accordingly: assert the logic locally against real PR history
(the comment endpoints are read-only and free), then merge and spike-test
with a PR that touches no workflow file. #157 was that spike.

**How to tell.** Compare `git hash-object
.github/workflows/claude-code-review.yml` against the contents API's `.sha`
for the default branch — the same blob comparison the action makes. The
delivery assertion exempts itself on that condition; without the carve-out it
red-Xes every workflow-touching PR by construction.

**It also rewrites history.** Six of the first 82 PRs carry no `claude[bot]`
output of any kind — full cost, green check, nothing posted, merged
unreviewed. One of them, #30, edited this workflow file, so it was never
going to be reviewed at all. Five — #21, #22, #69, #102, #105 — are the
orphaned-agent race that constraint 1 of the prompt tries to pin.

**A census of this is a moving target, so re-run it rather than citing one.**
The first draft of this entry said seven, because the snapshot behind it was
taken while #155 was still open; #155's "No issues found" comment landed 58
seconds before it merged. The review on #157 caught exactly that — its own
small proof that the Sonnet-pinned reviewer still reads carefully.

---

## 2026-09-15 — a connector changed the spelling of its ids, and the exact-match ledger synced every recording twice

**What went wrong.** The Plaud MCP connector listed recordings as a bare
32-hex id from the first sync through the morning run of 2026-09-15, then
as `of_<hex>` — the same hash under Plaud's object-type prefix (its storage
paths hold the audio at `of_<hex>/oc_at_<hex>.mp3`) — from the afternoon
run on. The bare form now 404s on `get_file` and `get_transcript`. The
ledger keyed on the literal `source-recording-id` string, so a recording
synced in the morning was `new` again in the afternoon and got a second
meeting note. Two duplicates in the dry-run vault, resolved by hand.

Nothing errored. `sync dedup` did exactly what it was written to do, the
worker fetched a complete transcript, `meeting write` wrote a conformant
note. The only symptom was two notes for one meeting.

**The rule.** An id from an external system is a *reference*, not a string:
decide what its identity is (here the hash) and canonicalise at every
comparison **and** every write — `syncjob.canonical_id()` — so the ledger
converges instead of forking on the next upstream cosmetic change. Compare
canonical, but answer in the caller's spelling where the caller has to match
the answer back to the upstream listing (`sync dedup`). And this is the third
instance of the 2026-08-26 lesson: when a skill hands an external tool's
output to the CLI, spend one live call reading the envelope — the id shape
included — before trusting what was written down last time.

---

## 2026-09-16 — an instruction said "never rebuild this" twice, and the orchestrator rebuilt it anyway

**What went wrong.** Two `sync-worker-m365` subagents were dispatched with
calendar URIs carrying `%2F` where `outlook_calendar_search` had emitted
`-`. Both retried three times and returned `fetch-error`; Graph answered
400 `RequestBroker--ParseUri` every time. Two meetings went unsynced with
nothing to show for it but a count in the run log.

Event ids from that listing arrive in Outlook's URL-safe base64 variant,
and the listing percent-encodes only the padding `=` as `%3D`. The
orchestrator reversed that substitution and percent-encoded the result by
hand, so every `-` became `%2F`. Downstream, the connector decodes the id
out of the URI and splices the resulting raw `/` into the Graph request
path without re-encoding, so Graph reads the tail as unknown path
segments. `%2F` in a `calendar:///events/` URI is a strong fingerprint of
a rebuilt URI — someone re-encoded the `id`, or lifted `webLink`'s
`itemid` (the one field that carries the un-substituted spelling).

**A second lesson rode along, from the review of the fix.** The first
version of this entry, and of the docstring, called that encoding
"base64url". It is not: RFC 4648 §5 substitutes `-` for `+` (62) and `_`
for `/` (63), and Outlook's variant is the **inverse** — measured on three
paired `uri`/`webLink` values, `-` ↔ `/` and `_` ↔ `+`. The reviewer
caught the contradiction and proposed inverting the mapping to match the
RFC, which would have contradicted the wire and reintroduced the bug. The
defect was the *label*, not the mapping. Naming a format by a standard it
does not follow invites exactly that well-meaning correction, so the docs
now say which variant it is and that it is not the RFC's, and the test
fixtures carry both `-` and `_` so the correction fails in CI rather than
in a client vault.

The same review caught a false positive in the first fix: a rule refusing
any URI containing `%2F` would also have refused a *correctly* derived one,
because `event_uri()` encodes a literal `/` if an un-substituted id ever
arrives. A spelling cannot distinguish "rebuilt" from "legitimately
encoded"; Graph's own `RequestBroker--ParseUri` code, read after the
failure, can. Diagnose on the failure, not on the shape.

`SKILL.md` already forbade this **twice** — "values verbatim from the
listing, never rebuilt", and for `uri` specifically "never decode or
reconstruct it". Prose was not the missing piece.

**The rule.** Read the failure precisely before deciding whose bug it is.
The `id` was copied byte-perfectly at every hop — orchestrator routing file,
worker briefing, tool call. Only the value that had to be **transformed**
came out wrong. A model copying an opaque string is reliable; the same model
applying an encoding rule to it is not. So when a value must cross a
model-authored boundary, make the boundary a copy and put the transform in
the CLI (`m365.event_uri()`, surfaced as triage's `event_uri`). Restating
a rule the model already read and violated buys nothing.

**The corollary for triage.** The first reading of this was "connector bug,
file it upstream" — the brief that opened the investigation said so. One
live call each way disproved it: the listing's own `uri` returned 200 and
the hand-encoded form returned 400, which locates the defect above the
connector, not inside it. The connector's decode-without-re-encode is real
but latent, because nothing in the normal path emits that form. Two calls
were the difference between a fix and three weeks of chasing the wrong
layer.

---

## 2026-09-16 — the callout accents shipped inert, and the icon rendering is what hid it

**What went wrong.** 0.11.0's recap callouts declared
`--callout-color: 14, 165, 233` — the `r, g, b` triplet Obsidian used to
compose a tint from via `rgba(var(--callout-color), 0.1)`. Obsidian 1.13
consumes a *whole colour* through
`color-mix(in oklch, var(--callout-color) 10%, transparent)` instead, and its
app.css contains no `rgba(var(--callout-color)` at all. A triplet makes those
`color-mix()` calls invalid at computed-value time, so `background-color` falls
back to its initial `transparent`. Every recap callout in a released vault
rendered with no tint, no border, and a title in plain body text. The vault
owner reported it off the first real v2 daily note.

Nothing errored, the snippet loaded, and `--callout-icon` worked perfectly —
an icon id is read by JS and never goes through colour maths. So each callout
showed its correct custom Lucide icon and no colour, which reads like a theme
problem. The declared value and `getPropertyValue('--callout-color')` both look
right while it is broken; only `getComputedStyle(el).backgroundColor` shows the
collapse. `[!quote]`, on Obsidian's own built-in `#9e9e9e`, kept its tint in the
same render — the control that isolates it to our four declarations.

**The rule, three parts.**

*Read the consuming stylesheet, not the docs.* The triplet form is still what
the community docs describe. One regex over
`Obsidian.app/Contents/Resources/obsidian.asar` settled it in a minute and gave
the exact `color-mix()` expression to reason about. When a CSS custom property
feeds a function, the function's arity and unit expectations are the contract —
and they change between app versions, silently, because a bad custom-property
substitution is not an error, it is a fallback.

*A partly-working feature is worse than a broken one.* The icon working is the
whole reason this survived review, a release, and a vault upgrade. When two
mechanisms in one declaration fail independently, assert both — the render test
here checks the tint **and** the icon, so a snippet that stops loading entirely
is distinguishable from one whose values are wrong.

*The visual tier can only see what it tours.* Three separate gaps had to be
closed before the render tier could have caught this: the probe toured the
*earliest* daily note (so the capture showed the oldest recap shape in the
fixture set), `fixtures/demo-vault`'s latest daily note still carried a **v1**
recap (so no fixture exercised the v2 callouts at all), and
`test_fixtures_ontology`'s marker regex rejected the CLI-owned `inputs=`
attribute. A new rendered shape needs a fixture that *is* that shape, on the
surface the probe actually visits, or the tier is green on a screen the product
no longer draws.

**A fourth part, found by the Windows job in the same PR.** The fixture that
finally exercised the v2 recap was also the first to carry an
`<!-- evening-sync:recap:begin inputs=… -->` stamp, and Windows CI immediately
disagreed with macOS and Ubuntu about its value — `ce0435975b22effb` against
`1f298595a5c7118b`. Reproduced in a minute by rewriting the fixture tree to
CRLF locally, which is what a runner with `core.autocrlf=true` checks out.
`recap_fingerprint` hashed `path.read_bytes()`, so the stamp forked on line
endings; since a mismatched stamp *regenerates* the region, a Windows-hosted
vault overwrote a recap the vault owner had already read on every run.

`provenance.digest` had normalised CRLF to LF since the day it was written, and
its module docstring already gives this exact reason. The rule: **before
writing a content hash over vault files, look for the repo's existing digest
helper — do not reach for `hashlib` directly.** Three places had already met
this problem (the `plugin/vendor/**` `-text` rule in `.gitattributes`,
`provenance.digest`, and `asset_bytes()` in `test_migration_001`) and each
solved it locally; a fourth site that skipped the search shipped the bug. The
corollary for review: a hash of file bytes is a portability decision, so ask
what happens to it on the other platform before the CI matrix asks for you.

## 2026-09-23 — the review's cost pin was reversed for orchestrator quality

**What changed.** The 2026-09-03 entry above pinned the review to
`--model claude-sonnet-5` as a cost fix. That pin is now
`--model claude-opus-5-5`, by deliberate choice: the orchestrator is the
step that reads the diff, briefs the reviewers and validates their findings,
and Sonnet was judged too weak for it. bta-agents-portal made the same pin
the same day (its PR #518). Until then it had never set a model and was running
on `claude-opus-5[1m]`, the default of the Claude Code build `@v1` happened
to install, even though Opus 5.5 was already out.

**The rule.** A model pin optimises one axis. Say which one in the comment
beside it, so the next person can tell a cost decision from a quality
decision before reversing it. And pin rather than leave it unset: an
unpinned review moves models whenever upstream changes a default, and
nothing in the repo records that it happened.

**What this reversal costs.** The 2026-09-03 mechanism still holds: `Task`
subagents inherit the session model unless the orchestrator passes an
override. So an Opus session probably pulls the five step-4 reviewers back
onto Opus too, not just the orchestrator. For reference, the last Opus
period had a median of $3.49 over 85 runs, and the six runs under the Sonnet
pin had ~$1.61. Measure Opus 5.5 from `total_cost_usd` over several runs
after merge, and read the Cost page grouped by Model, before quoting a
figure. If the bill is the problem and the orchestrator is not, the lever to
try is keeping the orchestrator on Opus while forcing the reviewers onto
Sonnet — untested here.

## 2026-09-23 — the plugin's model pins were honoured all along; two entries misread them

**What went wrong.** The 2026-09-03 entry says the `code-review` plugin asks
for Haiku and "5 parallel Sonnet agents", "asks for Opus nowhere", and that
its pins lose because subagents inherit the session model. The entry just
above repeats that and predicts the reviewers would follow the orchestrator
onto Opus. Both are wrong. The plugin file (unchanged upstream since
2026-03-12, so it read the same when the 2026-09-03 entry was written) asks
for haiku in steps 1–2, sonnet for the PR summary, the two CLAUDE.md
reviewers and their validators, and **opus for the two bug reviewers and the
bug-finding validators**. The run logs show the orchestrator honours those
assignments: every one of the six Sonnet-pinned runs up to 2026-09-21 lists
`claude-opus-5[1m]` in `modelUsage`, and an Opus-session run in
bta-agents-portal lists Sonnet and Haiku.

So the 85%-on-Opus split before #156 was the plugin's design (Opus bug
agents) plus an Opus orchestrator, not ignored pins. The Sonnet pin moved the
orchestrator only, and reversing it brings back only the orchestrator's
cost, not the reviewers'.

**A second gap it exposed.** The plugin names models by alias, and aliases
resolve inside whichever Claude Code build `@v1` installs. v2.1.278 resolved
`opus` to `claude-opus-5`, so the bug agents stayed on Opus 5 after
`--model claude-opus-5-5`. The fix is
`settings.env.ANTHROPIC_DEFAULT_OPUS_MODEL`, Claude Code's documented alias
override.

**The rule.** Before writing down what a plugin asks for, quote its current
file (`gh api repos/anthropics/claude-code/contents/plugins/code-review/commands/code-review.md`),
and before claiming a pin is ignored, check `modelUsage` in a run log. It
lists every model the session touched. `--model` is the orchestrator's model;
subagents' models are the plugin's aliases, resolved by the build.

## 2026-10-12 — a skill gated on "any migration pending", and an automatic stage read unbounded history

**What went wrong.** A pre-release review found two related gaps. A skill
checked whether *any* migration was pending rather than whether the vault had
reached the structure version that skill needs, so it either refused when
nothing it relied on was missing, or ran when the one thing it relied on was.
And an automatic stage that reads history (mail, Teams, recordings) took its
start point from state a migration was meant to set: on a vault where the
plugin had been updated but `/upgrade-vault` not yet run, that state was
absent and the stage would have read back without limit.

**The rule.** A skill gates on the specific `structure-version` it needs
(`>= N`), never on "pending is empty". Any automatic stage that reads history
is gated the same way and bounded on its own — a default window or a hard
cap — so a plugin update that lands ahead of `/upgrade-vault` cannot start an
unbounded run. Plugin updates and vault upgrades are separate events; assume
the gap between them.

## 2026-10-12 — a Python heredoc in Git Bash wrote a real line break where `\n` was meant

**What went wrong.** On Windows, editing a file with a Python heredoc run
from Git Bash, a `"\n"` inside a string literal in the replacement text
reached the target file as an actual line break, splitting a string literal
in two. The file no longer compiled, and nothing in the edit step said so.
Writing this very entry the same way did it again: every `\n` in the
paragraph landed as a line break.

**The rule.** For an edit whose text contains escape sequences (`\n`, `\t`,
backslashes in general), use the Edit tool, not a shell heredoc. Afterwards
compile or run the tests for that file before moving on, and for prose, look
at the bytes that landed.

## 2026-10-12 — a renamed table view broke the embeds that named it

**What went wrong.** A view in a template `.base` file was renamed. The
template's own embeds were updated, but vaults keep their old `.base` files
until a migration or template refresh replaces them, so places that embed
the view by name (the daily note's embeds) pointed at a view that the
owner's copy of the file did not have yet, and rendered empty.

**The rule.** When a view in a template `.base` is renamed, every place that
embeds it by name needs a fallback to the old name (or the refresh must land
in the same migration), because existing vaults run on the old file until it
is refreshed. Grep for the old view name across `plugin/` before merging.
