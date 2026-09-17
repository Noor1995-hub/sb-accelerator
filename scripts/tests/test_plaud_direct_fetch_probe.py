"""plaud_direct_fetch_probe.py: read-only spike probe for lever 6 (CLI-side
Plaud transcript fetch). All network access is either monkeypatched or
(for the redirect test, which must exercise urllib's real error-dispatch
chain) confined to two throwaway localhost servers — the probe must never
touch the real network in tests, must never call the refresh endpoint,
must never write anything, and must never surface token bytes (not even
a prefix) in whatever it reports.
"""
import contextlib
import http.server
import json
import sys
import threading
import time
import urllib.error
from pathlib import Path

import pytest

SPIKES_DIR = Path(__file__).resolve().parents[2] / "scripts" / "spikes"
if str(SPIKES_DIR) not in sys.path:
    sys.path.insert(0, str(SPIKES_DIR))

import plaud_direct_fetch_probe as probe  # noqa: E402


# ---------------------------------------------------------------------------
# token file inspection — never leaks token bytes
# ---------------------------------------------------------------------------


def test_missing_token_file_reports_not_present(tmp_path):
    info = probe.inspect_token_file(tmp_path / "nope.json")
    assert info["present"] is False
    assert info["keys_present"] == []
    assert info["expires_at"] is None


def test_token_file_reports_keys_present_and_expiry_without_leaking_values(tmp_path):
    token_path = tmp_path / "tokens-mcp.json"
    past = time.time() - 3600
    token_path.write_text(
        json.dumps(
            {
                "access_token": "super-secret-access-value",
                "refresh_token": "super-secret-refresh-value",
                "expires_at": past,
            }
        ),
        encoding="utf-8",
    )
    info = probe.inspect_token_file(token_path)
    assert info["present"] is True
    assert info["keys_present"] == ["access_token", "expires_at", "refresh_token"]
    assert info["expired"] is True
    assert info["expires_at"] is not None

    # Never leak the secret values, in any form, anywhere in the result.
    dumped = json.dumps(info)
    assert "super-secret-access-value" not in dumped
    assert "super-secret-refresh-value" not in dumped
    assert "access_token" not in info  # only keys_present names it, not the value
    assert "refresh_token" not in info


def test_token_file_not_expired_when_expires_at_in_future(tmp_path):
    token_path = tmp_path / "tokens-mcp.json"
    future = time.time() + 3600
    token_path.write_text(
        json.dumps({"access_token": "x", "refresh_token": "y", "expires_at": future}),
        encoding="utf-8",
    )
    info = probe.inspect_token_file(token_path)
    assert info["expired"] is False


def test_expires_at_in_epoch_milliseconds_is_recognized(tmp_path):
    """The MCP's real tokens-mcp.json stores expires_at as 13-digit epoch
    milliseconds, not seconds — observed on a live token file during the
    spike. A naive epoch-seconds read overflows datetime.fromtimestamp and
    silently degrades to an unparsed string with expired=None."""
    token_path = tmp_path / "tokens-mcp.json"
    past_ms = int((time.time() - 3600) * 1000)
    token_path.write_text(
        json.dumps({"access_token": "x", "refresh_token": "y", "expires_at": past_ms}),
        encoding="utf-8",
    )
    info = probe.inspect_token_file(token_path)
    assert info["expired"] is True
    assert info["expires_at"] is not None
    assert info["expires_at"] != str(past_ms)  # actually parsed, not a raw fallback


# ---------------------------------------------------------------------------
# fake opener plumbing for the egress / users-current / file checks — the
# probe calls `_OPENER.open(...)`, not `urllib.request.urlopen` directly
# (its opener refuses redirects; see test_redirect_* below), so tests
# monkeypatch `probe._OPENER.open`.
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status, body: bytes, headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_dry_run_never_touches_the_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry-run must not call urlopen")

    monkeypatch.setattr(probe._OPENER, "open", boom)

    args = probe.parse_args(
        ["--dry-run", "--file-id", "file123", "--hosts", "platform.plaud.ai,mcp.plaud.ai"]
    )
    summary = probe.build_summary(args)

    assert summary["dry_run"] is True
    assert all(e.get("dry_run") is True for e in summary["egress"])
    assert summary["users_current"].get("dry_run") is True
    assert summary["file"].get("dry_run") is True


