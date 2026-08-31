"""Unit tests for the probe wrapper, with the CLI seam stubbed.

No Obsidian required, so these run in CI — unlike test_obsidian_render.py,
which asserts on a captured tour. What they cover is the part that most needs
covering: the guard. It is the only thing standing between a mistargeted
`vault=` and someone's real notes, and a code review caught it not holding on
`up --shared` (the one path aimed at the user's own app) precisely because
nothing here exercised it.
"""
import base64
import json
import os
import subprocess
import sys
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


def stub_cli_for_tour(monkeypatch):
    """A cli() stub broad enough to carry a full cmd_tour pass: a real (tiny,
    fake) screenshot payload for Page.captureScreenshot, an inert value for
    Runtime.evaluate, and an empty string for everything else (dev:errors,
    dev:console, open, base:query, ...) — none of which cmd_tour inspects
    beyond storing verbatim."""
    calls = []

    def fake(args, **kw):
        calls.append((list(args), kw))
        joined = " ".join(args)
        if "Page.captureScreenshot" in joined:
            return json.dumps({"data": base64.b64encode(b"fakepng").decode()})
        if "Runtime.evaluate" in joined:
            return json.dumps({"result": {"value": "ok"}})
        return ""

    monkeypatch.setattr(probe, "cli", fake)
    return calls


def args_for(argv):
    """Build args the way main() would: parse, then fill in the derived
    --home default when one was not given explicitly."""
    args = probe.build_parser().parse_args(argv)
    probe.resolve_home(args)
    return args


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


# --- home derivation (#75: single-tenancy) -----------------------------------

def test_derive_probe_home_is_deterministic_for_the_same_repo_root():
    root = Path("/some/fixed/repo/root")
    assert probe.derive_probe_home(root) == probe.derive_probe_home(root)


def test_derive_probe_home_differs_for_different_repo_roots():
    one = probe.derive_probe_home(Path("/repo/checkout-one"))
    two = probe.derive_probe_home(Path("/repo/checkout-two"))
    assert one != two


def test_derive_probe_home_stays_under_the_socket_budget():
    """Hashed, not the literal path, embedded — so a shallow and a very deep
    repo root produce a socket path of the same length."""
    shallow = Path("/r")
    deep = Path("/very/deeply/nested/worktree/checkout/path/used/for/testing")
    shallow_len = len(str(probe.socket_path(probe.derive_probe_home(shallow))).encode())
    deep_len = len(str(probe.socket_path(probe.derive_probe_home(deep))).encode())
    assert shallow_len == deep_len


def test_resolve_home_fills_in_the_derived_default():
    args = probe.build_parser().parse_args(["doctor"])
    assert args.home is None
    probe.resolve_home(args)
    assert args.home == str(probe.derive_probe_home())


def test_resolve_home_keeps_an_explicit_override(tmp_path):
    args = probe.build_parser().parse_args(["--home", str(tmp_path), "doctor"])
    probe.resolve_home(args)
    assert args.home == str(tmp_path)


# --- lock primitives (#75) ----------------------------------------------------

def test_read_lock_returns_none_when_absent(tmp_path):
    assert probe.read_lock(tmp_path) is None


def test_write_lock_then_read_lock_round_trips(tmp_path):
    probe.write_lock(tmp_path, "/some/vault", 4242)
    held = probe.read_lock(tmp_path)
    assert held["pid"] == 4242
    assert held["vault"] == "/some/vault"
    assert "ts" in held


def test_pid_alive_true_for_self():
    assert probe.pid_alive(os.getpid())


def test_pid_alive_false_for_a_dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert not probe.pid_alive(proc.pid)


def test_release_lock_removes_the_file_and_is_idempotent(tmp_path):
    probe.write_lock(tmp_path, "/some/vault", 4242)
    probe.release_lock(tmp_path)
    assert probe.read_lock(tmp_path) is None
    probe.release_lock(tmp_path)  # no error the second time, nothing to remove


# --- cmd_up concurrency (#75) --------------------------------------------------

