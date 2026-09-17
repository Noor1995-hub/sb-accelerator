#!/usr/bin/env python3
"""Cost report for a Claude Code session export.

Sums `message.usage` — taking the **max per `message.id`**, since the
transcript repeats a message once per content block and each repeat
carries its own partial usage snapshot — over the main session and every
subagent transcript, prices each message at list rate for the model
family named in `message.model` (substring match: sonnet / haiku / opus;
an unrecognized model warns and is priced as sonnet), and prints a
per-agent table plus by-`agentType` totals.

Session export layout, as written by `mcp__ccd_session_mgmt__export_transcript`:

    transcript.jsonl                              — main session
    <session-uuid>/subagents/agent-<id>.jsonl      — one subagent's transcript
    <session-uuid>/subagents/agent-<id>.meta.json  — that subagent's
                                                      agentType/description
    metadata.json                                  — session metadata (unused here)

`input` (the export path) accepts either a session-export `.zip` (as
downloaded) or an already-extracted directory; either way the tool locates
`transcript.jsonl` itself rather than assuming a fixed nesting depth.

Why this exists rather than trusting the app's own session-cost card: the
card takes the *first* usage record it sees per message id, not the max —
see docs/cost-measurement.md.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

DEFAULT_PRICING = {
    "sonnet": {"in": 3.0, "out": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "haiku": {"in": 1.0, "out": 5.0, "cache_read": 0.10, "cache_write": 1.25},
    "opus": {"in": 15.0, "out": 75.0, "cache_read": 1.50, "cache_write": 18.75},
}

USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)

# Totals/rows carry these keys plus "cost".
TOTAL_KEYS = USAGE_KEYS + ("requests",)


def load_pricing(override_path) -> dict:
    """Default list prices, shallow-merged with an optional overrides file.

    The overrides file is JSON: {"<bucket>": {"in"|"out"|"cache_read"|
    "cache_write": <price per MTok>}}. A bucket/key not mentioned keeps its
    default; a new bucket not in DEFAULT_PRICING is accepted as-is (so a
    future model family can be priced without a code change).
    """
    pricing = {bucket: dict(prices) for bucket, prices in DEFAULT_PRICING.items()}
    if override_path is None:
        return pricing
    overrides = json.loads(Path(override_path).read_text(encoding="utf-8"))
    for bucket, prices in overrides.items():
        pricing.setdefault(bucket, {}).update(prices)
    return pricing


def classify_model(model, warnings: list) -> str:
    """sonnet/haiku/opus by substring of `message.model`; unknown -> warn,
    price as sonnet."""
    if model:
        lowered = model.lower()
        for bucket in ("sonnet", "haiku", "opus"):
            if bucket in lowered:
                return bucket
    warnings.append(f"unknown model {model!r}; pricing as sonnet")
    return "sonnet"


def read_jsonl(path: Path) -> list:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _empty_usage_totals() -> dict:
    return {key: 0 for key in USAGE_KEYS}


def aggregate(records: list, pricing: dict, warnings: list) -> dict:
    """Max usage per message.id (independently per token-count key), each
    message id priced by its own model. Returns totals across all message
    ids in `records` plus the request count and summed cost."""
    per_id: dict = {}
    model_by_id: dict = {}
    for rec in records:
        message = rec.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        mid = message.get("id")
        if not usage or not mid:
            continue
        current = per_id.setdefault(mid, _empty_usage_totals())
        for key in USAGE_KEYS:
            current[key] = max(current[key], usage.get(key, 0) or 0)
        if mid not in model_by_id and message.get("model"):
            model_by_id[mid] = message.get("model")

    totals = _empty_usage_totals()
    cost = 0.0
    for mid, usage in per_id.items():
        bucket = classify_model(model_by_id.get(mid), warnings)
        price = pricing[bucket]
        cost += (
            usage["input_tokens"] * price["in"]
            + usage["output_tokens"] * price["out"]
            + usage["cache_read_input_tokens"] * price["cache_read"]
            + usage["cache_creation_input_tokens"] * price["cache_write"]
        ) / 1_000_000
        for key in USAGE_KEYS:
            totals[key] += usage[key]

    return {"requests": len(per_id), **totals, "cost": cost}


def _is_safe_zip_member(name: str, dest_dir: Path) -> bool:
    """Zip-slip guard: reject a member whose normalised path is absolute
    or would resolve outside `dest_dir`. `zipfile.extractall` does not
    sanitize traversal names (`../evil.txt`) on its own."""
    if not name or os.path.isabs(name):
        return False
    dest_dir = dest_dir.resolve()
    resolved = (dest_dir / name).resolve()
    try:
        resolved.relative_to(dest_dir)
    except ValueError:
        return False
    return True


def _extract_zip_safely(zip_path: Path, dest_dir: Path) -> None:
    """Extract only members that stay inside `dest_dir`; skip (with a
    stderr warning) anything else instead of raising, so one poisoned
    member doesn't block reading the rest of a legitimate export."""
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if not _is_safe_zip_member(info.filename, dest_dir):
                print(
                    f"warning: skipped unsafe zip member {info.filename!r} "
                    "(escapes the extraction directory)",
                    file=sys.stderr,
                )
                continue
            zf.extract(info, dest_dir)


