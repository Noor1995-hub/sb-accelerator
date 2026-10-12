"""Deterministic scrub lint + approval-gated GitHub send.

The lint is the technical control behind the disclosure promise: a draft
that names anything from the vault is refused before a byte leaves the
machine.
"""
import json
import urllib.error

import pytest

from vaultlib import config, feedback

from test_vaultlib_vault import make_vault
from test_vaultlib_config import valid_config, write_config


def seeded_vault(tmp_path):
    root = make_vault(tmp_path)
    write_config(root, valid_config(
        feedback={"repo": "delaware-org/sb-client-demo"}))
    (root / "structure-version").write_text("2\n", encoding="utf-8")
    (root / "50-people" / "casey-morrow.md").write_text(
        "---\nperson-name: Casey Morrow\n---\n", encoding="utf-8")
    (root / "40-entities" / "northwind-logistics").mkdir(parents=True)
    (root / "40-entities" / "northwind-logistics" / "dossier.md").write_text(
        "---\nentity-name: Northwind Logistics\n---\n", encoding="utf-8")
    (root / "30-projects" / "fleet-renewal").mkdir(parents=True)
    (root / "30-projects" / "fleet-renewal" / "index.md").write_text(
        "---\nproject-name: Fleet Renewal\nentity: northwind-logistics\n---\n",
        encoding="utf-8")
    (root / "20-meetings" / "2026-08-20-northwind-steering.md").write_text(
        "---\ntitle: Northwind steering\n---\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("fragment,kind", [
    ("Casey Morrow told us", "person"),
    ("the casey-morrow note", "person"),
    ("Northwind Logistics renewal", "entity"),
    ("see fleet-renewal", "project"),
    ("in 2026-08-20-northwind-steering", "meeting"),
    ("mail me at casey@northwind.example", "email"),
    ("links like [[anything]]", "wikilink"),
    ("the file 20-meetings/2026-08-20-x.md", "vault-path"),
    ("hint was morgan@example.com", "email"),
])
def test_lint_blocks_vault_data(tmp_path, fragment, kind):
    root = seeded_vault(tmp_path)
    result = feedback.lint(root, f"The sync failed. {fragment}.")
    assert result["ok"] is False
    assert kind in {b["kind"] for b in result["blocked"]}


def test_lint_passes_a_clean_generic_draft(tmp_path):
    root = seeded_vault(tmp_path)
    clean = ("Expected the evening run to write one prep region per "
             "calendar meeting; got a structural-change error on re-run. "
             "3 meetings, 1 daily note.")
    result = feedback.lint(root, clean)
    assert result["ok"] is True and result["blocked"] == []
    assert result["terms_checked"] > 0


def test_send_posts_lint_clean_draft_with_deployment_and_disclosure(tmp_path):
    root = seeded_vault(tmp_path)
    (root / "99-workflow-config" / "secrets").mkdir(parents=True)
    (root / "99-workflow-config" / "secrets" / "feedback-token").write_text(
        "ghp_test123\n", encoding="utf-8")
    calls = {}

    def fake_post(url, token, payload):
        calls.update(url=url, token=token, payload=payload)
        return {"html_url": "https://github.com/delaware-org/sb-client-demo/issues/1"}

    result = feedback.send(root, "Evening sync re-run error",
                           "Generic description.", post=fake_post)
    assert result["issue_url"].endswith("/issues/1")
    assert calls["url"] == ("https://api.github.com/repos/"
                            "delaware-org/sb-client-demo/issues")
    assert calls["token"] == "ghp_test123"
    body = calls["payload"]["body"]
    assert "Generic description." in body
    assert "structure-version 2" in body        # deployment stamp
    assert feedback.DISCLOSURE in body           # promise travels with the issue


def test_send_refuses_blocked_draft_and_missing_channel(tmp_path):
    root = seeded_vault(tmp_path)
    (root / "99-workflow-config" / "secrets").mkdir(parents=True)
    (root / "99-workflow-config" / "secrets" / "feedback-token").write_text(
        "t\n", encoding="utf-8")
    with pytest.raises(feedback.FeedbackError):
        feedback.send(root, "x", "Casey Morrow said so", post=lambda *a: {})
    write_config(root, valid_config())           # feedback.repo back to null
    with pytest.raises(feedback.FeedbackError):
        feedback.send(root, "x", "clean", post=lambda *a: {})


def test_send_raises_naming_path_when_token_file_missing(tmp_path):
    root = seeded_vault(tmp_path)
    with pytest.raises(feedback.FeedbackError, match="feedback-token"):
        feedback.send(root, "x", "clean generic body", post=lambda *a: {})