def test_up_refuses_when_another_live_pid_holds_the_lock_for_a_different_vault(
        monkeypatch, tmp_path, vault):
    home = tmp_path / "probe-home"
    home.mkdir()
    monkeypatch.setattr(probe, "check_socket_path", lambda h: None)
    other_vault = tmp_path / "test-vaults" / "other"
    probe.write_lock(home, other_vault, os.getpid())  # self: definitely alive
    argv = ["--home", str(home), "up", "--vault", str(vault)]
    with pytest.raises(probe.ProbeError, match="already driving"):
        probe.cmd_up(args_for(argv))


def test_up_reuses_when_the_lock_matches_the_same_live_vault(monkeypatch, tmp_path, vault):
    home = tmp_path / "probe-home"
    home.mkdir()
    monkeypatch.setattr(probe, "check_socket_path", lambda h: None)
    probe.socket_path(home).write_text("")
    probe.write_lock(home, vault, os.getpid())
    stub_cli(monkeypatch, vault)

    def boom(*a, **kw):
        raise AssertionError("Popen must not run when a live lock is reused")
    monkeypatch.setattr(probe.subprocess, "Popen", boom)

    argv = ["--home", str(home), "up", "--vault", str(vault)]
    assert probe.cmd_up(args_for(argv)) == 0


def test_up_breaks_a_stale_lock_and_launches_fresh(monkeypatch, tmp_path, vault):
    home = tmp_path / "probe-home"
    home.mkdir()
    monkeypatch.setattr(probe, "check_socket_path", lambda h: None)
    # A genuinely dead pid, not a monkeypatched one — spawn and wait it out.
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    probe.write_lock(home, vault, dead.pid)
    stub_cli(monkeypatch, vault)

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kw):
        probe.socket_path(home).write_text("")  # simulate the instance binding
        return FakeProc()
    monkeypatch.setattr(probe.subprocess, "Popen", fake_popen)

    argv = ["--home", str(home), "up", "--vault", str(vault)]
    assert probe.cmd_up(args_for(argv)) == 0
    held = probe.read_lock(home)
    assert held["pid"] == 4242


def test_up_adopts_an_unlocked_running_instance_when_vault_matches(monkeypatch, tmp_path, vault):
    home = tmp_path / "probe-home"
    home.mkdir()
    monkeypatch.setattr(probe, "check_socket_path", lambda h: None)
    probe.socket_path(home).write_text("")  # running, but no lock on record
    stub_cli(monkeypatch, vault)  # the live instance answers for our vault

    argv = ["--home", str(home), "up", "--vault", str(vault)]
    assert probe.cmd_up(args_for(argv)) == 0
    held = probe.read_lock(home)
    assert held is not None and held["vault"] == str(vault)


def test_up_refuses_an_unlocked_running_instance_with_a_different_vault(
        monkeypatch, tmp_path, vault):
    home = tmp_path / "probe-home"
    home.mkdir()
    monkeypatch.setattr(probe, "check_socket_path", lambda h: None)
    probe.socket_path(home).write_text("")
    other = tmp_path / "test-vaults" / "other"
    other.mkdir(parents=True)
    calls = stub_cli(monkeypatch, other.resolve())  # answers a different vault

    argv = ["--home", str(home), "up", "--vault", str(vault)]
    with pytest.raises(probe.ProbeError, match="Refusing to guess"):
        probe.cmd_up(args_for(argv))
    assert not any("quit" in e for e in _eval_exprs(calls)), \
        "must never tear down an instance it did not launch and cannot identify"


