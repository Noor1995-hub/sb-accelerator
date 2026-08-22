## What & why

<!-- What does this change do, and why? -->

## Checklist

- [ ] Skill lint passes locally: `python scripts/lint_plugin.py`
- [ ] Template validates locally: `python scripts/validate_template.py`
- [ ] Validator tests pass locally: `python -m pytest scripts/tests -q`
- [ ] No secret, client name, or vault content is committed (clean-room rule — root `CLAUDE.md`).
- [ ] **Plugin version:** if this PR touches `plugin/` (other than `plugin/CLAUDE.md`), the version in `plugin/.claude-plugin/plugin.json` is bumped.
- [ ] **Migrations:** any new migration in `migrations/` is idempotent (safe to run twice).

## Linked issue

Closes #

---

<!--
Claude review: runs on open / ready-for-review / reopen — NOT on push. After pushing fixes the
`claude-review` check goes *absent* (which looks like "nothing to report").

Comment `/review` to re-run — but don't do it after every fix. A re-review costs the same as the
original (full diff). Re-run when your fix created code the first review never saw. Skip it when
you applied a suggestion literally or changed only docs/comments/tests.
-->
