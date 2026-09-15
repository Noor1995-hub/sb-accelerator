"""Meeting notes: schema-validated emission with collision guards.

The model extracts; this module writes. review_status is never a payload
field: every synced meeting lands needs-review (design decision 7 — the
auto-confirm gate needs per-deployment calibration data that a fresh vault
does not have), and the only paths out of it are the reviewed checkbox
(sync reconcile-reviews) or a human edit in Meetings.base.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from . import markdown, naming, project, schema, syncjob, vault

MEETINGS_DIR = vault.MEETINGS_DIR

REQUIRED_PAYLOAD = ("title", "date", "type", "calendar-subject",
                    "calendar_match", "attendees", "projects",
                    "recording-duration", "source", "takeaways", "debrief",
                    "source-recording-id")
OPTIONAL_PAYLOAD = ("attendee-emails", "organizer", "location", "recurring",
                    "source-filename",
                    "confidence", "confidence-reasons",
                    "action-items", "people", "entities")

# confidence-reasons is quoted wholesale: a "new-attendees:1" item in an
# unquoted flow list is exactly the kind of value PyYAML may read as a nested
# mapping — quoting every item costs nothing and parses identically in both
# parsers.
_QUOTE_KEYS = frozenset({"calendar-subject", "source-filename", "organizer",
                         "location", "conflicts-with", "confidence-reasons"})
_DATETIME_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?\Z")
_NEW_ATTENDEES_RE = re.compile(r"\Anew-attendees:[1-9]\d*\Z")
MAX_TAKEAWAYS = 5


class MeetingError(Exception):
    """A payload field or vault state the caller must fix."""


def _require_keys(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise MeetingError("the payload must be a JSON object")
    unknown = sorted(set(payload) - set(REQUIRED_PAYLOAD) - set(OPTIONAL_PAYLOAD))
    if unknown:
        raise MeetingError(
            f"unknown payload key(s) {unknown} — review_status, reviewed, "
            "archived and processed are set by this CLI, not by the caller"
        )
    missing = [key for key in REQUIRED_PAYLOAD if key not in payload]
    if missing:
        raise MeetingError(f"missing payload key(s) {missing}")


def _require_slug_list(payload: dict, key: str, *, allow_empty: bool) -> list:
    values = payload.get(key) or []
    if not isinstance(values, list):
        raise MeetingError(f"{key} must be a list of slugs")
    if not values and not allow_empty:
        raise MeetingError(f"{key} must be a non-empty list of slugs")
    for value in values:
        try:
            naming.validate_slug(str(value))
        except ValueError as exc:
            raise MeetingError(f"{key} entry {value!r}: {exc}") from exc
    return [str(v) for v in values]


def _require_entity_dossiers(root: Path, entities: list) -> None:
    for slug in entities:
        # The entity dossier's Meeting Log is a Dataview query over this
        # field. A slug with no dossier joins to nothing and fails silently:
        # the meeting simply never appears, with no error anywhere.
        if not (root / vault.ENTITIES_DIR / slug / "dossier.md").is_file():
            raise MeetingError(
                f"entities entry {slug!r} matches no dossier at "
                f"40-entities/{slug}/dossier.md — the entity's Meeting Log "
                "joins on this slug, so a typo silently empties it"
            )


def _require_joins(root: Path, attendees: list, projects: list,
                   people: list, entities: list) -> None:
    for slug in projects:
        if not (root / vault.PROJECTS_DIR / slug / "index.md").is_file():
            raise MeetingError(
                f"projects entry {slug!r} matches no project at "
                f"30-projects/{slug}/index.md — create it with /new-project, "
                "or leave projects empty for triage to catch"
            )
    _require_entity_dossiers(root, entities)
    for slug in dict.fromkeys(attendees + people):
        if not (root / vault.PEOPLE_DIR / f"{slug}.md").is_file():
            raise MeetingError(
                f"attendee {slug!r} has no person note at 50-people/{slug}.md "
                f"— run `person ensure` for them first"
            )


def _validate_confidence(payload: dict) -> None:
    rating = payload.get("confidence")
    reasons = payload.get("confidence-reasons")
    if (rating is None) != (reasons is None):
        raise MeetingError(
            "confidence and confidence-reasons travel together — pass both "
            "or neither"
        )
    if rating is None:
        return
    allowed_ratings = schema.enum_values("meeting", "confidence")
    if rating not in allowed_ratings:
        raise MeetingError(f"confidence {rating!r} is not one of {allowed_ratings}")
    groups = schema.for_object("meeting")["confidence_reasons"]
    if not isinstance(reasons, list):
        raise MeetingError("confidence-reasons must be a list")
    cal = [r for r in reasons if r in groups["calendar"]]
    proj = [r for r in reasons if r in groups["project-link"]]
    att = [r for r in reasons
           if r in groups["attendees"] or _NEW_ATTENDEES_RE.match(str(r))]
    leftovers = [r for r in reasons if r not in cal + proj + att]
    if leftovers:
        raise MeetingError(
            f"confidence-reasons {leftovers} are not in the closed vocabulary "
            "(new-attendees:{N} needs N >= 1)"
        )
    for name, hits in (("project-link", proj), ("calendar", cal),
                       ("attendees", att)):
        if len(hits) != 1:
            raise MeetingError(
                f"confidence-reasons needs exactly one {name} reason, got {hits}"
            )


def _validate_scalars(payload: dict) -> None:
    if not _DATETIME_RE.match(str(payload["date"])):
        raise MeetingError(
            f"date {payload['date']!r} must be ISO YYYY-MM-DD or YYYY-MM-DDTHH:MM"
        )
    duration = payload["recording-duration"]
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
        raise MeetingError("recording-duration must be an integer >= 0")
    if not isinstance(payload["calendar_match"], bool):
        raise MeetingError("calendar_match must be a boolean")
    takeaways = payload["takeaways"]
    if (not isinstance(takeaways, list) or not takeaways
            or len(takeaways) > MAX_TAKEAWAYS
            or not all(isinstance(t, str) and t.strip() for t in takeaways)):
        raise MeetingError(
            f"takeaways must be 1-{MAX_TAKEAWAYS} non-empty strings"
        )
    if not isinstance(payload["debrief"], str) or not payload["debrief"].strip():
        raise MeetingError("debrief must be a non-empty string")
    rid = payload.get("source-recording-id")
    if rid is not None:
        syncjob._validate_id(rid)


def _date_prefix(date_value: str) -> str:
    day = datetime.strptime(str(date_value)[:10], "%Y-%m-%d").date()
    return day.strftime("%d-%m-%y")


def date_from_stem(stem: str) -> Optional[date]:
    """The meeting date encoded in a stem, or None if it carries none.

    The inverse of _date_prefix, and it lives here so the pair moves
    together: meeting stems are DD-MM-YY-title, never ISO, and a caller
    that assumes otherwise (the recap fingerprint's window filter, for one)
    silently matches nothing. An ISO-prefixed stem is a decision note, and
    a hand-named note is simply not in any window.
    """
    try:
        return datetime.strptime(str(stem)[:8], "%d-%m-%y").date()
    except ValueError:
        return None


def _render_body(payload: dict) -> str:
    lines = ["", "## Key Takeaways"]
    lines += [f"- {item.strip()}" for item in payload["takeaways"]]
    lines += ["", "## Debrief", str(payload["debrief"]).strip()]
    action_items = payload.get("action-items") or []
    if action_items:
        lines += ["", "## Action Items"]
        lines += [f"- {item.strip()}" for item in action_items]
    people = payload.get("people") or []
    if people:
        lines += ["", "## People", " · ".join(f"[[{slug}]]" for slug in people)]
    return "\n".join(lines) + "\n"


def _frontmatter(payload: dict, review_status: str,
                 conflicts_with: Optional[str], entities: list) -> dict:
    data = {
        "date": payload["date"],
        "type": payload["type"],
        "calendar-subject": payload["calendar-subject"],
        "calendar_match": payload["calendar_match"],
    }
    for key in ("organizer", "location", "recurring", "attendee-emails"):
        if payload.get(key) is not None:
            data[key] = payload[key]
    data.update({
        "attendees": payload["attendees"],
        "projects": payload["projects"],
    })
    # Omitted rather than written empty: an entity dossier is the only reader,
    # and `entities: []` on a meeting with no entity counterparty is noise in
    # the properties panel of every note that has one.
    if entities:
        data["entities"] = entities
    data.update({
        "review_status": review_status,
        "reviewed": False,
        "archived": False,
    })
    for key in ("confidence", "confidence-reasons"):
        if payload.get(key) is not None:
            data[key] = payload[key]
    data["recording-duration"] = payload["recording-duration"]
    data["source"] = payload["source"]
    for key in ("source-recording-id", "source-filename"):
        if payload.get(key) is not None:
            data[key] = payload[key]
    if conflicts_with is not None:
        data["conflicts-with"] = f"[[{conflicts_with}]]"
    data["processed"] = True
    return data


def write(root: Path, payload: dict) -> dict:
    _require_keys(payload)
    _validate_scalars(payload)
    _validate_confidence(payload)
    if payload.get("source-recording-id") is not None:
        # Written in canonical form, so the ledger converges on one spelling
        # per recording going forward — the lookup below compares the same
        # way, so a recording already synced under the other spelling is
        # refused rather than written twice.
        payload = {**payload, "source-recording-id":
                   syncjob.canonical_id(payload["source-recording-id"])}
    # A note is the one capture that legitimately names nobody — a voice memo
    # musing, a pasted paragraph. Every meeting has attendees by definition.
    attendees = _require_slug_list(
        payload, "attendees", allow_empty=(payload["type"] == "note"))
    projects = _require_slug_list(payload, "projects", allow_empty=True)
    people = _require_slug_list(payload, "people", allow_empty=True)

    # entities is machine-owned once a meeting has a project: derived from
    # each project's `entity:` field so it can never drift from projects[]
    # at write time (the evening fold repairs drift introduced later by
    # retriage). A payload that passes entities anyway is refused here,
    # before the skill layer has a chance to build one — manual entities
    # only make sense on a project-less meeting.
    if projects and payload.get("entities") is not None:
        raise MeetingError(
            "entities is derived from projects[] once a meeting has a "
            "project — drop the entities key from the payload and let "
            "write() derive it from each project's `entity:` field; pass "
            "entities yourself only for a project-less meeting (leave "
            "projects empty)"
        )
    entities = [] if projects else _require_slug_list(
        payload, "entities", allow_empty=True)

    _require_joins(root, attendees, projects, people, entities)

    if projects:
        try:
            entities = project.derive_entities(root, projects)
        except project.ProjectError as exc:
            raise MeetingError(str(exc)) from exc
        _require_entity_dossiers(root, entities)

    prefix = _date_prefix(payload["date"])
    title_slug = naming.slugify(str(payload["title"]))
    base_stem = f"{prefix}-{title_slug}"
    naming.validate_slug(base_stem, max_length=naming.MAX_STEM_LENGTH)

    quote_keys = set(_QUOTE_KEYS)
    if ":" in str(payload["type"]):
        quote_keys.add("type")   # unquoted 1:1 is YAML for the integer 61

    # The collision guards look, then write — and concurrent sync workers can
    # both look before either writes (one meeting captured by two sources in
    # the same run derives one stem in both workers). atomic_create makes the
    # write refuse a name that appeared in between; the loser re-resolves and
    # lands on the collision path it would have taken had it looked later.
    for _ in range(3):
        stem, review_status, conflicts_with, conflict = _resolve_target(
            root, base_stem, payload)

        frontmatter = _frontmatter(
            payload, review_status, conflicts_with, entities)
        problems = schema.validate("meeting", frontmatter)
        if problems:
            raise MeetingError(
                "refusing to write non-conformant meeting frontmatter: "
                + "; ".join(problems)
            )

        target = root / MEETINGS_DIR / f"{stem}.md"
        try:
            vault.atomic_create(
                target, markdown.emit_frontmatter(frontmatter, quote_keys)
                + _render_body(payload))
        except FileExistsError:
            continue
        return {
            "stem": stem,
            "path": target.relative_to(root).as_posix(),
            "review_status": review_status,
            "recording_id": payload.get("source-recording-id"),
            "conflict": conflict,
        }
    raise MeetingError(
        f"could not claim a free stem for {base_stem!r} — concurrent writers "
        "kept taking every resolved name; re-run this recording"
    )


def _find_stem(folder: Path, stem: str) -> Optional[Path]:
    """Case-insensitive stem lookup (Linux VM writes, APFS/NTFS host)."""
    if not folder.is_dir():
        return None
    lowered = stem.lower()
    for candidate in sorted(folder.glob("*.md")):
        if candidate.stem.lower() == lowered:
            return candidate
    return None


def _first_free(folder: Path, pattern: str) -> str:
    for n in range(2, 100):
        candidate = pattern.format(n=n)
        if _find_stem(folder, candidate) is None:
            return candidate
    raise MeetingError(f"more than 98 collisions for {pattern!r} — clean up first")


def _namespace(recording_id) -> Optional[str]:
    text = str(recording_id or "")
    return text.split(":", 1)[0] if ":" in text else None


def _resolve_target(root: Path, stem: str, payload: dict):
    """Apply the collision guards, in order. Never overwrites."""
    rid = payload.get("source-recording-id")
    if rid is not None:
        known, _ = syncjob.known_recording_ids(root)
        if rid in known:
            raise MeetingError(
                f"recording {rid!r} is already synced as {known[rid]} — "
                "this is the dedup ledger working; do not write it again"
            )

    folder = root / MEETINGS_DIR
    existing = _find_stem(folder, stem)
    if existing is None:
        return stem, "needs-review", None, None

    try:
        data, _ = markdown.split_frontmatter(existing.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        data = {}   # unreadable counts as not-confirmed: suffix, don't touch
    status = data.get("review_status")

    if status == "confirmed":
        # An ordinary needs-review note: the conflicts-with edge below is the
        # clobber-risk signal, and reconcile_reviews refuses to fold a tick
        # while it is present.
        sibling = _first_free(folder, stem + "-v{n}")
        conflict = {"kind": "confirmed-target", "conflicts_with": existing.stem}
        return sibling, "needs-review", existing.stem, conflict

    mine = _namespace(rid)
    theirs = _namespace(data.get("source-recording-id"))
    if mine and theirs and mine != theirs:
        # Same stem, different source namespace: almost certainly one
        # conversation captured twice in the same run (a Plaud recording plus
        # the meeting's own Teams transcript) — the ledger keys on exact ids
        # and cannot see it, and a sibling worker's in-flight write is
        # invisible to the dispatch-time dedup. Flag it like a
        # confirmed-target sibling so triage shows the pair and
        # reconcile_reviews refuses to fold a tick until a human settles it.
        sibling = _first_free(folder, stem + "-v{n}")
        conflict = {"kind": "cross-source-duplicate",
                    "conflicts_with": existing.stem}
        return sibling, "needs-review", existing.stem, conflict

    suffixed = _first_free(folder, stem + "-{n}")
    conflict = {"kind": "stem-collision", "suffixed_from": existing.stem}
    return suffixed, "needs-review", None, conflict
