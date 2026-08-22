# Local setup

No app to run — this repo is a plugin + template + docs. You need:

- `gh` CLI, authenticated with access to `DLW-INT-BTA-BELUX`
- Python 3.13 with `pytest` and `pyyaml` (`pip install pytest pyyaml`)

## Run what CI runs

```bash
python scripts/lint_plugin.py
python scripts/validate_template.py
python -m pytest scripts/tests -q
```

(If `python` is not on your PATH — stock macOS — use `python3`.)

## Test the plugin against a scratch vault

Instantiate the template into a throwaway directory and point Claude Code at it:

```bash
cp -R template /tmp/scratch-vault
cd /tmp/scratch-vault && claude
```

(While `template/` is unpopulated this is a no-op; the template-extraction
issue makes it real.)
