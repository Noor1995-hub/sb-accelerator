"""Guards for shipped .obsidian configuration in the template.

The sidebar menu (bookmarks.json) references template paths — these tests
keep it honest when folders or .base files get renamed."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "plugin" / "template"
BOOKMARKS = TEMPLATE / ".obsidian" / "bookmarks.json"
MINIMAL_DATA = TEMPLATE / ".obsidian" / "plugins" / "obsidian-minimal-settings" / "data.json"
APPEARANCE = TEMPLATE / ".obsidian" / "appearance.json"
SNIPPET = TEMPLATE / ".obsidian" / "snippets" / "sb-accelerator.css"
WORKSPACE = TEMPLATE / ".obsidian" / "workspace.json"
CONFIG = TEMPLATE / "99-workflow-config" / "config.json"

# The sidebar is one menu (#263): Obsidian's Bookmarks list, each entry a
# table except Start here, with the rarely used ones in a folded Library group.
# Names are the readable folder names the owner already knew.
EXPECTED_MENU = [
    ("Start here", "Start here.md"),
    ("Daily notes", "60-daily-notes/Daily notes.base"),
    ("Thoughts & ideas", "80-thoughts-ideas/Thoughts & ideas.base"),
    ("Meetings", "20-meetings/Meetings.base"),
    ("Projects", "30-projects/Projects.base"),
    ("People", "50-people/People.base"),
    ("Entities", "40-entities/Entities.base"),
    ("Decisions", "30-projects/Decisions.base"),
    ("Input", "99-workflow-config/views/Input.base"),
]
EXPECTED_LIBRARY = [
    ("Recent", "99-workflow-config/views/Recent.base"),
    ("Resources", "99-workflow-config/views/Resources.base"),
    ("Heavy assets", "99-workflow-config/views/Heavy assets.base"),
    ("Private", "99-workflow-config/views/Private.base"),
    ("Archive", "99-workflow-config/views/Archive.base"),
]


def _menu() -> list:
    return json.loads(BOOKMARKS.read_text(encoding="utf-8"))["items"]


def test_menu_is_the_shipped_entries_in_order_and_every_target_exists():
    items = _menu()
    files = [(i["title"], i["path"]) for i in items if i["type"] == "file"]
    assert files == EXPECTED_MENU, f"menu drifted: {files}"
    groups = [i for i in items if i["type"] == "group"]
    assert [g["title"] for g in groups] == ["Library"] and items[-1] is groups[0]
    assert [(i["title"], i["path"]) for i in groups[0]["items"]] == EXPECTED_LIBRARY
    for _, path in EXPECTED_MENU + EXPECTED_LIBRARY:
        assert (TEMPLATE / path).is_file(), f"menu entry points at a missing file: {path}"


def test_menu_matches_what_migration_010_writes():
    """A fresh vault and an upgraded one get the same menu bytes."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "m010", REPO_ROOT / "plugin" / "migrations" / "010-structure-version-11" / "migrate.py")
    m010 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m010)
    assert _menu() == m010.shipped_menu()


def test_notebook_navigator_is_not_shipped():
    """#263 replaced it with the Bookmarks menu; nothing may still enable it."""
    plugins = json.loads((TEMPLATE / ".obsidian" / "community-plugins.json").read_text(encoding="utf-8"))
    assert "notebook-navigator" not in plugins
    assert not (TEMPLATE / ".obsidian" / "plugins" / "notebook-navigator").exists()
    pins = json.loads((REPO_ROOT / "plugin" / "lib" / "plugin-pins.json").read_text(encoding="utf-8"))
    assert "notebook-navigator" not in {p["id"] for p in pins["plugins"]}


def test_every_shipped_menu_entry_has_a_colour_and_an_icon():
    css = SNIPPET.read_text(encoding="utf-8")
    titles = [t for t, _ in EXPECTED_MENU] + ["Library"] + [f"Library/{t}" for t, _ in EXPECTED_LIBRARY]
    for title in titles:
        rule = f'.tree-item[data-path="{title}"] > .tree-item-self {{'
        assert rule in css, f"menu entry {title!r} has no colour rule"
        body = css.split(rule)[1].split("}")[0]
        assert "--sb-menu-color: #" in body and "--sb-menu-icon: url(" in body, title


def test_new_notes_go_to_thoughts_and_ideas():
    app = json.loads((TEMPLATE / ".obsidian" / "app.json").read_text(encoding="utf-8"))
    assert app["newFileLocation"] == "folder" and app["newFileFolderPath"] == "80-thoughts-ideas"


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


# --- recap callout accents ---------------------------------------------------

# The daily note's own callout types: the four the recap writes, and the
# review queues at the top of the note (#238).
RECAP_CALLOUTS = ("glance", "theme", "hot", "sync", "review")


