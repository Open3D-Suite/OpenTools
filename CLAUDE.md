# OpenTools

A panel of small everyday tools for 3ds Max: a dockable panel, a command palette and a macro per tool, all
in one package. One 3ds Max plugin, written in Python (Qt, pymxs) and MAXScript; nothing is compiled.

This file holds facts about this repo only, each one checkable in the code. Update it in the same commit
as a change that makes it old.

## Layout

- `OpenTools.bundle/`: the package 3ds Max loads. `Contents/scripts/opentools_startup.ms` starts the core.
- `Contents/python/opentools/`: the core. `bootstrap.py` starts it, `registry.py` reads the tools,
  `runner.py` runs one, `macros.py` and `menus.py` give each its macro and its menu entry, `maxhost.py` is
  a thin layer over 3ds Max. `ui/` is the Qt side: `hub.py` is the panel, `toolwindow.py` the base of the
  tool windows, `theme.py` the look, built from 3ds Max's own palette.
- `paths.py`: where OpenTools keeps its files, and carrying its old folders over. `open3d_settings.py`: what
  every Open3D app shares (the language and the folders), a copy of a common file.
- `Contents/tools/<id>/`: one folder per tool, with its `tool.json`, its code and its `icon.svg`.
- `dev/install_dev.ps1` installs a small bundle that loads this checkout and switches on the dev bridge;
  `dev/bridge.py` then runs Python inside the running 3ds Max.

## Build and check

- No build step. `tools\check.ps1` runs every check, and all must pass; it needs Python 3.11 or newer and
  the ruff that `ruff.toml` names. Built in: the version agrees in its four places, each `.py`, `.ms` and
  `.ps1` has its licence line, no file holds a path of somebody's computer. Then, from `tools/repo.toml`:
  `ruff format --check .`, `ruff check .`, `python -I dev/run_tests.py` (122 tests, without 3ds Max or Qt).
- `-Full` adds `3dsmaxbatch tests\batch_render_elements.ms`, Render Elements with Corona on a scene of its
  own. 3dsmaxbatch ends well even when the test fails, so the check removes the old
  `%TEMP%\OpenTools_render_elements_test\result.txt` first and reads the verdict in its last line after.
- CI: `.github/workflows/check.yml` runs `tools\check.ps1`, without `-Full`, on every push and pull request
  to `main`, on GitHub's Windows runner, once with Python 3.11 and once with 3.13.
- `tests/test_encoding.py` fails on a text source that is not valid UTF-8 or holds broken characters.
- `.editorconfig`, `.gitattributes`, `ruff.toml`, `LICENSE`, `tools/check.ps1`, `tools/repo.py`,
  `tools/repo_package.py`, `tools/repo_release.py` and `tools/repo_msi.py` are the same in every Open3D repo, and
  `opentools/open3d_settings.py` in every repo that has it; do not change them here. Only the end of `ruff.toml` is this repo's,
  `known-first-party = ["opentools"]`: ruff does not find the package inside the bundle and would sort
  its imports among `pymxs` and `PySide6`.

## Version and release

- The version is `AppVersion` in `PackageContents.xml`. The `ComponentEntry` `Version` there, `__version__`
  in `opentools/__init__.py` and the README's status line repeat it: `tools\check.ps1` fails if one differs,
  and `python -I tools/repo.py version set X.Y.Z` writes all four. The `0.0.0` in `dev/install_dev.ps1` is
  the development bundle's.
- Changes a user can notice go into `CHANGELOG.md` under `## In development`, in the same commit.
- `python -I tools/repo.py package` makes the release package as the `[package]` table of
  `tools/repo.toml` says: it needs the version's `## X.Y.Z` section in `CHANGELOG.md`, runs the quick
  checks and writes `dist/opentools-<version>-windows-x64-3dsmax.zip`, with the files Git has in
  `OpenTools.bundle/` at its root (never `__pycache__`) and `LICENSE` inside the bundle, and
  `dist/SHA256SUMS.txt`. It refuses a bundle whose `AppVersion` is not the version. Nothing is built.
- `python -I tools/repo.py release X.Y.Z` turns `## In development` into `## X.Y.Z — <date>`, sets the
  version, commits `Release X.Y.Z`, packages, tags `vX.Y.Z` and prints the pushes to approve; run again
  once they are done, it makes the GitHub release as a draft. It never pushes. `--dry-run` tries it all
  and writes only to `dist/`.

## Rules of this code

- The code runs inside 3ds Max's own Python: 3.11 in 3ds Max 2025, the oldest the bundle accepts
  (`SeriesMin` 2025, `SeriesMax` 2099). `pymxs` and `qtmax` exist only inside 3ds Max; PySide6 comes with it.
- In `opentools/`, only `ui/` and `devbridge.py` import them at module level; the other modules import
  them inside functions, so the tests can load them. A tool keeps what is tested in a module of its own
  without those imports (`render_elements/elements_model.py`, `random_select/picking.py`).
- A tool's `id` names its macro (`OpenTools_<id>`) and its saved options, so it stays when the tool is
  renamed: `scene_summary` is the Auditor, `ignite` is Random Replace, `asset_manager` is Relink Assets.
- Tool windows derive from `ToolWindow`, all but the Clipboard's: `self.guard(func)` wraps an action so
  an error is logged and shown, and `self.confirm(...)` asks Yes or Cancel.
- Its files (`paths.py`): settings in `%APPDATA%\Open3D\OpenTools`, the log, the clipboard slots, the
  theme's glyphs and pasted maps in `%LOCALAPPDATA%\Open3D\OpenTools`; `OPEN3D_SETTINGS_DIR` and
  `OPEN3D_DATA_DIR` move them, and `OPENTOOLS_CONFIG_DIR` and `OPENTOOLS_DATA_DIR` win over both. At the
  start of `bootstrap.start`, before the log opens and the settings are read, `paths.carry_over` copies the
  old `%APPDATA%\OpenTools` and `%LOCALAPPDATA%\OpenTools` into them once (not for a folder an
  `OPENTOOLS_*` variable names) and leaves them as they were; the log says what was copied. If a copy
  fails, that session uses the old folder and the next start tries again. It runs in `3dsmaxbatch` too.
- MAXScript files: 4 spaces, LF, plain ASCII without a BOM. Globals and structs start with `OTL_`.
- The interface is in English only: its texts are written straight in the code.

## Traps

- In 3ds Max 2027 `pymxs.undo` swallows every exception raised in its block: the code calls
  `maxhost.undo(label)` instead, which raises it again. `maxhost.quiet()` holds back modal error dialogs.
- A `.ms` entry that uses a global made by a file it loads with `fileIn` declares it `global` before its
  block; otherwise, on the first run in a session, the name compiles as an empty local.
- In a session without an interface (`3dsmaxbatch`, render nodes) only the tools and the macros load.
- When `OpenTools.bundle` and the development bundle are both installed, only the first to start runs.
