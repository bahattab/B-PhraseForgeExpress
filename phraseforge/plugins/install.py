"""Reading and installing a plugin package (FR-PLG-01, FR-PLG-08).

inspect(src) reads the manifest of a folder or .pfplugin zip without running anything and
without unpacking anything yet. install(src, dest_root) copies it into dest_root/<id>: zip
entries are checked first (no absolute paths, no "..", no links, size and count limits), the
copy goes to a temporary folder and only then replaces the old version.
"""
from __future__ import annotations

import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from phraseforge.plugins.manifest import Manifest, ManifestError, parse

MAX_FILES = 2000
MAX_BYTES = 200 * 1024 * 1024
MANIFEST = "plugin.toml"


def _zip_root(names: list[str]) -> str:
    """"" when plugin.toml is at the top, "x/" when everything sits in one folder x/."""
    if MANIFEST in names:
        return ""
    tops = {n.split("/", 1)[0] for n in names if n}
    if len(tops) == 1:
        top = next(iter(tops)) + "/"
        if top + MANIFEST in names:
            return top
    raise ManifestError("the package has no plugin.toml")


def _check_zip(z: zipfile.ZipFile) -> str:
    infos = z.infolist()
    if len(infos) > MAX_FILES:
        raise ManifestError(f"the package holds more than {MAX_FILES} files")
    total = 0
    for i in infos:
        name = i.filename
        p = PurePosixPath(name)
        if name.startswith(("/", "\\")) or (p.parts and ":" in p.parts[0]) or ".." in p.parts or "\\" in name:
            raise ManifestError(f"unsafe path in package: {name}")
        if stat.S_ISLNK(i.external_attr >> 16):
            raise ManifestError(f"the package contains a link: {name}")
        total += i.file_size
        if total > MAX_BYTES:
            raise ManifestError("the package is too large")
    return _zip_root([i.filename for i in infos])


def inspect(src: str | Path) -> Manifest:
    src = Path(src)
    if src.is_dir():
        f = src / MANIFEST
        if not f.is_file():
            raise ManifestError("the folder has no plugin.toml")
        m = parse(f.read_text(encoding="utf-8-sig"))
        if not (src / m.entry).is_file():
            raise ManifestError(f"entry {m.entry} is not in the plugin")
        return m
    if not zipfile.is_zipfile(src):
        raise ManifestError("not a plugin folder or .pfplugin package")
    with zipfile.ZipFile(src) as z:
        root = _check_zip(z)
        m = parse(z.read(root + MANIFEST).decode("utf-8-sig"))
        if root + m.entry not in z.namelist():
            raise ManifestError(f"entry {m.entry} is not in the plugin")
        return m


def install(src: str | Path, dest_root: str | Path) -> Manifest:
    """Copy the plugin into dest_root/<id> (replacing an older version). The caller asks for
    consent first."""
    src, dest_root = Path(src), Path(dest_root)
    m = inspect(src)
    dest_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{m.id}-", dir=dest_root))
    try:
        if src.is_dir():
            shutil.copytree(src, stage / "p", symlinks=False,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
        else:
            with zipfile.ZipFile(src) as z:
                root = _check_zip(z)
                out = stage / "p"
                for i in z.infolist():
                    if i.is_dir() or not i.filename.startswith(root):
                        continue
                    rel = i.filename[len(root):]
                    target = out.joinpath(*PurePosixPath(rel).parts)
                    if out.resolve() not in target.resolve().parents:
                        raise ManifestError(f"unsafe path in package: {i.filename}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(i) as r, open(target, "wb") as w:
                        shutil.copyfileobj(r, w)
        final = dest_root / m.id
        old = dest_root / f".{m.id}.old"
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
        if final.exists():
            final.rename(old)
        (stage / "p").rename(final)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return m


def uninstall(plugin_id: str, dest_root: str | Path) -> None:
    d = Path(dest_root) / plugin_id
    if d.is_dir() and d.parent == Path(dest_root):
        shutil.rmtree(d)
