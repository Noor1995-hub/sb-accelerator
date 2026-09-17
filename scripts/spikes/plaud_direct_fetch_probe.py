#!/usr/bin/env python3
"""Read-only probe for the Plaud direct-fetch spike (lever 6).

This is a **read-only** diagnostic for the "CLI-side Plaud transcript
fetch" spike (docs/superpowers/specs/2026-09-17-plaud-direct-fetch-spike.md).
It never calls the OAuth refresh endpoint, never writes anything to disk,
and never prints or logs token bytes — not even a prefix. It only issues
GET/HEAD requests and reports shapes, status codes, and sizes.

What it checks:
  - the local token file's presence, which expected keys it has, and
    whether `expires_at` has passed — never the token values themselves;
  - per-host HTTPS egress (`HEAD /health`);
  - `GET .../open/third-party/users/current` — status and an `id`-presence
    boolean only, never the response body;
  - `GET .../open/third-party/files/{file_id}` — status, byte size, and
    top-level JSON keys only, never the response body;
  - optionally (`--compare`), whether the utterance sequence the MCP
    itself already produced (a set of scratch page files, each with an
    offset and a `segments` list) matches the utterance sequence found in
    the direct API response's `source_list[]` "transaction" entry. If that
    entry's shape doesn't match what we expect, this reports the keys it
    saw instead of raising.

platform.plaud.ai sits behind Cloudflare, which bans the default
Python-urllib User-Agent outright (error 1010, "browser signature
banned") on every route — found live, 2026-09-17, with an otherwise
perfectly valid token. This probe sends a fixed non-Python UA
(`PROBE_USER_AGENT`) on every request and reports which one it used.

It never follows an HTTP redirect. The default urllib opener's
`HTTPRedirectHandler` copies almost every request header — including a
live `Authorization: Bearer …` — into the follow-up request with no
same-host check, so a 3xx from anywhere on the network path would
silently forward the token to a new host. This probe installs an opener
whose redirect handler refuses to redirect; a 3xx comes back as a status
plus (at most) the redirect target's *host name* — never its full URL,
which could carry a token in a query string.

Output is one JSON object on stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TOKEN_FILE = str(Path.home() / ".plaud" / "tokens-mcp.json")
DEFAULT_HOSTS = "platform.plaud.ai,mcp.plaud.ai"

USERS_CURRENT_URL = "https://platform.plaud.ai/developer/api/open/third-party/users/current"
FILES_URL_TEMPLATE = "https://platform.plaud.ai/developer/api/open/third-party/files/{file_id}"

EXPECTED_TOKEN_KEYS = ("access_token", "refresh_token", "expires_at")

# platform.plaud.ai sits behind Cloudflare, which returns 403 "error 1010 —
# browser signature banned" for the default Python-urllib User-Agent, on
# every route including /health and users/current — with the token
# otherwise perfectly valid (found live, 2026-09-17). Any UA not starting
# with "Python-urllib" (the Node MCP itself sends `undici`) clears it, so
# the probe sends one fixed, non-Python UA on every request and reports it.
PROBE_USER_AGENT = "sb-accelerator-spike/1 (undici-compatible)"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow any redirect.

    Python's default opener's `HTTPRedirectHandler.redirect_request`
    copies nearly every request header — including a live
    `Authorization: Bearer …` — into the follow-up request, with no
    same-host check. `check_users_current` and `fetch_file` both attach
    that header, so a redirect (from Plaud's edge or anything on the
    network path) would silently forward the token to whatever host the
    redirect names (PR #215 review finding). Returning None here tells
    urllib not to redirect — urllib's own error dispatch then falls
    through to `HTTPDefaultErrorHandler`, which *raises* `HTTPError` for
    the 3xx rather than returning it as a response (see `_http`'s
    `except HTTPError` handling). Either way, no second, credential-
    bearing request is ever issued."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# One opener, reused for every request in this module — built once so
# tests can monkeypatch its `.open` in place of the real network call.
_OPENER = urllib.request.build_opener(_NoRedirectHandler)


# ---------------------------------------------------------------------------
# token file — presence/shape only, never values
# ---------------------------------------------------------------------------


def _normalize_expires_at(expires_at):
    """Return (iso_string, expired_bool). Falls back to (str(value), None)
    for a value that isn't a recognizable epoch number or ISO string.

    `~/.plaud/tokens-mcp.json` stores `expires_at` as epoch
    **milliseconds** (a 13-digit int, e.g. 1789719041966) — observed on a
    live token file during this spike, not documented anywhere. Epoch
    seconds for realistic dates stay under 1e11 until the year 5138, so
    anything larger is treated as milliseconds."""
    try:
        if isinstance(expires_at, (int, float)):
            value = expires_at / 1000 if expires_at > 1e11 else expires_at
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            text = str(expires_at).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return str(expires_at), None
    now = datetime.now(tz=timezone.utc)
    return dt.isoformat(), dt <= now


def inspect_token_file(path) -> dict:
    """Presence + key names + expiry only. Never returns token values."""
    path = Path(path)
    result = {
        "path": str(path),
        "present": False,
        "keys_present": [],
        "expires_at": None,
        "expired": None,
    }
    if not path.exists():
        return result
    result["present"] = True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        result["error"] = "unreadable-or-invalid-json"
        return result
    if not isinstance(data, dict):
        result["error"] = "not-a-json-object"
        return result
    result["keys_present"] = sorted(k for k in EXPECTED_TOKEN_KEYS if k in data)
    expires_at = data.get("expires_at")
    if expires_at is not None:
        iso, expired = _normalize_expires_at(expires_at)
        result["expires_at"] = iso
        result["expired"] = expired
    return result


def _read_access_token(path):
    """Read the access token value for use in a request header only —
    never returned from here into anything that gets printed."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data.get("access_token")


