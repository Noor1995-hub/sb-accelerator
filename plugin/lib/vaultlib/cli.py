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
import sys
from pathlib import Path
from typing import Optional, Sequence

if __package__ in (None, ""):
    # Executed as a file path rather than imported as a package, which is how
    # the skills invoke it.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vaultlib import dates, decision, entity, person, project, schema, syncjob, vault  # noqa: E402


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

    sync_skip = sync_sub.add_parser(
        "skip", help="never propose this recording id again")
    _add_vault_argument(sync_skip)
    sync_skip.add_argument("--id", dest="recording_id", required=True)

    sync_rec = sync_sub.add_parser(
        "reconcile-reviews",
        help="flip review_status needs-review -> confirmed where reviewed is ticked")
    _add_vault_argument(sync_rec)

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    # dates (and later stateless subcommands) take no --vault.
    root = vault.resolve(args.vault) if hasattr(args, "vault") else None
    if args.group == "dates":
        return _ok(dates.window(args.start, timezone=args.timezone,
                                utc_offset=args.utc_offset, hours=args.hours))
    if args.group == "identity":
        return _ok({"identity": vault.read_identity_block(root)})
    if args.group == "person":
        today = vault.today_iso(getattr(args, "today", None))
        return _ok(person.ensure(root, args.name, today))
    if args.group == "project":
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
        if args.action == "skip":
            return _ok(syncjob.skip(root, args.recording_id))
        if args.action == "reconcile-reviews":
            return _ok(syncjob.reconcile_reviews(root))
    raise AssertionError(f"unhandled group {args.group!r}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except vault.VaultError as exc:
        return _fail(str(exc), "Check the --vault path points at the vault root.")
    except dates.DatesError as exc:
        return _fail(str(exc), "Fix the date or timezone argument and retry.")
    except project.ProjectError as exc:
        return _fail(str(exc), "Fix the named constraint and retry.")
    except entity.EntityError as exc:
        return _fail(str(exc), "Fix the named constraint and retry.")
    except decision.DecisionError as exc:
        return _fail(str(exc), "Fix the named constraint and retry.")
    except syncjob.SyncError as exc:
        return _fail(str(exc), "Fix the named id or argument and retry.")
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
