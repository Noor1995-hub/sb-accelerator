#!/usr/bin/env python3
"""Drive a live Obsidian instance and capture what the vault actually renders.

Why this exists: the five .base files, the Minimal theme, Style Settings and
the Dataview blocks in note bodies *are* this product's UI, and until now the
only way to check that any of it rendered was for a human to open Obsidian and
look (docs/local-setup.md step 3). scripts/basesim.py closed the "which rows"
half of that gap in CI. This closes the other half — rendering — by asking the
real app instead of simulating it.

Obsidian 1.10+ ships an official CLI (Obsidian.app/Contents/MacOS/obsidian-cli)
whose dev: subcommands expose screenshots, the rendered DOM, computed CSS and
an eval hook. This module is a thin, *guarded* wrapper over it.

THE GUARD IS THE POINT. The CLI targets "the most recently focused vault" when
no vault= is given, and that default drifts silently — during development of
this script, a bare `obsidian bases` returned a test vault's bases while the
author believed the real one was focused. So doctor, up and tour each resolve
app.vault.adapter.basePath *before issuing anything else* and refuse unless it
sits under test-vaults/; validating the --vault argument is not the same check
and does not substitute for it. (`down` is exempt because it only ever
addresses the probe's own instance, over the probe's own socket.) Nothing else
in the repo may call the CLI directly.

Local-only by construction: a licensed macOS GUI app and a plugin-trust dialog
that cannot ship as files. This never becomes a CI check; see
docs/visual-verification.md.

Dev-time only — never imported by the plugin, so PyYAML is fair game.
Must stay Python 3.10-clean: CI runs this suite on the runtime floor.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path, PurePath
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]

# Short by necessity, not taste: the CLI binds "$HOME/.obsidian-cli.sock" and
# macOS caps a unix socket path (sun_path) at 104 bytes. A rig inside the repo
# — .../.claude/worktrees/<name>/.obsidian-probe/home — is 127 chars and the
# app dies with `listen EINVAL`. Living outside the repo also means the
# one-time "enable the CLI" click survives every worktree and rebuild.
DEFAULT_PROBE_HOME = Path.home() / ".sb-probe"
SOCKET_NAME = ".obsidian-cli.sock"
LOCK_NAME = "probe.lock"
SUN_PATH_MAX = 104

# The probe always registers its vault under this one id, whatever the vault's
# path. Obsidian records plugin trust as a localStorage key keyed by vault id
# (`enable-plugin-<id>`), so a fixed id means the one-time "trust author and
# enable plugins" click carries over to every throwaway vault built afterwards.
# Without this, every fresh make_test_vault.py run costs another click — and an
# un-dismissed trust modal wedges the CLI socket for the whole instance.
PROBE_VAULT_ID = "5b0000000000c1a0"

OBSIDIAN_APP = Path("/Applications/Obsidian.app")
OBSIDIAN_BIN = OBSIDIAN_APP / "Contents/MacOS/Obsidian"
OBSIDIAN_CLI = OBSIDIAN_APP / "Contents/MacOS/obsidian-cli"

# Only vaults with this directory somewhere in their path may be driven. A
# path *component*, not a substring: the original "/test-vaults/" substring
# check never matched on Windows, where separators are backslashes, so the
# guard refused every vault — fail-closed, but unusable. CI's Windows job
# caught it. Component matching is also stricter: "my-test-vaults-backup" is
# no longer a match.
TEST_VAULT_DIR = "test-vaults"

# Fixed and documented so header capture is reproducible. Bases virtualises
# columns horizontally — at 1024px wide a 8-column view renders 5 headers, at
# 1600px it renders 7 — so any width-dependent assertion has to know its width.
WINDOW_W, WINDOW_H = 1920, 1200

# Keep the probe window painting while it sits cloaked (cloak_window) or
# buried. Chromium throttles and eventually stops compositing a window it
# believes is occluded, which is what makes captures hand back a stale frame;
# the alternative was raising the window before all 17 captures, which makes
# the machine unusable during a tour. Disabling occlusion detection buys
# freshness without the window ever being seen.
BACKGROUND_FLAGS = (
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion",
)


# Set by --foreground. Off by default: a tour raising the window 17 times makes
# the machine unusable while it runs.
FOREGROUND = False


class ProbeError(Exception):
    """Anything that should stop the run with a message, not a traceback."""


# ---------------------------------------------------------------- CLI plumbing

def cli(args: Sequence[str], *, home: Optional[Path] = None,
        vault: Optional[str] = None, timeout: int = 20) -> str:
    """Run one obsidian CLI command and return stdout.

    The single seam the tests monkeypatch — nothing else in this module shells
    out. `home` selects which Obsidian instance answers: the CLI resolves its
    socket from $HOME, so overriding HOME is what isolates the probe instance
    from the user's own.
    """
    if not OBSIDIAN_CLI.exists():
        raise ProbeError(f"Obsidian CLI not found at {OBSIDIAN_CLI}")
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = str(home)
    cmd = [str(OBSIDIAN_CLI)]
    if vault:
        cmd.append(f"vault={vault}")
    cmd.extend(args)
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(
            f"obsidian {' '.join(args)} timed out after {timeout}s — the instance is "
            "wedged.\n  A modal dialog blocks the CLI socket for every vault in an "
            "instance, not just the one showing it (a first-open 'trust plugins' or "
            "folder-permission prompt does this).\n  Fix: dismiss the dialog in that "
            "Obsidian window, or close the window.") from exc
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if "Command line interface is not enabled" in out + err:
        raise ProbeError(
            "the CLI is disabled in this Obsidian profile.\n"
            "  Fix: in that Obsidian window, Settings -> General -> Advanced -> "
            "enable 'Command line interface'.\n"
            "  It is a per-profile setting stored in localStorage, so it cannot "
            "be seeded from disk — one click, once per profile.")
    if proc.returncode != 0:
        raise ProbeError(f"obsidian {' '.join(args)} failed: {err or out}")
    return out


def eval_js(code: str, **kw) -> str:
    """Evaluate JS in the app and return the result as a string.

    Routed through `dev:cdp Runtime.evaluate` rather than the friendlier `eval`
    subcommand: a freshly launched probe profile did not list `eval` among its
    101 commands and answered "Command not found. It may require a plugin to be
    enabled", while `dev:cdp` was present and worked. Whatever gates `eval`,
    CDP is the dependable route. Runtime.evaluate accepts statement sequences
    and returns the completion value, so `a(); b(); 'ok'` behaves the way the
    call sites expect.
    """
    params = json.dumps({"expression": code, "returnByValue": True})
    out = cli(["dev:cdp", "method=Runtime.evaluate", f"params={params}"], **kw)
    try:
        data = json.loads(out)
    except ValueError as exc:
        raise ProbeError(f"unparseable CDP reply for {code!r}: {out[:200]}") from exc
    if "exceptionDetails" in data:
        detail = data["exceptionDetails"]
        text = (detail.get("exception") or {}).get("description") or detail.get("text")
        raise ProbeError(f"JS threw while evaluating {code[:80]!r}: {text}")
    return str((data.get("result") or {}).get("value", ""))


def socket_path(home: Path) -> Path:
    return Path(home) / SOCKET_NAME


def register_vault(userdata: Path, vault: Path) -> None:
    """Write the probe profile's vault registry directly.

    Not via `obsidian://open?path=` — that route prompts, and any modal blocks
    the instance's CLI socket for every vault in it. Writing the registry is
    also where `cli: true` goes: the CLI-enabled flag lives in this file, not in
    localStorage, so the probe profile never needs a visit to Settings.
    """
    registry = userdata / "obsidian.json"
    data = {}
    if registry.is_file():
        try:
            data = json.loads(registry.read_text())
        except ValueError:
            data = {}
    vaults = data.setdefault("vaults", {})
    for entry in vaults.values():
        entry.pop("open", None)
    vaults[PROBE_VAULT_ID] = {"path": str(vault),
                              "ts": int(time.time() * 1000),
                              "open": True}
    data["cli"] = True
    registry.write_text(json.dumps(data, indent=2) + "\n")


def check_socket_path(home: Path) -> None:
    """Fail fast on the 104-byte limit rather than let the app die with EINVAL."""
    p = str(socket_path(home))
    if len(p.encode()) > SUN_PATH_MAX:
        raise ProbeError(
            f"probe HOME is too deep: the socket path is {len(p)} bytes and "
            f"macOS caps unix socket paths at {SUN_PATH_MAX}.\n  {p}\n"
            f"  Fix: use a shorter --home (the default {DEFAULT_PROBE_HOME} is safe).")


def derive_probe_home(repo_root: Path = REPO_ROOT) -> Path:
    """One probe profile per worktree checkout. Hashed, not the literal path
    embedded, so the socket stays well under the 104-byte sun_path cap
    regardless of how deep the worktree lives (see check_socket_path)."""
    digest = hashlib.sha256(str(repo_root).encode()).hexdigest()[:10]
    return DEFAULT_PROBE_HOME.parent / f"{DEFAULT_PROBE_HOME.name}-{digest}"


def resolve_home(args) -> None:
    """Fill in the derived default only when --home was not given explicitly."""
    if getattr(args, "home", None) is None:
        args.home = str(derive_probe_home())


# ------------------------------------------------------------------- the lock

def lock_path(home: Path) -> Path:
    return Path(home) / LOCK_NAME


def read_lock(home) -> Optional[dict]:
    """None when no lock is held, or its file is not valid JSON."""
    p = lock_path(home)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except ValueError:
        return None


def pid_alive(pid) -> bool:
    """Best-effort liveness of a lock's recorded pid, via a signal-0 probe."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours
    except OSError:
        return False
    return True


