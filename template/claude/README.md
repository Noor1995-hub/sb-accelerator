# claude/ — vault-local Claude Code home (visible)

Obsidian hides dot-folders, so this vault keeps Claude Code's home as a
visible `claude/` directory with a `.claude` symlink pointing at it —
Claude Code reads `.claude/`, you browse and edit the same files here.

- `skills/` — vault-local skills (per-deployment customizations), usable
  **only from Claude Code**. Cowork does not load skills from a connected
  folder at all: it reads them from installed plugins and from your own
  skill store. So the product's core skills ship via the accelerator
  plugin — not a convention, a platform constraint. Anything placed here is
  invisible to Cowork.
- The `.claude → claude` symlink is created at instantiation
  (`make_test_vault.py` does it automatically; for client machines it is a
  provisioning step — see the template README). It is intentionally not a
  checked-in file: symlinks do not survive naive copies or Windows
  checkouts without symlink privileges.
