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
from pathlib import Path
from typing import Optional, Sequence

if __package__ in (None, ""):
    # Executed as a file path rather than imported as a package, which is how
    # the skills invoke it.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultlib import config, dailynote, dates, decision, entity, feedback, health, m365, meeting, migrate, person, plaud, project, schema, syncjob, updatequeue, vault  # noqa: E402


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
    value_group.add_argument("--value", help="the new value (true/false for .enabled)")
    value_group.add_argument("--null", action="store_true",
                             help="unset the field (nullable fields only)")

    dates_group = top.add_parser("dates", help="date and timezone arithmetic")
    dates_sub = dates_group.add_subparsers(dest="action", required=True)
    dates_window = dates_sub.add_parser(
        "window", help="UTC query window around a local timestamp")
    dates_window.add_argument("--start", required=True,
                              help="local ISO date or datetime")
    dates_window.add_argument("--timezone", help="IANA timezone name")
    dates_window.add_argument("--utc-offset", dest="utc_offset",
                              help="explicit offset like -05:00")
    dates_window.add_argument("--hours", type=float, default=2.0,
                              help="half-width of the window (default 2)")

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

    people = top.add_parser("person", help="person notes")
    people_sub = people.add_subparsers(dest="action", required=True)
    person_ensure = people_sub.add_parser(
        "ensure", help="create a person note if none exists")
    _add_vault_argument(person_ensure)
    person_ensure.add_argument("--name", required=True, help="display name")
    person_ensure.add_argument("--today", help="ISO date; defaults to today")

    projects = top.add_parser("project", help="project folders")
    projects_sub = projects.add_subparsers(dest="action", required=True)
    scaffold = projects_sub.add_parser(
        "scaffold", help="create a project index and decisions folder")
    _add_vault_argument(scaffold)
    scaffold.add_argument("--name", required=True, help="human-readable project name")
    scaffold.add_argument("--type", dest="project_type", required=True,
                          choices=schema.enum_values("project", "project-type"))
    scaffold.add_argument("--entity", required=True, help="entity slug (join key)")
    scaffold.add_argument("--owner", required=True, help="owner person slug")
    scaffold.add_argument("--parent", help="parent project slug (initiatives only)")
    scaffold.add_argument("--today", help="ISO date; defaults to today")
    scaffold.add_argument("--stage", help="one line for the Now callout")
    scaffold.add_argument("--contacts", help="one line for the Context callout")
    scaffold.add_argument("--source", help="one line for the Context callout")

    proj_touch = projects_sub.add_parser(
        "touch", help="bump last-updated (and optionally the milestone pair)")
    _add_vault_argument(proj_touch)
    proj_touch.add_argument("--slug", required=True)
    proj_touch.add_argument("--date", help="ISO date; defaults to today")
    proj_touch.add_argument("--next-milestone", dest="next_milestone",
                            help="one line; requires --next-milestone-date")
    proj_touch.add_argument("--next-milestone-date", dest="next_milestone_date",
                            help="ISO date; requires --next-milestone")

    entities = top.add_parser("entity", help="entity dossiers")
    entities_sub = entities.add_subparsers(dest="action", required=True)

    ent_ensure = entities_sub.add_parser(
        "ensure", help="create a dossier if none exists")
    _add_vault_argument(ent_ensure)
    ent_ensure.add_argument("--slug", required=True)
    ent_ensure.add_argument("--name", required=True, help="display name")
    ent_ensure.add_argument("--type", dest="entity_type",
                            choices=schema.enum_values("entity", "entity-type"))
    ent_ensure.add_argument("--status", default="prospect",
                            choices=schema.enum_values("entity", "status"))
    ent_ensure.add_argument("--owner", help="owner person slug")
    ent_ensure.add_argument("--today", help="ISO date; defaults to today")

    ent_read = entities_sub.add_parser(
        "read", help="print the dossier's frontmatter and sections as JSON")
    _add_vault_argument(ent_read)
    ent_read.add_argument("--slug", required=True)

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
                              help="exec-local start, YYYY-MM-DDTHH:MM")
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
    sync_queue.add_argument("--executive", required=True,
                            help="the executive's person slug (excluded from key-people)")
    sync_queue.add_argument("--today", help="ISO date; defaults to today")

    meetings = top.add_parser("meeting", help="meeting notes")
    meetings_sub = meetings.add_subparsers(dest="action", required=True)
    meeting_write = meetings_sub.add_parser(
        "write", help="write one meeting note from a JSON payload")
    _add_vault_argument(meeting_write)
    meeting_write.add_argument("--note", required=True,
                               help="path to a JSON file, or - to read stdin")

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
        "ids", help="derive m365: recording ids from full calendar event reads")
    m365_ids.add_argument("--events", required=True,
                          help="path to a JSON array of event objects, or - for stdin")
    m365_re = m365_sub.add_parser(
        "reassemble",
        help="render an event read + transcript read into one capture-bundle blob")
    m365_re.add_argument("--event", required=True)
    m365_re.add_argument("--transcript", required=True)
    m365_re.add_argument("--out", required=True,
                         help="scratch directory for the blob (never the vault)")
    m365_re.add_argument("--timezone", help="IANA timezone name")
    m365_re.add_argument("--utc-offset", dest="utc_offset")

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