def test_up_warns_before_unlinking_a_socket_that_is_not_answering(
        monkeypatch, tmp_path, vault, capsys):
    """The regression test for review finding #3: a socket that raises on
    resolve_vault_path is not necessarily dead -- 'a modal blocks the CLI
    socket for the entire instance' (docs/visual-verification.md) describes a
    wedged-but-alive window. Unlinking to let a fresh launch through is still
    correct, but it must say so, since it makes that window unreachable via
    `down`/`doctor` afterwards."""
    home = tmp_path / "probe-home"
    home.mkdir()
    monkeypatch.setattr(probe, "check_socket_path", lambda h: None)
    probe.socket_path(home).write_text("")  # present, about to prove unresponsive

    calls = {"n": 0}

    def fake_cli(args, **kw):
        calls["n"] += 1
        if calls["n"] == 1:  # the one resolve_vault_path check against the old socket
            raise probe.ProbeError("wedged: no answer")
        return json.dumps({"result": {"value": str(vault)}})
    monkeypatch.setattr(probe, "cli", fake_cli)

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kw):
        probe.socket_path(home).write_text("")  # the fresh instance binds
        return FakeProc()
    monkeypatch.setattr(probe.subprocess, "Popen", fake_popen)

    argv = ["--home", str(home), "up", "--vault", str(vault)]
    assert probe.cmd_up(args_for(argv)) == 0

    err = capsys.readouterr().err
    assert "was not answering" in err
    assert str(home / "userdata") in err, "must name the profile so a human can find it"


def test_up_refusal_leaves_the_profile_registry_untouched(monkeypatch, tmp_path, vault):
    """Regression test for review finding #1: cmd_up used to mkdir userdata
    and register_vault -- which destructively overwrites the one fixed
    PROBE_VAULT_ID entry -- before adjudicating the lock. A refused
    `up --vault B` therefore used to leave session A's own registry pointed
    at B on its way out. Every refusal must fire before that write."""
    home = tmp_path / "probe-home"
    home.mkdir()
    userdata = home / "userdata"
    userdata.mkdir()
    registry = userdata / "obsidian.json"
    sentinel = (b'{"vaults": {"5b0000000000c1a0": {"path": "/session-a/vault", '
                b'"open": true}}, "cli": true}')
    registry.write_bytes(sentinel)

    monkeypatch.setattr(probe, "check_socket_path", lambda h: None)
    other_vault = tmp_path / "test-vaults" / "other"
    probe.write_lock(home, other_vault, os.getpid())  # self: definitely alive

    argv = ["--home", str(home), "up", "--vault", str(vault)]
    with pytest.raises(probe.ProbeError, match="already driving"):
        probe.cmd_up(args_for(argv))

    assert registry.read_bytes() == sentinel, \
        "a refused up must not touch the other session's registry"


def test_up_refuses_a_foreign_vault_against_an_adopted_lock(monkeypatch, tmp_path, vault):
    """Regression test for review finding #2: a pid-less adopted lock must
    still be treated as live while its socket answers, or a foreign-vault
    `up` demotes it back to "unidentified socket" instead of refusing."""
    home = tmp_path / "probe-home"
    home.mkdir()
    monkeypatch.setattr(probe, "check_socket_path", lambda h: None)
    probe.socket_path(home).write_text("")
    probe.write_lock(home, vault, pid=None)  # adopted, as cmd_up itself writes it

    other = tmp_path / "test-vaults" / "other"
    other.mkdir(parents=True)
    argv = ["--home", str(home), "up", "--vault", str(other.resolve())]
    with pytest.raises(probe.ProbeError, match="already driving"):
        probe.cmd_up(args_for(argv))


def test_doctor_reports_an_adopted_live_lock_as_live_not_stale(
        monkeypatch, tmp_path, vault, capsys):
    """The other half of finding #2: doctor must not call a live adopted
    instance stale just because its lock has no pid on record."""
    home = tmp_path / "probe-home"
    home.mkdir()
    monkeypatch.setattr(probe, "check_socket_path", lambda h: None)
    probe.socket_path(home).write_text("")
    probe.write_lock(home, vault, pid=None)  # adopted
    stub_cli(monkeypatch, vault)  # so doctor's follow-up checks stay offline

    probe.cmd_doctor(args_for(["--home", str(home), "doctor"]))

    out = capsys.readouterr().out
    assert "lock: LIVE" in out
    assert "lock: stale" not in out


