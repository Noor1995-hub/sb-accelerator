#!/usr/bin/env python3
"""Compile the ontology's fenced yaml blocks into plugin/lib/vaultlib/schema.json.

The ontology doc stays the single human-editable source of truth. The plugin's
runtime cannot depend on PyYAML (unverified in the Cowork VM), so the schema
is compiled here — at dev time, where PyYAML is available — and the generated
JSON is checked in. scripts/tests/test_compile_ontology.py regenerates and
diffs, so editing the ontology without regenerating fails CI.

Usage:
    python3 scripts/compile_ontology.py            # write schema.json
    python3 scripts/compile_ontology.py --check    # exit 1 if stale
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_DOC = REPO_ROOT / "template" / "99-workflow-config" / "reference" / "ontology.md"
SCHEMA_JSON = REPO_ROOT / "plugin" / "lib" / "vaultlib" / "schema.json"
SOURCE_LABEL = "template/99-workflow-config/reference/ontology.md"

YAML_FENCE_RE = re.compile(r"^```yaml\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)

CARRIED_KEYS = ("required", "optional", "enums", "keys_present", "body_sections")


def load_blocks(doc: Path) -> dict:
    """Return {object-name: block} for every fenced yaml block with an
    `object:` key. Narrative example blocks are skipped; malformed or
    duplicated blocks raise, because a broken ontology must fail loudly."""
    blocks = {}
    for match in YAML_FENCE_RE.finditer(doc.read_text(encoding="utf-8")):
        try:
            data = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            raise RuntimeError(f"{doc}: unparseable yaml block: {exc}") from exc
        if not isinstance(data, dict) or "object" not in data:
            continue
        name = data["object"]
        if name in blocks:
            raise RuntimeError(f"{doc}: duplicate schema block for {name!r}")
        blocks[name] = data
    if not blocks:
        raise RuntimeError(f"{doc}: no schema blocks found")
    return blocks


def compile_schema(doc: Path = ONTOLOGY_DOC) -> dict:
    objects = {}
    for name, block in sorted(load_blocks(doc).items()):
        objects[name] = {key: block[key] for key in CARRIED_KEYS if key in block}
    return {"generated_from": SOURCE_LABEL, "objects": objects}


def render(schema: dict) -> str:
    """Stable bytes: sorted keys, two-space indent, trailing newline."""
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the checked-in schema.json is stale")
    args = parser.parse_args(argv)
    rendered = render(compile_schema())
    if args.check:
        current = SCHEMA_JSON.read_text(encoding="utf-8") if SCHEMA_JSON.is_file() else ""
        if current != rendered:
            print(f"{SCHEMA_JSON.relative_to(REPO_ROOT)} is stale — "
                  f"run: python3 scripts/compile_ontology.py")
            return 1
        return 0
    SCHEMA_JSON.parent.mkdir(parents=True, exist_ok=True)
    with SCHEMA_JSON.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    print(f"wrote {SCHEMA_JSON.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
