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
- `Contents/tools/<id>/`: one folder per tool, with its `tool.json`, its code and its `icon.svg`.
- `dev/install_dev.ps1` installs a small bundle that loads this checkout and switches on the dev bridge;
  `dev/bridge.py` then runs Python inside the running 3ds Max.

## Build and check

- There is no build step. Checks, all of which must pass:
  - `python -I dev/run_tests.py` (113 tests; they need neither 3ds Max nor Qt)
  - `ruff format --check .` and `ruff check .`
- `tests/test_encoding.py` fails on a text source that is not valid UTF-8 or holds broken characters.
- `3dsmaxbatch tests\batch_render_elements.ms` tests Render Elements with Corona, apart from the checks
  above. It resets the scene and writes `%TEMP%\OpenTools_render_elements_test\result.txt`.
- `.editorconfig`, `.gitattributes` and `ruff.toml` are the same in every Open3D repo. Do not change them
  here. Only the end of `ruff.toml` is this repo's, `known-first-party = ["opentools"]`: ruff does not
  find the package inside the bundle and would sort its imports among `pymxs` and `PySide6`.

## Version and release

- The version is written by hand in three places that must agree: `AppVersion` and the `ComponentEntry`
  `Version` in `PackageContents.xml`, and `__version__` in `opentools/__init__.py`. The status line of the
  README names it too. Nothing in this repo compares them; the launcher's publishing script checks
  `AppVersion` alone against the tag.
- Changes a user can notice go into `CHANGELOG.md` under `## In development`, in the same commit.
- This repo has no packager of its own. The Open3D launcher's publishing script zips `OpenTools.bundle` as
  it is in the `vX.Y.Z` tag, adds `LICENSE` to it and needs that version's section in `CHANGELOG.md`.

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
- MAXScript files: 4 spaces, LF, plain ASCII without a BOM. Globals and structs start with `OTL_`.
- The interface is in English only: its texts are written straight in the code.

## Traps

- In 3ds Max 2027 `pymxs.undo` swallows every exception raised in its block: the code calls
  `maxhost.undo(label)` instead, which raises it again. `maxhost.quiet()` holds back modal error dialogs.
- A `.ms` entry that uses a global made by a file it loads with `fileIn` declares it `global` before its
  block; otherwise, on the first run in a session, the name compiles as an empty local.
- In a session without an interface (`3dsmaxbatch`, render nodes) only the tools and the macros load.
- When `OpenTools.bundle` and the development bundle are both installed, only the first to start runs.