def test_egress_and_endpoint_checks_report_status_and_shape(monkeypatch, tmp_path):
    token_path = tmp_path / "tokens-mcp.json"
    token_path.write_text(
        json.dumps({"access_token": "tok-abc", "refresh_token": "ref-xyz", "expires_at": time.time() + 3600}),
        encoding="utf-8",
    )

    file_body = json.dumps({"id": "file123", "source_list": [], "duration": 42}).encode()
    users_body = json.dumps({"id": "user-1", "name": "someone"}).encode()

    def fake_urlopen(req, timeout=10):
        url = req.full_url
        if url.endswith("/health"):
            return FakeResponse(200, b"")
        if url.endswith("/users/current"):
            return FakeResponse(200, users_body)
        if url.endswith("/files/file123"):
            return FakeResponse(200, file_body)
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(probe._OPENER, "open", fake_urlopen)

    args = probe.parse_args(
        [
            "--token-file",
            str(token_path),
            "--file-id",
            "file123",
            "--hosts",
            "platform.plaud.ai,mcp.plaud.ai",
        ]
    )
    summary = probe.build_summary(args)

    assert summary["token_file"]["present"] is True
    assert {e["host"] for e in summary["egress"]} == {"platform.plaud.ai", "mcp.plaud.ai"}
    assert all(e["status"] == 200 for e in summary["egress"])
    assert all(e["reachable"] is True for e in summary["egress"])
    assert summary["user_agent"] == probe.PROBE_USER_AGENT

    assert summary["users_current"]["status"] == 200
    assert summary["users_current"]["has_id"] is True
    # No field beyond status/has_id/url leaks the body.
    assert set(summary["users_current"]) <= {"url", "status", "has_id"}

    assert summary["file"]["status"] == 200
    assert summary["file"]["size_bytes"] == len(file_body)
    assert set(summary["file"]["top_level_keys"]) == {"id", "source_list", "duration"}
    # The file body itself (transcript content) never appears in the summary.
    assert set(summary["file"]) <= {"url", "status", "size_bytes", "top_level_keys"}

    # Access token bytes never appear anywhere in the JSON-serialized summary.
    dumped = json.dumps(summary)
    assert "tok-abc" not in dumped
    assert "ref-xyz" not in dumped


def test_http_error_is_reported_as_status_not_raised(monkeypatch, tmp_path):
    token_path = tmp_path / "tokens-mcp.json"
    token_path.write_text(json.dumps({"access_token": "tok", "refresh_token": "r"}), encoding="utf-8")

    def fake_urlopen(req, timeout=10):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(probe._OPENER, "open", fake_urlopen)

    args = probe.parse_args(
        ["--token-file", str(token_path), "--file-id", "f1", "--hosts", "platform.plaud.ai"]
    )
    summary = probe.build_summary(args)
    assert summary["egress"][0]["status"] == 403
    assert summary["egress"][0]["reachable"] is False
    assert summary["users_current"]["status"] == 403
    assert summary["file"]["status"] == 403


def test_connection_error_reports_error_class_not_traceback(monkeypatch, tmp_path):
    token_path = tmp_path / "tokens-mcp.json"
    token_path.write_text(json.dumps({"access_token": "tok"}), encoding="utf-8")

    def fake_urlopen(req, timeout=10):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(probe._OPENER, "open", fake_urlopen)

    args = probe.parse_args(
        ["--token-file", str(token_path), "--hosts", "mcp.plaud.ai", "--file-id", "f1"]
    )
    summary = probe.build_summary(args)
    assert summary["egress"][0]["error"] == "ConnectionRefusedError"
    assert summary["egress"][0]["reachable"] is False


