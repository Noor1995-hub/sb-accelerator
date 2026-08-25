# skills/ — vault-local skills

Empty by design, and usually stays that way.

The product's skills ship in the accelerator **plugin**, not here. Cowork loads
skills only from installed plugins and your own skill store — never from a
connected folder — so anything placed in this directory is invisible there and
works only from Claude Code. That is a platform constraint, not a convention.

Use this folder for a genuinely per-deployment customisation that will only ever
be run from Claude Code. Everything else belongs upstream in the plugin, where
both surfaces can see it. See `../README.md`.
