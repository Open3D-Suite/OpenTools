# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene asset management: list, relink, clean, collect and package external files.

Built on 3ds Max's own Asset Tracking (ATSOps), so every file a plugin registers
(bitmaps of any renderer, proxies, IES, HDRI, LUTs, caches, XRefs...) is covered
without per-class code.

Independent implementation of the features found in Relink Bitmaps (Colin Senner) and
Collect Asset (antomor / Xiruim); written from their public feature lists only.

The file-system helpers at the top are pure Python (tested outside Max). Everything
that needs 3ds Max imports pymxs lazily. Usable from scripts too, e.g.:

    from opentools import assets
    found = assets.scan()
    assets.relink_missing([r"\\\\nas\\textures"], ignore_extension=True)
    assets.collect(r"D:\\job\\maps", copy_scene=True)
"""

import hashlib
import os
import re
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

SCENE_OWNER = "(scene)"  # files used by the environment, render settings, etc.


# =========================================================== pure helpers
def norm(path):
    """Comparable form of a path (case-insensitive, normalised separators)."""
    return os.path.normcase(os.path.normpath(str(path)))


def path_keys(path, bases=()):
    """The comparable forms (see norm) of a file's path: the path itself and, when it is relative, the path rooted
    at each folder of `bases`, where 3ds Max looks for it first (the project folder, then the scene's folder)."""
    path = str(path or "")
    if not path:
        return set()
    keys = {norm(path)}
    if not os.path.isabs(path):
        keys.update(norm(os.path.join(str(base), path)) for base in bases if base)
    return keys


def match_owners(files, owner_pairs, bases=()):
    """The objects that use each file: one sorted list of names per file.

    files: [(path as stored, resolved path)] from Asset Tracking. owner_pairs: [(path, object name)] from
    ATSOps.GetDependencyFileList, which gives the path where 3ds Max found the file (absolute) and the stored one
    only when it found none. So a file is matched by its stored path, its resolved path and, when it is relative,
    the path rooted at `bases`."""
    owners = {}
    for dep, name in owner_pairs:
        owners.setdefault(norm(dep), set()).add(str(name))
    out = []
    for path, resolved in files:
        names = set()
        for key in path_keys(path, bases) | path_keys(resolved, bases):
            names |= owners.get(key, set())
        out.append(sorted(names))
    return out


def changed_paths(sent, after):
    """The paths of `sent` that are no longer in `after`, the scene's file list once they were changed: the ones
    that really changed. A path that only differs in case or separators has not changed."""
    left = {norm(p) for p in after}
    return [p for p in sent if norm(p) not in left]


def human_size(size):
    if size is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return ("%d %s" if unit == "B" else "%.1f %s") % (size, unit)
        size /= 1024.0
    return ""


def build_index(folders, recursive=True, should_stop=None):
    """{'names': {name.lower(): [paths]}, 'stems': {stem.lower(): [paths]}} for the folders."""
    names, stems = {}, {}
    seen = set()
    for folder in folders:
        folder = str(folder)
        if not os.path.isdir(folder):
            continue
        walker = os.walk(folder) if recursive else [(folder, [], os.listdir(folder))]
        for root, _dirs, files in walker:
            if should_stop is not None and should_stop():
                return {"names": names, "stems": stems}
            for name in files:
                full = os.path.join(root, name)
                key = norm(full)
                if key in seen or not os.path.isfile(full):
                    continue
                seen.add(key)
                names.setdefault(name.lower(), []).append(full)
                stems.setdefault(os.path.splitext(name)[0].lower(), []).append(full)
    return {"names": names, "stems": stems}


def candidates(missing, index, ignore_extension=False):
    """Files in the index that could replace `missing` (same name, or same stem)."""
    base = os.path.basename(str(missing).replace("/", "\\"))
    found = list(index["names"].get(base.lower(), []))
    if ignore_extension:
        stem = os.path.splitext(base)[0].lower()
        for path in index["stems"].get(stem, []):
            if path not in found:
                found.append(path)
    return found


_hash_cache = {}


def file_hash(path):
    """SHA-1 of a file (cached per path + size + mtime)."""
    stat = os.stat(path)
    key = (norm(path), stat.st_size, stat.st_mtime)
    if key not in _hash_cache:
        digest = hashlib.sha1(usedforsecurity=False)  # only tells identical files apart
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        _hash_cache[key] = digest.hexdigest()
    return _hash_cache[key]


def same_content(a, b):
    try:
        if norm(a) == norm(b):
            return True
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        return file_hash(a) == file_hash(b)
    except OSError:
        return False


def pick(missing, found):
    """Choose a replacement among candidates.

    Returns (path or None, ambiguous). Identical copies count as one; a file with the
    same extension as the missing one wins over one that only shares the stem.
    """
    if not found:
        return None, False
    ext = os.path.splitext(str(missing))[1].lower()
    same_ext = [p for p in found if os.path.splitext(p)[1].lower() == ext]
    pool = same_ext or found
    distinct = []
    for path in pool:
        if not any(same_content(path, other) for other in distinct):
            distinct.append(path)
    if len(distinct) == 1:
        return distinct[0], False
    return None, True


# A compact table, kept out of the formatter: it would put every letter on its own line.
# fmt: off
_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya", "і": "i", "ї": "yi", "є": "ye",
    "ґ": "g",
}
# fmt: on


