"""Guards for shipped .obsidian configuration in the template.

The Notebook Navigator settings file references template paths (shortcuts)
— these tests keep it honest when folders or .base files get renamed."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "plugin" / "template"
NN_DATA = TEMPLATE / ".obsidian" / "plugins" / "notebook-navigator" / "data.json"
MINIMAL_DATA = TEMPLATE / ".obsidian" / "plugins" / "obsidian-minimal-settings" / "data.json"
APPEARANCE = TEMPLATE / ".obsidian" / "appearance.json"
SNIPPET = TEMPLATE / ".obsidian" / "snippets" / "sb-accelerator.css"
WORKSPACE = TEMPLATE / ".obsidian" / "workspace.json"
CONFIG = TEMPLATE / "99-workflow-config" / "config.json"

EXPECTED_SHORTCUTS = [
    # The orientation note pins first: a fresh vault otherwise opens to an empty
    # "New tab" with nothing telling the vault owner how any of it works (#60 item 6).
    ("note", "Start here.md"),
    ("note", "20-meetings/Meetings.base"),
    ("note", "30-projects/Projects.base"),
    # Decisions sit under Projects: they are project objects, and the two
    # tables are read together at a tune-up.
    ("note", "30-projects/Decisions.base"),
    ("note", "40-entities/Entities.base"),
    ("note", "50-people/People.base"),
    ("folder", "60-daily-notes"),
]


def load_profile() -> dict:
    data = json.loads(NN_DATA.read_text(encoding="utf-8"))
    profiles = data["vaultProfiles"]
    assert len(profiles) == 1, "template ships exactly one NN profile"
    return profiles[0]


def test_nn_data_json_parses_and_profile_selected():
    data = json.loads(NN_DATA.read_text(encoding="utf-8"))
    assert data["vaultProfile"] == data["vaultProfiles"][0]["id"]


def test_nn_shortcuts_exact_order_and_paths_exist():
    profile = load_profile()
    got = [(s["type"], s["path"]) for s in profile["shortcuts"]]
    assert got == EXPECTED_SHORTCUTS, f"shortcut list drifted: {got}"
    for kind, path in got:
        target = TEMPLATE / path
        if kind == "folder":
            assert target.is_dir(), f"shortcut folder missing in template: {path}"
        else:
            assert target.is_file(), f"shortcut file missing in template: {path}"


def test_nn_file_visibility_is_all():
    """.base files show even under "documents"; "all" is a deliberate choice so attachments and generated deliverables are browsable too."""
    assert load_profile()["fileVisibility"] == "all"


def test_nn_folder_appearances_claude_skills_path_exists():
    data = json.loads(NN_DATA.read_text(encoding="utf-8"))
    assert "claude/skills" in data["folderAppearances"]
    assert (TEMPLATE / "claude" / "skills").is_dir()


def test_nn_rainbow_enabled_for_folders_shortcuts_recents():
    rainbow = load_profile()["navRainbow"]
    for section in ("folders", "shortcuts", "recent"):
        assert rainbow[section]["enabled"] is True, f"navRainbow.{section} must be enabled"


# --- appearance defaults (#60 items 1-3) ------------------------------------
# These are the settings a client's vault opens with. None of them is visible
# to CI, so the probe harness verifies the *rendering*; these tests only keep
# the files present and the intent explicit. See docs/visual-verification.md.

def test_minimal_settings_ship_colourful_headings_and_reading_width():
    """Without a shipped data.json these sit at Minimal's own defaults —
    mono-coloured headings and a 40-char line width, which is what #60
    reported as 'no coloured headings' and 'page too narrow'."""
    d = json.loads(MINIMAL_DATA.read_text(encoding="utf-8"))
    assert d["colorfulHeadings"] is True
    # readableLineLength must be on or lineWidth is inert.
    assert d["readableLineLength"] is True
    assert d["lineWidth"] >= 55, f"reading width too narrow: {d['lineWidth']}"
    assert d["lineWidthWide"] >= 100


def test_css_snippet_ships_and_is_enabled():
    assert SNIPPET.is_file(), "the sb-accelerator snippet must ship with the template"
    enabled = json.loads(APPEARANCE.read_text(encoding="utf-8")).get("enabledCssSnippets", [])
    assert SNIPPET.stem in enabled, (
        f"{SNIPPET.stem} is not listed in appearance.json enabledCssSnippets — "
        "a snippet on disk but unlisted does nothing")


def test_snippet_hides_comment_only_lines_in_live_preview():
    """#60 item 3. The marker syntax is a CLI contract, so the fix is CSS. The
    selector was verified against Obsidian 1.13's DOM (dev:dom) — markers render
    as .cm-comment directly inside .cm-line."""
    css = SNIPPET.read_text(encoding="utf-8")
    assert ".cm-comment" in css and "display: none" in css


def test_snippet_collapses_properties_by_default():
    """Obsidian has no default-fold setting for properties, so the snippet
    inverts app.css's own `.metadata-container.is-collapsed .metadata-property`
    rule (verified live on 1.13.7): rows hide while the container is *not*
    `.is-collapsed`. Both halves must be present — hiding without the
    restoring rule would make the heading a dead click — and both editing
    modes must be covered, scoped to the main editor so the sidebar
    Properties pane and the Bases new-item popover stay editable."""
    css = SNIPPET.read_text(encoding="utf-8")
    for mode in (".markdown-source-view", ".markdown-preview-view"):
        # Clipped (max-height), not display:none — a display:none row cannot
        # take focus, and "Add file property" focuses the row it just added.
        assert (f".mod-root {mode} .metadata-container:not(.is-collapsed)"
                ":not(:focus-within) .metadata-properties") in css
        assert f".mod-root {mode} .metadata-container.is-collapsed .metadata-property" in css
    assert "max-height: 0" in css
    assert ".metadata-container:not(.is-collapsed) .metadata-add-button" in css
    # Collapsing writes an inline display:none on .metadata-content (JS);
    # without this override the click to expand shows nothing.
    assert ".metadata-container.is-collapsed .metadata-content" in css
    assert "display: block !important" in css
    # Every selector is scoped; an unscoped one would reach the popover.
    for line in css.splitlines():
        if ".metadata-" in line and line.startswith("."):
            assert line.startswith(".mod-root "), f"unscoped properties selector: {line}"


# --- .base property namespacing ---------------------------------------------

def test_base_property_keys_are_namespaced():
    """Obsidian resolves note properties under a `note.` namespace, so a
    `properties:` block keyed with the bare name is parsed and then ignored —
    the column header silently falls back to the raw property name. All 41
    declarations across the five .base files were inert until this was fixed;
    nothing in the repo noticed. The probe asserts the rendered result, this
    catches the cause at edit time."""
    import yaml
    offenders = {}
    for base in sorted(TEMPLATE.rglob("*.base")):
        props = (yaml.safe_load(base.read_text(encoding="utf-8")) or {}).get("properties") or {}
        bare = [k for k in props
                if not k.startswith(("note.", "file.", "formula."))]
        if bare:
            offenders[base.relative_to(TEMPLATE).as_posix()] = bare
    assert not offenders, (
        "these properties: keys need a `note.` prefix or their displayName is "
        f"silently ignored: {offenders}")


def test_every_ordered_column_has_a_display_name():
    """A prefix fix only helps a column that has a declaration at all. A column
    listed in a view's `order:` with no `properties:` entry renders its raw
    property name — `type` beside `Subject` and `✓ Reviewed`. That is the same
    defect as an inert displayName, one step earlier, and it is what promoting
    `type` to the second Triage column exposed: it was the only unlabelled
    column on the vault's busiest surface."""
    import yaml
    offenders = {}
    for base in sorted(TEMPLATE.rglob("*.base")):
        doc = yaml.safe_load(base.read_text(encoding="utf-8")) or {}
        labelled = {k.split(".", 1)[1] for k in (doc.get("properties") or {})
                    if k.startswith("note.")}
        for view in doc.get("views") or []:
            unlabelled = [col for col in view.get("order") or []
                          if not col.startswith(("file.", "formula."))
                          and col not in labelled]
            if unlabelled:
                key = f"{base.relative_to(TEMPLATE).as_posix()}:{view.get('name')}"
                offenders[key] = unlabelled
    assert not offenders, (
        "these ordered columns have no displayName, so they render their raw "
        f"property name: {offenders}")


