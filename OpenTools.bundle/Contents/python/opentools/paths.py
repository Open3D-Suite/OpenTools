# SPDX-License-Identifier: GPL-3.0-or-later
"""Filesystem locations used by OpenTools.

Its settings live in %APPDATA%\\Open3D\\OpenTools and everything else it writes (the log, the clipboard
slots, the theme's glyphs) in %LOCALAPPDATA%\\Open3D\\OpenTools, or in OpenTools inside the folders that
OPEN3D_SETTINGS_DIR and OPEN3D_DATA_DIR name (D-042, D-044). OPENTOOLS_CONFIG_DIR and
OPENTOOLS_DATA_DIR, when set, win over both.

At start, before anything reads the settings or opens the log, carry_over copies the folders of an
OpenTools from before, %APPDATA%\\OpenTools and %LOCALAPPDATA%\\OpenTools, into the new ones, once, and
leaves them as they were (D-048, D-049). When a copy fails, that session uses the old folder and the
next start tries again.
"""

import os
from pathlib import Path

from . import open3d_settings

APP = "OpenTools"

# abspath (not resolve) so a mapped network drive stays "Z:\..." instead of a UNC path.
PACKAGE_DIR = Path(os.path.abspath(__file__)).parent  # .../Contents/python/opentools
CONTENTS_DIR = PACKAGE_DIR.parent.parent  # .../Contents
BUILTIN_TOOLS_DIR = CONTENTS_DIR / "tools"

# The old folder used this session in place of a new one whose copy failed: {"config" | "data": Path}.
_instead = {}


def _base(env_var, fallback):
    value = os.environ.get(env_var)
    return Path(value) if value else Path.home() / fallback


def config_dir():
    """Per-user settings; roams and survives 3ds Max upgrades."""
    override = os.environ.get("OPENTOOLS_CONFIG_DIR")
    if override:
        return Path(override)
    return _instead.get("config") or new_config_dir()


def data_dir():
    """Per-machine data such as logs and caches."""
    override = os.environ.get("OPENTOOLS_DATA_DIR")
    if override:
        return Path(override)
    return _instead.get("data") or new_data_dir()


def new_config_dir():
    """%APPDATA%\\Open3D\\OpenTools, or OpenTools in the folder OPEN3D_SETTINGS_DIR names."""
    return open3d_settings.app_settings_dir(APP) or Path.home() / "AppData/Roaming/Open3D" / APP


def new_data_dir():
    """%LOCALAPPDATA%\\Open3D\\OpenTools, or OpenTools in the folder OPEN3D_DATA_DIR names."""
    return open3d_settings.app_data_dir(APP) or Path.home() / "AppData/Local/Open3D" / APP


def old_config_dir():
    """Where OpenTools kept its settings before: %APPDATA%\\OpenTools."""
    return _base("APPDATA", "AppData/Roaming") / APP


def old_data_dir():
    """Where OpenTools kept the rest before: %LOCALAPPDATA%\\OpenTools."""
    return _base("LOCALAPPDATA", "AppData/Local") / APP


def carry_over():
    """Copies each old folder into its new one, the first time OpenTools starts with the new folders.
    A folder named by OPENTOOLS_CONFIG_DIR or OPENTOOLS_DATA_DIR is left alone. Returns
    [(old, new, open3d_settings.CarryOver)] for the folders it looked at. When a copy fails, the old
    folder is used for the rest of the session. It never raises for a folder or a file."""
    done = []
    for kind, override, old, new in (
        ("config", "OPENTOOLS_CONFIG_DIR", old_config_dir(), new_config_dir()),
        ("data", "OPENTOOLS_DATA_DIR", old_data_dir(), new_data_dir()),
    ):
        _instead.pop(kind, None)
        if os.environ.get(override):
            continue
        outcome = open3d_settings.carry_over(old, new)
        if outcome.kind == open3d_settings.FAILED:
            _instead[kind] = old
        done.append((old, new, outcome))
    return done


def log_dir():
    return data_dir() / "logs"


def log_file():
    return log_dir() / "opentools.log"
