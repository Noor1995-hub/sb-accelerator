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

These four entries are about the probe. Traps about what the vault renders —
column virtualisation, occluded windows returning stale frames, non-pristine
vaults poisoning the row cross-check — live in `docs/visual-verification.md`
under "Traps worth knowing".