def _callout_declarations(prop: str) -> dict:
    """Every value the snippet declares for `prop`, keyed by callout type.

    Scoped per rule, deliberately. A whole-file `prop in css` substring check
    is loop-invariant — it cannot name which rule is missing a declaration,
    and the prose comment above these rules mentions both property names, so
    such a check passes even with all four declarations deleted.
    """
    import re
    pattern = re.compile(
        r'\.callout\[data-callout="(?P<type>[a-z-]+)"\]'
        r'[^{}]*\{[^{}]*?' + re.escape(prop) + r':\s*(?P<value>[^;}]+)')
    return {m.group("type"): m.group("value").strip()
            for m in pattern.finditer(SNIPPET.read_text(encoding="utf-8"))}


def _callout_colors() -> dict:
    return _callout_declarations("--callout-color")


def test_every_recap_callout_declares_a_colour_and_an_icon():
    colors = _callout_declarations("--callout-color")
    icons = _callout_declarations("--callout-icon")
    assert set(colors) == set(RECAP_CALLOUTS), (
        f"recap callout types missing a --callout-color: {sorted(colors)}")
    assert set(icons) == set(RECAP_CALLOUTS), (
        f"recap callout types missing a --callout-icon: {sorted(icons)}")
    # An icon id Obsidian does not recognise renders the default pencil, which
    # looks like a working callout, so the value shape is pinned too.
    bad = {k: v for k, v in icons.items() if not v.startswith("lucide-")}
    assert not bad, f"these --callout-icon values are not Lucide ids: {bad}"


def test_callout_colours_are_colour_values_not_rgb_triplets():
    """A bare `r, g, b` triplet renders the callout with no tint at all.

    Obsidian used to compose the tint as `rgba(var(--callout-color), 0.1)`,
    which needs the triplet. Current Obsidian does not: `.callout` declares
    `--callout-color: var(--callout-default)` — a whole colour — and consumes
    it through `color-mix(in oklch, var(--callout-color) 10%, transparent)`
    for the background and a matching `color-mix` for the border (verified by
    reading app.css out of Obsidian 1.13's bundle; it contains zero
    occurrences of `rgba(var(--callout-color)`).

    Feed `color-mix()` a triplet and the function is invalid at
    computed-value time, so `background-color` falls back to its initial
    `transparent` — while `--callout-icon` keeps working, because an icon id
    is read by JS and never goes through colour maths. That asymmetry is what
    shipped in 0.11.0: the recap callouts rendered with their custom icons
    and no colour coding, and it looked like a theme problem rather than a
    snippet one."""
    offenders = {k: v for k, v in _callout_colors().items() if "," in v}
    assert not offenders, (
        "these --callout-color values are legacy rgb triplets; current "
        "Obsidian feeds the value to color-mix(), which rejects them and "
        f"renders no tint: {offenders}")


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
    property name — `type` beside `Subject` and `Keep`. That is the same
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


def test_workspace_opens_with_the_menu_selected():
    """The left sidebar opens on the Bookmarks tab — the menu (#263). Without a
    shipped workspace.json a fresh vault gets Obsidian's default sidebar with
    the file explorer selected, and the menu is a tab nobody clicks. The probe
    harness found the equivalent problem with Navigator (#60)."""
    tabs = _left_sidebar_tabs()
    types = [c["state"]["type"] for c in tabs["children"]]
    assert types[0] == "bookmarks", f"the menu must lead the sidebar, got {types}"
    assert "notebook-navigator" not in types
    assert tabs.get("currentTab") == 0, "the menu tab must be the selected one"


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


def test_sidebar_is_narrow_now_that_it_holds_only_the_menu():
    """Navigator needed 400px for two panes (#240); the menu needs far less,
    and the pages get the width back."""
    assert json.loads(WORKSPACE.read_text(encoding="utf-8"))["left"]["width"] == 280


def test_file_view_hides_the_machinery():
    """Obsidian's file view stays one click away, without the assistant's
    machinery (Navigator hid it before #263)."""
    css = SNIPPET.read_text(encoding="utf-8")
    rule = css.split('.nav-folder:has(> .nav-folder-title:is(')[1].split("{")[0]
    for folder in ("claude", "99-workflow-config", "_messages"):
        assert f'[data-path="{folder}"]' in rule
    assert '.nav-file:has(> .nav-file-title[data-path="CLAUDE.md"])' in css


def test_ribbon_keeps_today_and_the_quick_switcher_only():
    hidden = json.loads(WORKSPACE.read_text(encoding="utf-8"))["left-ribbon"]["hiddenItems"]
    shown = sorted(k for k, v in hidden.items() if v is False)
    assert shown == ["daily-notes:Open today's daily note", "switcher:Open quick switcher"]


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


