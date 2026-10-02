"""Routing message groups to people and projects, from what the vault knows.

No hand-kept table (unlike the colleague's capture): an entity's domains come
from the meetings linked to it, a project's words from its name and its
`keywords`, its people from stakeholders and key people. Strong links queue a
project-state update; weak links only link (spec §7.1, decision 15).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Set

from . import markdown, naming, person, vault

MIN_DOMAIN_MEETINGS = 2


def _frontmatter(path: Path) -> dict:
    try:
        data, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        return data
    except (ValueError, OSError):
        return {}


def _as_list(value) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)] if value else []


def active_projects(root: Path) -> List[dict]:
    out = []
    folder = root / vault.PROJECTS_DIR
    for index in sorted(folder.glob("*/index.md")) if folder.is_dir() else []:
        data = _frontmatter(index)
        if data.get("status") != "active" or not data.get("slug"):
            continue
        out.append({"slug": str(data["slug"]), "name": str(data.get("project-name") or data["slug"]),
                    "entity": str(data.get("entity") or ""),
                    "keywords": _as_list(data.get("keywords")),
                    "people": sorted(set(_as_list(data.get("stakeholders")) + _as_list(data.get("key-people"))))})
    return out


def entity_domains(root: Path, home_domains: Iterable[str]) -> Dict[str, Set[str]]:
    home = {d.casefold() for d in (home_domains or [])}
    project_entity = {p["slug"]: p["entity"] for p in active_projects(root)}
    counts: Dict[str, Counter] = defaultdict(Counter)
    meetings = root / vault.MEETINGS_DIR
    for path in sorted(meetings.glob("*.md")) if meetings.is_dir() else []:
        data = _frontmatter(path)
        entities = set(_as_list(data.get("entities")))
        entities |= {project_entity[p] for p in _as_list(data.get("projects")) if project_entity.get(p)}
        domains = {str(e).rsplit("@", 1)[1].casefold() for e in _as_list(data.get("attendee-emails")) if "@" in str(e)}
        for entity in entities:
            for domain in domains - home:
                counts[entity][domain] += 1
    return {entity: {d for d, n in c.items() if n >= MIN_DOMAIN_MEETINGS}
            for entity, c in counts.items() if any(n >= MIN_DOMAIN_MEETINGS for n in c.values())}


def _has_word(word: str, text: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(word.casefold()) + r"(?!\w)", text.casefold()))


# Local parts that name a mailbox role, not a person: an address whose local
# part is one of these (separators ignored: `no-reply`, `do.not.reply`) or
# holds one as a part (`hr.team`) never becomes a person note.
ROLE_WORDS = frozenset(("noreply", "donotreply", "info", "support", "admin", "office", "contact",
                        "sales", "billing", "hr", "team", "notifications"))
MAX_NAME_PARTS = 3


def _name_from_address(address: str):
    local = address.split("@", 1)[0].casefold()
    parts = [p for p in re.split(r"[._-]", local) if p.isalpha()]
    if re.sub(r"[._-]", "", local) in ROLE_WORDS or any(p in ROLE_WORDS for p in parts):
        return None
    if not 2 <= len(parts) <= MAX_NAME_PARTS:
        return None
    return " ".join(p.capitalize() for p in parts)


def route(root: Path, groups: List[dict], *, home_domains, owner_addresses, today: str) -> dict:
    owners = {a.casefold() for a in owner_addresses}
    projects = active_projects(root)
    domains = entity_domains(root, home_domains)
    domain_projects: Dict[str, List[str]] = defaultdict(list)
    for p in projects:
        for domain in domains.get(p["entity"], set()):
            domain_projects[domain].append(p["slug"])
    created, emails_set = [], []

    for g in groups:  # learn addresses first: chat members carry names
        for address, name in g["names"].items():
            if address in owners or not name:
                continue
            try:
                slug = naming.slugify(name)
            except ValueError:
                continue  # an unsluggable display name must not abort routing
            if person.set_email_if_missing(root, slug, address):
                emails_set.append(slug)
    book = person.address_book(root)

    for g in groups:
        create = []
        if g["kind"] == "chat" and g["chat_type"] == "oneOnOne":
            create = [(a, g["names"].get(a)) for a in g["participants"]]
        elif g["kind"] == "mail":
            create = [(a, _name_from_address(a)) for a in g.get("direct_to", [])]
        for address, name in create:
            if address in owners or address in book or not name:
                continue
            try:
                result = person.ensure(root, name, today, email=address)
            except ValueError:
                continue
            if result["created"]:
                created.append(result["slug"])
                book[address] = result["slug"]
        g["people"] = sorted({book[a] for a in g["participants"] if a in book and a not in owners})

        strong, weak = set(), set()
        for address in g["participants"]:
            hits = domain_projects.get(address.rpartition("@")[2], [])
            (strong if len(hits) == 1 else weak).update(hits)
        texts = " \n ".join(m["text"] for m in g["messages"])
        for p in projects:
            words = [p["name"]] + p["keywords"]
            if any(_has_word(w, g["label"]) for w in words):
                strong.add(p["slug"])
            elif any(_has_word(k, texts) for k in p["keywords"]):
                weak.add(p["slug"])
        holders = [p["slug"] for p in projects if set(p["people"]) & set(g["people"])]
        if len(holders) == 1:
            weak.add(holders[0])
        weak -= strong
        g["projects"] = sorted(strong) + sorted(weak)
        g["projects_weak"] = sorted(weak)
        g["entities"] = sorted({p["entity"] for p in projects if p["slug"] in g["projects"] and p["entity"]})
    return {"created": sorted(created), "emails_set": sorted(set(emails_set))}
