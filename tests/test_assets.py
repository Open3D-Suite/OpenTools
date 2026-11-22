# SPDX-License-Identifier: GPL-3.0-or-later
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

import helpers  # noqa: F401 - quiets logging

from opentools import assets


def write(path, data=b"x"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


class AssetHelperTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_index_and_candidates(self):
        a = write(self.root / "lib" / "Wood.JPG")
        b = write(self.root / "lib" / "sub" / "wood.png")
        index = assets.build_index([self.root / "lib"])
        self.assertEqual(assets.candidates(r"C:\old\wood.jpg", index), [a])
        self.assertEqual(sorted(assets.candidates(r"C:\old\wood.jpg", index, ignore_extension=True)), sorted([a, b]))
        flat = assets.build_index([self.root / "lib"], recursive=False)
        self.assertEqual(assets.candidates("x/wood.png", flat), [])

    def test_pick_prefers_identical_and_same_extension(self):
        a = write(self.root / "a" / "t.jpg", b"same")
        b = write(self.root / "b" / "t.jpg", b"same")
        c = write(self.root / "c" / "t.jpg", b"different")
        png = write(self.root / "d" / "t.png", b"png")
        self.assertEqual(assets.pick("t.jpg", [a, b]), (a, False))
        self.assertEqual(assets.pick("t.jpg", [a, c]), (None, True))
        self.assertEqual(assets.pick("t.jpg", [png, a]), (a, False))
        self.assertEqual(assets.pick("t.jpg", [png]), (png, False))
        self.assertEqual(assets.pick("t.jpg", []), (None, False))

    def test_transliterate(self):
        self.assertEqual(assets.transliterate("Текстура_дерево.jpg"), "Tekstura_derevo.jpg")
        self.assertEqual(assets.transliterate("pàgina façana.png"), "pagina facana.png")
        self.assertEqual(assets.transliterate("木材.jpg"), "file.jpg")
        self.assertFalse(assets.needs_transliteration("plain.jpg"))
        self.assertTrue(assets.needs_transliteration("façana.jpg"))

    def test_ifl_frames(self):
        write(self.root / "seq" / "f001.jpg")
        ifl = self.root / "seq" / "anim.ifl"
        ifl.write_text("f001.jpg\nf002.jpg 3\n; comment\n\nC:\\abs\\f003.jpg\n", encoding="utf-8")
        frames = assets.ifl_frames(ifl)
        self.assertEqual(frames[0], os.path.join(str(self.root / "seq"), "f001.jpg"))
        self.assertEqual(frames[1], os.path.join(str(self.root / "seq"), "f002.jpg"))
        self.assertEqual(frames[2], "C:\\abs\\f003.jpg")

    def test_plan_collect_reuses_identical_and_numbers_conflicts(self):
        dest = self.root / "maps"
        dest.mkdir()
        a = write(self.root / "a" / "wood.jpg", b"one")
        a_copy = write(self.root / "b" / "wood.jpg", b"one")
        other = write(self.root / "c" / "wood.jpg", b"two")
        cyr = write(self.root / "d" / "дерево.png", b"three")
        steps = assets.plan_collect([a, a_copy, other, cyr, str(self.root / "gone.jpg")], dest, ascii_names=True)
        self.assertEqual([s.action for s in steps], ["copy", "reuse", "copy", "copy", "missing"])
        self.assertEqual(os.path.basename(steps[0].target), "wood.jpg")
        self.assertEqual(steps[1].target, steps[0].target)
        self.assertEqual(os.path.basename(steps[2].target), "wood_2.jpg")
        self.assertEqual(os.path.basename(steps[3].target), "derevo.png")

    def test_plan_collect_sees_files_already_in_destination(self):
        dest = self.root / "maps"
        write(dest / "wood.jpg", b"old")
        same = write(self.root / "a" / "wood.jpg", b"old")
        steps = assets.plan_collect([same], dest)
        self.assertEqual(steps[0].action, "reuse")
        differs = write(self.root / "b" / "wood.jpg", b"new")
        steps = assets.plan_collect([differs], dest)
        self.assertEqual(os.path.basename(steps[0].target), "wood_2.jpg")

    def test_zip_folder(self):
        folder = self.root / "job"
        write(folder / "maps" / "a.jpg", b"a")
        write(folder / "scene.max", b"m")
        archive = assets.zip_folder(folder, self.root / "job.zip")
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(sorted(z.namelist()), ["job/maps/a.jpg", "job/scene.max"])

    def test_changed_paths_counts_only_the_paths_that_changed(self):
        sent = [r"C:\job\maps\wood.jpg", r"C:\job\maps\stone.jpg", r"maps\metal.png"]
        # "Make UNC" on files of a local disk: the list is the same afterwards
        self.assertEqual(assets.changed_paths(sent, sent + [r"C:\other\sky.hdr"]), [])
        # "Make absolute": only the relative path changed
        after = [r"C:\job\maps\wood.jpg", r"C:\job\maps\stone.jpg", r"C:\job\maps\metal.png"]
        self.assertEqual(assets.changed_paths(sent, after), [r"maps\metal.png"])
        # only the case or the separators differ: the same path
        self.assertEqual(assets.changed_paths([r"C:\Job\Maps\Wood.jpg"], ["c:/job/maps/wood.jpg"]), [])
        self.assertEqual(assets.changed_paths(sent, []), sent)

    def test_owners_of_relative_paths(self):
        # GetDependencyFileList gives the path 3ds Max resolved; Asset Tracking lists the path as stored
        bases = (r"C:\job", r"D:\scenes")
        files = [
            (r"C:\job\maps\wood.jpg", r"C:\job\maps\wood.jpg"),
            (r"maps\stone.jpg", r"maps\stone.jpg"),  # relative to the project folder
            (r"tex\metal.png", r"tex\metal.png"),  # relative, found next to the scene
            (r"maps\gone.jpg", r"maps\gone.jpg"),  # relative and missing: listed as stored
            (r"maps\sky.hdr", r"\\nas\lib\sky.hdr"),  # found through the map paths
            (r"maps\env.hdr", r"maps\env.hdr"),  # used by the environment only
        ]
        pairs = [
            (r"C:\job\maps\wood.jpg", "Box001"),
            (r"C:\job\maps\stone.jpg", "Wall"),
            (r"C:\job\maps\stone.jpg", "Box001"),
            (r"D:\scenes\tex\metal.png", "Rail"),
            (r"maps\gone.jpg", "Floor"),
            (r"\\nas\lib\sky.hdr", "Dome"),
        ]
        self.assertEqual(
            assets.match_owners(files, pairs, bases),
            [["Box001"], ["Box001", "Wall"], ["Rail"], ["Floor"], ["Dome"], []],
        )

    def test_render_outputs_are_not_found_files(self):
        # Asset Tracking lists the render output and calls it found before a render wrote it
        texture = write(self.root / "maps" / "wood.jpg", b"wood")
        beauty = str(self.root / "out" / "shot.exr")  # not written yet
        element = write(self.root / "out" / "shot_Z.exr", b"z")  # written by an earlier render
        relative = write(self.root / "out" / "shot_Wire.exr", b"w")
        entries = [
            (texture, "#(#ok)", texture),
            (beauty, "#(#ok)", beauty),
            (element, "#(#ok)", element),
            (r"out\shot_Wire.exr", "#(#ok)", r"out\shot_Wire.exr"),
            (str(self.root / "maps" / "gone.jpg"), "#(#missing)", str(self.root / "maps" / "gone.jpg")),
        ]
        outputs = [beauty, element, r"out\shot_Wire.exr"]
        found = {a.name: a for a in assets.make_assets(entries, [], outputs, bases=(str(self.root),))}
        self.assertEqual(found["wood.jpg"].status, "ok")
        self.assertEqual(found["gone.jpg"].status, "missing")
        for name in ("shot.exr", "shot_Z.exr", "shot_Wire.exr"):
            self.assertEqual(found[name].status, "output", name)
        self.assertFalse(found["shot.exr"].written)
        self.assertIsNone(found["shot.exr"].size)
        self.assertTrue(found["shot_Z.exr"].written)
        self.assertEqual(found["shot_Wire.exr"].size, os.path.getsize(relative))
        # not counted among the missing files, never collected
        self.assertEqual([a.name for a in found.values() if a.status == "missing"], ["gone.jpg"])
        self.assertEqual([a.name for a in found.values() if a.status == "ok"], ["wood.jpg"])

    def test_human_size(self):
        self.assertEqual(assets.human_size(512), "512 B")
        self.assertEqual(assets.human_size(2048), "2.0 KB")
        self.assertEqual(assets.human_size(None), "")


if __name__ == "__main__":
    unittest.main()