@contextlib.contextmanager
def export_root(input_path):
    """Yield the directory that directly contains transcript.jsonl.

    Accepts an already-extracted export directory (searched for
    transcript.jsonl at top level, then recursively as a fallback) or a
    .zip file (extracted to a temporary directory for the duration of the
    `with` block).
    """
    input_path = Path(input_path)
    if input_path.is_dir():
        if (input_path / "transcript.jsonl").exists():
            yield input_path
            return
        candidates = list(input_path.rglob("transcript.jsonl"))
        if not candidates:
            raise FileNotFoundError(f"no transcript.jsonl found under {input_path}")
        yield candidates[0].parent
        return
    if input_path.suffix == ".zip":
        with tempfile.TemporaryDirectory(prefix="cost_report_") as tmp:
            tmp_path = Path(tmp)
            _extract_zip_safely(input_path, tmp_path)
            candidates = list(tmp_path.rglob("transcript.jsonl"))
            if not candidates:
                raise FileNotFoundError(f"no transcript.jsonl found in {input_path}")
            yield candidates[0].parent
        return
    raise ValueError(f"expected a directory or a .zip file, got {input_path}")


def build_report(root: Path, pricing: dict) -> dict:
    root = Path(root)
    warnings: list = []
    rows = []

    main_path = root / "transcript.jsonl"
    if not main_path.exists():
        raise FileNotFoundError(f"{main_path} not found")
    main_usage = aggregate(read_jsonl(main_path), pricing, warnings)
    rows.append({"agent_type": "main", "description": "", **main_usage})

    for jsonl_path in sorted(root.glob("*/subagents/agent-*.jsonl")):
        meta_path = jsonl_path.with_name(jsonl_path.name.replace(".jsonl", ".meta.json"))
        agent_type = "unknown"
        description = ""
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            agent_type = meta.get("agentType", "unknown")
            description = meta.get("description", "")
        else:
            warnings.append(f"no meta.json for {jsonl_path.name}; agentType unknown")
        usage = aggregate(read_jsonl(jsonl_path), pricing, warnings)
        rows.append({"agent_type": agent_type, "description": description, **usage})

    totals_by_type: dict = {}
    for row in rows:
        bucket = totals_by_type.setdefault(
            row["agent_type"], {**_empty_usage_totals(), "requests": 0, "cost": 0.0}
        )
        for key in TOTAL_KEYS:
            bucket[key] += row[key]
        bucket["cost"] += row["cost"]

    grand_total = {key: sum(row[key] for row in rows) for key in TOTAL_KEYS}
    grand_total["cost"] = sum(row["cost"] for row in rows)

    return {
        "rows": rows,
        "totals_by_type": totals_by_type,
        "grand_total": grand_total,
        "warnings": warnings,
    }


def format_table(report: dict) -> str:
    header = (
        f"{'agentType':<30} {'description':<30} {'reqs':>5} {'out':>9} "
        f"{'cache_read':>11} {'cache_write':>12} {'$ list':>9}"
    )
    lines = [header, "-" * len(header)]
    for row in report["rows"]:
        lines.append(
            f"{row['agent_type']:<30.30} {row['description']:<30.30} {row['requests']:>5d} "
            f"{row['output_tokens']:>9d} {row['cache_read_input_tokens']:>11d} "
            f"{row['cache_creation_input_tokens']:>12d} {row['cost']:>9.4f}"
        )
    lines.append("")
    lines.append("by agentType:")
    for agent_type, totals in report["totals_by_type"].items():
        lines.append(
            f"  {agent_type:<30} reqs={totals['requests']:<4d} "
            f"out={totals['output_tokens']:<8d} "
            f"cache_read={totals['cache_read_input_tokens']:<8d} "
            f"cache_write={totals['cache_creation_input_tokens']:<8d} "
            f"$ {totals['cost']:.4f}"
        )
    gt = report["grand_total"]
    lines.append(
        f"GRAND TOTAL: reqs={gt['requests']} out={gt['output_tokens']} "
        f"cache_read={gt['cache_read_input_tokens']} "
        f"cache_write={gt['cache_creation_input_tokens']} $ {gt['cost']:.4f}"
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Cost report for a Claude Code session export (list-price sum, max usage per message.id)."
    )
    parser.add_argument(
        "input",
        help="session export .zip, or an already-extracted export directory",
    )
    parser.add_argument(
        "--pricing",
        help='JSON file overriding default per-MTok list prices, e.g. {"sonnet": {"out": 14}}',
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="also print a machine-readable JSON report after the table",
    )
    args = parser.parse_args(argv)

    pricing = load_pricing(args.pricing)
    with export_root(args.input) as root:
        report = build_report(root, pricing)

    print(format_table(report))
    for warning in report["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)
    if args.json:
        print()
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