def write_lock(home, vault, pid) -> None:
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    lock_path(home).write_text(json.dumps(
        {"pid": pid, "vault": str(vault), "ts": time.time()}))


def release_lock(home) -> None:
    try:
        lock_path(home).unlink(missing_ok=True)
    except OSError:
        pass


# --------------------------------------------------------------------- the guard

def wait_ready(timeout: float = 30.0, **kw) -> None:
    """Wait for the renderer's command surface, not just the socket.

    The CLI socket is bound by the main process at boot, several seconds before
    `dev:cdp` is answerable — so polling the socket alone races and `up` fails
    with "Command dev:cdp not found" against an instance that is merely still
    starting.
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            resolve_vault_path(**kw)
            return
        except ProbeError as exc:
            last = exc
            time.sleep(1.0)
    raise ProbeError(f"probe instance never became ready: {last}")


def under_test_vaults(path) -> bool:
    """True when `path` has a `test-vaults` component, on any platform."""
    parts = getattr(path, "parts", None)
    if parts is None:
        parts = PurePath(path).parts
    return TEST_VAULT_DIR in parts


def resolve_vault_path(**kw) -> Path:
    """Ask the app which vault it has open. The one fact the guard turns on."""
    base = eval_js("app.vault.adapter.basePath", **kw)
    if not base or base.startswith("Error"):
        raise ProbeError(f"could not read the open vault path (got {base!r}). "
                         "Is a vault open in that instance?")
    return Path(base)


def guard(**kw) -> Path:
    """Refuse to drive anything that is not a test vault.

    Fails closed: any doubt about which vault answered stops the run. This is
    the only thing standing between a mistargeted `vault=` and someone's real
    notes, so it runs before every subcommand that touches app state.
    """
    base = resolve_vault_path(**kw)
    if not under_test_vaults(base):
        raise ProbeError(
            f"refusing to drive {base}\n"
            f"  Only vaults under a {TEST_VAULT_DIR}/ directory may be "
            f"probed. Build one with:\n"
            f"    python scripts/make_test_vault.py test-vaults/$(date +%F)-visual --with-plugins")
    return base


# ------------------------------------------------------------------ provenance

# .obsidian/ is excluded because --with-plugins legitimately adds plugin and
# theme files that no source tree carries; .claude is the symlink make_test_vault
# creates; the rest is OS litter.
_IGNORED_PREFIXES = (".obsidian/", ".claude/", ".trash/")
_IGNORED_NAMES = {".DS_Store", ".claude"}


def _inventory(root: Path) -> set:
    out = set()
    for p in root.rglob("*"):
        if not p.is_file() or p.is_symlink():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(_IGNORED_PREFIXES) or Path(rel).name in _IGNORED_NAMES:
            continue
        out.add(rel)
    return out


def provenance(vault: Path, repo_root: Path = REPO_ROOT, fresh: bool = False) -> tuple:
    """Compare a vault's content against plugin/template/ (+ fixtures/) it was built from.

    Why this is not optional: cross-validating base:query against basesim.py on
    a *hand-tested* vault reports phantom regressions. The first run of this
    harness flagged Meetings/Triage as 6 rows against basesim's 4 — and both
    were right, because two meetings created during manual testing existed only
    in that vault. A dirty vault must skip the comparison, not fail it.

    Returns (extra, missing) — either non-empty means "not pristine".
    """
    sources = [repo_root / "plugin" / "template"]
    if not fresh:
        sources.append(repo_root / "fixtures" / "demo-vault")
    expected = set()
    for src in sources:
        if src.is_dir():
            expected |= _inventory(src)
    actual = _inventory(vault)
    return actual - expected, expected - actual


# --------------------------------------------------------------------- surfaces

def _yaml_load(text: str):
    """Reuse basesim's loader: it already drops YAML-1.1 sexagesimal ints, which
    Obsidian's js-yaml also drops. A second, subtly different parser here would
    be a bug generator."""
    from basesim import _yaml_load as loader  # noqa: PLC0415 - keeps import local
    return loader(text)


def base_views(base_file: Path) -> list:
    """View names declared in a .base file, in declaration order."""
    data = _yaml_load(base_file.read_text()) or {}
    return [v.get("name") for v in (data.get("views") or []) if v.get("name")]


def declared_display_names(base_file: Path) -> dict:
    """The properties: block's displayName map, keyed as written.

    Obsidian 1.13 resolves note properties under a `note.` namespace, so a
    bare `date:` key here never matches the rendered column and the header
    falls back to the raw property name. Returned unnormalised on purpose —
    the caller compares against what actually rendered.
    """
    data = _yaml_load(base_file.read_text()) or {}
    out = {}
    for key, spec in (data.get("properties") or {}).items():
        if isinstance(spec, dict) and "displayName" in spec:
            out[key] = spec["displayName"]
    return out


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def surfaces(vault: Path) -> list:
    """Every screen worth capturing, discovered from the vault rather than listed.

    Discovery over a hardcoded list so a new .base file or a renamed fixture is
    covered without editing this module.
    """
    found = []
    for base in sorted(vault.rglob("*.base")):
        rel = base.relative_to(vault).as_posix()
        for view in base_views(base) or [None]:
            key = f"base-{_slug(base.stem)}-{_slug(view or 'default')}"
            found.append({"key": key, "kind": "base", "path": rel, "view": view})

    def add_note(pattern: str, kind: str, mode: str, limit: int = 1):
        hits = sorted(vault.glob(pattern))[:limit]
        for p in hits:
            rel = p.relative_to(vault).as_posix()
            found.append({"key": f"{kind}-{_slug(p.parent.name or p.stem)}-{mode}",
                          "kind": "note", "path": rel, "mode": mode})

    # The first thing a client sees. Shipping the navigator's config is not
    # enough — without a workspace.json the sidebar opens on Obsidian's default
    # file-explorer and every configured Shortcut is invisible, which is exactly
    # how that shipped unnoticed.
    add_note("Start here.md", "firstrun", "preview")

    # A project index renders Dataview tables; an entity dossier is the body
    # layout that #60 item 5 is about.
    add_note("30-projects/*/index.md", "project", "preview", limit=2)
    add_note("40-entities/*/dossier.md", "entity", "preview")
    # The daily note goes in Live Preview specifically: that is where the
    # <!-- evening-sync:* --> markers show and where the vault owner actually
    # types.
    for p in sorted(vault.glob("60-daily-notes/*.md")):
        if "evening-sync" in p.read_text(errors="ignore"):
            found.append({"key": f"daily-{p.stem}-livepreview", "kind": "note",
                          "path": p.relative_to(vault).as_posix(), "mode": "source"})
            break
    return found


# ----------------------------------------------------------------- driving the app

def focus_window(**kw) -> None:
    """Un-cloak, raise and focus the probe window. Opt-in via --foreground.

    Kept as the fallback if cloaked capture ever stops working: a window
    Chromium stops compositing hands back the last painted frame, and that
    once produced a screenshot of an empty "New tab" while the app genuinely
    had a Bases view active — confidently wrong evidence, worse than none.
    """
    eval_js("try{require('electron').remote.BrowserWindow.getAllWindows()"
            ".forEach(w=>{w.setOpacity(1);w.setIgnoreMouseEvents(false);w.show()})}catch(e){};"
            "window.focus(); 'ok'", **kw)


def cloak_window(**kw) -> None:
    """Make the probe window invisible where it stands: opacity 0, clicks
    pass through, keyboard focus surrendered. The user sees and feels
    nothing, while Chromium still treats the window as a plain visible
    window and keeps compositing it — so captures stay fresh.

    Every simpler shape failed, each verified live before landing here:
    - blur() drops key focus but macOS never reorders a window on blur, so
      the probe stayed top-of-stack covering the display (the original
      complaint).
    - hide() stops compositing regardless of BACKGROUND_FLAGS: captures of
      a window hidden since boot time out at 20s ("wedged"), and captures
      of a window hidden after painting return byte-identical stale frames
      for every surface. app.dock.hide() wedges captures the same way.
    - setPosition() off-screen gets clamped back onto a display — Electron
      re-anchors the window at (0, menubar) and it covers the screen again.

    All windows, not getCurrentWindow(): a probe profile that restored more
    than one vault window would otherwise leave one visible.
    """
    eval_js("try{require('electron').remote.BrowserWindow.getAllWindows()"
            ".forEach(w=>{w.setOpacity(0);w.setIgnoreMouseEvents(true);w.blur()})}catch(e){};"
            " 'ok'", **kw)


def capture_png(path, **kw) -> None:
    """Capture the current frame over CDP rather than `dev:screenshot`.

    Two reasons, both observed: dev:screenshot focuses the app on every
    capture — a 17-surface tour is 17 focus steals — and it cannot capture
    a window that is not composited normally (hidden: 20s timeout per
    frame). Page.captureScreenshot does neither: no focus change, and
    under the opacity-0 cloak it returns fresh, fully rendered frames.
    """
    out = cli(["dev:cdp", "method=Page.captureScreenshot",
               'params={"format":"png"}'], timeout=30, **kw)
    try:
        data = json.loads(out)["data"]
    except (ValueError, KeyError) as exc:
        raise ProbeError(f"unparseable CDP screenshot reply: {out[:200]}") from exc
    Path(path).write_bytes(base64.b64decode(data))


def set_window_size(width: int = WINDOW_W, height: int = WINDOW_H, **kw) -> None:
    """Pin the window size so column capture is reproducible (Bases virtualises
    columns by available width)."""
    eval_js(f"try{{require('electron').remote.getCurrentWindow().setSize({width},{height})}}"
            f"catch(e){{}}; 'ok'", **kw)


def open_surface(surface: dict, **kw) -> None:
    cli(["open", f"path={surface['path']}"], **kw)
    time.sleep(1.0)
    if surface["kind"] == "base" and surface.get("view"):
        view = surface["view"].replace("'", "\\'")
        eval_js(f"app.workspace.activeLeaf.view.controller.selectView('{view}'); 'ok'", **kw)
    elif surface["kind"] == "note":
        mode = surface.get("mode", "preview")
        eval_js(f"app.workspace.activeLeaf.view.setState({{mode:'{mode}'}},{{}}); 'ok'", **kw)
    time.sleep(1.0)
    if FOREGROUND:
        focus_window(**kw)
    time.sleep(0.8)


def capture_dom(surface: dict, **kw) -> dict:
    """Everything assertable about the current screen, in one payload."""
    if surface["kind"] == "base":
        js = ("(() => {const q=s=>[...document.querySelectorAll(s)];"
              "const err=document.querySelector('.bases-error');"
              "return JSON.stringify({"
              "headers:q('.bases-table-header-name').map(e=>e.innerText),"
              "rows:q('.bases-tbody .bases-tr').length,"
              "resultCount:(document.querySelector('.bases-toolbar-result-count')||{}).innerText||null,"
              "errorVisible:!!(err && getComputedStyle(err).display!=='none' && err.innerText.trim()),"
              "errorText:err?err.innerText.trim():''"
              "})})()")
    else:
        js = ("(() => {const q=s=>[...document.querySelectorAll(s)];"
              "const markers=q('.cm-comment').filter(e=>e.textContent.includes('evening-sync'));"
              "const markerLines=q('.cm-line:has(> .cm-comment:only-child)');"
              "return JSON.stringify({"
              "dataviewTables:q('.block-language-dataview table').length,"
              "dataviewErrors:q('.block-language-dataview .dataview-error').length,"
              # Row counts, not just table counts: Dataview renders a table
              # element for a query that matches nothing, so "a table rendered"
              # passes for the empty-table-in-front-of-a-client failure.
              "dataviewRows:q('.block-language-dataview table')"
              ".map(t=>t.querySelectorAll('tbody tr').length),"
              "markerNodes:markers.length,"
              "markerLines:markerLines.length,"
              # [].every() is vacuously true, so a note with no markers must
              # report null rather than "hidden" or the check passes for free.
              "markerLinesHidden:markerLines.length?markerLines.every(e=>getComputedStyle(e).display==='none'):null,"
              "headings:[...new Set(q('.markdown-preview-view h2, .cm-header-2')"
              ".map(e=>e.innerText.trim()))].slice(0,8)"
              "})})()")
    raw = eval_js(js, **kw)
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {"_unparsed": raw}


def query_base(surface: dict, **kw) -> list:
    """Row paths straight from the real Bases engine — the cross-check basesim's
    FIDELITY RULE has been asking for since it was written."""
    args = ["base:query", f"path={surface['path']}", "format=paths"]
    if surface.get("view"):
        args.append(f"view={surface['view']}")
    out = cli(args, **kw)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


# ------------------------------------------------------------------- subcommands

def _instance_kw(args) -> dict:
    return {} if args.shared else {"home": Path(args.home)}


def cmd_doctor(args) -> int:
    problems = []
    notes = []

    if sys.platform != "darwin":
        notes.append(
            f"platform is {sys.platform!r}. Only macOS is verified. The CLI binds a "
            "unix socket at $HOME/.obsidian-cli.sock on macOS; Windows almost "
            "certainly uses a named pipe and resolves USERPROFILE, not HOME — "
            "untested. Please report what you find (docs/visual-verification.md).")

    if not OBSIDIAN_APP.exists():
        problems.append(f"Obsidian not found at {OBSIDIAN_APP}")
    if not OBSIDIAN_CLI.exists():
        problems.append(f"Obsidian CLI not found at {OBSIDIAN_CLI} (needs Obsidian >= 1.10)")

    if args.shared:
        notes.append("--shared: driving your own Obsidian instance. The guard still "
                     "applies, but screenshots capture your window and navigation "
                     "moves your session.")
    else:
        home = Path(args.home)
        notes.append(f"probe home: {home}")
        held = read_lock(home)
        if held and pid_alive(held.get("pid", -1)):
            notes.append(f"lock: LIVE pid={held.get('pid')} "
                         f"vault={held.get('vault')} ts={held.get('ts')}")
        elif held:
            notes.append(f"lock: stale pid={held.get('pid')} "
                         f"vault={held.get('vault')} ts={held.get('ts')}")
        else:
            notes.append("lock: none held")
        try:
            check_socket_path(home)
        except ProbeError as exc:
            problems.append(str(exc))
        if not socket_path(home).exists():
            problems.append(
                f"no probe instance listening at {socket_path(home)}\n"
                f"  Fix: python scripts/obsidian_probe.py up --vault <test vault>")

    kw = _instance_kw(args)
    if not problems:
        try:
            vaults = cli(["vaults"], **kw)
            notes.append("instance reachable; vaults known to it: " +
                         (", ".join(vaults.split()) or "(none yet)"))
        except ProbeError as exc:
            problems.append(str(exc))

    if not problems:
        try:
            base = guard(**kw)
            notes.append(f"open vault: {base}")
            extra, missing = provenance(base)
            if extra or missing:
                notes.append(
                    f"vault is NOT pristine ({len(extra)} extra, {len(missing)} missing "
                    "vs plugin/template/ + fixtures/). Rendering checks still run; the "
                    "basesim cross-check will skip.")
            else:
                notes.append("vault is pristine — full cross-validation available.")
        except ProbeError as exc:
            problems.append(str(exc))

    for n in notes:
        print(f"  ok  {n}")
    for p in problems:
        print(f"FAIL  {p}", file=sys.stderr)
    return 1 if problems else 0


def cmd_up(args) -> int:
    vault = Path(args.vault).resolve()
    if not vault.is_dir():
        raise ProbeError(f"no such vault directory: {vault}")
    if not under_test_vaults(vault):
        raise ProbeError(
            f"refusing to open {vault}\n  Only vaults under a "
            f"{TEST_VAULT_DIR}/ directory may be probed.")

    if args.shared:
        # Verify, do not steer. The CLI has no "switch focused vault" command,
        # and `path=` is a vault-relative *note* path everywhere else in this
        # file — so the `open path=<vault dirname>` that used to live here could
        # never focus anything. Worse, issuing any command before resolving
        # basePath dispatches it at whatever vault happens to be focused, which
        # is exactly the drift the guard exists to stop. So resolve first and
        # refuse a mistargeted session instead of writing into it.
        base = guard()
        if base != vault:
            raise ProbeError(
                f"--shared drives whichever vault your Obsidian has focused, and that is\n"
                f"    {base}\n"
                f"  not the one you asked for:\n"
                f"    {vault}\n"
                f"  Fix: focus {vault.name!r} in Obsidian and re-run — or drop --shared "
                f"and let the probe use its own isolated instance.")
        print(f"using your own instance, driving {base}")
        return 0

    home = Path(args.home)
    check_socket_path(home)
    userdata = home / "userdata"
    fresh_profile = not userdata.exists()
    userdata.mkdir(parents=True, exist_ok=True)
    register_vault(userdata, vault)

    # Never tear down a live instance to get here — that is another
    # session's Obsidian, possibly mid-tour. Refuse on a foreign live lock,
    # break a stale one automatically, and only launch fresh once neither a
    # live lock nor a live-but-unlocked instance explains the socket.
    held = read_lock(home)
    if held and pid_alive(held.get("pid", -1)):
        if held.get("vault") != str(vault):
            raise ProbeError(
                f"probe home {home} is already driving a different vault:\n"
                f"    {held.get('vault')}\n"
                f"  (pid {held.get('pid')}, started {time.ctime(held.get('ts', 0))})\n"
                "  Refusing rather than tearing it down mid-tour -- never kill another\n"
                "  session's instance (docs/superpowers/lessons.md).\n"
                "  Fix: wait for that session's `down`, or pass a different --home.")
        # same vault, live pid: fall through; socket exists so launch is skipped
    else:
        if held:
            release_lock(home)  # stale: recorded pid is dead
        if socket_path(home).exists():
            # socket with no live lock: legacy instance or crash orphan — verify
            try:
                live_vault = resolve_vault_path(home=home)
            except ProbeError:
                live_vault = None
            if live_vault == vault:
                write_lock(home, vault, pid=None)  # adopt; pid unknown, still tracked
            elif live_vault is not None:
                raise ProbeError(
                    f"probe home {home} has a running instance with no lock on "
                    f"record, and it is driving {live_vault}, not the requested "
                    f"{vault}.\n  Refusing to guess. Fix: "
                    f"`python scripts/obsidian_probe.py --home {home} down`, then retry.")
            else:
                try:
                    socket_path(home).unlink()  # dead/wedged; let launch fire
                except OSError:
                    pass

    if not socket_path(home).exists():
        env = dict(os.environ, HOME=str(home))
        # --user-data-dir is what actually defeats Electron's single-instance
        # lock (HOME alone does not: the second launch hands off and exits).
        # HOME is what moves the CLI socket, so both are required.
        # --use-mock-keychain: Chromium's safeStorage resolves the login keychain
        # from $HOME/Library/Keychains, which an overridden HOME does not have, so
        # the probe instance otherwise opens a macOS "Keychain Not Found" dialog
        # offering to reset the default keychain — and any modal wedges the CLI
        # socket. The probe never signs in to anything, so an in-memory keychain
        # costs nothing and leaves the real one untouched.
        proc = subprocess.Popen([str(OBSIDIAN_BIN), f"--user-data-dir={userdata}",
                                 "--use-mock-keychain", *BACKGROUND_FLAGS],
                                env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        # Recorded before the poll below, not after: a second `up` racing this
        # one during boot must see a live lock, not an empty window.
        write_lock(home, vault, proc.pid)
        for _ in range(40):
            time.sleep(0.5)
            if socket_path(home).exists():
                break
        else:
            raise ProbeError(
                f"probe instance never bound {socket_path(home)} within 20s.\n"
                "  If the probe window is showing 'trust author and enable plugins', "
                "accept it — turning off Restricted Mode is the one step that cannot "
                "ship as files. Thanks to the fixed vault id it is asked once per "
                "profile, not once per vault.")

    wait_ready(home=home)
    base = guard(home=home)
    set_window_size(args.width, args.height, home=home)
    if FOREGROUND:
        focus_window(home=home)
    else:
        cloak_window(home=home)
    print(f"probe instance driving {base}")
    if fresh_profile:
        print(
            f"fresh probe profile at {home} -- if this vault carries community "
            "plugins, accept the one-time 'trust author and enable plugins' "
            "dialog in the probe window (per-profile, not global -- a new "
            "worktree costs one click).")
    return 0


def cmd_tour(args) -> int:
    kw = _instance_kw(args)
    vault = guard(**kw)
    if not args.shared:
        home = Path(args.home)
        held = read_lock(home)
        if held and held.get("vault") not in (None, str(vault)):
            raise ProbeError(
                f"lock at {home} records vault {held['vault']!r} but the live "
                f"instance answered for {vault}. Another session may have taken "
                "over this home mid-run -- re-run `doctor` before trusting this capture.")
    # Re-cloak in case the window was left showing — a trust dialog just
    # accepted, or a previous --foreground run. Never for --shared: that is
    # the user's own window.
    if not args.shared and not FOREGROUND:
        cloak_window(**kw)
    # Resolved against the invocation's cwd, not the probe instance's: a
    # relative --out from a caller in a different directory (a CI-adjacent
    # wrapper, a different shell) previously landed wherever the process
    # happened to be chdir'd to, which was easy to get wrong silently.
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / "dom").mkdir(parents=True)

    set_window_size(args.width, args.height, **kw)
    cli(["dev:errors", "clear"], **kw)
    # dev:console captures nothing until the CDP debugger is attached — without
    # this the "no console errors" check silently passes on an empty buffer.
    try:
        cli(["dev:debug", "on"], **kw)
    except ProbeError:
        pass
    cli(["dev:console", "clear"], **kw)

    captured = []
    failed = []
    for s in surfaces(vault):
        open_surface(s, **kw)
        png = out / f"{s['key']}.png"
        capture_png(png, **kw)
        # capture_png is synchronous — no polling — so the file (or its
        # absence) is already final by the time we check it. A silently
        # empty or missing PNG is worse than a loud one: it looks like a
        # captured surface until someone opens the file.
        ok = png.is_file() and png.stat().st_size > 0
        payload = {"surface": s, "dom": capture_dom(s, **kw), "pngCaptured": ok}
        if s["kind"] == "base":
            payload["queryRows"] = query_base(s, **kw)
        (out / "dom" / f"{s['key']}.json").write_text(
            json.dumps(payload, indent=2) + "\n")
        if ok:
            captured.append(s["key"])
            print(f"  captured {s['key']}")
        else:
            failed.append(s["key"])
            print(f"  FAILED  {s['key']} (no screenshot written to {png})",
                  file=sys.stderr)

    (out / "summary.json").write_text(json.dumps({
        "vault": str(vault),
        "window": [args.width, args.height],
        "surfaces": captured,
        "failedSurfaces": failed,
        "errors": cli(["dev:errors"], **kw),
        "consoleErrors": cli(["dev:console", "level=error"], **kw),
    }, indent=2) + "\n")
    tail = f" ({len(failed)} FAILED: {', '.join(failed)})" if failed else ""
    print(f"\n{len(captured)} surfaces -> {out}{tail}")
    return 1 if failed else 0


def cmd_down(args) -> int:
    if args.shared:
        print("--shared: nothing to stop (your own instance left alone)")
        return 0
    home = Path(args.home)
    if not socket_path(home).exists():
        release_lock(home)  # tidy leftovers
        print("no probe instance running")
        return 0
    held = read_lock(home)
    if held:
        print(f"  stopping pid {held.get('pid')} (vault {held.get('vault')})")
    try:
        eval_js("require('electron').remote.app.quit(); 'quitting'", home=home)
    except ProbeError:
        pass
    time.sleep(2)
    release_lock(home)
    print("probe instance stopped")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--home", default=None,
                   help="probe profile dir (default: derived per-worktree under "
                        f"{DEFAULT_PROBE_HOME.parent}, so concurrent checkouts don't "
                        "fight over one instance -- `doctor` prints the resolved "
                        "path); pass a value to force a fixed/shared profile. Keep "
                        "it short either way, macOS caps socket paths at 104 bytes")
    p.add_argument("--shared", action="store_true",
                   help="drive your own Obsidian instead of an isolated one "
                        "(the guard still applies)")
    p.add_argument("--foreground", action="store_true",
                   help="keep the probe window visible and raise it before each "
                        "capture (default hides the window entirely once the "
                        "instance is ready; use this only if captures come back "
                        "stale)")
    p.add_argument("--width", type=int, default=WINDOW_W)
    p.add_argument("--height", type=int, default=WINDOW_H)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check prerequisites and report each gap's fix")
    up = sub.add_parser("up", help="launch the probe instance and open a test vault")
    up.add_argument("--vault", required=True)
    tour = sub.add_parser("tour", help="capture every surface to --out")
    tour.add_argument("--out", default=str(REPO_ROOT / ".obsidian-probe-out"))
    sub.add_parser("down", help="stop the probe instance")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    resolve_home(args)
    global FOREGROUND
    FOREGROUND = bool(getattr(args, "foreground", False))
    handler = {"doctor": cmd_doctor, "up": cmd_up, "tour": cmd_tour,
               "down": cmd_down}[args.cmd]
    try:
        return handler(args)
    except ProbeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