def test_egress_404_is_reachable_but_403_is_not(monkeypatch, tmp_path):
    """platform.plaud.ai has no /health route at all for a non-Python UA —
    a 404 there still means the host was reached; only a connection error
    or a Cloudflare 403 means the path is actually blocked."""
    token_path = tmp_path / "tokens-mcp.json"
    token_path.write_text(json.dumps({"access_token": "tok"}), encoding="utf-8")

    def fake_urlopen(req, timeout=10):
        if "platform.plaud.ai" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", hdrs=None, fp=None)
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(probe._OPENER, "open", fake_urlopen)

    args = probe.parse_args(
        ["--token-file", str(token_path), "--hosts", "platform.plaud.ai,mcp.plaud.ai"]
    )
    summary = probe.build_summary(args)
    by_host = {e["host"]: e for e in summary["egress"]}
    assert by_host["platform.plaud.ai"]["status"] == 404
    assert by_host["platform.plaud.ai"]["reachable"] is True
    assert by_host["mcp.plaud.ai"]["status"] == 403
    assert by_host["mcp.plaud.ai"]["reachable"] is False


def test_user_agent_header_set_on_every_request(monkeypatch, tmp_path):
    """The default Python-urllib UA gets Cloudflare-banned (error 1010) on
    platform.plaud.ai even with a valid token — found live, 2026-09-17.
    Every request the probe makes must carry the fixed non-Python UA."""
    token_path = tmp_path / "tokens-mcp.json"
    token_path.write_text(
        json.dumps({"access_token": "tok", "refresh_token": "r", "expires_at": time.time() + 3600}),
        encoding="utf-8",
    )
    captured_requests = []

    def fake_urlopen(req, timeout=10):
        captured_requests.append(req)
        return FakeResponse(200, b"{}")

    monkeypatch.setattr(probe._OPENER, "open", fake_urlopen)

    args = probe.parse_args(
        [
            "--token-file",
            str(token_path),
            "--file-id",
            "f1",
            "--hosts",
            "platform.plaud.ai,mcp.plaud.ai",
        ]
    )
    summary = probe.build_summary(args)

    # 2 egress checks + users/current + files/{id}
    assert len(captured_requests) == 4
    for req in captured_requests:
        assert req.headers.get("User-agent") == probe.PROBE_USER_AGENT
    assert not probe.PROBE_USER_AGENT.startswith("Python-urllib")
    assert summary["user_agent"] == probe.PROBE_USER_AGENT


# ---------------------------------------------------------------------------
# real localhost servers for the redirect test
#
# Round 1's redirect test monkeypatched `probe._OPENER.open` directly with a
# fake that just returned a 302 response object — it never exercised
# urllib's own error-dispatch chain. In reality, `_NoRedirectHandler.
# redirect_request` returning None makes `http_error_302` return None,
# which OpenerDirector.error() then routes to HTTPDefaultErrorHandler,
# which *raises* HTTPError for the 3xx (verified against
# urllib.request.OpenerDirector.error/_call_chain/HTTPDefaultErrorHandler
# source). Only two real HTTP servers driven through the actual opener
# exercise that chain.
# ---------------------------------------------------------------------------


