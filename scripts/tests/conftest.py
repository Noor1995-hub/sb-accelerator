import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# scripts/ — for compile_ontology, lint_plugin, validate_template, make_test_vault
sys.path.insert(0, str(REPO_ROOT / "scripts"))
# plugin/lib/ — for the vaultlib package the skills call at runtime
sys.path.insert(0, str(REPO_ROOT / "plugin" / "lib"))