def test_doctor_reports_a_pidless_lock_as_stale_once_its_socket_is_gone(
        monkeypatch, tmp_path, vault, capsys):
    """The pid-less-is-live exception is narrow: once the socket it was
    adopted against is gone too, it must revert to an ordinary stale lock,
    not stay live forever."""
    home = tmp_path / "probe-home"
    home.mkdir()
    monkeypatch.setattr(probe, "check_socket_path", lambda h: None)
    probe.write_lock(home, vault, pid=None)  # adopted, but no socket present

    probe.cmd_doctor(args_for(["--home", str(home), "doctor"]))

    out = capsys.readouterr().out
    assert "lock: stale" in out
    assert "lock: LIVE" not in out


# --- cmd_tour (#67: tour output reliability, plus the #75 lock cross-check) ---

def test_tour_resolves_a_relative_out_to_the_invocation_cwd(monkeypatch, tmp_path, vault):
    monkeypatch.setattr(probe, "guard", lambda **kw: vault)
    monkeypatch.setattr(probe, "surfaces",
                        lambda v: [{"key": "surf1", "kind": "note",
                                    "path": "Start here.md", "mode": "preview"}])
    monkeypatch.setattr(probe.time, "sleep", lambda s: None)
    stub_cli_for_tour(monkeypatch)

    monkeypatch.chdir(tmp_path)
    argv = ["--home", str(tmp_path / "probe-home"), "tour", "--out", "relout"]
    probe.cmd_tour(args_for(argv))

    assert (tmp_path / "relout" / "summary.json").is_file(), \
        "a relative --out must resolve against the invocation's cwd"


def test_tour_reports_a_missing_png_as_a_failure_not_captured(monkeypatch, tmp_path, vault, capsys):
    monkeypatch.setattr(probe, "guard", lambda **kw: vault)
    monkeypatch.setattr(probe, "surfaces",
                        lambda v: [{"key": "surf1", "kind": "note",
                                    "path": "Start here.md", "mode": "preview"}])
    monkeypatch.setattr(probe.time, "sleep", lambda s: None)
    stub_cli_for_tour(monkeypatch)
    monkeypatch.setattr(probe, "capture_png", lambda path, **kw: None)  # no file written

    out = tmp_path / "out"
    argv = ["--home", str(tmp_path / "probe-home"), "tour", "--out", str(out)]
    rc = probe.cmd_tour(args_for(argv))

    assert rc == 1
    summary = json.loads((out / "summary.json").read_text())
    assert summary["failedSurfaces"] == ["surf1"]
    assert "surf1" not in summary["surfaces"]
    assert json.loads((out / "dom" / "surf1.json").read_text())["pngCaptured"] is False
    err = capsys.readouterr().err
    assert "FAILED" in err and "surf1" in err


def test_tour_reports_success_when_the_png_is_written(monkeypatch, tmp_path, vault):
    monkeypatch.setattr(probe, "guard", lambda **kw: vault)
    monkeypatch.setattr(probe, "surfaces",
                        lambda v: [{"key": "surf1", "kind": "note",
                                    "path": "Start here.md", "mode": "preview"}])
    monkeypatch.setattr(probe.time, "sleep", lambda s: None)
    stub_cli_for_tour(monkeypatch)
    monkeypatch.setattr(probe, "capture_png",
                        lambda path, **kw: Path(path).write_bytes(b"x"))

    out = tmp_path / "out"
    argv = ["--home", str(tmp_path / "probe-home"), "tour", "--out", str(out)]
    rc = probe.cmd_tour(args_for(argv))

    assert rc == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["surfaces"] == ["surf1"]
    assert summary["failedSurfaces"] == []


def test_tour_refuses_on_a_lock_vault_mismatch(monkeypatch, tmp_path, vault):
    home = tmp_path / "probe-home"
    home.mkdir()
    other_vault = tmp_path / "test-vaults" / "other"
    probe.write_lock(home, other_vault, os.getpid())
    monkeypatch.setattr(probe, "guard", lambda **kw: vault)
    surfaces_called = []
    monkeypatch.setattr(probe, "surfaces", lambda v: surfaces_called.append(v) or [])

    argv = ["--home", str(home), "tour", "--out", str(tmp_path / "out")]
    with pytest.raises(probe.ProbeError, match="Another session"):
        probe.cmd_tour(args_for(argv))
    assert not surfaces_called, "must refuse before touching any surface"
