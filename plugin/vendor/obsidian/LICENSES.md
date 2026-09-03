# Vendored Obsidian plugins and theme — licences

This directory carries the unmodified release assets of the Obsidian community plugins and theme the vault expects, so `lib/provision_plugins.py` can install them without network access. Each subdirectory holds exactly the files listed in `lib/plugin-pins.json` for that entry, byte-for-byte as published upstream at the pinned tag, plus that project's licence text as `LICENSE`. Nothing inside those subdirectories is written or modified by delaware; they are regenerated from the pins by tooling and never edited by hand. This index is the one hand-maintained file here.

| Directory | Upstream project | Pinned tag | Licence |
|---|---|---|---|
| `dataview/` | [blacksmithgu/obsidian-dataview](https://github.com/blacksmithgu/obsidian-dataview) | [0.5.68](https://github.com/blacksmithgu/obsidian-dataview/releases/tag/0.5.68) | MIT — `dataview/LICENSE` |
| `obsidian-minimal-settings/` | [kepano/obsidian-minimal-settings](https://github.com/kepano/obsidian-minimal-settings) | [9.0.0](https://github.com/kepano/obsidian-minimal-settings/releases/tag/9.0.0) | MIT — `obsidian-minimal-settings/LICENSE` |
| `obsidian-style-settings/` | [community-archive/obsidian-style-settings](https://github.com/community-archive/obsidian-style-settings) | [1.0.9](https://github.com/community-archive/obsidian-style-settings/releases/tag/1.0.9) | GPL-3.0 — `obsidian-style-settings/LICENSE` |
| `notebook-navigator/` | [johansan/notebook-navigator](https://github.com/johansan/notebook-navigator) | [3.3.4](https://github.com/johansan/notebook-navigator/releases/tag/3.3.4) | GPL-3.0 — `notebook-navigator/LICENSE` |
| `Minimal/` (theme) | [kepano/obsidian-minimal](https://github.com/kepano/obsidian-minimal) | [9.0.2](https://github.com/kepano/obsidian-minimal/releases/tag/9.0.2) | MIT — `Minimal/LICENSE` |

The MIT-licensed projects are redistributed with their copyright and permission notices intact (the `LICENSE` file in each directory). The GPL-3.0 projects are redistributed unmodified, in the form their authors published, with the full licence text alongside; their complete corresponding source is the upstream repository at the pinned tag linked above. Copyright in every file under this directory remains with the respective upstream authors.