# --- first-run layout -------------------------------------------------------

def _left_sidebar_tabs() -> dict:
    layout = json.loads(WORKSPACE.read_text(encoding="utf-8"))
    return layout["left"]["children"][0]


def test_workspace_opens_with_notebook_navigator_selected():
    """Without a shipped workspace.json a fresh vault gets Obsidian's default
    sidebar (file-explorer / search / bookmarks) and the whole Notebook
    Navigator configuration — the rainbow Shortcuts to the five Bases and the
    orientation note — is invisible on first open. The plugin's data.json
    shipping is not enough; the layout that surfaces it has to ship too.

    This was found by the probe harness. The manual check in
    docs/local-setup.md step 3 had passed, because the vault it was run against
    had accumulated a workspace.json from being clicked around in."""
    tabs = _left_sidebar_tabs()
    types = [c["state"]["type"] for c in tabs["children"]]
    assert types[0] == "notebook-navigator", f"navigator must lead the sidebar, got {types}"
    assert tabs.get("currentTab") == 0, "the navigator tab must be the selected one"


def test_workspace_opens_the_orientation_note_in_reading_view():
    layout = json.loads(WORKSPACE.read_text(encoding="utf-8"))
    state = layout["main"]["children"][0]["children"][0]["state"]["state"]
    assert state["file"] == "Start here.md"
    assert (TEMPLATE / state["file"]).is_file()
    assert state["mode"] == "preview", "the orientation note is to read, not edit"