def test_shipped_config_carries_the_m365_home_domains_key():
    """adapters.m365.home_domains is validated (config.py); the shipped
    default must carry it explicitly as null so a fresh vault's config.json
    documents the shape rather than relying on the read-side default, same
    as feedback.repo and sync.start-date above."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert cfg["adapters"]["m365"] == {
        "enabled": False, "account_hint": None, "home_domains": None}


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


def test_vault_opens_on_todays_daily_note():
    """#263: Obsidian's own Daily notes plugin opens today's note on startup
    (Navigator's homepage did it in #238). It creates the note, empty, when
    there is none; the daily-note code treats a blank note as absent, so the
    catch-up run writes the real one over it (test_vaultlib_dailynote)."""
    daily = json.loads((TEMPLATE / ".obsidian" / "daily-notes.json").read_text(encoding="utf-8"))
    assert daily == {"folder": "60-daily-notes", "format": "YYYY-MM-DD", "autorun": True}


def test_review_callout_collapses_when_empty_and_spans_the_pane():
    css = (TEMPLATE / ".obsidian" / "snippets" / "sb-accelerator.css").read_text(encoding="utf-8")
    # keyed on the body's height for the result count, not on drawn rows:
    # Bases draws only on-screen rows, so a table below the fold has none
    assert '.bases-embed:has(.bases-tbody[style*="height: 0px"])' in css
    assert '.callout[data-callout="review"]:not(:has(.bases-tbody:not([style*="height: 0px"])))' in css
    assert ".bases-tbody .bases-tr" not in css
    # collapsed, never display:none — Bases stops re-rendering a hidden view
    rule = css.split('.callout[data-callout="review"]:not(:has(.bases-tbody:not([style*="height: 0px"]))) {')[1].split("}")[0]
    assert "height: 0" in rule and "display" not in rule
    assert '.cm-embed-block:has(.callout[data-callout="review"])' in css


def test_triage_rows_are_tall_enough_for_three_attendees():
    import yaml
    base = yaml.safe_load((TEMPLATE / "20-meetings" / "Meetings.base").read_text(encoding="utf-8"))
    triage = next(v for v in base["views"] if v["name"] == "To review")
    assert triage["rowHeight"] == "tall"


def test_entities_table_keeps_teams_under_their_parent_without_headings():
    """#253 grouped teams under a bold heading per parent; with no teams every
    heading just repeated its one row (#263). Now there are no headings: the
    table sorts on the parent's *name* (looked up from its dossier, never the
    slug), the parent first, and a team's name carries a leading arrow."""
    import yaml
    base = yaml.safe_load((TEMPLATE / "40-entities" / "Entities.base").read_text(encoding="utf-8"))
    assert 'file("40-entities/" + parent + "/dossier.md").properties["entity-name"]' in base["formulas"]["group"]
    assert base["formulas"]["name"].startswith('if(parent, "↳ "')
    for name in ("All", "Active"):
        view = next(v for v in base["views"] if v["name"] == name)
        assert "groupBy" not in view
        assert view["sort"][:2] == [{"property": "formula.group", "direction": "ASC"},
                                    {"property": "formula.team-order", "direction": "ASC"}]
        assert view["order"][1:3] == ["formula.name", "formula.part-of"]

def test_input_shows_dropped_files_and_notes_ticked_include():
    import yaml
    base = yaml.safe_load((TEMPLATE / "99-workflow-config" / "views" / "Input.base")
                          .read_text(encoding="utf-8"))
    branches = base["filters"]["or"]
    flat = [" ".join(b["and"]) for b in branches]
    assert any('file.inFolder("10-inbox")' in f and 'file.name != "README"' in f for f in flat)
    assert any('file.inFolder("80-thoughts-ideas")' in f and "include == true" in f
               and 'file.ext == "md"' in f for f in flat)
    assert [v["name"] for v in base["views"]] == ["Tonight"]
    assert base["properties"]["formula.item"]["displayName"] == "Picked up tonight"


def test_thoughts_and_ideas_has_yours_and_absorbed_views():
    import yaml
    base = yaml.safe_load((TEMPLATE / "80-thoughts-ideas" / "Thoughts & ideas.base")
                          .read_text(encoding="utf-8"))
    views = {v["name"]: v for v in base["views"]}
    assert list(views) == ["Yours", "Absorbed"]
    assert "include" in views["Yours"]["order"]
    assert views["Absorbed"]["groupBy"] == {"property": "formula.project_group", "direction": "ASC"}
    assert base["properties"]["note.include"]["displayName"] == "Include"


def test_no_owner_facing_template_text_calls_it_the_inbox():
    for rel in ["Start here.md", "How it works.md", "10-inbox/README.md"]:
        text = (TEMPLATE / rel).read_text(encoding="utf-8")
        assert "**Inbox**" not in text and "# Inbox" not in text, rel
