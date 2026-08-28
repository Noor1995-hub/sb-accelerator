"""Unit tests for the probe wrapper, with the CLI seam stubbed.

No Obsidian required, so these run in CI — unlike test_obsidian_render.py,
which asserts on a captured tour. What they cover is the part that most needs
covering: the guard. It is the only thing standing between a mistargeted
`vault=` and someone's real notes, and a code review caught it not holding on
`up --shared` (the one path aimed at the user's own app) precisely because
nothing here exercised it.
"""
import json
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

import obsidian_probe as probe


@pytest.fixture
def vault(tmp_path):
    """A directory that satisfies the argument-level check."""
    v = tmp_path / "test-vaults" / "demo"
    v.mkdir(parents=True)
    return v.resolve()


def stub_cli(monkeypatch, base_path):
    """Answer eval_js's CDP call with a fixed app.vault.adapter.basePath."""
    calls = []

    def fake(args, **kw):
        calls.append((list(args), kw))
        return json.dumps({"result": {"value": str(base_path)}})

    monkeypatch.setattr(probe, "cli", fake)
    return calls


def args_for(argv):
    return probe.build_parser().parse_args(argv)


# --- the guard ---------------------------------------------------------------

def test_guard_refuses_a_vault_outside_test_vaults(monkeypatch):
    stub_cli(monkeypatch, "/Users/someone/Documents/RealVault")
    with pytest.raises(probe.ProbeError, match="refusing to drive"):
        probe.guard()


def test_guard_accepts_a_test_vault(monkeypatch, vault):
    stub_cli(monkeypatch, vault)
    assert probe.guard() == vault


# --- up --shared: the path the review found unguarded ------------------------

def test_up_shared_refuses_when_the_focused_vault_is_a_real_one(monkeypatch, vault):
    """The regression test for the review finding. The --vault argument is a
    legitimate test vault, but the instance that actually answers has a real
    vault open — so this must refuse rather than issue a command into it."""
    stub_cli(monkeypatch, "/Users/someone/Documents/RealVault")
    with pytest.raises(probe.ProbeError, match="refusing to drive"):
        probe.cmd_up(args_for(["--shared", "up", "--vault", str(vault)]))


def test_up_shared_refuses_when_a_different_test_vault_is_focused(monkeypatch, vault):
    other = vault.parent / "other"
    other.mkdir()
    stub_cli(monkeypatch, other.resolve())
    with pytest.raises(probe.ProbeError, match="not the one you asked for"):
        probe.cmd_up(args_for(["--shared", "up", "--vault", str(vault)]))


def test_up_shared_issues_no_command_before_resolving_the_vault(monkeypatch, vault):
    """Ordering matters, not just the outcome: anything dispatched before the
    guard lands on whichever vault happens to be focused."""
    calls = stub_cli(monkeypatch, "/Users/someone/Documents/RealVault")
    with pytest.raises(probe.ProbeError):
        probe.cmd_up(args_for(["--shared", "up", "--vault", str(vault)]))
    assert len(calls) == 1, f"expected only the basePath probe, got {calls}"
    assert calls[0][0][0] == "dev:cdp", f"first call was not the guard: {calls[0]}"


def test_up_shared_succeeds_when_the_focused_vault_matches(monkeypatch, vault):
    stub_cli(monkeypatch, vault)
    assert probe.cmd_up(args_for(["--shared", "up", "--vault", str(vault)])) == 0


def test_up_refuses_a_vault_argument_outside_test_vaults(monkeypatch, tmp_path):
    real = tmp_path / "RealVault"
    real.mkdir()
    stub_cli(monkeypatch, real)
    with pytest.raises(probe.ProbeError, match="refusing to open"):
        probe.cmd_up(args_for(["--shared", "up", "--vault", str(real)]))


# --- staying off the user's screen -------------------------------------------

def _eval_exprs(calls):
    """The JS expressions sent through dev:cdp, in order."""
    exprs = []
    for args, _kw in calls:
        if args and args[0] == "dev:cdp":
            for a in args:
                if a.startswith("params="):
                    exprs.append(json.loads(a[len("params="):])["expression"])
    return exprs


def _up_against_running_instance(monkeypatch, tmp_path, vault, extra=()):
    """Run a non-shared `up` against a stubbed already-running instance."""
    home = tmp_path / "probe-home"
    home.mkdir()
    monkeypatch.setattr(probe, "check_socket_path", lambda h: None)
    probe.socket_path(home).write_text("")  # exists() is all cmd_up checks
    calls = stub_cli(monkeypatch, vault)
    argv = ["--home", str(home), *extra, "up", "--vault", str(vault)]
    assert probe.cmd_up(args_for(argv)) == 0
    return calls


