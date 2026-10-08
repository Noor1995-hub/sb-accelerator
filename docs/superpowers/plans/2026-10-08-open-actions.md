# Open actions — implementation plan (#257)

Spec: `docs/superpowers/specs/2026-10-08-open-actions-design.md`.
Executed inline, TDD per task; full suite + lint + template validation at the end.

1. **Due phrases** — `dates.resolve_due(phrase, anchor) -> date | None`
   (ISO, D/M[/Y] with `/ - .`, en/nl/fr weekdays, today/tomorrow).
   Tests in `test_vaultlib_dates.py`.
2. **Daily-note reader** — `dailynote.read` also returns `loose_actions`
   (`{text, done}` for `- [ ]` lines outside a meeting block). Existing keys
   unchanged. Test in `test_vaultlib_dailynote.py`.
3. **Action module** — `vaultlib/actions.py`: `harvest(root, from, to)`,
   `create(root, items, today)`; `vault.ACTIONS_DIR = "65-actions"`.
   Dedup on (source, text); close-on-tick across all open notes.
   Tests in `test_vaultlib_actions.py`.
4. **CLI** — `actions harvest --from --to`, `actions create --payload`;
   error mapping in `main`. Test in `test_vaultlib_cli.py`.
5. **Ontology** — Action section + edges; daily-note "never routes" line;
   recompile `schema.json`; fixture harness glob; `dqlrefs` path type.
6. **Template** — `65-actions/Actions.base`, bookmarks entry, CSS colour +
   icon, `template.py` tier, Start here / How it works / CLAUDE.md wording,
   structure-version 12, feedback scrub folder list.
7. **Migration 011** — insert the bookmark; idempotent; verify. Tests in
   `test_migration_011.py`; point 010's "shipped menu = template" pin at the
   current template menu minus Actions (history stays true).
8. **Fixtures + view tests** — demo action notes (open with/without project,
   overdue, done); expected rows for Open and Done; first view is Open;
   Done column exposed in Open.
9. **evening-sync skill** — stage 2 actions paragraph, stage 7 summary line;
   skill contract tests if they pin wording.
10. **Release** — bump `plugin.json` to 0.13.10, CHANGELOG Unreleased line.
11. **Verify** — lint, validate_template, pytest; visual check in an isolated
    Obsidian on a composed vault (menu entry, Open view grouping/sorting,
    New, tick).
