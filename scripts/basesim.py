#!/usr/bin/env python3
"""Evaluate Obsidian Bases view filters against a vault, deterministically.

Why this exists: the five .base files in template/ are the vault's primary UI,
and until now the only check that a view selected the right rows was a human
opening Obsidian and counting rows by eye (docs/local-setup.md step 3). An
ontology rename silently empties a table, and nothing in CI notices.

This is a deliberately partial reimplementation. It covers exactly the filter
vocabulary the five shipped .base files use and raises UnmodeledFilter on
anything else, because an unrecognised operator quietly read as "no match"
would turn a real regression into a green test with an empty expectation.

FIDELITY RULE: the expected row sets in scripts/tests/test_bases_views.py were
verified by hand in real Obsidian (docs/local-setup.md step 3). When this
module and Obsidian disagree, Obsidian is right and this module is the bug.

Dev-time only — never imported by the plugin, so PyYAML is fair game here.
Must stay Python 3.10-clean: CI runs this suite on the runtime floor.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Set

import yaml


class _ObsidianYamlLoader(yaml.SafeLoader):
    """SafeLoader minus YAML-1.1 sexagesimal integers.

    Obsidian's property editor strips quotes, so a real vault can carry
    `type: 1:1` bare. Stock PyYAML reads that as int 61 (base-60 notation);
    Obsidian's js-yaml (v4+) dropped sexagesimal and reads the string "1:1".
    The FIDELITY RULE above says Obsidian wins. Sexagesimal *floats* need a
    trailing `.digits` part (`2:30.5`), which no vault field shape can
    produce, so only the int resolver is replaced.
    """


_ObsidianYamlLoader.yaml_implicit_resolvers = {
    first_char: [(tag, regexp) for tag, regexp in resolvers
                 if tag != "tag:yaml.org,2002:int"]
    for first_char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_ObsidianYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int",
    re.compile(r"\A[-+]?[0-9]+\Z"),
    list("-+0123456789"))
# The stock constructor keeps YAML-1.1 semantics where a leading 0 means
# octal, so `08` (which the resolver above tags as int) would raise. YAML-1.2
# core — what js-yaml v4 implements — is plain decimal.
_ObsidianYamlLoader.add_constructor(
    "tag:yaml.org,2002:int",
    lambda loader, node: int(loader.construct_scalar(node), 10))


def _yaml_load(text: str):
    return yaml.load(text, Loader=_ObsidianYamlLoader)


Corpus = Dict[str, Dict[str, Any]]

# `file.<attr>` attributes this module knows how to compute.
_FILE_ATTRS = {"name", "ext", "path", "folder"}
# Methods, keyed by what they may be called on.
_FILE_METHODS = {"inFolder"}
_PROPERTY_METHODS = {"isEmpty"}

_COMPARE_RE = re.compile(r"\A(?P<left>[^=!<>]+?)\s*(?P<op>==|!=)\s*(?P<right>.+)\Z")
_CALL_RE = re.compile(r"\A(?P<ref>.+?)\.(?P<method>[A-Za-z][A-Za-z0-9]*)\((?P<args>.*)\)\Z")
_NOTE_BRACKET_RE = re.compile(r'\Anote\[\s*"(?P<prop>[^"]+)"\s*\]\Z')
_PLAIN_PROP_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_-]*\Z")
_INT_RE = re.compile(r"\A-?\d+\Z")
_MISSING = object()


class UnmodeledFilter(Exception):
    """A filter expression outside the vocabulary this module implements.

    Raised rather than returning False: see the module docstring.
    """


# --- references ---------------------------------------------------------


class _FileRef:
    """`file`, or `file.<attr>`."""

    def __init__(self, attr: Optional[str]):
        self.attr = attr

    def value(self, relpath: str, frontmatter: dict):
        if self.attr == "name":
            return relpath.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if self.attr == "ext":
            tail = relpath.rsplit("/", 1)[-1]
            return tail.rsplit(".", 1)[1] if "." in tail else ""
        if self.attr == "path":
            return relpath
        if self.attr == "folder":
            return relpath.rsplit("/", 1)[0] if "/" in relpath else ""
        raise UnmodeledFilter(f"file.{self.attr} is not a bare value")


class _PropRef:
    """A frontmatter property, written bare or as `note["name"]`."""

    def __init__(self, name: str):
        self.name = name

    def value(self, relpath: str, frontmatter: dict):
        return frontmatter.get(self.name, _MISSING)


def _parse_ref(text: str):
    text = text.strip()
    if text == "file":
        return _FileRef(None)
    if text.startswith("file."):
        attr = text[len("file."):]
        if attr not in _FILE_ATTRS:
            raise UnmodeledFilter(f"unknown file attribute: {text!r}")
        return _FileRef(attr)
    bracket = _NOTE_BRACKET_RE.match(text)
    if bracket:
        return _PropRef(bracket.group("prop"))
    if _PLAIN_PROP_RE.match(text):
        return _PropRef(text)
    raise UnmodeledFilter(f"unparseable reference: {text!r}")


def _parse_literal(text: str):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "null":
        return None
    if _INT_RE.match(text):
        return int(text)
    raise UnmodeledFilter(f"unsupported literal: {text!r}")


# --- expressions --------------------------------------------------------


class _Compare:
    def __init__(self, ref, op: str, literal):
        if isinstance(ref, _FileRef) and ref.attr is None:
            raise UnmodeledFilter("`file` cannot be compared directly")
        self.ref, self.op, self.literal = ref, op, literal

    def matches(self, relpath: str, frontmatter: dict) -> bool:
        actual = self.ref.value(relpath, frontmatter)
        # A property that is absent behaves as null, so `reviewed != true`
        # holds for a note carrying no `reviewed` key at all — which is what
        # Meetings/Triage relies on.
        if actual is _MISSING:
            actual = None
        # Guard against Python's bool/int equivalence: `reviewed == true` must
        # not match `reviewed: 1`, and `count == 1` must not match `true`.
        if isinstance(self.literal, bool) != isinstance(actual, bool):
            equal = False
        else:
            equal = actual == self.literal
        return equal if self.op == "==" else not equal


class _Call:
    def __init__(self, ref, method: str, args: str):
        if isinstance(ref, _FileRef):
            if method not in _FILE_METHODS:
                raise UnmodeledFilter(f"unknown file method: {method}()")
        elif method not in _PROPERTY_METHODS:
            raise UnmodeledFilter(f"unknown property method: {method}()")
        self.ref, self.method = ref, method
        self.arg = _parse_literal(args) if args.strip() else None
        # Argument arity is part of the grammar: an argument-less inFolder()
        # would otherwise compare against the string "None" and quietly match
        # nothing, which is the silent-empty-view failure this module exists to
        # catch.
        if self.method == "inFolder" and not isinstance(self.arg, str):
            raise UnmodeledFilter("inFolder() takes one quoted folder path")
        if self.method == "isEmpty" and self.arg is not None:
            raise UnmodeledFilter("isEmpty() takes no arguments")

    def matches(self, relpath: str, frontmatter: dict) -> bool:
        if self.method == "inFolder":
            folder = str(self.arg).rstrip("/")
            # Recursive: Decisions.base filters on `30-projects` while its
            # notes live at 30-projects/<slug>/decisions/*.md. The trailing
            # slash is what stops `30-projects-archive/` matching too.
            return relpath.startswith(folder + "/")
        value = self.ref.value(relpath, frontmatter)
        if value is _MISSING or value is None or value == "":
            return True
        if isinstance(value, (list, dict, tuple, set)):
            return len(value) == 0
        return False


class _Negate:
    def __init__(self, inner):
        self.inner = inner

    def matches(self, relpath: str, frontmatter: dict) -> bool:
        return not self.inner.matches(relpath, frontmatter)


class _Group:
    def __init__(self, combinator: str, children):
        self.combinator, self.children = combinator, children

    def matches(self, relpath: str, frontmatter: dict) -> bool:
        results = (child.matches(relpath, frontmatter) for child in self.children)
        return all(results) if self.combinator == "and" else any(results)


# --- parsing ------------------------------------------------------------


def _parse_leaf(text: str):
    stripped = text.strip()
    if stripped.startswith("!"):
        return _Negate(_parse_leaf(stripped[1:]))
    compare = _COMPARE_RE.match(stripped)
    if compare:
        return _Compare(
            _parse_ref(compare.group("left")),
            compare.group("op"),
            _parse_literal(compare.group("right")),
        )
    call = _CALL_RE.match(stripped)
    if call:
        return _Call(_parse_ref(call.group("ref")), call.group("method"), call.group("args"))
    raise UnmodeledFilter(f"unmodeled filter expression: {text!r}")


def compile_filters(node) -> Optional[object]:
    """Compile a .base `filters:` tree into something with .matches()."""
    if node is None:
        return None
    if isinstance(node, str):
        return _parse_leaf(node)
    if isinstance(node, dict):
        if len(node) != 1:
            raise UnmodeledFilter(f"expected exactly one combinator, got {sorted(node)}")
        combinator, children = next(iter(node.items()))
        if combinator not in ("and", "or"):
            raise UnmodeledFilter(f"unmodeled combinator: {combinator!r}")
        if not isinstance(children, list):
            raise UnmodeledFilter(f"{combinator!r} takes a list, got {type(children).__name__}")
        return _Group(combinator, [compile_filters(child) for child in children])
    raise UnmodeledFilter(f"unmodeled filter node: {node!r}")


# --- vault + base loading ------------------------------------------------


def load_base(path) -> dict:
    """Parse a .base file."""
    return _yaml_load(Path(path).read_text(encoding="utf-8"))


def load_corpus(vault_root) -> Corpus:
    """Every indexable file in the vault, keyed by posix-relative path.

    Non-markdown files are included with empty frontmatter so `file.ext == "md"`
    stays load-bearing. Dot-directories (.obsidian, .git) are skipped, matching
    what Obsidian indexes.

    Paths are normalised to forward slashes: the Windows CI job would otherwise
    hand `file.inFolder("20-meetings")` a backslash path that never matches.
    """
    root = Path(vault_root)
    corpus: Corpus = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        corpus[relative.as_posix()] = _frontmatter(path) if path.suffix == ".md" else {}
    return corpus


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    data = _yaml_load(text[4:end])
    return data if isinstance(data, dict) else {}


# --- the public question -------------------------------------------------


def view_rows(base: dict, corpus: Corpus, view_name: str) -> Set[str]:
    """The relative paths a named view of this base would show."""
    views = base.get("views") or []
    for view in views:
        if view.get("name") == view_name:
            break
    else:
        raise KeyError(f"no view named {view_name!r}; have {[v.get('name') for v in views]}")
    tests = [
        compiled
        for compiled in (compile_filters(base.get("filters")), compile_filters(view.get("filters")))
        if compiled is not None
    ]
    return {
        relpath
        for relpath, frontmatter in corpus.items()
        if all(test.matches(relpath, frontmatter) for test in tests)
    }


def view_names(base: dict):
    return [view.get("name") for view in (base.get("views") or [])]