class _FakeResponse:
    """Mimics the context-manager object urllib.request.urlopen returns."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_post_happy_path_sends_auth_header_and_returns_parsed_json(monkeypatch):
    """_post is the real HTTP transport (post=None default); every other
    test injects a fake poster, so this exercises it directly."""
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse(
            json.dumps({"html_url": "https://github.com/o/r/issues/9"})
            .encode("utf-8"))

    monkeypatch.setattr(feedback.urllib.request, "urlopen", fake_urlopen)

    result = feedback._post(
        "https://api.github.com/repos/o/r/issues", "ghp_supersecret",
        {"title": "t", "body": "b"},
    )

    assert result == {"html_url": "https://github.com/o/r/issues/9"}
    assert (captured["request"].get_header("Authorization")
            == "Bearer ghp_supersecret")
    assert captured["timeout"] == feedback._HTTP_TIMEOUT


def test_post_wraps_http_error_without_echoing_token_or_headers(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            "https://api.github.com/repos/o/r/issues", 403, "Forbidden",
            hdrs={"X-Fake-Auth": "Bearer ghp_supersecret"}, fp=None,
        )

    monkeypatch.setattr(feedback.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(feedback.FeedbackError) as excinfo:
        feedback._post(
            "https://api.github.com/repos/o/r/issues", "ghp_supersecret",
            {"title": "t", "body": "b"},
        )

    message = str(excinfo.value)
    assert "403" in message
    assert "ghp_supersecret" not in message
    assert "X-Fake-Auth" not in message


def test_post_wraps_url_error_without_echoing_token(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("nope")

    monkeypatch.setattr(feedback.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(feedback.FeedbackError) as excinfo:
        feedback._post(
            "https://api.github.com/repos/o/r/issues", "ghp_supersecret",
            {"title": "t", "body": "b"},
        )

    message = str(excinfo.value)
    assert "nope" in message
    assert "ghp_supersecret" not in message


def test_a_fact_from_what_i_know_is_blocked(tmp_path):
    root = seeded_vault(tmp_path)
    (root / "50-people" / "zed.md").write_text(
        '---\nperson-name: "Zed Q"\nslug: zed\n---\n# Zed Q\n\n## What I know\n\n'
        "- 2026-10-08 — Is selling the house in Ghent. (meeting · [[m]])\n"
        "- Plays chess on Sundays.\n", encoding="utf-8")
    result = feedback.lint(root, "The sync crashed; also is selling the house in ghent lol")
    assert result["ok"] is False
    assert {"kind": "fact", "fragment": "Is selling the house in Ghent"} in result["blocked"]
    assert feedback.lint(root, "plays chess on sundays")["ok"] is False
    assert feedback.lint(root, "The sync crashed on step 6.")["ok"] is True


def test_migrated_lines_and_any_heading_case_are_blocked(tmp_path):
    # Final review I2: a migrated /update-entity line carries two trailing
    # parentheticals, and the heading may be "## What I Know".
    root = seeded_vault(tmp_path)
    (root / "50-people" / "zed.md").write_text(
        '---\nperson-name: "Zed Q"\nslug: zed\n---\n# Zed Q\n\n## What I Know\n\n'
        "- Wants numbers, not narrative. (from /update-entity, 2026-10-01) (Notes from Acme)\n",
        encoding="utf-8")
    result = feedback.lint(root, "the user wants numbers, not narrative in the recap")
    assert {"kind": "fact", "fragment": "Wants numbers, not narrative"} in result["blocked"]


def test_code_blocks_under_what_i_know_are_not_facts(tmp_path):
    # PR review: a migrated dataview block must not put "LIST" on the
    # blocklist — it would refuse any draft containing "list".
    root = seeded_vault(tmp_path)
    (root / "50-people" / "zed.md").write_text(
        '---\nperson-name: "Zed Q"\nslug: zed\n---\n# Zed Q\n\n## What I know\n\n'
        "```dataview\nLIST\n```\n\n- Plays chess on Sundays.\n", encoding="utf-8")
    assert feedback.lint(root, "The list view crashed in dataview.")["ok"] is True
    assert feedback.lint(root, "plays chess on sundays")["ok"] is False


def test_decisions_to_dos_and_own_notes_are_blocked(tmp_path):
    # Review 2026-10-12: none of these was on the list.
    root = seeded_vault(tmp_path)
    folder = root / "30-projects" / "zz-proj" / "decisions"
    folder.mkdir(parents=True)
    (folder / "2026-10-01-close-the-ghent-plant.md").write_text(
        '---\ntype: decision\nsummary: "Close the Ghent plant by March"\n---\n', encoding="utf-8")
    (root / "65-to-dos").mkdir(exist_ok=True)
    (root / "65-to-dos" / "2026-10-02-call.md").write_text(
        '---\ntype: to-do\nto-do: "Call the works council chair"\n---\n', encoding="utf-8")
    (root / "80-thoughts-ideas").mkdir(exist_ok=True)
    (root / "80-thoughts-ideas" / "Reorg options for finance.md").write_text("x", encoding="utf-8")
    for draft in ("we decided to close the ghent plant by march",
                  "the to do call the works council chair vanished",
                  "my note reorg options for finance was not read"):
        assert feedback.lint(root, draft)["ok"] is False, draft
    assert feedback.lint(root, "The sync crashed on step 6.")["ok"] is True
