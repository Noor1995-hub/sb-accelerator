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
