"""Frontmatter and section handling for vault markdown.

Stdlib only, deliberately: PyYAML's presence in the Cowork VM is unverified.
The parser covers the flat subset vault frontmatter actually uses — scalars,
inline lists, block lists, nulls, integers, booleans — and raises on anything
outside it rather than guessing. CI's conformance guard still uses PyYAML, and
scripts/tests/test_vaultlib_markdown.py pins the subset both must agree on.
"""
from __future__ import annotations

import re
from typing import Collection, List, Mapping, Optional, Sequence, Tuple

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
_KEY_RE = re.compile(r"\A([A-Za-z_][A-Za-z0-9_-]*):(.*)\Z")
_INT_RE = re.compile(r"\A-?\d+\Z")
_FENCE_RE = re.compile(r"\A\s*(```|~~~)")
_WIKILINK_RE = re.compile(r"\A\[\[[^\[\]]+\]\]\Z")

_PENDING = object()


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _scalar(raw: str):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        inner = raw[1:-1]
        if raw[0] != '"':
            return inner
        # Mirror of emit_scalar: only \\ and \" are our escapes. Any other
        # backslash sequence is legacy content from before the escaping fix
        # and stays verbatim. Legacy content that itself contained \\ halves
        # here once — that is what every real YAML parser already read it as,
        # and the next write re-escapes it correctly.
        return re.sub(r'\\(["\\])', r"\1", inner)
    if raw in ("", "null", "~"):
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    if _INT_RE.match(raw):
        return int(raw)
    return raw


def _split_top_level(body: str) -> List[str]:
    """Split on commas that are not inside a quoted run."""
    parts, buf, quote = [], [], None
    for char in body:
        if quote:
            if char == quote:
                quote = None
            buf.append(char)
        elif char in "\"'":
            quote = char
            buf.append(char)
        elif char == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    parts.append("".join(buf))
    return [part for part in (p.strip() for p in parts) if part]


def _inline_list(raw: str) -> list:
    inner = raw.strip()
    if not (inner.startswith("[") and inner.endswith("]")):
        raise ValueError(f"malformed inline list: {raw!r}")
    body = inner[1:-1].strip()
    return [_scalar(part) for part in _split_top_level(body)] if body else []


def parse_frontmatter_block(block: str) -> dict:
    """Parse the text between the `---` fences into a flat mapping."""
    data: dict = {}
    current_key: Optional[str] = None
    last_key: Optional[str] = None
    for line in _normalize(block).split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") or stripped == "-":
            if current_key is None:
                if last_key is not None:
                    raise ValueError(
                        f"list item under completed key {last_key!r}: {line!r}"
                        " — looks like an orphaned block-list continuation "
                        "left behind by an external edit; delete the "
                        f"dangling '- ' lines under {last_key!r}"
                    )
                raise ValueError(f"list item before any key: {line!r}")
            if data[current_key] is _PENDING:
                data[current_key] = []
            data[current_key].append(_scalar(stripped[1:]))
            continue
        match = _KEY_RE.match(stripped)
        if not match:
            raise ValueError(f"unparseable frontmatter line: {line!r}")
        key, rest = match.group(1), match.group(2).strip()
        last_key = key
        if rest == "":
            # Could be a null value or the header of a block list — only the
            # next line tells us, so defer and resolve at the end.
            data[key] = _PENDING
            current_key = key
        elif rest.startswith("["):
            # Wikilink fields are written quoted, but Obsidian's property
            # editor strips the quotes. A whole-value [[...]] can only be a
            # wikilink — vault inline lists never start `[[` because list
            # items holding wikilinks are always quoted — so read it as the
            # string it was meant to be rather than a mangled nested list.
            if _WIKILINK_RE.match(rest):
                data[key] = rest
            else:
                data[key] = _inline_list(rest)
            current_key = None
        else:
            data[key] = _scalar(rest)
            current_key = None
    return {key: (None if value is _PENDING else value) for key, value in data.items()}


def split_frontmatter(text: str) -> Tuple[dict, str]:
    """Return (frontmatter mapping, body). Raises if frontmatter is absent."""
    match = _FRONTMATTER_RE.match(_normalize(text))
    if not match:
        raise ValueError("file has no YAML frontmatter")
    return parse_frontmatter_block(match.group(1)), _normalize(text)[match.end():]


_NEWLINE_RE = re.compile(r"[\r\n]")
_MAPPING_LOOKALIKE_RE = re.compile(r":(?:\s|\Z)")