def test_workspace_references_no_files_outside_the_template():
    """A layout captured from a live vault can carry paths that do not ship."""
    import re
    blob = WORKSPACE.read_text(encoding="utf-8")
    for path in set(re.findall(r'"file":\s*"([^"]+)"', blob)):
        assert (TEMPLATE / path).exists(), f"workspace.json references {path!r}, absent from plugin/template/"


def test_workspace_sidebar_is_wide_enough_for_the_navigator():
    """Notebook Navigator collapses to a single pane at Obsidian's default 300px
    sidebar and shows the *file list*, hiding the Shortcuts entirely — so a
    fresh vault opened on the configured shortcuts without showing them. It goes
    dual-pane by 360px; verified live against Obsidian 1.13."""
    layout = json.loads(WORKSPACE.read_text(encoding="utf-8"))
    assert layout["left"]["width"] >= 360, (
        f"sidebar is {layout['left']['width']}px — the navigator will hide its Shortcuts")


def test_orientation_note_has_no_duplicate_h1():
    """show-inline-title is on, so a leading H1 renders the title twice."""
    body = (TEMPLATE / "Start here.md").read_text(encoding="utf-8").split("---", 2)[-1]
    assert not body.lstrip().startswith("# "), "drop the H1; the inline title covers it"


# --- deployment config.json --------------------------------------------------

def test_shipped_config_carries_null_feedback_repo():
    """The feedback key is optional-but-validated (config.py); the shipped
    default must still carry it explicitly so a fresh vault's config.json
    documents the shape rather than relying on the read-side default."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert cfg["feedback"] == {"repo": None}


def test_shipped_config_carries_null_sync_start_date():
    """sync.start-date is written at provisioning (#110); the shipped default
    must carry it explicitly as null so a fresh vault's config.json documents
    the shape rather than relying on the read-side default."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert cfg["sync"] == {"start-date": None}


def test_base_groupby_uses_the_object_form():
    """#60 item 8. Bases rejects `groupBy: <property>` with "must be a object"
    and the whole view then renders a parse error and zero rows — so the string
    form is not a cosmetic mistake, it breaks the table. Both `property` and
    `direction` are required; `property` alone fails the same way. Verified
    against Obsidian 1.13 with the probe."""
    import yaml
    for base in sorted(TEMPLATE.rglob("*.base")):
        for view in (yaml.safe_load(base.read_text(encoding="utf-8")) or {}).get("views") or []:
            group = view.get("groupBy")
            if group is None:
                continue
            where = f"{base.name}:{view.get('name')}"
            assert isinstance(group, dict), f"{where}: groupBy must be a mapping, got {group!r}"
            assert "property" in group and "direction" in group, (
                f"{where}: groupBy needs both property and direction, got {sorted(group)}")
