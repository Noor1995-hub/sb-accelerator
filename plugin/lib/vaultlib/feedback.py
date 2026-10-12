"""Deterministic scrub lint + approval-gated GitHub send.

The lint is the technical control behind the disclosure promise: a draft
that names anything from the vault is refused before a byte leaves the
machine. `send` always runs it itself — there is no code path that posts an
unlinted draft, no matter what a caller upstream already checked. That
includes every fact on a person page's `## What I know` (#273 piece 4):
facts about people never leave the vault.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from vaultlib import config, markdown, vault

SECRETS_RELPATH = Path("99-workflow-config") / "secrets" / "feedback-token"

# Long enough for a slow client-side connection, short enough that a skill
# never hangs unattended waiting on a dead GitHub endpoint.
_HTTP_TIMEOUT = 30

DISCLOSURE = (
    "**What this report contains and how it is used:** this report carries "
    "only the plugin version, the vault structure version, the skill "
    "involved, a generic description of expected vs. actual behavior, and "
    "counts. It contains zero personal or business content: no note text, "
    "no names of people or organizations, no meeting titles. A deterministic "
    "scrub check enforces this before anything is sent. The only identifying "
    "fact is which deployment it came from, which is what makes it "
    "actionable. delaware uses these reports solely to improve the product. "
    "Nothing is ever sent without your explicit approval."
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_WIKILINK_RE = re.compile(r"\[\[")
_VAULT_PATH_RE = re.compile(
    r"\b(?:10-inbox|20-meetings|30-projects|40-entities|50-people|"
    r"60-daily-notes|65-to-dos|70-resources|80-thoughts-ideas|90-archive|95-private)/\S+")
_MIN_TERM_LEN = 4   # "Jo" as a substring would block the word "major"


class FeedbackError(Exception):
    """A blocked draft or an unconfigured/unreachable feedback channel."""


_FACT_DATE_RE = re.compile(r"\A- (?:\d{4}-\d{2}-\d{2} — )?")
_FACT_MARKER_RE = re.compile(
    r"\s*\((?:meeting|mail|chat|session|note|moved from|from|notes from) [^()]*\)\s*\Z",
    re.IGNORECASE)


def _facts(body: str) -> list:
    """The text of each line under `## What I know` (#273 piece 4), without
    its date and source marker: facts about a person never leave the vault."""
    out = []
    for title, content in markdown.split_sections(body):
        if title.strip().lower() != "what i know":
            continue
        fence = None
        for line in content.split("\n"):
            # A code block (a query the upgrade moved here) holds no facts;
            # its words would refuse any draft that says "list".
            match = markdown._FENCE_RE.match(line)
            if match:
                token = match.group(1)
                fence = None if fence == token else (fence or token)
                continue
            line = line.strip()
            if not line or fence is not None:
                continue
            # Every trailing marker goes — a line the structure-15 upgrade
            # moved can carry two — and so does the closing punctuation, so a
            # draft quoting the fact mid-sentence still matches.
            text = _FACT_DATE_RE.sub("", line)
            while True:
                stripped = _FACT_MARKER_RE.sub("", text)
                if stripped == text:
                    break
                text = stripped
            text = text.strip().rstrip(".!?;:,")
            if text:
                out.append(text)
    return out


def _blocklist(root: Path) -> list:
    """(kind, term) pairs. Deterministic, order-stable, casefolded later.

    A file that fails to read or parse still contributes its filename-stem
    term (the slug is still identifying) — only the frontmatter-derived
    display name is skipped, so one mangled object can't blind the guard.
    """
    terms = []
    for path in sorted((root / vault.PEOPLE_DIR).glob("*.md")):
        terms.append(("person", path.stem))
        try:
            front, body = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            front, body = {}, ""
        if front.get("person-name"):
            terms.append(("person", str(front["person-name"])))
        terms.extend(("fact", fact) for fact in _facts(body))
    for path in sorted((root / vault.ENTITIES_DIR).glob("*/dossier.md")):
        terms.append(("entity", path.parent.name))
        try:
            front, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            front = {}
        if front.get("entity-name"):
            terms.append(("entity", str(front["entity-name"])))
    for path in sorted((root / vault.PROJECTS_DIR).glob("*/index.md")):
        terms.append(("project", path.parent.name))
        try:
            front, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            front = {}
        if front.get("project-name"):
            terms.append(("project", str(front["project-name"])))
    for path in sorted((root / vault.MEETINGS_DIR).glob("*.md")):
        terms.append(("meeting", path.stem))
        try:
            front, _ = markdown.split_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            front = {}
        subject = front.get("calendar-subject") or front.get("title")
        if subject:
            terms.append(("meeting", str(subject)))
    cfg = config.read(root)["config"]
    if cfg["owner"]:
        terms.append(("owner", cfg["owner"]))
    for name in config.CONNECTOR_ADAPTERS:
        hint = cfg["adapters"][name]["account_hint"]
        if hint:
            terms.append(("account", hint))
    return [(kind, term) for kind, term in terms
            if len(term.strip()) >= _MIN_TERM_LEN]


def lint(root: Path, text: str) -> dict:
    """Scrub-check `text` against every vault-derived identifying term.

    Deterministic and order-stable: the blocklist terms are checked first
    (in the order `_blocklist` produced them), then the three structural
    regexes, deduped on (kind, fragment).
    """
    blocklist = _blocklist(root)
    folded = text.casefold()
    blocked = []
    seen = set()
    for kind, term in blocklist:
        if term.casefold() in folded:
            key = (kind, term)
            if key not in seen:
                seen.add(key)
                blocked.append({"kind": kind, "fragment": term})
    for kind, regex in (
        ("email", _EMAIL_RE),
        ("wikilink", _WIKILINK_RE),
        ("vault-path", _VAULT_PATH_RE),
    ):
        for match in regex.finditer(text):
            fragment = match.group(0)
            key = (kind, fragment)
            if key not in seen:
                seen.add(key)
                blocked.append({"kind": kind, "fragment": fragment})
    return {
        "ok": not blocked,
        "blocked": blocked,
        "terms_checked": len(blocklist),
    }


def _post(url: str, token: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "sb-accelerator",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Never echo the token: HTTPError's str is status/reason/body, none
        # of which the request supplied.
        raise FeedbackError(
            f"GitHub rejected the issue (HTTP {exc.code} {exc.reason})"
        ) from None
    except urllib.error.URLError as exc:
        raise FeedbackError(f"could not reach GitHub: {exc.reason}") from None


def send(root: Path, title: str, body: str, post=None) -> dict:
    """Lint, stamp, and file one GitHub issue. `post` is injectable for tests.

    Runs the lint itself — no code path here posts an unlinted draft, even
    if a caller already linted the same text upstream.
    """
    cfg = config.read(root)["config"]
    repo = cfg["feedback"]["repo"]
    if not repo:
        raise FeedbackError(
            "feedback.repo is not configured — set it with "
            "`config write --field feedback.repo` before sending a report")

    token_path = root / SECRETS_RELPATH
    if not token_path.is_file():
        raise FeedbackError(
            f"{SECRETS_RELPATH.as_posix()} is missing from this vault — add the "
            "GitHub token there before sending a report")
    token = token_path.read_text(encoding="utf-8").strip()

    lint_result = lint(root, title + "\n" + body)
    if not lint_result["ok"]:
        details = ", ".join(
            f"{b['kind']}: {b['fragment']!r}" for b in lint_result["blocked"])
        raise FeedbackError(
            f"draft blocked by the scrub lint — {details}")

    full_body = (
        body.rstrip() + "\n\n---\n"
        f"**Deployment:** plugin {vault.plugin_version()} · "
        f"structure-version {vault.structure_version(root)}\n\n"
        + DISCLOSURE + "\n"
    )
    payload = {"title": title, "body": full_body}
    url = f"https://api.github.com/repos/{repo}/issues"
    poster = post if post is not None else _post
    response = poster(url, token, payload)
    return {"issue_url": response["html_url"], "lint": lint_result}
