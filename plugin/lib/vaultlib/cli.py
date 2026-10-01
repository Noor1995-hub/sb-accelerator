#!/usr/bin/env python3
"""Deterministic vault operations for the Second Brain Accelerator skills.

Skills call these subcommands via Bash and read one JSON object from stdout.
The model decides — slug quality, context extraction, section routing, prose —
and this CLI writes: validation, collision detection, frontmatter emission,
table merges, atomic writes.

Invoke it as:

    python3 "${CLAUDE_PLUGIN_ROOT}/lib/vaultlib/cli.py" <subcommand> --vault <path> ...

Every run prints exactly one JSON object:

    {"ok": true,  "result": {...}}                       exit 0
    {"ok": false, "error": "...", "hint": "..."}         exit 1

Stdlib only, Python 3.10 floor — this runs inside the Cowork Linux VM.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

if __package__ in (None, ""):
    # Executed as a file path rather than imported as a package, which is how
    # the skills invoke it.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultlib import config, dailynote, dates, decision, discover, entity, feedback, fetcherrors, health, lastsync, m365, meeting, migrate, person, plaud, project, projectstate, provenance, runlog, scratch, schema, seenevents, syncjob, template, updatequeue, vault  # noqa: E402


def _emit(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _ok(result: dict) -> int:
    _emit({"ok": True, "result": result})
    return 0


def _fail(message: str, hint: str) -> int:
    _emit({"ok": False, "error": message, "hint": hint})
    return 1


def _add_vault_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--vault", required=True,
        help="absolute path to the vault root (a mount point under Cowork)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vaultlib", description=__doc__)
    top = parser.add_subparsers(dest="group", required=True)

    identity = top.add_parser("identity", help="read the context portfolio")
    identity_sub = identity.add_subparsers(dest="action", required=True)
    identity_show = identity_sub.add_parser(
        "show", help="print identity.md's setup-my-brain content block")
    _add_vault_argument(identity_show)

    context = top.add_parser("context", help="context portfolio marker blocks")
    context_sub = context.add_subparsers(dest="action", required=True)
    context_read = context_sub.add_parser("read", help="print one file's block")
    _add_vault_argument(context_read)
    context_read.add_argument("--file", required=True,
                              choices=sorted(vault.CONTEXT_FILES))
    context_write = context_sub.add_parser(
        "write", help="replace one file's setup-my-brain block")
    _add_vault_argument(context_write)
    context_write.add_argument("--file", required=True,
                               choices=sorted(vault.CONTEXT_FILES))
    context_write.add_argument("--content", required=True,
                               help="path to a text file, or - to read stdin")

    config_group = top.add_parser(
        "config", help="deployment config — the machine-read half of 99-workflow-config")
    config_sub = config_group.add_subparsers(dest="action", required=True)
    config_read = config_sub.add_parser(
        "read", help="read and validate 99-workflow-config/config.json")
    _add_vault_argument(config_read)
    config_verify = config_sub.add_parser(
        "verify-account",
        help="check a connector's signed-in account against its account_hint")
    _add_vault_argument(config_verify)
    config_verify.add_argument(
        "--adapter", required=True, choices=sorted(config.CONNECTOR_ADAPTERS),
        help="which connector adapter's binding to check")
    config_verify.add_argument(
        "--identity", required=True,
        help="path to the raw whoami JSON the connector returned (or - for stdin)")
    config_write = config_sub.add_parser(
        "write", help="set one config field; the whole file re-validates first")
    _add_vault_argument(config_write)
    config_write.add_argument(
        "--field", required=True, choices=sorted(config.WRITABLE_FIELDS))
    value_group = config_write.add_mutually_exclusive_group(required=True)
    value_group.add_argument(
        "--value",
        help="the new value (true/false for .enabled; a comma-separated "
             "list for adapters.m365.home_domains, e.g. "
             '"example.com,example.org")')
    value_group.add_argument("--null", action="store_true",
                             help="unset the field (nullable fields only)")

    dates_group = top.add_parser("dates", help="date and timezone arithmetic")
    dates_sub = dates_group.add_subparsers(dest="action", required=True)
    dates_window = dates_sub.add_parser(
        "window", help="UTC query window around a local timestamp")
    dates_window.add_argument(
        "--vault",
        help="optional vault root: the window is clamped to the vault's "
             "sync.start-date, so no adapter is ever asked for a meeting "
             "from before the vault existed. Omit only for a deliberate, "
             "interactive backfill.")
    dates_mode = dates_window.add_mutually_exclusive_group(required=True)
    dates_mode.add_argument("--start",
                            help="enrichment mode: local ISO date or datetime "
                                 "the window centers on")
    dates_mode.add_argument("--trailing-days", dest="trailing_days", type=int,
                            help="discovery mode: the trailing N local days, "
                                 "ending now — the window never reaches into "
                                 "the future")
    dates_window.add_argument("--timezone", help="IANA timezone name")
    dates_window.add_argument("--utc-offset", dest="utc_offset",
                              help="explicit offset like -05:00")
    dates_window.add_argument("--hours", type=float, default=None,
                              help="enrichment half-width (default 2); "
                                   "not accepted with --trailing-days")
    dates_window.add_argument(
        "--now", help="UTC ISO datetime override (tests); "
                      "--trailing-days only")
    dates_window.add_argument(
        "--adapter", choices=sorted(lastsync.ADAPTERS),
        help="narrow the trailing window to this adapter's last-sync "
             "watermark (read via --vault); --trailing-days only")

    dates_plan = dates_sub.add_parser(
        "plan", help="authoritative date block: today, next business day, recap window")
    _add_vault_argument(dates_plan)
    dates_plan.add_argument("--today", help="ISO date override (tests, backfills)")
    dates_plan.add_argument("--timezone", help="IANA timezone name")
    dates_plan.add_argument("--utc-offset", dest="utc_offset",
                            help="explicit offset like +02:00")
    dates_plan.add_argument(
        "--catchup-threshold", dest="catchup_threshold", type=int, default=5,
        help="business days missed before the recap is bounded (default 5)")
    dates_plan.add_argument(
        "--for-today", dest="for_today", action="store_true",
        help="plan the missed-evening run executed late: the note lands on "
             "today and the recap ends yesterday")
    dates_plan.add_argument(
        "--now", help="UTC ISO datetime override (tests); defaults to now")

    people = top.add_parser("person", help="person notes")
    people_sub = people.add_subparsers(dest="action", required=True)
    person_ensure = people_sub.add_parser(
        "ensure", help="create a person note if none exists")
    _add_vault_argument(person_ensure)
    person_ensure.add_argument("--name", required=True, help="display name")
    person_ensure.add_argument("--today", help="ISO date; defaults to today")
    person_ensure.add_argument(
        "--email", help="the attendee's address; stored on creation, and "
                        "filled into an existing note whose email is empty")

    projects = top.add_parser("project", help="project folders")
    projects_sub = projects.add_subparsers(dest="action", required=True)
    scaffold = projects_sub.add_parser(
        "scaffold", help="create a project index and decisions folder")
    _add_vault_argument(scaffold)
    scaffold.add_argument("--name", required=True, help="human-readable project name")
    scaffold.add_argument("--type", dest="project_type", required=True,
                          choices=schema.enum_values("project", "project-type"))
    scaffold.add_argument("--entity", required=True, help="entity slug (join key)")
    scaffold.add_argument(
        "--slug",
        help="explicit slug override; default is {entity}-{name-slug}")
    scaffold.add_argument("--owner", required=True, help="owner person slug")
    scaffold.add_argument("--parent", help="parent project slug (initiatives only)")
    scaffold.add_argument("--today", help="ISO date; defaults to today")
    scaffold.add_argument("--stage", help="one line for the Where it stands card")
    scaffold.add_argument("--contacts", help="one line for the Context callout")
    scaffold.add_argument("--source", help="one line for the Context callout")

    proj_touch = projects_sub.add_parser(
        "touch", help="bump last-updated and state-updated (and optionally "
                      "the milestone pair)")
    _add_vault_argument(proj_touch)
    proj_touch.add_argument("--slug", required=True)
    proj_touch.add_argument("--date", help="ISO date; defaults to today")
    proj_touch.add_argument(
        "--timestamp",
        help="ISO datetime YYYY-MM-DDTHH:MM; defaults to now — when the "
             "project's state was actually synthesized")
    proj_touch.add_argument("--next-milestone", dest="next_milestone",
                            help="one line; requires --next-milestone-date")
    proj_touch.add_argument("--next-milestone-date", dest="next_milestone_date",
                            help="ISO date; requires --next-milestone")

    proj_state = projects_sub.add_parser(
        "state", help="project state: render the index body from JSON")
    proj_state_sub = proj_state.add_subparsers(dest="state_action", required=True)
    proj_state_write = proj_state_sub.add_parser(
        "write", help="replace the index body from a state JSON and touch the frontmatter")
    _add_vault_argument(proj_state_write)
    proj_state_write.add_argument("--slug", required=True)
    proj_state_write.add_argument("--state", required=True,
                                  help="path to a JSON file, or - to read stdin")
    proj_state_write.add_argument("--today", help="ISO date; defaults to today")
    proj_state_write.add_argument("--timestamp",
                                  help="ISO datetime YYYY-MM-DDTHH:MM; defaults to now")

    entities = top.add_parser("entity", help="entity dossiers")
    entities_sub = entities.add_subparsers(dest="action", required=True)

    ent_ensure = entities_sub.add_parser(
        "ensure", help="create a dossier if none exists")
    _add_vault_argument(ent_ensure)
    ent_ensure.add_argument("--slug", required=True)
    ent_ensure.add_argument("--name", required=True, help="display name")
    ent_ensure.add_argument("--type", dest="entity_type",
                            choices=schema.enum_values("entity", "entity-type"))
    # No default: None means "not provided", so a re-run of ensure against an
    # existing dossier (say, to pick up --owner) does not silently stomp a
    # status set earlier. ensure() applies "prospect" itself, but only when
    # creating.
    ent_ensure.add_argument("--status",
                            choices=schema.enum_values("entity", "status"))
    ent_ensure.add_argument("--owner", help="owner person slug")
    ent_ensure.add_argument("--today", help="ISO date; defaults to today")

    ent_read = entities_sub.add_parser(
        "read", help="print the dossier's frontmatter and sections as JSON")
    _add_vault_argument(ent_read)
    ent_read.add_argument("--slug", required=True)

    ent_validate = entities_sub.add_parser(
        "validate",
        help="clear the [!unvalidated] banner — the explicit review act; "
             "content writes never do this as a side effect")
    _add_vault_argument(ent_validate)
    ent_validate.add_argument("--slug", required=True)
    ent_validate.add_argument("--today", help="ISO date; defaults to today")

    ent_write = entities_sub.add_parser(
        "write", help="apply section edits from a JSON payload")
    _add_vault_argument(ent_write)
    ent_write.add_argument("--slug", required=True)
    ent_write.add_argument("--edits", required=True,
                           help="path to a JSON file, or - to read stdin")
    ent_write.add_argument("--today", help="ISO date; defaults to today")

    decisions = top.add_parser("decision", help="decision notes")
    decisions_sub = decisions.add_subparsers(dest="action", required=True)

    dec_list = decisions_sub.add_parser(
        "list", help="print a project's decisions as JSON")
    _add_vault_argument(dec_list)
    dec_list.add_argument("--project", required=True, help="project slug")

    dec_write = decisions_sub.add_parser(
        "write", help="write a decision note, applying any supersession edge")
    _add_vault_argument(dec_write)
    dec_write.add_argument("--project", required=True, help="project slug")
    dec_write.add_argument(
        "--date", help="ISO date the decision was MADE; defaults to today")
    dec_write.add_argument("--note", required=True,
                           help="path to a JSON file, or - to read stdin")
    # No default: the mode decides what goes into the `reviewed` audit field,
    # and a wrong default writes a lie into it.
    mode = dec_write.add_mutually_exclusive_group(required=True)
    mode.add_argument("--foreground", action="store_true",
                      help="a human validated this inline; writes reviewed: true")
    mode.add_argument("--background", action="store_true",
                      help="unattended capture; writes reviewed: false")

    sync = top.add_parser("sync", help="recording-sync ledger operations")
    sync_sub = sync.add_subparsers(dest="action", required=True)

    sync_scan = sync_sub.add_parser(
        "scan", help="partition 10-inbox/ files against the sync ledger")
    _add_vault_argument(sync_scan)

    sync_dedup = sync_sub.add_parser(
        "dedup", help="filter a JSON list of namespaced ids against the ledger")
    _add_vault_argument(sync_dedup)
    sync_dedup.add_argument("--ids", required=True,
                            help="path to a JSON array of ids, or - for stdin")

    sync_collide = sync_sub.add_parser(
        "collide",
        help="find meeting notes whose time window overlaps a candidate recording")
    _add_vault_argument(sync_collide)
    sync_collide.add_argument("--start", required=True,
                              help="owner-local start, YYYY-MM-DDTHH:MM")
    sync_collide.add_argument("--duration-min", dest="duration_min",
                              required=True, type=int,
                              help="candidate recording length in minutes")

    sync_skip = sync_sub.add_parser(
        "skip", help="never propose this recording id again")
    _add_vault_argument(sync_skip)
    sync_skip.add_argument("--id", dest="recording_id", required=True)
    sync_skip.add_argument("--reason",
                           help="why, for whoever reads the list later")

    sync_rec = sync_sub.add_parser(
        "reconcile-reviews",
        help="flip review_status needs-review -> confirmed where reviewed is "
             "ticked; a note still carrying conflicts-with is reported, "
             "not flipped")
    _add_vault_argument(sync_rec)
    sync_rec.add_argument(
        "--timestamp",
        help="ISO datetime YYYY-MM-DDTHH:MM stamped as confirmed-at on every "
             "note flipped; defaults to now")

    sync_archive = sync_sub.add_parser(
        "archive",
        help="move a processed or parked inbox file to 90-archive/inbox/")
    _add_vault_argument(sync_archive)
    sync_archive.add_argument(
        "--path", required=True,
        help="vault-relative path of the inbox file, e.g. 10-inbox/notes.txt")
    sync_archive.add_argument("--today", help="ISO date; defaults to today")

    # --reason has no default on purpose. A park suppresses an id forever and
    # moves a file out of sight; the reason is the only thing that makes that
    # reviewable later, so argparse refuses the call rather than let it be
    # omitted.
    sync_park = sync_sub.add_parser(
        "park",
        help="archive a non-capture inbox file, suppress its id, record why")
    _add_vault_argument(sync_park)
    sync_park.add_argument(
        "--path", required=True,
        help="vault-relative path of the inbox file, e.g. 10-inbox/deck.pptx")
    sync_park.add_argument("--id", dest="recording_id", required=True)
    sync_park.add_argument(
        "--reason", required=True,
        help="why this is not a capture, e.g. 'vendor whitepaper, no capture "
             "content'")
    sync_park.add_argument("--today", help="ISO date; defaults to today")

    sync_queue = sync_sub.add_parser(
        "update-queue",
        help="write meeting metrics and list projects needing state synthesis")
    _add_vault_argument(sync_queue)
    sync_queue.add_argument("--owner", required=True,
                            help="the vault owner's person slug (excluded from key-people)")
    sync_queue.add_argument("--today", help="ISO date; defaults to today")

    sync_triage = sync_sub.add_parser(
        "m365-triage",
        help="answer, from the cheap calendar-search listing alone, which "
             "event occurrences still need the full event fetch")
    _add_vault_argument(sync_triage)
    sync_triage.add_argument(
        "--events", required=True,
        help="path to the raw search listing (JSON array of event objects), "
             "or - for stdin")
    sync_triage.add_argument(
        "--now", help="UTC ISO datetime override (tests); defaults to now")
    sync_triage.add_argument(
        "--collide", action="store_true",
        help="also run the cross-adapter duplicate check against each "
             "fetch survivor's own time window, moving a strong, "
             "non-imprecise match into the `duplicate` bucket instead of "
             "`fetch`; requires --timezone or --utc-offset")
    sync_triage.add_argument(
        "--timezone", help="IANA timezone name; only with --collide")
    sync_triage.add_argument(
        "--utc-offset", dest="utc_offset",
        help="explicit offset like +02:00; only with --collide")

    sync_record = sync_sub.add_parser(
        "m365-record",
        help="record per-occurrence outcomes back into the seen-events "
             "cache, so the next run's triage skips them pre-fetch")
    _add_vault_argument(sync_record)
    sync_record.add_argument(
        "--outcomes", required=True,
        help="path to a JSON array of {id, start_utc, outcome[, "
             "recording_id]} objects, or - for stdin")
    sync_record.add_argument(
        "--now", help="UTC ISO datetime override (tests); defaults to now")

    sync_forget = sync_sub.add_parser(
        "m365-forget",
        help="drop every seen-events cache entry with one outcome, forcing "
             "a re-check next run (the hand-editable-cache fallback, made "
             "deterministic) — e.g. after adding the organizer's domain to "
             "adapters.m365.home_domains or after client IT switches on "
             "the tenant's Microsoft Graph transcript-access setting, "
             "either of which can turn a no-access 403 into a fetch")
    _add_vault_argument(sync_forget)
    sync_forget.add_argument(
        "--outcome",
        help="bulk mode: the outcome to drop — no-access, forbidden, or "
             "no-transcript; written and skipped are refused (they would "
             "re-trigger a paid dispatch wave or undo a deliberate "
             "decision, not a stale denial). Mutually exclusive with "
             "--event-id/--start-utc")
    sync_forget.add_argument(
        "--event-id", dest="event_id",
        help="targeted mode: forget exactly this occurrence's seen-events "
             "entry, regardless of its outcome — the undo for a "
             "triage-caught cross-adapter duplicate (sync "
             "settle-duplicate); travels with --start-utc")
    sync_forget.add_argument(
        "--start-utc", dest="start_utc",
        help="the occurrence's start_utc key; travels with --event-id")

    sync_settle = sync_sub.add_parser(
        "settle-duplicate",
        help="settle an unattended cross-adapter duplicate: validated, "
             "then the skip-list line and, when the m365 occurrence is "
             "known, the seen-events skipped entry — in that order")
    _add_vault_argument(sync_settle)
    sync_settle.add_argument(
        "--id", dest="recording_id", required=True,
        help="the new recording's own id, e.g. m365:<hex>")
    sync_settle.add_argument(
        "--existing", dest="existing_id", required=True,
        help="the id of the meeting note it duplicates")
    sync_settle.add_argument(
        "--stem", required=True,
        help="the existing meeting note's stem, named in the reason text")
    sync_settle.add_argument(
        "--event-id", dest="event_id",
        help="the underlying m365 event id, when known — travels with "
             "--start-utc")
    sync_settle.add_argument(
        "--start-utc", dest="start_utc",
        help="the occurrence's start_utc key, when known — travels with "
             "--event-id")
    sync_settle.add_argument(
        "--now", help="UTC ISO datetime override (tests); defaults to now")

    sync_unskip = sync_sub.add_parser(
        "unskip",
        help="remove one id from the never-propose-again list; refuses an "
             "id that is not on it")
    _add_vault_argument(sync_unskip)
    sync_unskip.add_argument("--id", dest="recording_id", required=True)

    sync_unsettle = sync_sub.add_parser(
        "unsettle-duplicate",
        help="undo a worker-settled cross-adapter duplicate: removes the "
             "skip-list line and, when the m365 occurrence is named, the "
             "seen-events entry too — sync unskip alone would leave an "
             "M365 occurrence permanently filtered out of every future "
             "triage")
    _add_vault_argument(sync_unsettle)
    sync_unsettle.add_argument(
        "--id", dest="recording_id", required=True,
        help="the recording id sync settle-duplicate was given, e.g. "
             "m365:<hex>")
    sync_unsettle.add_argument(
        "--event-id", dest="event_id",
        help="the underlying m365 event id, if settle-duplicate was given "
             "one — travels with --start-utc")
    sync_unsettle.add_argument(
        "--start-utc", dest="start_utc",
        help="the occurrence's start_utc key, if settle-duplicate was "
             "given one — travels with --event-id")

    sync_rederive = sync_sub.add_parser(
        "rederive-entities",
        help="recompute entities from projects on every meeting; repairs "
             "triage drift left by re-assigning projects[] after the note "
             "was written")
    _add_vault_argument(sync_rederive)

    sync_watermark = sync_sub.add_parser(
        "watermark",
        help="advance an adapter's last-successful-sync mark; monotonic — "
             "a --utc-to earlier than the stored mark is a no-op")
    _add_vault_argument(sync_watermark)
    sync_watermark.add_argument("--adapter", required=True,
                                choices=lastsync.ADAPTERS)
    sync_watermark.add_argument(
        "--utc-to", dest="utc_to", required=True,
        help="UTC ISO datetime the sync run covered through")

    sync_routing = sync_sub.add_parser(
        "routing-signals",
        help="compact digest of projects/entities/people for routing a "
             "recording — values only, never note bodies")
    _add_vault_argument(sync_routing)

    sync_fetch_error = sync_sub.add_parser(
        "fetch-error",
        help="count a batch's fetch-error outcomes per recording id; parks "
             "an id (writes the skip-list line) once it has failed on three "
             "distinct UTC days, each within 14 days of the previous "
             "failure — never on repeat attempts within one UTC day. Also "
             "clears any tracked id the vault's own ledger now shows as "
             "written.")
    _add_vault_argument(sync_fetch_error)
    sync_fetch_error.add_argument(
        "--outcomes", required=True,
        help="path to a JSON array of {id, reason} objects, or - for stdin")
    sync_fetch_error.add_argument(
        "--now", help="UTC ISO datetime override (tests); defaults to now")

    meetings = top.add_parser("meeting", help="meeting notes")
    meetings_sub = meetings.add_subparsers(dest="action", required=True)
    meeting_write = meetings_sub.add_parser(
        "write", help="write one meeting note from a JSON payload")
    _add_vault_argument(meeting_write)
    meeting_write.add_argument("--note", required=True,
                               help="path to a JSON file, or - to read stdin")
    meeting_write.add_argument(
        "--accept-collision", dest="accept_collision", action="store_true",
        help="write anyway despite a strong, non-imprecise cross-adapter "
             "time-window collision from another adapter — the "
             "interactive 'write it anyway' re-dispatch")

    plaud_group = top.add_parser("plaud", help="Plaud MCP adapter helpers")
    plaud_sub = plaud_group.add_subparsers(dest="action", required=True)
    plaud_re = plaud_sub.add_parser(
        "reassemble", help="render raw MCP JSON into one capture-bundle blob")
    plaud_re.add_argument("--meta", required=True)
    plaud_re.add_argument("--transcript", required=True, nargs="+",
                          metavar="PAGE",
                          help="transcript JSON; one path per get_transcript "
                               "page, in any order")
    plaud_re.add_argument("--note")
    plaud_re.add_argument("--out", required=True,
                          help="scratch directory for the blob (never the vault)")
    plaud_re.add_argument("--timezone", help="IANA timezone name")
    plaud_re.add_argument("--utc-offset", dest="utc_offset")

    m365_group = top.add_parser(
        "m365", help="Microsoft 365 / Teams transcript adapter helpers")
    m365_sub = m365_group.add_subparsers(dest="action", required=True)
    m365_ids = m365_sub.add_parser(
        "ids", help="derive m365: recording ids from event reads (the trimmed event file)")
    m365_ids.add_argument("--events", required=True,
                          help="path to a JSON array of event objects, or - for stdin")
    m365_ids.add_argument(
        "--timezone", help="IANA timezone name — adds recorded_local and "
                           "event_duration_min to each derived entry")
    m365_ids.add_argument(
        "--utc-offset", dest="utc_offset",
        help="explicit offset like +02:00 — same effect as --timezone")
    m365_agenda = m365_sub.add_parser(
        "agenda",
        help="the day's meetings from a raw calendar-search listing, filtered, "
             "sorted and rendered in the owner's local time (daily-note prep)")
    m365_agenda.add_argument(
        "--events", required=True,
        help="path to the raw outlook_calendar_search output (every page, "
             "as written), or - for stdin")
    m365_agenda.add_argument("--timezone", help="IANA timezone name")
    m365_agenda.add_argument("--utc-offset", dest="utc_offset",
                             help="explicit offset like +02:00 — same effect as --timezone")
    m365_agenda.add_argument(
        "--date", help="owner-local day YYYY-MM-DD — events whose local start "
                       "falls on another day are dropped and counted")
    m365_re = m365_sub.add_parser(
        "reassemble",
        help="render an event read + transcript read into one capture-bundle blob")
    m365_re.add_argument("--event", required=True)
    m365_re.add_argument("--transcript", required=True)
    m365_re.add_argument("--out", required=True,
                         help="scratch directory for the blob (never the vault)")
    m365_re.add_argument("--timezone", help="IANA timezone name")
    m365_re.add_argument("--utc-offset", dest="utc_offset")

    discover_group = top.add_parser(
        "discover", help="Session-1 discovery: M365 evidence and the proposal check")
    discover_sub = discover_group.add_subparsers(dest="action", required=True)
    discover_window = discover_sub.add_parser(
        "window", help="UTC query windows for the two setup reads (no start-date clamp)")
    discover_window.add_argument("--timezone", help="IANA timezone name")
    discover_window.add_argument("--utc-offset", dest="utc_offset",
                                 help="explicit offset like +02:00")
    discover_window.add_argument("--days-back", dest="days_back", type=int, default=84)
    discover_window.add_argument("--days-forward", dest="days_forward", type=int, default=14)
    discover_window.add_argument("--now", help="UTC ISO datetime override (tests)")
    discover_build = discover_sub.add_parser(
        "build", help="turn one read's payload files in --dir into the evidence list")
    _add_vault_argument(discover_build)
    discover_build.add_argument("--dir", required=True,
                                help="the session scratch directory (never the vault)")
    discover_build.add_argument(
        "--consume", action="store_true",
        help="delete exactly the payload files this build read, once the "
             "evidence is written")
    discover_build.add_argument(
        "--expect",
        help="worker row counts from its outcome line, e.g. "
             "calendar=180,sent=64; use <source>=error for a source the "
             "worker reported as failed and <source>=unread for one the "
             "clock stopped before its first page")
    discover_clock_start = discover_sub.add_parser(
        "clock-start", help="start the read's time budget (the worker cannot see a clock)")
    discover_clock_start.add_argument("--dir", required=True)
    discover_clock_start.add_argument(
        "--budget", type=int, default=discover.DEFAULT_BUDGET_S,
        help="seconds the read may take (default 300)")
    discover_clock_start.add_argument("--now", help="UTC ISO datetime override (tests)")
    discover_clock_check = discover_sub.add_parser(
        "clock-check", help="may the read go on? answers continue true or false")
    discover_clock_check.add_argument("--dir", required=True)
    discover_clock_check.add_argument("--now", help="UTC ISO datetime override (tests)")
    discover_answer = discover_sub.add_parser(
        "answer", help="record what the owner said, verbatim, as citable evidence")
    discover_answer.add_argument("--dir", required=True)
    discover_answer.add_argument("--question", required=True)
    discover_answer.add_argument("--text", required=True)
    discover_check = discover_sub.add_parser(
        "check", help="split a proposal into passed and dropped, or check a block")
    discover_check.add_argument("--dir", required=True)
    discover_target = discover_check.add_mutually_exclusive_group(required=True)
    discover_target.add_argument("--proposal", help="path to a proposal JSON file")
    discover_target.add_argument("--block", help="path to a draft context block")

    feedback_group = top.add_parser(
        "feedback", help="scrub-linted product feedback, sent as a GitHub issue")
    feedback_sub = feedback_group.add_subparsers(dest="action", required=True)
    feedback_lint = feedback_sub.add_parser(
        "lint", help="run the deterministic scrub check against a draft")
    _add_vault_argument(feedback_lint)
    feedback_lint.add_argument("--body-file", dest="body_file", required=True,
                               help="path to the draft text, or - to read stdin")
    feedback_send = feedback_sub.add_parser(
        "send", help="lint, stamp with deployment info, and file a GitHub issue")
    _add_vault_argument(feedback_send)
    feedback_send.add_argument("--title", required=True)
    feedback_send.add_argument("--body-file", dest="body_file", required=True,
                               help="path to the draft text, or - to read stdin")

    daily = top.add_parser("daily-note",
                           help="daily notes: region write and harvest read")
    daily_sub = daily.add_subparsers(dest="action", required=True)
    daily_write = daily_sub.add_parser(
        "write", help="render or region-merge one daily note from a JSON payload")
    _add_vault_argument(daily_write)
    daily_write.add_argument("--note", required=True,
                             help="path to a JSON file, or - to read stdin")
    daily_read = daily_sub.add_parser(
        "read", help="parse a daily note into regions and human jottings")
    _add_vault_argument(daily_read)
    daily_read.add_argument("--date", required=True, help="ISO date of the note")

    migrate_group = top.add_parser(
        "migrate", help="vault structure migrations: snapshot, apply, verify")
    migrate_sub = migrate_group.add_subparsers(dest="action", required=True)
    migrate_status = migrate_sub.add_parser(
        "status", help="pending migrations and the current/expected version")
    _add_vault_argument(migrate_status)
    migrate_run = migrate_sub.add_parser(
        "run", help="snapshot then apply+verify every pending migration in order")
    _add_vault_argument(migrate_run)
    migrate_run.add_argument("--today", help="ISO date; defaults to today")
    migrate_run.add_argument(
        "--stamp", help="snapshot timestamp override (tests)")

    scratch_group = top.add_parser(
        "scratch", help="scratch-directory hygiene for unattended runs")
    scratch_sub = scratch_group.add_subparsers(dest="action", required=True)
    scratch_sweep = scratch_sub.add_parser(
        "sweep", help="delete the built-in pattern list from --dir, and only --dir")
    scratch_sweep.add_argument(
        "--dir", required=True,
        help="the session scratch directory to sweep — never the vault")

    runlog_group = top.add_parser(
        "runlog", help="append-only one-line-per-run log for unattended routines")
    runlog_sub = runlog_group.add_subparsers(dest="action", required=True)
    runlog_append = runlog_sub.add_parser(
        "append", help="append one outcome line to 99-workflow-config/logs/routine-runs.log")
    _add_vault_argument(runlog_append)
    runlog_append.add_argument(
        "--routine", required=True,
        help="routine name, kebab-case, e.g. evening-sync or sync-recordings")
    runlog_append.add_argument(
        "--outcome", required=True,
        help="one line describing what happened, including a no-op run")

    provenance_group = top.add_parser(
        "provenance", help="CLI-owned vault provenance record (read-only here; "
                           "written in-process by provision and migrate)")
    provenance_sub = provenance_group.add_subparsers(dest="action", required=True)
    provenance_read = provenance_sub.add_parser(
        "read", help="the recorded provenance plus plugin-version drift")
    _add_vault_argument(provenance_read)

    template_group = top.add_parser(
        "template", help="managed template-file tiers: status, diff, refresh "
                          "(#117, built on provenance)")
    template_sub = template_group.add_subparsers(dest="action", required=True)
    template_status = template_sub.add_parser(
        "status", help="per managed file: current/refresh/needs-consent/"
                       "missing/blocked, against the shipped template")
    _add_vault_argument(template_status)
    template_diff = template_sub.add_parser(
        "diff", help="unified diff from the vault's copy to the shipped "
                     "template for one managed file")
    _add_vault_argument(template_diff)
    template_diff.add_argument("--file", required=True,
                               help="managed relpath, e.g. 20-meetings/Meetings.base")
    template_refresh = template_sub.add_parser(
        "refresh", help="replace managed files with the shipped template; "
                        "--consent required for edited/missing files")
    _add_vault_argument(template_refresh)
    template_refresh.add_argument(
        "--file", action="append", dest="files",
        help="a managed relpath to refresh (repeatable); default is every "
             "silently-refreshable file")
    template_refresh.add_argument(
        "--all-pending", action="store_true",
        help="select every refresh/needs-consent/missing file (never a "
             "seeded-once file, which is refused regardless)")
    template_refresh.add_argument(
        "--consent", action="store_true",
        help="required alongside --file/--all-pending for edited or missing files")
    template_refresh.add_argument("--today", help="ISO date; defaults to today")
    template_refresh.add_argument(
        "--stamp", help="backup-directory timestamp override (tests)")

    health_group = top.add_parser(
        "health", help="content-free vault health metrics (read-only)")
    health_sub = health_group.add_subparsers(dest="action", required=True)
    health_report = health_sub.add_parser(
        "report", help="counts/rates/ages over a lookback window; never a "
                       "title, name, or filename")
    _add_vault_argument(health_report)
    health_report.add_argument("--today", help="ISO date; defaults to today")
    # No type=int here: an out-of-range or non-numeric value is a HealthError
    # raised from health.report(), not an argparse SystemExit.
    health_report.add_argument(
        "--window", help="lookback window in days (default 28)")
    health_report.add_argument(
        "--write", action="store_true",
        help="also render to 99-workflow-config/health-reports/{today}.md")

    return parser


def _parse_expect(text: Optional[str]) -> Optional[dict]:
    if not text:
        return None
    counts: dict = {}
    for part in text.split(","):
        source, sep, value = part.strip().partition("=")
        if not sep or not source.strip():
            raise ValueError(f"--expect entry {part!r} must look like calendar=180")
        value = value.strip()
        counts[source.strip()] = value if value in ("error", "unread") else int(value)
    return counts


def _dispatch(args: argparse.Namespace) -> int:
    # dates window (stateless unless clamping) and dates plan aside, --vault
    # is required everywhere it exists — getattr covers both shapes.
    root = (vault.resolve(args.vault)
            if getattr(args, "vault", None) is not None else None)
    if args.group == "dates":
        if args.action == "window":
            start_date = (config.read(root)["config"]["sync"]["start-date"]
                          if root is not None else None)
            if args.trailing_days is not None:
                if args.hours is not None:
                    raise dates.DatesError(
                        "--hours is the enrichment half-width; the trailing "
                        "window runs local midnight to now and takes none")
                if args.adapter is not None and root is None:
                    raise dates.DatesError(
                        "--adapter requires --vault so the adapter's "
                        "last-sync watermark can be read")
                now_utc = (dates._parse_now(args.now)
                           if args.now is not None else None)
                watermark = (lastsync.read(root, args.adapter)
                            if args.adapter is not None else None)
                return _ok(dates.trailing_window(
                    args.trailing_days, timezone=args.timezone,
                    utc_offset=args.utc_offset, start_date=start_date,
                    now_utc=now_utc, watermark=watermark))
            if args.adapter is not None:
                raise dates.DatesError(
                    "--adapter narrows --trailing-days discovery; --start "
                    "does not take it")
            if args.now is not None:
                raise dates.DatesError(
                    "--now applies to --trailing-days discovery only")
            return _ok(dates.window(args.start, timezone=args.timezone,
                                    utc_offset=args.utc_offset,
                                    hours=(2.0 if args.hours is None
                                           else args.hours),
                                    start_date=start_date))
        return _ok(dates.plan(root, args.today, timezone=args.timezone,
                              utc_offset=args.utc_offset,
                              catchup_threshold=args.catchup_threshold,
                              for_today=args.for_today,
                              now_utc=(dates._parse_now(args.now)
                                       if args.now is not None else None)))
    if args.group == "identity":
        return _ok({"identity": vault.read_identity_block(root)})
    if args.group == "context":
        if args.action == "read":
            return _ok({"file": args.file,
                        "content": vault.read_context_block(root, args.file)})
        content = (sys.stdin.read() if args.content == "-"
                   else Path(args.content).read_text(encoding="utf-8"))
        return _ok(vault.write_context_block(root, args.file, content))
    if args.group == "config":
        if args.action == "read":
            return _ok(config.read(root))
        if args.action == "write":
            if args.null:
                value = None
            elif args.field.endswith(".enabled"):
                if args.value not in ("true", "false"):
                    raise config.ConfigError(
                        f"{args.field} takes --value true or false")
                value = args.value == "true"
            elif args.field in config._LIST_FIELDS:
                value = [v.strip() for v in args.value.split(",")]
                value = [v for v in value if v]
            else:
                value = args.value
            return _ok(config.write(root, args.field, value))
        payload = (json.load(sys.stdin) if args.identity == "-"
                   else json.loads(Path(args.identity).read_text(encoding="utf-8")))
        return _ok(config.verify_account(root, args.adapter, payload))
    if args.group == "person":
        today = vault.today_iso(getattr(args, "today", None))
        return _ok(person.ensure(root, args.name, today, email=args.email))
    if args.group == "project":
        if args.action == "state":
            payload = (json.load(sys.stdin) if args.state == "-"
                       else json.loads(Path(args.state).read_text(encoding="utf-8")))
            return _ok(projectstate.write(
                root, slug=args.slug, payload=payload,
                today=vault.today_iso(args.today), timestamp=args.timestamp))
        if args.action == "touch":
            return _ok(project.touch(
                root, slug=args.slug, date_iso=vault.today_iso(args.date),
                timestamp=args.timestamp,
                next_milestone=args.next_milestone,
                next_milestone_date=args.next_milestone_date,
            ))
        today = vault.today_iso(getattr(args, "today", None))
        return _ok(project.scaffold(
            root, name=args.name, project_type=args.project_type,
            entity=args.entity, owner=args.owner, today=today,
            parent=args.parent, stage=args.stage,
            contacts=args.contacts, source=args.source,
            slug=args.slug,
        ))
    if args.group == "entity":
        if args.action == "ensure":
            return _ok(entity.ensure(
                root, slug=args.slug, name=args.name,
                today=vault.today_iso(args.today),
                entity_type=args.entity_type, status=args.status,
                owner=args.owner,
            ))
        if args.action == "read":
            return _ok(entity.read(root, args.slug))
        if args.action == "validate":
            return _ok(entity.validate(root, args.slug,
                                       vault.today_iso(args.today)))
        payload = (json.load(sys.stdin) if args.edits == "-"
                   else json.loads(Path(args.edits).read_text(encoding="utf-8")))
        return _ok(entity.write(root, args.slug, payload,
                                vault.today_iso(args.today)))
    if args.group == "decision":
        if args.action == "list":
            return _ok(decision.list_decisions(root, args.project))
        payload = (json.load(sys.stdin) if args.note == "-"
                   else json.loads(Path(args.note).read_text(encoding="utf-8")))
        return _ok(decision.write(
            root, project=args.project, date=vault.today_iso(args.date),
            payload=payload, reviewed=args.foreground,
        ))
    if args.group == "sync":
        if args.action == "scan":
            return _ok(syncjob.scan(root))
        if args.action == "dedup":
            payload = (json.load(sys.stdin) if args.ids == "-"
                       else json.loads(Path(args.ids).read_text(encoding="utf-8")))
            if not isinstance(payload, list):
                raise syncjob.SyncError("--ids must be a JSON array of id strings")
            return _ok(syncjob.dedup(root, payload))
        if args.action == "collide":
            return _ok(syncjob.collide(root, args.start, args.duration_min))
        if args.action == "skip":
            return _ok(syncjob.skip(root, args.recording_id,
                                    reason=args.reason))
        if args.action == "reconcile-reviews":
            return _ok(syncjob.reconcile_reviews(root,
                                                 timestamp=args.timestamp))
        if args.action == "archive":
            return _ok(syncjob.archive(root, args.path,
                                       vault.today_iso(args.today)))
        if args.action == "park":
            return _ok(syncjob.park(root, args.path, args.recording_id,
                                    args.reason, vault.today_iso(args.today)))
        if args.action == "update-queue":
            return _ok(updatequeue.run(root, vault.today_iso(args.today),
                                       args.owner))
        if args.action == "m365-triage":
            payload = (json.load(sys.stdin) if args.events == "-"
                       else json.loads(Path(args.events).read_text(encoding="utf-8")))
            home_domains, home_domains_warning = config.m365_home_domains(root)
            result = seenevents.triage(
                root, payload, seenevents.parse_now(args.now),
                home_domains=home_domains, collide=args.collide,
                timezone=args.timezone, utc_offset=args.utc_offset)
            if home_domains_warning:
                result["warnings"] = result["warnings"] + [home_domains_warning]
            return _ok(result)
        if args.action == "m365-record":
            payload = (json.load(sys.stdin) if args.outcomes == "-"
                       else json.loads(Path(args.outcomes).read_text(encoding="utf-8")))
            return _ok(seenevents.record(root, payload, seenevents.parse_now(args.now)))
        if args.action == "m365-forget":
            id_scoped = args.event_id is not None or args.start_utc is not None
            if id_scoped and args.outcome is not None:
                raise seenevents.SeenEventsError(
                    "--outcome and --event-id/--start-utc are mutually "
                    "exclusive — pass the bulk outcome form or the "
                    "targeted id form, not both"
                )
            if id_scoped:
                if args.event_id is None or args.start_utc is None:
                    raise seenevents.SeenEventsError(
                        "--event-id and --start-utc travel together — "
                        "pass both"
                    )
                return _ok(seenevents.forget_event(
                    root, args.event_id, args.start_utc))
            if args.outcome is None:
                raise seenevents.SeenEventsError(
                    "pass --outcome for the bulk form, or --event-id and "
                    "--start-utc together for the targeted form"
                )
            return _ok(seenevents.forget(root, args.outcome))
        if args.action == "settle-duplicate":
            return _ok(seenevents.settle_duplicate(
                root, args.recording_id, args.existing_id, args.stem,
                event_id=args.event_id, start_utc=args.start_utc,
                now_utc=seenevents.parse_now(args.now)))
        if args.action == "unskip":
            return _ok(syncjob.unskip(root, args.recording_id))
        if args.action == "unsettle-duplicate":
            return _ok(seenevents.unsettle_duplicate(
                root, args.recording_id,
                event_id=args.event_id, start_utc=args.start_utc))
        if args.action == "rederive-entities":
            return _ok(syncjob.rederive_entities(root))
        if args.action == "watermark":
            now_utc = datetime.now(timezone.utc).replace(
                tzinfo=None, microsecond=0)
            return _ok(lastsync.set_mark(root, args.adapter, args.utc_to,
                                         now_utc))
        if args.action == "routing-signals":
            return _ok(syncjob.routing_signals(root))
        if args.action == "fetch-error":
            payload = (json.load(sys.stdin) if args.outcomes == "-"
                       else json.loads(Path(args.outcomes).read_text(encoding="utf-8")))
            return _ok(fetcherrors.record(
                root, payload, fetcherrors.parse_now(args.now)))
    if args.group == "meeting":
        payload = (json.load(sys.stdin) if args.note == "-"
                   else json.loads(Path(args.note).read_text(encoding="utf-8")))
        return _ok(meeting.write(root, payload,
                                 accept_collision=args.accept_collision))
    if args.group == "plaud":
        return _ok(plaud.reassemble(
            args.meta, args.transcript, args.note, args.out,
            timezone=args.timezone, utc_offset=args.utc_offset))
    if args.group == "m365":
        if args.action == "ids":
            payload = (json.load(sys.stdin) if args.events == "-"
                       else json.loads(Path(args.events).read_text(encoding="utf-8")))
            return _ok(m365.ids(payload, timezone=args.timezone,
                                utc_offset=args.utc_offset))
        if args.action == "agenda":
            text = (sys.stdin.read() if args.events == "-"
                    else Path(args.events).read_text(encoding="utf-8"))
            return _ok(m365.agenda(m365.load_listing(text), timezone=args.timezone,
                                   utc_offset=args.utc_offset, date=args.date))
        return _ok(m365.reassemble(
            args.event, args.transcript, args.out,
            timezone=args.timezone, utc_offset=args.utc_offset))
    if args.group == "discover":
        if args.action == "window":
            return _ok(discover.window(
                timezone=args.timezone, utc_offset=args.utc_offset,
                days_back=args.days_back, days_forward=args.days_forward, now=args.now))
        if args.action == "clock-start":
            return _ok(discover.clock_start(args.dir, budget_s=args.budget, now=args.now))
        if args.action == "clock-check":
            return _ok(discover.clock_check(args.dir, now=args.now))
        if args.action == "build":
            home_domains, _warning = config.m365_home_domains(root)
            return _ok(discover.build(
                args.dir, home_domains=home_domains, consume=args.consume,
                expect=_parse_expect(args.expect)))
        if args.action == "answer":
            return _ok(discover.answer(args.dir, question=args.question, text=args.text))
        if args.proposal is not None:
            return _ok(discover.check(args.dir, args.proposal))
        return _ok(discover.check_block(args.dir, args.block))
    if args.group == "feedback":
        body_text = (sys.stdin.read() if args.body_file == "-"
                    else Path(args.body_file).read_text(encoding="utf-8"))
        if args.action == "lint":
            return _ok(feedback.lint(root, body_text))
        return _ok(feedback.send(root, args.title, body_text))
    if args.group == "daily-note":
        if args.action == "write":
            payload = (json.load(sys.stdin) if args.note == "-"
                       else json.loads(Path(args.note).read_text(encoding="utf-8")))
            return _ok(dailynote.write(root, payload))
        return _ok(dailynote.read(root, args.date))
    if args.group == "migrate":
        if args.action == "status":
            return _ok(migrate.status(root))
        return _ok(migrate.run(root, vault.today_iso(args.today),
                               stamp=args.stamp))
    if args.group == "scratch":
        return _ok(scratch.sweep(args.dir))
    if args.group == "runlog":
        return _ok(runlog.append(root, args.routine, args.outcome))
    if args.group == "provenance":
        data = provenance.read(root)
        running = vault.plugin_version()
        if data is None:
            return _ok({"present": False, "provenance": None,
                       "plugin_drift": "unknown", "running_plugin_version": running})
        return _ok({"present": True, "provenance": data,
                   "plugin_drift": provenance.drift(data),
                   "running_plugin_version": running})
    if args.group == "template":
        if args.action == "status":
            return _ok(template.status(root))
        if args.action == "diff":
            return _ok({"relpath": args.file, "diff": template.diff(root, args.file)})
        return _ok(template.refresh(
            root, files=args.files, all_pending=args.all_pending,
            consent=args.consent, today=vault.today_iso(args.today),
            stamp=args.stamp))
    if args.group == "health":
        window = args.window if args.window is not None else health.DEFAULT_WINDOW_DAYS
        data = health.report(root, vault.today_iso(args.today), window=window)
        if args.write:
            data["written"] = health.write_report(root, data)
        return _ok(data)
    raise AssertionError(f"unhandled group {args.group!r}")


# Flags whose legitimate values can start with a dash (a negative UTC
# offset). argparse before Python 3.14 reads `--utc-offset -05:00` as a flag
# followed by a missing argument; merging the pair into `--utc-offset=-05:00`
# parses identically on every supported version — the Cowork VM runs 3.10.
_DASH_VALUE_FLAGS = frozenset({"--utc-offset"})
_DASH_VALUE_RE = re.compile(r"\A-\d")


def _merge_dash_values(argv: Sequence[str]) -> list:
    merged, skip = [], False
    for index, token in enumerate(argv):
        if skip:
            skip = False
            continue
        follower = argv[index + 1] if index + 1 < len(argv) else None
        if (token in _DASH_VALUE_FLAGS and follower is not None
                and _DASH_VALUE_RE.match(follower)):
            merged.append(f"{token}={follower}")
            skip = True
        else:
            merged.append(token)
    return merged


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(
        _merge_dash_values(sys.argv[1:] if argv is None else argv))
    if args.group == "sync" and args.action == "m365-triage" \
            and args.collide and (args.timezone is None) == (args.utc_offset is None):
        # Argparse-level, not a runtime DatesError buried inside the first
        # candidate's collide check: --collide with neither or both of
        # --timezone/--utc-offset is a call that can never do useful work.
        parser.error(
            "sync m365-triage --collide requires exactly one of --timezone "
            "or --utc-offset")
    try:
        return _dispatch(args)
    except vault.VaultError as exc:
        return _fail(str(exc), "Check the --vault path points at the vault root.")
    except config.ConfigError as exc:
        return _fail(str(exc),
                     "Fix 99-workflow-config/config.json (see the template "
                     "default) and retry.")
    except dates.DatesError as exc:
        return _fail(str(exc), "Fix the date or timezone argument and retry.")
    except project.ProjectError as exc:
        return _fail(str(exc), "Fix the named constraint and retry.")
    except projectstate.ProjectStateError as exc:
        return _fail(str(exc), "Fix the named state field and retry.")
    except entity.EntityError as exc:
        return _fail(str(exc), "Fix the named constraint and retry.")
    except decision.DecisionError as exc:
        return _fail(str(exc), "Fix the named constraint and retry.")
    except meeting.MeetingError as exc:
        return _fail(str(exc), "Fix the named payload field and retry.")
    except syncjob.SyncError as exc:
        return _fail(str(exc), "Fix the named id or argument and retry.")
    except seenevents.SeenEventsError as exc:
        return _fail(str(exc), "Fix the named listing or outcome entry and retry.")
    except lastsync.LastSyncError as exc:
        return _fail(str(exc), "Fix --adapter or --utc-to and retry.")
    except fetcherrors.FetchErrorsError as exc:
        return _fail(str(exc), "Fix the named id or reason and retry.")
    except plaud.PlaudError as exc:
        return _fail(str(exc), "Check the raw MCP JSON files named in the error.")
    except m365.M365Error as exc:
        return _fail(str(exc), "Check the raw M365 JSON files named in the error.")
    except discover.DiscoverError as exc:
        return _fail(str(exc), "Fix the named argument or payload and retry; "
                     "nothing from this call was shown to the owner.")
    except updatequeue.UpdateQueueError as exc:
        return _fail(str(exc), "Fix the named argument and retry.")
    except dailynote.DailyNoteError as exc:
        return _fail(str(exc), "Fix the named payload field or note state and retry.")
    except feedback.FeedbackError as exc:
        return _fail(str(exc), "Fix the named constraint; nothing was sent.")
    except scratch.ScratchError as exc:
        return _fail(str(exc), "Check --dir points at the session scratch "
                     "directory and retry.")
    except runlog.RunLogError as exc:
        return _fail(str(exc), "Fix --routine or --outcome and retry.")
    except health.HealthError as exc:
        return _fail(str(exc), "Fix --today or --window and retry.")
    except provenance.ProvenanceError as exc:
        return _fail(str(exc), "CLI-owned; restore from a snapshot or delete "
                     "it to start from an unknown baseline.")
    except template.TemplateError as exc:
        return _fail(str(exc), "Re-run `template status`; pass --consent "
                     "with --file / --all-pending for edited or missing "
                     "files.")
    except migrate.MigrateError as exc:
        # The per-file list rides the hint rather than a fourth envelope key:
        # `hint` is already "what to do", and these files are the whole of it.
        # Without this the consultant got a verify message and no idea which
        # notes to repair — the list apply built died with the report.
        hint = ("Restore from the named snapshot if needed; fix the cause; "
                "re-run.")
        if getattr(exc, "needs_human", None):
            hint += (" These files need a human first: "
                     + "; ".join(exc.needs_human))
        return _fail(str(exc), hint)
    except json.JSONDecodeError as exc:
        return _fail(f"payload is not valid JSON: {exc}",
                     "Pass a JSON object in a file, or - to read stdin.")
    except ValueError as exc:
        return _fail(str(exc), "Fix the argument named in the error and retry.")
    except OSError as exc:
        return _fail(f"filesystem error: {exc}",
                     "Check the vault is mounted and writable from this session.")
    except (KeyError, TypeError, AttributeError) as exc:
        # Backstop, not the primary guard: entity._validate_items rejects a
        # malformed payload with a useful message. This is here so no future
        # direct-index or attribute access can escape the envelope — a
        # traceback on stdout gives the calling model no `ok` to read.
        return _fail(f"malformed edits payload: {exc}",
                     "Check every entry has the fields its section requires.")


if __name__ == "__main__":
    sys.exit(main())
