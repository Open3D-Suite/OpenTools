# SPDX-License-Identifier: GPL-3.0-or-later
"""Where OpenTools keeps its files, and the copy of its old folders at start. Every folder is a
temporary one: the variables that name the folders point there."""

import contextlib
import io
import json
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401 - quiets logging

from opentools import app as app_mod
from opentools import bootstrap, log, object_clipboard, open3d_settings, paths
from opentools.settings import Settings

# A PNG of one pixel, as the clipboard keeps its thumbnails.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


def blob(size):
    """Bytes that look like a binary file of that size."""
    return (bytes(range(256)) * (size // 256 + 1))[:size]


def make_old_opentools(appdata, localappdata):
    """An OpenTools from before, as a person who uses it has it: settings, the log, clipboard slots of
    every mode with .max files and thumbnails, a locked slot, the theme's glyphs and pasted maps."""
    settings = {
        "version": 1,
        "show_hub_on_startup": False,
        "favorites": ["select_instances", "object_clipboard"],
        "recent": ["object_clipboard", "attach_objects"],
        "hub_icon_size": "large",
        "tool_options": {"detach_elements": {"mode": "material_id", "pivot": False}},
        "object_clipboard_mode": "materials",
        "object_clipboard_remotes": ["\\\\nas\\share\\clip"],
    }
    config = Path(appdata) / "OpenTools"
    config.mkdir(parents=True)
    (config / "settings.json").write_text(json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8")
    data = Path(localappdata) / "OpenTools"
    files = {
        "logs/opentools.log": b"2026-11-19 10:00:00 INFO    opentools.bootstrap: OpenTools 0.6.0 starting.\n",
        "logs/opentools.log.1": b"older lines\n" * 200,
        "clipboard/slot_1/objects.max": blob(1_500_000),
        "clipboard/slot_1/thumb.png": PNG,
        "clipboard/slot_1/info.json": b'{"kind": "objects", "count": 3, "names": ["Box001"]}',
        "clipboard/slot_2/objects.max": blob(300_000),
        "clipboard/slot_2/lock.json": b'{"user": "artist", "machine": "PC-01", "at": "2026-11-19 10:00:00"}',
        "clipboard/materials/slot_3/materials.mat": blob(80_000),
        "clipboard/materials/slot_3/thumb.png": PNG,
        "clipboard/modifiers/slot_4/modifiers.max": blob(120_000),
        "clipboard/animation/slot_5/animation.max": blob(90_000),
        "theme/check_e0e0e0.svg": b'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"/>',
        "clipboard_maps/brick ladrillo.jpg": blob(200_000),
    }
    for name, content in files.items():
        (data / name).parent.mkdir(parents=True, exist_ok=True)
        (data / name).write_bytes(content)
    (data / "clipboard" / "slot_8").mkdir()
    return config, data, len(files)


def snapshot(folder):
    """Every file and folder inside `folder`, by its path inside it, with a file's bytes."""
    found = {}
    for base, folders, names in os.walk(folder):
        for name in folders:
            found[os.path.relpath(os.path.join(base, name), folder)] = None
        for name in names:
            found[os.path.relpath(os.path.join(base, name), folder)] = Path(base, name).read_bytes()
    return found


class FoldersTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.appdata, self.local = self.root / "Roaming", self.root / "Local"
        self.environ = {"APPDATA": str(self.appdata), "LOCALAPPDATA": str(self.local)}
        for name in ("OPENTOOLS_CONFIG_DIR", "OPENTOOLS_DATA_DIR", "OPEN3D_SETTINGS_DIR", "OPEN3D_DATA_DIR"):
            self.environ[name] = ""
        self.addCleanup(paths._instead.clear)

    def patched(self, **variables):
        return mock.patch.dict(os.environ, {**self.environ, **variables})

    def test_the_new_folders_are_in_open3d(self):
        with self.patched():
            self.assertEqual(paths.config_dir(), self.appdata / "Open3D" / "OpenTools")
            self.assertEqual(paths.data_dir(), self.local / "Open3D" / "OpenTools")
            self.assertEqual(paths.log_file(), self.local / "Open3D" / "OpenTools" / "logs" / "opentools.log")
            self.assertEqual(paths.old_config_dir(), self.appdata / "OpenTools")
            self.assertEqual(paths.old_data_dir(), self.local / "OpenTools")
            self.assertEqual(Settings().path, self.appdata / "Open3D" / "OpenTools" / "settings.json")
            self.assertEqual(object_clipboard.folder(None), self.local / "Open3D" / "OpenTools" / "clipboard")

    def test_the_open3d_variables_move_them(self):
        with self.patched(OPEN3D_SETTINGS_DIR=str(self.root / "suite"), OPEN3D_DATA_DIR=str(self.root / "cache")):
            self.assertEqual(paths.config_dir(), self.root / "suite" / "OpenTools")
            self.assertEqual(paths.data_dir(), self.root / "cache" / "OpenTools")

    def test_the_old_overrides_win_and_their_folder_is_not_copied(self):
        make_old_opentools(self.appdata, self.local)
        own = self.root / "my settings"
        with self.patched(OPENTOOLS_CONFIG_DIR=str(own)):
            self.assertEqual(paths.config_dir(), own)
            done = paths.carry_over()
            self.assertEqual([new for _, new, _ in done], [self.local / "Open3D" / "OpenTools"])
            self.assertEqual(paths.config_dir(), own)
        self.assertFalse((self.appdata / "Open3D").exists())
        self.assertFalse(own.exists())

    def test_the_old_folders_are_copied_once_and_left_as_they_were(self):
        config, data, files = make_old_opentools(self.appdata, self.local)
        before = snapshot(config), snapshot(data)
        with self.patched():
            done = paths.carry_over()
            self.assertEqual([(old, outcome.kind) for old, _, outcome in done], [(config, "copied"), (data, "copied")])
            self.assertEqual(sum(outcome.files for _, _, outcome in done), files + 1)
            self.assertEqual((snapshot(paths.config_dir()), snapshot(paths.data_dir())), before)
            self.assertEqual(Settings().get("favorites"), ["select_instances", "object_clipboard"])
            slot = object_clipboard.slot_state(1, Settings(), mode="objects")
            self.assertTrue(slot["filled"])
            self.assertEqual(slot["folder"], self.local / "Open3D" / "OpenTools" / "clipboard" / "slot_1")
            self.assertTrue(object_clipboard.lock_info(object_clipboard.slot_dir(2, Settings(), mode="objects")))
            # A change made in the new folder stays: a second start copies nothing.
            Settings().set("hub_icon_size", "small")
            again = paths.carry_over()
            self.assertEqual([outcome.kind for _, _, outcome in again], ["nothing", "nothing"])
            self.assertEqual(Settings().get("hub_icon_size"), "small")
        self.assertEqual((snapshot(config), snapshot(data)), before)
        # Nothing else is left beside the new folders.
        self.assertEqual(
            os.listdir(self.appdata / "Open3D") + os.listdir(self.local / "Open3D"), ["OpenTools", "OpenTools"]
        )

    def test_a_copy_that_fails_leaves_the_session_on_the_old_folder(self):
        config, _, _ = make_old_opentools(self.appdata, self.local)
        # The folder the new settings go in is a file.
        blocked = self.root / "blocked"
        blocked.write_bytes(b"a file")
        with self.patched(OPEN3D_SETTINGS_DIR=str(blocked)):
            done = paths.carry_over()
            self.assertEqual([outcome.kind for _, _, outcome in done], ["failed", "copied"])
            self.assertEqual(paths.config_dir(), config)
            self.assertFalse(Settings().get("show_hub_on_startup"))
        blocked.unlink()
        with self.patched(OPEN3D_SETTINGS_DIR=str(blocked)):
            # The next start copies it.
            self.assertEqual([outcome.kind for _, _, outcome in paths.carry_over()], ["copied", "nothing"])
            self.assertEqual(paths.config_dir(), blocked / "OpenTools")


class StartTest(unittest.TestCase):
    """The start-up of the plugin, outside 3ds Max: it copies the old folders before it reads them."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.appdata, self.local = self.root / "Roaming", self.root / "Local"
        environ = {"APPDATA": str(self.appdata), "LOCALAPPDATA": str(self.local)}
        for name in ("OPENTOOLS_CONFIG_DIR", "OPENTOOLS_DATA_DIR", "OPEN3D_SETTINGS_DIR", "OPEN3D_DATA_DIR"):
            environ[name] = ""
        patcher = mock.patch.dict(os.environ, environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(paths._instead.clear)
        self.addCleanup(self.stop)

    def stop(self):
        """Ends the started OpenTools and closes its log, so the folder can be removed."""
        app_mod.set_current(None)
        logger = logging.getLogger(log.LOGGER_NAME)
        for handler in list(logger.handlers):
            if getattr(handler, "_opentools", False):
                logger.removeHandler(handler)
                handler.close()
        logger.addHandler(logging.NullHandler())

    def start(self):
        with contextlib.redirect_stdout(io.StringIO()):
            started = bootstrap.start()
        self.stop()
        return started

    def test_the_first_start_copies_the_old_folders_and_reads_the_copy(self):
        config, data, _ = make_old_opentools(self.appdata, self.local)
        before = snapshot(config), snapshot(data)
        started = self.start()
        self.assertEqual(started.settings.path, self.appdata / "Open3D" / "OpenTools" / "settings.json")
        self.assertFalse(started.settings.get("show_hub_on_startup"))
        self.assertEqual(started.settings.get("hub_icon_size"), "large")
        written = (self.local / "Open3D" / "OpenTools" / "logs" / "opentools.log").read_text(encoding="utf-8")
        # The old log was copied first, then this start wrote after it.
        self.assertTrue(written.startswith("2026-11-19 10:00:00 INFO"), written[:200])
        self.assertIn("Copied 1 file(s) from %s" % config, written)
        self.assertIn("Copied 13 file(s) from %s" % data, written)
        self.assertEqual((snapshot(config), snapshot(data)), before)
        # The second start finds the new folders and copies nothing.
        self.start()
        written = (self.local / "Open3D" / "OpenTools" / "logs" / "opentools.log").read_text(encoding="utf-8")
        self.assertEqual(written.count("Copied "), 2)
        self.assertEqual((snapshot(config), snapshot(data)), before)

    def test_a_start_with_nothing_before_makes_only_the_new_folders(self):
        self.start()
        self.assertFalse((self.appdata / "OpenTools").exists())
        self.assertFalse((self.local / "OpenTools").exists())
        self.assertTrue((self.local / "Open3D" / "OpenTools" / "logs" / "opentools.log").is_file())

    def test_a_start_whose_copy_fails_logs_it_and_uses_the_old_folder(self):
        config, _, _ = make_old_opentools(self.appdata, self.local)
        (self.appdata / "Open3D").write_bytes(b"a file in the way")
        started = self.start()
        self.assertEqual(started.settings.path, config / "settings.json")
        written = (self.local / "Open3D" / "OpenTools" / "logs" / "opentools.log").read_text(encoding="utf-8")
        self.assertIn("Could not copy %s" % config, written)
        self.assertIn("this session uses %s" % config, written)

    def test_the_shared_module_is_the_one_inside_the_package(self):
        self.assertEqual(Path(open3d_settings.__file__).parent, paths.PACKAGE_DIR)
        self.assertEqual(open3d_settings.app_settings_dir("OpenTools", {"APPDATA": "R"}), Path("R/Open3D/OpenTools"))


if __name__ == "__main__":
    unittest.main()