def test_up_cloaks_the_window_rather_than_blurring_it(monkeypatch, tmp_path, vault):
    """The regression test for the foreground complaint. blur() drops key
    focus but macOS never reorders a window on blur, so the probe stayed
    top-of-stack covering the display. Background means invisible —
    opacity 0, clicks passing through."""
    calls = _up_against_running_instance(monkeypatch, tmp_path, vault)
    exprs = _eval_exprs(calls)
    assert any("setOpacity(0)" in e for e in exprs), f"no cloak issued: {exprs}"
    assert not any("window.focus()" in e for e in exprs)


def test_up_foreground_shows_instead_of_cloaking(monkeypatch, tmp_path, vault):
    monkeypatch.setattr(probe, "FOREGROUND", True)
    calls = _up_against_running_instance(monkeypatch, tmp_path, vault)
    exprs = _eval_exprs(calls)
    assert any("window.focus()" in e for e in exprs)
    assert not any("setOpacity(0)" in e for e in exprs)


def test_up_shared_never_cloaks_the_users_own_window(monkeypatch, vault):
    """--shared drives the user's real Obsidian; making their window
    invisible is never acceptable, backgrounded run or not."""
    calls = stub_cli(monkeypatch, vault)
    assert probe.cmd_up(args_for(["--shared", "up", "--vault", str(vault)])) == 0
    assert not any("setOpacity(0)" in e for e in _eval_exprs(calls))


# --- socket path length (macOS sun_path cap) --------------------------------

def test_check_socket_path_rejects_a_deep_home(tmp_path):
    deep = tmp_path.joinpath(*(["averylongdirectorysegment"] * 8))
    with pytest.raises(probe.ProbeError, match="too deep"):
        probe.check_socket_path(deep)


def test_check_socket_path_accepts_the_default():
    probe.check_socket_path(probe.DEFAULT_PROBE_HOME)


# --- provenance -------------------------------------------------------------

def test_provenance_flags_a_dirty_vault(tmp_path):
    from make_test_vault import build_vault
    v = tmp_path / "v"
    build_vault(v, probe.REPO_ROOT, fresh=False)
    assert probe.provenance(v) == (set(), set())
    (v / "20-meetings" / "hand-written.md").write_text("---\ntype: meeting\n---\n")
    extra, missing = probe.provenance(v)
    assert "20-meetings/hand-written.md" in extra and not missing


# --- .base parsing ----------------------------------------------------------

def test_base_views_reads_the_shipped_files():
    meetings = probe.REPO_ROOT / "plugin" / "template" / "20-meetings" / "Meetings.base"
    assert probe.base_views(meetings) == ["Triage", "All Meetings"]


def test_declared_display_names_are_namespaced_in_every_shipped_base():
    """Mirrors the template test, from the probe's own parser."""
    for base in sorted((probe.REPO_ROOT / "plugin" / "template").rglob("*.base")):
        for key in probe.declared_display_names(base):
            assert key.startswith(("note.", "file.", "formula.")), (
                f"{base.name}: {key!r} is not namespaced, so its displayName is ignored")


# --- the guard's path matching, asserted for both platforms from either -------

@pytest.mark.parametrize("flavour", [PurePosixPath, PureWindowsPath])
def test_under_test_vaults_accepts_a_test_vault_on_either_platform(flavour):
    """Runs the Windows case on macOS and vice versa.

    The first implementation matched the substring "/test-vaults/", which never
    matched a backslash-separated Windows path — so the guard refused every
    vault there. Only CI's Windows job caught it, which is too late and too
    narrow a net for the one check protecting someone's real notes."""
    root = "C:/work" if flavour is PureWindowsPath else "/home/work"
    assert probe.under_test_vaults(flavour(f"{root}/test-vaults/demo"))
    assert probe.under_test_vaults(flavour(f"{root}/test-vaults/demo/nested"))


@pytest.mark.parametrize("flavour", [PurePosixPath, PureWindowsPath])
def test_under_test_vaults_rejects_lookalikes(flavour):
    root = "C:/work" if flavour is PureWindowsPath else "/home/work"
    assert not probe.under_test_vaults(flavour(f"{root}/Documents/RealVault"))
    # Component matching, so a name that merely contains the marker is not one.
    assert not probe.under_test_vaults(flavour(f"{root}/my-test-vaults-backup/demo"))
