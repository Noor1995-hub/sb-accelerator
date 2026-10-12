"""Read the part of an Obsidian `.base` file the Excel export needs (#272).

Not a YAML parser (the plugin is stdlib only, and nothing parses YAML at
runtime): it reads three blocks by indentation, `formulas:` (name →
expression), `properties:` (key → displayName) and `views:` (name, order).
Everything else is skipped, never guessed.
"""
from __future__ import annotations

from typing import Dict, List


class BaseFileError(Exception):
    """The file has no view with a column order."""


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def read(text: str) -> dict:
    formulas: Dict[str, str] = {}
    display: Dict[str, str] = {}
    views: List[dict] = []
    section = None
    current_prop = None
    view = None
    in_order = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 0:
            section = stripped[:-1] if stripped.endswith(":") else None
            in_order = False
            continue
        if section == "formulas" and indent == 2 and ":" in stripped:
            key, _, expr = stripped.partition(":")
            formulas[_unquote(key)] = _unquote(expr)
        elif section == "properties":
            if indent == 2 and stripped.endswith(":"):
                current_prop = _unquote(stripped[:-1])
            elif indent == 4 and stripped.startswith("displayName:") and current_prop:
                display[current_prop] = _unquote(stripped.partition(":")[2])
        elif section == "views":
            if indent == 2 and stripped.startswith("- "):
                view = {"name": "", "order": []}
                views.append(view)
                in_order = False
                rest = stripped[2:]
                if rest.startswith("name:"):
                    view["name"] = _unquote(rest.partition(":")[2])
            elif view is not None and in_order and indent >= 4 and stripped.startswith("- "):
                # YAML allows the items at the key's own indent.
                view["order"].append(_unquote(stripped[2:]))
            elif view is not None and indent == 4:
                in_order = stripped == "order:"
                if stripped.startswith("name:"):
                    view["name"] = _unquote(stripped.partition(":")[2])
            elif view is not None and in_order and indent >= 6 and stripped.startswith("- "):
                view["order"].append(_unquote(stripped[2:]))
    views = [v for v in views if v["order"]]
    if not views:
        raise BaseFileError("no view with a column order")
    return {"formulas": formulas, "display": display, "views": views}
