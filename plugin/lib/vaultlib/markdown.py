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

_PENDING = object()


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _scalar(raw: str):
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        inner = raw[1:-1]
        return inner.replace('\\"', '"') if raw[0] == '"' else inner
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
    for line in _normalize(block).split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") or stripped == "-":
            if current_key is None:
                raise ValueError(f"list item before any key: {line!r}")
            if data[current_key] is _PENDING:
                data[current_key] = []
            data[current_key].append(_scalar(stripped[1:]))
            continue
        match = _KEY_RE.match(stripped)
        if not match:
            raise ValueError(f"unparseable frontmatter line: {line!r}")
        key, rest = match.group(1), match.group(2).strip()
        if rest == "":
            # Could be a null value or the header of a block list — only the
            # next line tells us, so defer and resolve at the end.
            data[key] = _PENDING
            current_key = key
        elif rest.startswith("["):
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


def _emit_scalar(value, quoted: bool) -> str:
    if quoted:
        return '"{}"'.format(str(value).replace('"', '\\"'))
    return str(value)


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
            rendered = ", ".join(_emit_scalar(item, quoted) for item in value)
            lines.append(f"{key}: [{rendered}]")
        else:
            lines.append(f"{key}: {_emit_scalar(value, quoted)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def replace_scalar_field(text: str, field: str, value: str) -> str:
    """Replace one top-level scalar inside existing frontmatter, leaving every
    other byte alone.

    Editing an existing note this way rather than re-emitting the whole block
    is what keeps hand-authored key order, quoting and comments intact.
    """
    normalized = _normalize(text)
    match = _FRONTMATTER_RE.match(normalized)
    if not match:
        raise ValueError("file has no YAML frontmatter")
    block = match.group(1)
    pattern = re.compile(rf"^({re.escape(field)}:)([ \t]*)(.*)$", re.MULTILINE)
    if not pattern.search(block):
        raise ValueError(f"field {field!r} is not present in frontmatter")
    updated_block = pattern.sub(rf"\g<1> {value}", block, count=1)
    return normalized[: match.start(1)] + updated_block + normalized[match.end(1):]


def split_sections(body: str, level: int = 2) -> List[Tuple[str, str]]:
    """Split a body into (heading title, content) pairs at the given heading
    level. Content before the first heading is returned under "".

    Headings inside fenced code blocks are ignored — project index bodies
    carry Dataview blocks, and a `##` inside one is not a section.
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
