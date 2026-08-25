import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# scripts/ — for compile_ontology, lint_plugin, validate_template, make_test_vault
sys.path.insert(0, str(REPO_ROOT / "scripts"))
# plugin/lib/ — for the vaultlib package the skills call at runtime
sys.path.insert(0, str(REPO_ROOT / "plugin" / "lib"))


def pytest_configure(config):
    """Register the marker here rather than in a new pytest.ini — keeps `-q`
    free of unknown-marker warnings without adding a config file."""
    config.addinivalue_line(
        "markers",
        "obsidian: needs a live Obsidian instance and a captured probe tour "
        "(local only; skipped in CI)")