def transliterate(name):
    """ASCII-only version of a file name: Cyrillic is transliterated, accents dropped,
    anything else replaced. 'Текстура_дерево.jpg' -> 'Tekstura_derevo.jpg'."""
    stem, ext = os.path.splitext(name)
    out = []
    for char in stem:
        lower = char.lower()
        if lower in _CYRILLIC:
            latin = _CYRILLIC[lower]
            out.append(latin.capitalize() if char != lower and latin else latin)
            continue
        decomposed = unicodedata.normalize("NFKD", char)
        ascii_part = decomposed.encode("ascii", "ignore").decode("ascii")
        out.append(ascii_part if ascii_part else "_")
    clean = re.sub(r"_+", "_", "".join(out)).strip(" _") or "file"
    return clean + ext.encode("ascii", "ignore").decode("ascii")


def needs_transliteration(name):
    try:
        name.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def ifl_frames(ifl_path):
    """Image files listed in an .ifl sequence (resolved next to the .ifl when relative)."""
    frames = []
    try:
        lines = Path(ifl_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return frames
    folder = os.path.dirname(str(ifl_path))
    for line in lines:
        entry = line.strip()
        if not entry or entry.startswith(";"):
            continue
        entry = re.sub(r"\s+\d+$", "", entry)  # optional repeat count after the name
        path = entry if os.path.isabs(entry) else os.path.join(folder, entry)
        if path not in frames:
            frames.append(path)
    return frames


@dataclass
class CopyStep:
    source: str
    target: str
    action: str  # "copy", "reuse" (identical file already there) or "missing"


def plan_collect(sources, destination, ascii_names=False):
    """Decide where each source file goes in `destination`.

    Same name + same content -> one copy is reused. Same name + different content ->
    the newcomer gets a numbered name (wood.jpg, wood_2.jpg...). Returns [CopyStep].
    """
    destination = str(destination)
    taken = {}  # lower target name -> source it holds
    steps = []
    for source in sources:
        source = str(source)
        if not os.path.isfile(source):
            steps.append(CopyStep(source, "", "missing"))
            continue
        name = os.path.basename(source)
        if ascii_names and needs_transliteration(name):
            name = transliterate(name)
        stem, ext = os.path.splitext(name)
        number = 1
        while True:
            candidate = name if number == 1 else "%s_%d%s" % (stem, number, ext)
            target = os.path.join(destination, candidate)
            holder = taken.get(candidate.lower())
            if holder is None and os.path.isfile(target):
                holder = target  # already in the folder from an earlier collect
            if holder is None:
                taken[candidate.lower()] = source
                steps.append(CopyStep(source, target, "copy"))
                break
            if same_content(holder, source):
                steps.append(CopyStep(source, target, "reuse"))
                break
            number += 1
    return steps


def zip_folder(folder, zip_path, should_stop=None):
    folder = Path(folder)
    zip_path = Path(zip_path)
    tmp = zip_path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for path in sorted(folder.rglob("*")):
            if should_stop is not None and should_stop():
                break
            if path.is_file() and path != tmp and path != zip_path:
                archive.write(path, path.relative_to(folder.parent))
    os.replace(tmp, zip_path)
    return zip_path


# =========================================================== 3ds Max side
@dataclass
class Asset:
    path: str  # as stored in the scene
    status: str  # "ok", "missing" or "output" (a file the render writes, see make_assets)
    resolved: str = ""  # where 3ds Max actually finds it (map paths, etc.)
    owners: list = field(default_factory=list)  # node names, or SCENE_OWNER
    size: int = None
    written: bool = False  # an output that a render already wrote

    @property
    def name(self):
        return os.path.basename(self.path.replace("/", "\\"))

    @property
    def folder(self):
        return os.path.dirname(self.path.replace("/", "\\"))

    @property
    def found_elsewhere(self):
        return self.status == "ok" and self.resolved and norm(self.resolved) != norm(self.path)

    @property
    def is_xref(self):
        return self.path.lower().endswith(".max")


_SCAN_MS = r"""
(
    -- An unsaved scene has no file name but may still have a folder (its template's).
    local sceneFile = if maxFileName == "" then "" else maxFilePath + maxFileName
    local wasExcluded = ATSOps.ExcludeOutputFiles
    ATSOps.ExcludeOutputFiles = true
    ATSOps.Refresh()
    local files = #()
    ATSOps.GetFiles &files
    ATSOps.ExcludeOutputFiles = wasExcluded
    local resolved = #()
    ATSOps.GetResolvedPaths files &resolved
    local result = #()
    -- The first entry of Asset Tracking is the scene itself (or the template it was
    -- created from, for an unsaved scene): never an asset to relink or collect.
    local first = if sceneFile == "" and files.count > 0 and matchPattern files[1] pattern:"*.max" then 1 else 0
    for i = 1 to files.count where i != first and files[i] != "" and (sceneFile == "" or (toLower files[i]) != (toLower sceneFile)) do
    (
        local st = (ATSOps.GetFileSystemStatus files[i]) as string
        local r = if resolved[i] != undefined then resolved[i] else ""
        append result #(files[i], st, r)
    )
    local owners = #()
    for n in (if %(selected)s then (selection as array) else (objects as array)) do
    (
        local deps = #()
        ATSOps.GetDependencyFileList n &deps true
        for d in deps do append owners #(d, n.name)
    )
    #(result, owners)
)
"""  # noqa: E501 - a line of MAXScript inside the string is longer


def locate(path, resolved="", bases=()):
    """Where a file is on disk: the first that exists of its resolved path, its path and, when that is relative,
    the path rooted at each folder of `bases`; "" when none does."""
    path, resolved = str(path or ""), str(resolved or "")
    places = [resolved, path]
    if path and not os.path.isabs(path):
        places += [os.path.join(str(base), path) for base in bases if base]
    for place in places:
        if place and os.path.isabs(place) and os.path.isfile(place):
            return place
    return ""


def make_assets(entries, owner_pairs, outputs=(), bases=(), selected_only=False, include_xrefs=True):
    """The Asset of each file Asset Tracking lists. entries: [(path as stored, Asset Tracking's status, resolved
    path)]; owner_pairs and bases: see match_owners.

    outputs: the files the scene's render writes (see render_outputs). Asset Tracking lists them too and calls them
    found even before a render wrote them; here their status is "output", so they are neither collected nor counted
    among the missing files, and `written` says whether a render already wrote them."""
    files = [(str(e[0]), str(e[1]).lower(), str(e[2])) for e in entries]
    owners = match_owners([(f[0], f[2]) for f in files], owner_pairs, bases)
    output_keys = set()
    for output in outputs:
        output_keys |= path_keys(output, bases)
    assets = []
    for (path, status, resolved), node_owners in zip(files, owners, strict=True):
        if selected_only and not node_owners:
            continue
        if output_keys & (path_keys(path, bases) | path_keys(resolved, bases)):
            status = "output"
        else:
            status = "missing" if "missing" in status else "ok"
        asset = Asset(path=path, status=status, resolved=resolved, owners=node_owners or [SCENE_OWNER])
        if not include_xrefs and asset.is_xref:
            continue
        if status == "output":
            real = locate(path, resolved, bases)
            asset.written = bool(real)
        else:
            real = (asset.resolved or asset.path) if status == "ok" else ""
        try:
            asset.size = os.path.getsize(real) if real else None
        except OSError:
            asset.size = None
        assets.append(asset)
    assets.sort(key=lambda a: (a.status != "missing", a.name.lower()))
    return assets


def scan(selected_only=False, include_xrefs=True):
    """Every external file of the scene (or of the selected objects) with its status."""
    from pymxs import runtime as rt

    files, owner_pairs = rt.execute(_SCAN_MS % {"selected": "true" if selected_only else "false"})
    # a relative path is looked for in the project folder first, then in the scene's folder
    bases = (str(rt.pathConfig.getCurrentProjectFolder() or ""), str(rt.maxFilePath or ""))
    return make_assets(
        files,
        [(str(p[0]), str(p[1])) for p in owner_pairs],
        outputs=render_outputs(),
        bases=bases,
        selected_only=selected_only,
        include_xrefs=include_xrefs,
    )


def render_outputs():
    """The files the scene's render writes: the render output and the file of each render element."""
    from pymxs import runtime as rt

    outputs = [str(rt.rendOutputFilename or "")]
    manager = rt.maxOps.GetCurRenderElementMgr()
    if manager is not None:
        for i in range(manager.NumRenderElements()):
            outputs.append(str(manager.GetRenderElementFilename(i) or ""))
    return [p for p in outputs if p]


def retarget(mapping):
    """Point every use of old path -> new path (whole scene: materials, environment,
    render settings...). Returns the number of paths changed."""
    from pymxs import runtime as rt

    from . import maxhost

    changed = 0
    with maxhost.quiet():  # a corrupt file must not stop everything with a dialog
        for old, new in mapping.items():
            if old == new:
                continue
            rt.ATSOps.RetargetAssets(rt.rootScene, str(old), str(new))
            changed += 1
        rt.ATSOps.Refresh()
    return changed


def relink_missing(folders, recursive=True, ignore_extension=False, assets=None, choices=None, should_stop=None):
    """Find every missing file in `folders` and relink it.

    choices: {missing path: chosen path} for files that had several different candidates.
    Returns {"relinked": {old: new}, "ambiguous": {old: [candidates]}, "not_found": [old]}.
    """
    if assets is None:
        assets = scan()
    missing = [a for a in assets if a.status == "missing"]
    index = build_index(folders, recursive=recursive, should_stop=should_stop)
    relinked, ambiguous, not_found = {}, {}, []
    for asset in missing:
        if choices and asset.path in choices:
            relinked[asset.path] = choices[asset.path]
            continue
        found = candidates(asset.path, index, ignore_extension)
        chosen, is_ambiguous = pick(asset.path, found)
        if chosen:
            relinked[asset.path] = chosen
        elif is_ambiguous:
            ambiguous[asset.path] = found
        else:
            not_found.append(asset.path)
    retarget(relinked)
    return {"relinked": relinked, "ambiguous": ambiguous, "not_found": not_found}


def strip_paths(paths):
    """Keep only the file name (3ds Max then looks in the map paths)."""
    return retarget({p: os.path.basename(str(p).replace("/", "\\")) for p in paths})


_FILES_MS = r"""
(
    local wasExcluded = ATSOps.ExcludeOutputFiles
    ATSOps.ExcludeOutputFiles = true
    ATSOps.Refresh()
    local files = #()
    ATSOps.GetFiles &files
    ATSOps.ExcludeOutputFiles = wasExcluded
    files
)
"""


def resolve_paths(paths, mode):
    """mode: 'relative' (to the project folder), 'absolute' or 'unc'. Returns the number of paths that changed:
    3ds Max leaves alone a path it cannot change (a file of a local disk has no UNC path)."""
    from pymxs import runtime as rt

    paths = [str(p) for p in paths]
    rt.ATSOps.Refresh()
    rt.ATSOps.ClearSelection()
    rt.ATSOps.SelectFiles(rt.Array(*paths))
    action = {
        "relative": rt.ATSOps.ResolveSelectionRelativeToProjectFolder,
        "absolute": rt.ATSOps.ResolveSelectionToAbsolute,
        "unc": rt.ATSOps.ResolveSelectionToUNC,
    }[mode]
    action()
    rt.ATSOps.ClearSelection()
    after = [str(f) for f in rt.execute(_FILES_MS)]  # the same list as scan's, read after a Refresh
    return len(changed_paths(paths, after))


def clear_render_element_paths():
    """Empty the output path of every render element. Returns how many were set."""
    from pymxs import runtime as rt

    manager = rt.maxOps.GetCurRenderElementMgr()
    count = 0
    for i in range(manager.NumRenderElements()):
        if str(manager.GetRenderElementFilename(i) or ""):
            manager.SetRenderElementFilename(i, "")
            count += 1
    return count


def select_owners(asset):
    from pymxs import runtime as rt

    nodes = [rt.getNodeByName(name, exact=True) for name in asset.owners if name != SCENE_OWNER]
    nodes = [n for n in nodes if n is not None]
    rt.clearSelection()
    if nodes:
        rt.select(rt.Array(*nodes))
    rt.redrawViews()
    return len(nodes)


def save_scene_copy(target, version=0, selected_only=False):
    """Save a copy of the scene (or only the selection) without changing the open file."""
    from pymxs import runtime as rt

    from . import maxhost

    target = str(target)
    year = maxhost.max_year()
    kwargs = {"quiet": True}
    if version and year and version < year:
        kwargs["saveAsVersion"] = version
    with maxhost.quiet():
        if selected_only:
            rt.saveNodes(rt.getCurrentSelection(), target, **kwargs)
        else:
            rt.saveMaxFile(target, clearNeedSaveFlag=False, useNewFile=False, **kwargs)
    return target


def collect(
    destination,
    assets=None,
    selected_only=False,
    include_xrefs=True,
    ascii_names=False,
    relink=True,
    copy_scene=False,
    scene_version=0,
    make_zip=False,
    progress=None,
    should_stop=None,
):
    """Copy the scene's files into `destination` and (optionally) relink to the copies.

    copy_scene saves a copy of the .max next to the files, pointing at the copies;
    make_zip zips the folder afterwards. progress(done, total, text) is called while copying.
    Returns a report dict.
    """
    from . import maxhost

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if assets is None:
        assets = scan(selected_only=selected_only, include_xrefs=include_xrefs)
    usable = [a for a in assets if a.status == "ok"]
    sources = [a.resolved or a.path for a in usable]
    extra = []
    for source in sources:
        if source.lower().endswith(".ifl"):
            extra.extend(f for f in ifl_frames(source) if os.path.isfile(f))
    steps = plan_collect(sources + extra, destination, ascii_names=ascii_names)
    copied = reused = 0
    stopped = False
    for i, step in enumerate(steps):
        if should_stop is not None and should_stop():
            stopped = True
            break
        if progress is not None:
            progress(i, len(steps), os.path.basename(step.source))
        if step.action == "copy":
            shutil.copy2(step.source, step.target)
            copied += 1
        elif step.action == "reuse":
            reused += 1
    mapping = {}
    for asset, step in zip(usable, steps[: len(usable)], strict=False):
        if step.action in ("copy", "reuse") and norm(asset.path) != norm(step.target):
            mapping[asset.path] = step.target
    report = {
        "copied": copied,
        "reused": reused,
        "stopped": stopped,
        "missing": [a.path for a in assets if a.status == "missing"],
        "folder": str(destination),
        "scene_copy": "",
        "zip": "",
    }
    if stopped:
        return report

    from pymxs import runtime as rt

    def save_copy():
        name = str(rt.maxFileName) or "untitled_scene.max"
        if selected_only:
            name = os.path.splitext(name)[0] + "_selection.max"
        report["scene_copy"] = save_scene_copy(destination / name, version=scene_version, selected_only=selected_only)

    if relink:
        if mapping:
            with maxhost.undo("Collect Assets"):
                retarget(mapping)
        if copy_scene:
            save_copy()
    elif copy_scene:
        # The copy must point at the collected files, the open scene must not:
        # relink, save the copy, then undo the relink (retargeting is undoable).
        if mapping:
            try:
                with maxhost.undo("Collect Assets (copy only)"):
                    retarget(mapping)
                save_copy()
            finally:
                rt.execute("max undo")
                rt.ATSOps.Refresh()
        else:
            save_copy()
    report["relinked"] = len(mapping) if relink else 0
    if make_zip:
        report["zip"] = str(zip_folder(destination, destination.with_suffix(".zip"), should_stop))
    return report
