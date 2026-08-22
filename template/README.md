# Vault template

The L0 vault skeleton instantiated once per client: folder structure,
`.obsidian/` config (incl. sync exclusions for the exec-private folder),
`.base` views, a de-personalized `CLAUDE.md`, context-portfolio files with
guided placeholder slots, and a `structure-version` marker consumed by
`/upgrade-vault`.

Not yet populated — extraction from busdev is tracked in the backlog
(area:template). Once populated, `scripts/validate_template.py` requires
`template/CLAUDE.md` and `template/structure-version` to exist.
