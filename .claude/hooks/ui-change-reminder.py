#!/usr/bin/env python3
"""PostToolUse hook: flag edits whose effect a human can only see in Obsidian.

Rendering regressions in this repo are invisible to CI by construction — a
renamed property silently empties a table, an inert displayName silently shows a
raw column name. Both shipped before. The reminder exists because a convention
that depends on remembering is one that gets missed; see
docs/visual-verification.md.

Emits a systemMessage and always exits 0: this nudges, it never blocks.
"""
import json
import sys

# Paths whose effect is only observable in a rendered vault.
UI_PATHS = (
    "plugin/template/.obsidian/",                                  # theme, settings, snippets, navigator
    "fixtures/demo-vault/",                                       # changes what renders
    "plugin/template/99-workflow-config/reference/ontology.md",    # renames empty tables silently
    "plugin/lib/vaultlib/markdown.py",                             # emits the bodies that render
)
UI_SUFFIXES = (".base", ".canvas")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path:
        return 0
    rel = path.split("/sb-accelerator/", 1)[-1]
    hit = rel.endswith(UI_SUFFIXES) or any(k in rel for k in UI_PATHS)
    if not hit:
        return 0
    print(json.dumps({"systemMessage": (
        f"[visual] {rel.rsplit('/', 1)[-1]} has UI impact that CI cannot see. "
        "Verify with /visual-check (probe tour + pytest -m obsidian + read the "
        "screenshots) before calling this done - see docs/visual-verification.md.")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