def _dispatch(args: argparse.Namespace) -> int:
    # dates (and later stateless subcommands) take no --vault.
    root = vault.resolve(args.vault) if hasattr(args, "vault") else None
    if args.group == "dates":
        if args.action == "window":
            return _ok(dates.window(args.start, timezone=args.timezone,
                                    utc_offset=args.utc_offset, hours=args.hours))
        return _ok(dates.plan(root, args.today, timezone=args.timezone,
                              utc_offset=args.utc_offset,
                              catchup_threshold=args.catchup_threshold))
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
            else:
                value = args.value
            return _ok(config.write(root, args.field, value))
        payload = (json.load(sys.stdin) if args.identity == "-"
                   else json.loads(Path(args.identity).read_text(encoding="utf-8")))
        return _ok(config.verify_account(root, args.adapter, payload))
    if args.group == "person":
        today = vault.today_iso(getattr(args, "today", None))
        return _ok(person.ensure(root, args.name, today))
    if args.group == "project":
        if args.action == "touch":
            return _ok(project.touch(
                root, slug=args.slug, date_iso=vault.today_iso(args.date),
                next_milestone=args.next_milestone,
                next_milestone_date=args.next_milestone_date,
            ))
        today = vault.today_iso(getattr(args, "today", None))
        return _ok(project.scaffold(
            root, name=args.name, project_type=args.project_type,
            entity=args.entity, owner=args.owner, today=today,
            parent=args.parent, stage=args.stage,
            contacts=args.contacts, source=args.source,
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
            return _ok(syncjob.reconcile_reviews(root))
        if args.action == "archive":
            return _ok(syncjob.archive(root, args.path,
                                       vault.today_iso(args.today)))
        if args.action == "park":
            return _ok(syncjob.park(root, args.path, args.recording_id,
                                    args.reason, vault.today_iso(args.today)))
        if args.action == "update-queue":
            return _ok(updatequeue.run(root, vault.today_iso(args.today),
                                       args.executive))
    if args.group == "meeting":
        payload = (json.load(sys.stdin) if args.note == "-"
                   else json.loads(Path(args.note).read_text(encoding="utf-8")))
        return _ok(meeting.write(root, payload))
    if args.group == "plaud":
        return _ok(plaud.reassemble(
            args.meta, args.transcript, args.note, args.out,
            timezone=args.timezone, utc_offset=args.utc_offset))
    if args.group == "m365":
        if args.action == "ids":
            payload = (json.load(sys.stdin) if args.events == "-"
                       else json.loads(Path(args.events).read_text(encoding="utf-8")))
            return _ok(m365.ids(payload))
        return _ok(m365.reassemble(
            args.event, args.transcript, args.out,
            timezone=args.timezone, utc_offset=args.utc_offset))
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
    args = build_parser().parse_args(
        _merge_dash_values(sys.argv[1:] if argv is None else argv))
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
    except entity.EntityError as exc:
        return _fail(str(exc), "Fix the named constraint and retry.")
    except decision.DecisionError as exc:
        return _fail(str(exc), "Fix the named constraint and retry.")
    except meeting.MeetingError as exc:
        return _fail(str(exc), "Fix the named payload field and retry.")
    except syncjob.SyncError as exc:
        return _fail(str(exc), "Fix the named id or argument and retry.")
    except plaud.PlaudError as exc:
        return _fail(str(exc), "Check the raw MCP JSON files named in the error.")
    except m365.M365Error as exc:
        return _fail(str(exc), "Check the raw M365 JSON files named in the error.")
    except updatequeue.UpdateQueueError as exc:
        return _fail(str(exc), "Fix the named argument and retry.")
    except dailynote.DailyNoteError as exc:
        return _fail(str(exc), "Fix the named payload field or note state and retry.")
    except feedback.FeedbackError as exc:
        return _fail(str(exc), "Fix the named constraint; nothing was sent.")
    except health.HealthError as exc:
        return _fail(str(exc), "Fix --today or --window and retry.")
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