# ---------------------------------------------------------------------------
# HTTP — GET/HEAD only, errors reported as status/error-class, never raised
# ---------------------------------------------------------------------------


def _redirect_target_host(resp_or_exc):
    """Extract just the hostname from a 3xx's Location header — never the
    full URL, which can carry credentials or a token in its query string
    (the reason this exists at all: PR #215). Takes either a response
    object or the `HTTPError` urllib actually raises for an unfollowed
    redirect (`urllib.error.HTTPError.headers` holds the same headers a
    response object would)."""
    headers = getattr(resp_or_exc, "headers", None)
    location = headers.get("Location") if headers else None
    if not location:
        return None
    return urllib.parse.urlparse(location).hostname


def _http(url, headers=None, method="GET", timeout=10):
    merged_headers = {"User-Agent": PROBE_USER_AGENT}
    merged_headers.update(headers or {})
    req = urllib.request.Request(url, headers=merged_headers, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return {"status": resp.getcode(), "body": resp.read()}
    except urllib.error.HTTPError as exc:
        # _NoRedirectHandler.redirect_request returning None does not
        # make urlopen return the 3xx response — urllib's own error
        # dispatch falls through to HTTPDefaultErrorHandler, which
        # *raises* HTTPError for it (verified against
        # urllib.request.OpenerDirector.error/_call_chain). So a real
        # redirect always lands here, never in the block above; report
        # it without ever acting on Location ourselves.
        if 300 <= exc.code < 400:
            return {
                "status": exc.code,
                "redirected": True,
                "redirected_to_host": _redirect_target_host(exc),
            }
        return {"status": exc.code}
    except urllib.error.URLError as exc:
        reason = exc.reason
        return {"error": type(reason).__name__ if reason is not None else type(exc).__name__}
    except OSError as exc:
        return {"error": type(exc).__name__}


def check_egress(host, dry_run) -> dict:
    """`/health` doesn't exist on platform.plaud.ai for a non-Python UA —
    every non-Python request gets a 404, which still means the host was
    reached. Only a connection error or a 403 (Cloudflare block) means the
    egress path itself is blocked; report `reachable` accordingly
    alongside whatever status/error came back."""
    url = f"https://{host}/health"
    if dry_run:
        return {"host": host, "url": url, "dry_run": True}
    result = _http(url, method="HEAD")
    if "error" in result:
        return {"host": host, "url": url, "error": result["error"], "reachable": False}
    if result.get("redirected"):
        return {
            "host": host,
            "url": url,
            "status": result["status"],
            "reachable": True,
            "redirected": True,
            "redirected_to_host": result.get("redirected_to_host"),
        }
    status = result["status"]
    return {"host": host, "url": url, "status": status, "reachable": status != 403}


def check_users_current(token, dry_run) -> dict:
    if dry_run:
        return {"url": USERS_CURRENT_URL, "dry_run": True}
    if not token:
        return {"url": USERS_CURRENT_URL, "error": "no-access-token"}
    result = _http(USERS_CURRENT_URL, headers={"Authorization": f"Bearer {token}"})
    if "error" in result:
        return {"url": USERS_CURRENT_URL, "error": result["error"]}
    if result.get("redirected"):
        return {
            "url": USERS_CURRENT_URL,
            "status": result["status"],
            "redirected": True,
            "redirected_to_host": result.get("redirected_to_host"),
        }
    if "status" in result and result["status"] != 200:
        return {"url": USERS_CURRENT_URL, "status": result["status"]}
    has_id = False
    try:
        parsed = json.loads(result["body"])
        has_id = isinstance(parsed, dict) and "id" in parsed
    except json.JSONDecodeError:
        pass
    return {"url": USERS_CURRENT_URL, "status": result["status"], "has_id": has_id}


def fetch_file(token, file_id, dry_run):
    """Returns (summary_dict_for_report, parsed_body_or_None). The parsed
    body is for --compare only and is never included in the summary."""
    if not file_id:
        return {"skipped": "no --file-id given"}, None
    url = FILES_URL_TEMPLATE.format(file_id=file_id)
    if dry_run:
        return {"url": url, "dry_run": True}, None
    if not token:
        return {"url": url, "error": "no-access-token"}, None
    result = _http(url, headers={"Authorization": f"Bearer {token}"})
    if "error" in result:
        return {"url": url, "error": result["error"]}, None
    if result.get("redirected"):
        return {
            "url": url,
            "status": result["status"],
            "redirected": True,
            "redirected_to_host": result.get("redirected_to_host"),
        }, None
    if result["status"] != 200:
        return {"url": url, "status": result["status"]}, None
    body = result["body"]
    summary = {"url": url, "status": result["status"], "size_bytes": len(body)}
    parsed = None
    try:
        parsed = json.loads(body)
        summary["top_level_keys"] = sorted(parsed.keys()) if isinstance(parsed, dict) else []
    except json.JSONDecodeError:
        summary["top_level_keys"] = []
    return summary, parsed


# ---------------------------------------------------------------------------
# --compare: MCP scratch pages vs. the API's source_list transaction entry
# ---------------------------------------------------------------------------


def load_compare_pages(page_paths) -> list:
    """Load MCP scratch page files and concatenate their `segments` lists
    in offset order into a flat utterance sequence.

    Real MCP scratch-page shape (plugin/skills/sync-recordings/references/
    worker-contract.md): each page is a JSON object with `offset`,
    `returned`, `total`, `next_cursor`, and a `segments` list of
    `{speaker, content, end_time}` dicts."""
    pages = []
    for page_path in page_paths:
        data = json.loads(Path(page_path).read_text(encoding="utf-8"))
        pages.append(data)
    pages.sort(key=lambda page: page.get("offset", 0) if isinstance(page, dict) else 0)
    utterances = []
    for page in pages:
        segments = page.get("segments", []) if isinstance(page, dict) else []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            utterances.append(
                {
                    "speaker": seg.get("speaker"),
                    "content": seg.get("content"),
                    "end_time": seg.get("end_time"),
                }
            )
    return utterances


def extract_api_utterances(parsed_file_body):
    """Find source_list[] entry with data_type == "transaction", parse its
    data_content JSON string, and pull out its utterance list.

    Real shape (found live, 2026-09-17, against recording
    of_de01a3bd6a5aed9b81d31af60758c080): `data_content` is a JSON string
    of a bare list of utterance dicts (not wrapped in an object), each
    with `content`, `end_time`, `original_speaker`, `speaker`,
    `start_time`. This still handles a dict-wrapped `segments`/
    `utterances` list too, in case a future response nests it.

    Never raises: on any shape mismatch, returns (None, observed) where
    `observed` names the keys actually seen, so the caller can report
    rather than fail."""
    if not isinstance(parsed_file_body, dict):
        return None, {"top_level": "not-a-dict"}
    source_list = parsed_file_body.get("source_list")
    if not isinstance(source_list, list):
        return None, {"top_level_keys": sorted(parsed_file_body.keys())}

    transaction_entries = [
        e for e in source_list if isinstance(e, dict) and e.get("data_type") == "transaction"
    ]
    if not transaction_entries:
        seen_types = sorted(
            {e.get("data_type") for e in source_list if isinstance(e, dict) and "data_type" in e}
        )
        return None, {"source_list_data_types": seen_types}

    entry = transaction_entries[0]
    data_content = entry.get("data_content")
    if not isinstance(data_content, str):
        return None, {"entry_keys": sorted(entry.keys())}
    try:
        inner = json.loads(data_content)
    except json.JSONDecodeError:
        return None, {"data_content": "not-json"}

    segments = None
    if isinstance(inner, dict):
        segments = inner.get("segments")
        if segments is None:
            segments = inner.get("utterances")
    elif isinstance(inner, list):
        segments = inner

    if not isinstance(segments, list):
        if isinstance(inner, dict):
            return None, {"inner_keys": sorted(inner.keys())}
        return None, {"inner_type": type(inner).__name__}

    utterances = [
        {
            "speaker": seg.get("speaker"),
            "content": seg.get("content"),
            "start_time": seg.get("start_time"),
            "end_time": seg.get("end_time"),
            "original_speaker": seg.get("original_speaker"),
        }
        for seg in segments
        if isinstance(seg, dict)
    ]
    return utterances, None


def compare_sequences(mcp_utterances, api_utterances) -> dict:
    """Compare on (speaker, content) only — the MCP page's `end_time` and
    the API's `start_time`/`end_time`/`original_speaker` aren't expected to
    line up field-for-field (different pagination, different speaker
    labeling), so pinning the match to the two fields both shapes share
    avoids false mismatches."""

    def key(u):
        return (u.get("speaker"), u.get("content"))

    mcp_keys = [key(u) for u in mcp_utterances]
    api_keys = [key(u) for u in api_utterances]
    return {
        "match": mcp_keys == api_keys,
        "mcp_count": len(mcp_keys),
        "api_count": len(api_keys),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only probe for the Plaud direct-fetch spike (lever 6). "
        "Never refreshes the token, never writes, never prints token bytes."
    )
    parser.add_argument(
        "--token-file",
        default=DEFAULT_TOKEN_FILE,
        help=f"path to the MCP's token file (default: {DEFAULT_TOKEN_FILE})",
    )
    parser.add_argument("--file-id", help="Plaud file id to probe /files/{file_id} with")
    parser.add_argument(
        "--compare",
        nargs="+",
        metavar="PAGE",
        default=None,
        help="MCP scratch page JSON files to compare against the direct API response",
    )
    parser.add_argument(
        "--hosts",
        default=DEFAULT_HOSTS,
        help=f"comma-separated hosts to egress-check (default: {DEFAULT_HOSTS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="describe what would be checked without making any network call",
    )
    return parser.parse_args(argv)


def build_summary(args) -> dict:
    token_file = Path(args.token_file).expanduser()
    token_info = inspect_token_file(token_file)

    access_token = None
    if not args.dry_run and token_info["present"]:
        access_token = _read_access_token(token_file)

    hosts = [h.strip() for h in args.hosts.split(",") if h.strip()]
    egress = [check_egress(host, args.dry_run) for host in hosts]
    users_current = check_users_current(access_token, args.dry_run)
    file_summary, file_body = fetch_file(access_token, args.file_id, args.dry_run)

    summary = {
        "dry_run": args.dry_run,
        "user_agent": PROBE_USER_AGENT,
        "token_file": token_info,
        "egress": egress,
        "users_current": users_current,
        "file": file_summary,
    }

    if args.compare:
        mcp_utterances = load_compare_pages(args.compare)
        api_utterances, observed = extract_api_utterances(file_body)
        if api_utterances is None:
            summary["compare"] = {"error": "unexpected-response-shape", "observed": observed}
        else:
            summary["compare"] = compare_sequences(mcp_utterances, api_utterances)

    return summary


def main(argv=None) -> int:
    args = parse_args(argv)
    summary = build_summary(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