def emit_scalar(value, quoted: bool) -> str:
    """Render one scalar, refusing anything that would not parse back.

    Emitting frontmatter nothing can read is worse than failing: the file is
    written, the caller is told it succeeded, and every later read of that
    object fails permanently. A newline ends the scalar even inside quotes
    (this module's parser is line-based and PyYAML rejects the result too), and
    an unquoted `: ` turns the value into a nested mapping.
    """
    text = str(value)
    if _NEWLINE_RE.search(text):
        raise ValueError(
            f"frontmatter value {text!r} contains a newline; YAML ends the "
            "scalar there, so the file would not parse back. Pass a single-line "
            "value."
        )
    if not quoted and _MAPPING_LOOKALIKE_RE.search(text):
        raise ValueError(
            f"frontmatter value {text!r} contains ':' followed by whitespace or "
            "end of value, which YAML reads as a nested mapping. Pass a value "
            "without it."
        )
    if quoted:
        # Backslash first: it is an escape character to every real YAML
        # parser, and escaping it after the quote would double the quote's
        # own backslash (issue #47).
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def emit_frontmatter(data: Mapping, quote_keys: Collection[str] = ()) -> str:
    """Render a frontmatter block.

    Quoting is caller-declared rather than inferred: the vault's convention is
    semantic (display names and prose quoted; slugs, enums and dates bare),
    which no syntactic rule can recover.
    """
    lines = ["---"]
    for key, value in data.items():
        quoted = key in quote_keys
        if value is None:
            lines.append(f"{key}:")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, (list, tuple)):
            rendered = ", ".join(emit_scalar(item, quoted) for item in value)
            lines.append(f"{key}: [{rendered}]")
        else:
            lines.append(f"{key}: {emit_scalar(value, quoted)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _node_end(lines: List[str], key_index: int) -> int:
    """Index one past the last line belonging to the node at ``key_index``.

    Mirrors parse_frontmatter_block: after a key line, block-list items keep
    accumulating under that key across blank and comment lines. Trailing
    blanks/comments with no item after them are layout, not node, and are
    left in place.
    """
    end = scan = key_index + 1
    while scan < len(lines):
        stripped = lines[scan].strip()
        if stripped.startswith("- ") or stripped == "-":
            scan += 1
            end = scan
        elif not stripped or stripped.startswith("#"):
            scan += 1
        else:
            break
    return end


def _replace_field_node(text: str, field: str, value: str,
                        insert_if_missing: bool) -> str:
    normalized = _normalize(text)
    match = _FRONTMATTER_RE.match(normalized)
    if not match:
        raise ValueError("file has no YAML frontmatter")
    lines = match.group(1).split("\n")
    for index, line in enumerate(lines):
        if not line.startswith(f"{field}:"):
            continue
        replaced = lines[:index] + [f"{field}: {value}"]
        replaced += lines[_node_end(lines, index):]
        block = "\n".join(replaced)
        return normalized[: match.start(1)] + block + normalized[match.end(1):]
    if not insert_if_missing:
        raise ValueError(f"field {field!r} is not present in frontmatter")
    block = "\n".join(lines) + f"\n{field}: {value}"
    return normalized[: match.start(1)] + block + normalized[match.end(1):]


def replace_scalar_field(text: str, field: str, value: str) -> str:
    """Replace one top-level field inside existing frontmatter, leaving every
    other byte alone.

    Editing an existing note this way rather than re-emitting the whole block
    is what keeps hand-authored key order, quoting and comments intact. The
    whole node is replaced, not just the key line: Obsidian's property editor
    expands inline lists to block lists, and replacing only the key line would
    orphan the continuation items and corrupt the file (issue #53). Interior
    comments and blanks belong to the node and are replaced with it.
    """
    return _replace_field_node(text, field, value, insert_if_missing=False)


def upsert_scalar_field(text: str, field: str, value: str) -> str:
    """replace_scalar_field, but inserting the field before the closing `---`
    when it is absent. For metric fields that are optional in the schema —
    every other byte, including hand-authored key order, stays put.
    """
    return _replace_field_node(text, field, value, insert_if_missing=True)


def split_sections(body: str, level: int = 2) -> List[Tuple[str, str]]:
    """Split a body into (heading title, content) pairs at the given heading
    level. Content before the first heading is returned under "".

    Headings inside fenced code blocks are ignored — project index bodies
    carry Dataview blocks, and a `##` inside one is not a section.

    Heading-shaped content *inside* a block-list item — `- ## Not a section` —
    deliberately does not split either, because the check is a `startswith` on
    the raw line and no vault writer emits that shape. Making it split would
    carve a human's own list in half and surface a phantom section that
    render_sections then writes back as a real heading.
    """
    marker = "#" * level + " "
    sections: List[Tuple[str, List[str]]] = [("", [])]
    fence: Optional[str] = None
    for line in _normalize(body).split("\n"):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            token = fence_match.group(1)
            fence = None if fence == token else (fence or token)
        if fence is None and line.startswith(marker):
            sections.append((line[len(marker):].strip(), []))
            continue
        sections[-1][1].append(line)
    return [(title, "\n".join(lines)) for title, lines in sections]


def render_sections(sections: Sequence[Tuple[str, str]], level: int = 2) -> str:
    """Inverse of split_sections."""
    marker = "#" * level + " "
    chunks = []
    for title, content in sections:
        chunks.append(content if not title else f"{marker}{title}\n{content}")
    return "\n".join(chunks)