class _RedirectHandler(http.server.BaseHTTPRequestHandler):
    """Answers every request with a 302 to `self.server.redirect_location`
    and counts hits on `self.server.hits`."""

    def _handle(self):
        self.server.hits += 1
        self.send_response(302)
        self.send_header("Location", self.server.redirect_location)
        self.end_headers()

    def do_GET(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def log_message(self, format, *args):  # silence default stderr logging
        pass


class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    """Answers 200 with an empty JSON object and counts hits on
    `self.server.hits` — must stay at 0 if a redirect to this server is
    never followed."""

    def _handle(self):
        self.server.hits += 1
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def log_message(self, format, *args):
        pass


@contextlib.contextmanager
def _local_server(handler_cls):
    server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
    server.hits = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_redirect_is_never_followed_and_authorization_never_leaks(monkeypatch, tmp_path):
    """PR #215 review finding, round 2: drive the *real* opener/error
    chain, not a faked response. `target` must see zero requests; `source`
    (which answers every request with a 302 to `target`) must see exactly
    one request per authenticated endpoint — proving the probe never
    issues the "followed" second request that would carry Authorization
    to a new host."""
    token_path = tmp_path / "tokens-mcp.json"
    token_path.write_text(json.dumps({"access_token": "tok-secret-value"}), encoding="utf-8")

    with _local_server(_RecordingHandler) as target, _local_server(_RedirectHandler) as source:
        source.redirect_location = f"http://127.0.0.1:{target.server_port}/x"
        base = f"http://127.0.0.1:{source.server_port}"
        monkeypatch.setattr(probe, "USERS_CURRENT_URL", f"{base}/users/current")
        monkeypatch.setattr(probe, "FILES_URL_TEMPLATE", base + "/files/{file_id}")

        # No --hosts: this test targets the two authenticated call sites
        # the finding named (users/current, files/{id}); egress uses a
        # hardcoded https:// URL this plain-http test server can't answer.
        args = probe.parse_args(
            ["--token-file", str(token_path), "--file-id", "f1", "--hosts", ""]
        )
        summary = probe.build_summary(args)

        assert target.hits == 0  # never followed
        assert source.hits == 2  # users/current + file, one request each

    assert summary["users_current"]["status"] == 302
    assert summary["users_current"]["redirected"] is True
    assert summary["users_current"]["redirected_to_host"] == "127.0.0.1"

    assert summary["file"]["status"] == 302
    assert summary["file"]["redirected"] is True
    assert summary["file"]["redirected_to_host"] == "127.0.0.1"

    dumped = json.dumps(summary)
    assert "tok-secret-value" not in dumped  # the bearer token itself
    # Never the raw Location URL — it can carry a token/query string, and
    # only the host name is reported.
    assert "/x" not in dumped
    assert str(target.server_port) not in dumped


def test_no_file_id_skips_file_check_without_erroring(monkeypatch, tmp_path):
    token_path = tmp_path / "tokens-mcp.json"
    token_path.write_text(json.dumps({"access_token": "tok"}), encoding="utf-8")

    def fake_urlopen(req, timeout=10):
        if req.full_url.endswith("/health"):
            return FakeResponse(200, b"")
        if req.full_url.endswith("/users/current"):
            return FakeResponse(200, b"{}")
        raise AssertionError("file endpoint should not be called without --file-id")

    monkeypatch.setattr(probe._OPENER, "open", fake_urlopen)

    args = probe.parse_args(["--token-file", str(token_path), "--hosts", "platform.plaud.ai"])
    summary = probe.build_summary(args)
    assert "skipped" in summary["file"]


# ---------------------------------------------------------------------------
# --compare: MCP scratch pages vs. the API's source_list transaction entry
# ---------------------------------------------------------------------------


def _mcp_page(offset, segments):
    return {"offset": offset, "segments": segments}


def test_compare_matching_sequences(tmp_path):
    page0 = tmp_path / "page0.json"
    page1 = tmp_path / "page1.json"
    page0.write_text(
        json.dumps(_mcp_page(0, [{"speaker": "A", "content": "hello", "end_time": 1.0}])),
        encoding="utf-8",
    )
    page1.write_text(
        json.dumps(_mcp_page(1, [{"speaker": "B", "content": "world", "end_time": 2.0}])),
        encoding="utf-8",
    )

    api_body = {
        "source_list": [
            {
                "data_type": "transaction",
                "data_content": json.dumps(
                    {
                        "segments": [
                            {"speaker": "A", "content": "hello", "end_time": 1.0},
                            {"speaker": "B", "content": "world", "end_time": 2.0},
                        ]
                    }
                ),
            }
        ]
    }

    mcp_utterances = probe.load_compare_pages([str(page0), str(page1)])
    api_utterances, observed = probe.extract_api_utterances(api_body)
    assert observed is None
    result = probe.compare_sequences(mcp_utterances, api_utterances)
    assert result["match"] is True
    assert result["mcp_count"] == result["api_count"] == 2


def test_compare_mismatched_sequences(tmp_path):
    page0 = tmp_path / "page0.json"
    page0.write_text(
        json.dumps(_mcp_page(0, [{"speaker": "A", "content": "hello", "end_time": 1.0}])),
        encoding="utf-8",
    )
    api_body = {
        "source_list": [
            {
                "data_type": "transaction",
                "data_content": json.dumps(
                    {"segments": [{"speaker": "A", "content": "DIFFERENT", "end_time": 1.0}]}
                ),
            }
        ]
    }
    mcp_utterances = probe.load_compare_pages([str(page0)])
    api_utterances, observed = probe.extract_api_utterances(api_body)
    assert observed is None
    result = probe.compare_sequences(mcp_utterances, api_utterances)
    assert result["match"] is False


def test_compare_unexpected_shape_reports_keys_instead_of_failing():
    api_body = {"weird": "shape", "no_source_list": True}
    api_utterances, observed = probe.extract_api_utterances(api_body)
    assert api_utterances is None
    assert observed == {"top_level_keys": ["no_source_list", "weird"]}


def test_compare_no_transaction_entry_reports_seen_data_types():
    api_body = {"source_list": [{"data_type": "audio"}, {"data_type": "image"}]}
    api_utterances, observed = probe.extract_api_utterances(api_body)
    assert api_utterances is None
    assert observed == {"source_list_data_types": ["audio", "image"]}


def test_compare_matches_the_real_api_shape_bare_list_of_utterances(tmp_path):
    """Found live, 2026-09-17: `data_content` is a JSON string of a bare
    list of utterance dicts (not wrapped in a {"segments": [...]} object),
    each carrying content/end_time/original_speaker/speaker/start_time.
    Comparison is on (speaker, content) only — start_time/end_time/
    original_speaker differing from the MCP page's own end_time must not
    cause a false mismatch."""
    page0 = tmp_path / "page0.json"
    page0.write_text(
        json.dumps(_mcp_page(0, [{"speaker": "A", "content": "hello", "end_time": 1.0}])),
        encoding="utf-8",
    )
    api_body = {
        "source_list": [
            {
                "data_type": "transaction",
                "data_content": json.dumps(
                    [
                        {
                            "speaker": "A",
                            "content": "hello",
                            "start_time": 0.4,
                            "end_time": 999.9,  # deliberately different from the MCP page
                            "original_speaker": "Speaker 1",
                        }
                    ]
                ),
            }
        ]
    }
    mcp_utterances = probe.load_compare_pages([str(page0)])
    api_utterances, observed = probe.extract_api_utterances(api_body)
    assert observed is None
    assert api_utterances[0]["original_speaker"] == "Speaker 1"  # carried through, not dropped
    result = probe.compare_sequences(mcp_utterances, api_utterances)
    assert result["match"] is True


# ---------------------------------------------------------------------------
# safety invariants: never refresh, never write
# ---------------------------------------------------------------------------


def test_module_never_references_the_refresh_endpoint():
    import inspect

    source = inspect.getsource(probe)
    assert "access-token/refresh" not in source


def test_module_has_no_write_calls_on_the_token_file():
    import inspect

    source = inspect.getsource(probe)
    # No function in this module opens any path in a write mode.
    assert 'mode="w"' not in source
    assert "'w'" not in source
    assert '"w"' not in source
    assert "write_text(" not in source
    assert "write_bytes(" not in source
