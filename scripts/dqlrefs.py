#!/usr/bin/env python3
"""Reference-check Dataview queries against the ontology.

Dataview fails silently: a query naming a property the ontology renamed
renders an empty table rather than an error, so a project index can look fine
and show nothing. This module extracts the *identifiers* a DQL block names and
lets a test assert they exist. It deliberately does NOT evaluate DQL —
reimplementing the language to run 10 queries would cost more fidelity than it
buys, and the failure being guarded against is a dangling reference.

Anything outside the vocabulary the vault actually uses raises UnmodeledQuery,
so a new DQL function is added to the allowlist deliberately rather than being
silently mistaken for a property.

Dev-time only. Must stay Python 3.10-clean: CI runs this suite on the floor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Set

from vaultlib import schema

# DQL functions the vault's queries use. Extend deliberately.
KNOWN_FUNCTIONS = {"link", "dateformat", "econtains", "slice",
                   # names and labels instead of codes (#259)
                   "map", "default", "choice", "upper", "substring"}

# Matched case-insensitively: Dataview's keywords are case-insensitive.
KEYWORDS = {
    "table", "list", "task", "calendar", "without", "id", "as", "from", "where",
    "sort", "limit", "group", "by", "flatten", "rows", "asc", "desc", "and", "or", "not",
    # literals, not fields: `WHERE archived != true` (#247)
    "true", "false", "null",
}

_FENCE_RE = re.compile(r"(?P<ticks>`{3,})dataview[ \t]*\n(?P<body>.*?)\n(?P=ticks)", re.DOTALL)
_FROM_RE = re.compile(r"\bFROM\b(?P<rest>[^\n]*)", re.IGNORECASE)
_QUOTED_RE = re.compile(r"\"[^\"]*\"|'[^']*'")
_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*)\s*\(")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
# `(a) => ...` — a lambda's parameter is a local name, not a property.
_LAMBDA_RE = re.compile(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*=>")
# `link("50-people/" + a).person-name` reads a field of *another* note; the
# literal folder at the start of the link says which object type it is.
_DEREF_RE = re.compile(r'link\("(?P<prefix>[^"]*)"[^()]*(?:\([^()]*\)[^()]*)*\)\.(?P<field>[A-Za-z_][A-Za-z0-9_-]*)')
_DEREF_TAIL_RE = re.compile(r"\)\.[A-Za-z_][A-Za-z0-9_-]*")
_LINK_PREFIX_TYPES = [("50-people/", "person"), ("40-entities/", "entity"), ("30-projects/", "project")]

# Object notes, by where they live. Same shapes as the HARNESS globs in
# test_fixtures_ontology.py, expressed as paths because that is what a DQL
# FROM clause and a `this.` reference both resolve through.
_FOLDER_TYPES = [
    (re.compile(r"\A20-meetings\Z"), "meeting"),
    (re.compile(r"\A50-people\Z"), "person"),
    (re.compile(r"\A40-entities\Z"), "entity"),
    (re.compile(r"\A30-projects/[^/]+/decisions\Z"), "decision"),
]

# Folders holding more than one object type. Named rather than left to fall
# through to "unmodeled" so the error says which types collide.
_AMBIGUOUS_FOLDERS = {"30-projects": {"project", "decision"}}

_PATH_TYPES = [
    (re.compile(r"\A40-entities/[^/]+/dossier\.md\Z"), "entity"),
    (re.compile(r"\A30-projects/[^/]+/index\.md\Z"), "project"),
    (re.compile(r"\A30-projects/[^/]+/decisions/[^/]+\.md\Z"), "decision"),
    (re.compile(r"\A50-people/[^/]+\.md\Z"), "person"),
    (re.compile(r"\A20-meetings/[^/]+\.md\Z"), "meeting"),
    (re.compile(r"\A65-to-dos/[^/]+\.md\Z"), "to-do"),
]


class UnmodeledQuery(Exception):
    """A query construct outside what this module models, or an unresolvable
    FROM clause. Raised rather than ignored: see the module docstring."""


@dataclass
class Refs:
    """Identifiers one DQL block names."""

    properties: Set[str] = field(default_factory=set)
    this_properties: Set[str] = field(default_factory=set)
    from_paths: Set[str] = field(default_factory=set)
    # (object type, field) pairs read through `link("folder/...").field`
    linked_properties: Set[tuple] = field(default_factory=set)


def dataview_blocks(text: str):
    """Bodies of every ```dataview fence in a markdown document.

    The closing fence is matched by backreference, not a fixed three
    backticks — a block nested inside a four-backtick fence would otherwise
    terminate early (docs/superpowers/lessons.md).
    """
    return [match.group("body") for match in _FENCE_RE.finditer(text)]


def extract_refs(block: str) -> Refs:
    refs = Refs()

    # FROM paths first: they live inside string literals, which the next step
    # strips out.
    for match in _FROM_RE.finditer(block):
        refs.from_paths.update(re.findall(r"\"([^\"]+)\"", match.group("rest")))

    for match in _DEREF_RE.finditer(block):
        kind = next((t for prefix, t in _LINK_PREFIX_TYPES
                     if match.group("prefix").startswith(prefix)), None)
        if kind is None:
            raise UnmodeledQuery(f"link({match.group('prefix')!r}...).{match.group('field')}: "
                                 "no object type for that folder")
        refs.linked_properties.add((kind, match.group("field")))
    params = set(_LAMBDA_RE.findall(block))

    # Strip literals so format strings ("dd-MM-yy") and display aliases
    # (AS "Date") cannot masquerade as property references.
    stripped = _QUOTED_RE.sub(" ", block)
    stripped = _DEREF_TAIL_RE.sub(") ", stripped)

    functions = set(_CALL_RE.findall(stripped))
    unknown = functions - KNOWN_FUNCTIONS
    if unknown:
        raise UnmodeledQuery(
            f"unmodeled DQL function(s) {sorted(unknown)}; add to KNOWN_FUNCTIONS "
            "once you have confirmed how the query behaves"
        )

    for token in _IDENT_RE.findall(stripped):
        if token.startswith("this."):
            refs.this_properties.add(token[len("this."):])
        elif token == "file" or token.startswith("file."):
            continue
        elif token.lower() in KEYWORDS or token in functions or token in params:
            continue
        else:
            refs.properties.add(token)
    return refs


def object_type_for_path(relpath: str) -> Optional[str]:
    """The ontology object a vault path holds, or None if it is not an object."""
    for pattern, name in _PATH_TYPES:
        if pattern.match(relpath):
            return name
    return None


def folder_object_type(from_path: str) -> str:
    """The object type a FROM folder selects, from its path shape.

    Shape, not contents, deliberately. A project with no decisions yet has no
    decisions/ folder at all, and its index still carries the decisions query —
    an empty table is the correct render there, not a dangling reference. An
    earlier contents-based version of this read those two fixture projects as
    broken.
    """
    folder = from_path.strip("/")
    for pattern, name in _FOLDER_TYPES:
        if pattern.match(folder):
            return name
    if folder in _AMBIGUOUS_FOLDERS:
        raise UnmodeledQuery(
            f'FROM "{from_path}" mixes object types {sorted(_AMBIGUOUS_FOLDERS[folder])}; '
            "property references cannot be checked against a single schema"
        )
    raise UnmodeledQuery(
        f'FROM "{from_path}" is not a folder shape this module maps to an object '
        "type — check the path, or add the shape to _FOLDER_TYPES"
    )


def known_fields(object_name: str) -> Set[str]:
    """Every frontmatter field the ontology declares for an object.

    Same union schema.validate() computes as `known`. Duplicated here rather
    than added to plugin/lib/vaultlib/schema.py so this stays out of plugin/
    and clear of CI's version guard; promote it there if a third caller wants it.
    """
    block = schema.for_object(object_name)
    return (
        set(block.get("required", []))
        | set(block.get("optional", []))
        | set(block.get("keys_present", []))
        | set(block.get("enums", {}))
    )
