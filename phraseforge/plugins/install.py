"""Reading and installing a plugin package (FR-PLG-01, FR-PLG-08).

inspect(src) reads the manifest of a folder or .pfplugin zip without running anything and
without unpacking anything yet. install(src, dest_root) copies it into dest_root/<id>: zip
entries are checked first (no absolute paths, no "..", no links, size and count limits), the
copy goes to a temporary folder and only then replaces the old version.
"""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from phraseforge.plugins.manifest import Manifest, ManifestError, parse

MAX_FILES = 2000
MAX_BYTES = 200 * 1024 * 1024
MANIFEST = "plugin.toml"
# Windows file names that are devices (CON, NUL, COM1, ...), with or without an extension
_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


def _bad_part(part: str) -> bool:
    """A path part Windows would read differently from Linux (security R104)."""
    return (":" in part or part.endswith((".", " ")) or part.split(".", 1)[0].lower() in _RESERVED
            or any(ord(c) < 32 for c in part))


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
    seen: set[str] = set()
    for i in infos:
        name = i.filename
        p = PurePosixPath(name)
        if (name.startswith(("/", "\\")) or ".." in p.parts or "\\" in name
                or any(_bad_part(x) for x in p.parts)):
            raise ManifestError(f"unsafe path in package: {name}")
        key = name.rstrip("/").casefold()           # PLUGIN.TOML would overwrite plugin.toml on Windows
        if key in seen:
            raise ManifestError(f"two files with the same name in package: {name}")
        seen.add(key)
        if stat.S_ISLNK(i.external_attr >> 16):
            raise ManifestError(f"the package contains a link: {name}")
        total += i.file_size
        if total > MAX_BYTES:
            raise ManifestError("the package is too large")
    return _zip_root([i.filename for i in infos])


def _check_folder(src: Path) -> None:
    """No links or junctions (they would copy files from elsewhere on the PC), same limits as zips."""
    count = total = 0
    for root, dirs, files in os.walk(src, followlinks=False):
        for name in dirs + files:
            p = Path(root) / name
            if p.is_symlink() or _is_junction(p):
                raise ManifestError(f"the plugin folder contains a link: {p.relative_to(src)}")
        for name in files:
            count += 1
            total += (Path(root) / name).stat().st_size
            if count > MAX_FILES:
                raise ManifestError(f"the plugin holds more than {MAX_FILES} files")
            if total > MAX_BYTES:
                raise ManifestError("the plugin is too large")


def _is_junction(p: Path) -> bool:
    try:
        return bool(getattr(os.lstat(p), "st_file_attributes", 0) & 0x400)   # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return False


def inspect(src: str | Path) -> Manifest:
    """Every way a package can be broken gives a ManifestError (R103)."""
    try:
        return _inspect(Path(src))
    except ManifestError:
        raise
    except (UnicodeDecodeError, zipfile.BadZipFile, KeyError, OSError, ValueError, RuntimeError) as e:
        raise ManifestError(f"the plugin cannot be read: {e}") from e


def _inspect(src: Path) -> Manifest:
    if src.is_symlink():
        raise ManifestError("the plugin folder is a link")
    if src.is_dir():
        _check_folder(src)
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


def signature(src: str | Path, trusted=frozenset()):
    """signing.Signature of a plugin folder or package, without installing it (shown at consent)."""
    from phraseforge.plugins import signing
    src = Path(src)
    if src.is_dir():
        _check_folder(src)
        return signing.verify(signing.folder_files(src), trusted)
    with zipfile.ZipFile(src) as z:
        root = _check_zip(z)
        files = {i.filename[len(root):]: z.read(i) for i in z.infolist()
                 if not i.is_dir() and i.filename.startswith(root)
                 and not set(PurePosixPath(i.filename).parts) & {"__pycache__", ".git"}
                 and not i.filename.endswith(".pyc")}
    return signing.verify(files, trusted)


def install(src: str | Path, dest_root: str | Path, trusted=frozenset(), require_signed: bool = False) -> Manifest:
    """Copy the plugin into dest_root/<id> (replacing an older version). The caller asks for
    consent first. A plugin whose plugin.sig does not match its files is refused; with
    require_signed (policy) so is one not signed by a trusted key. The check runs on the copied
    files, so what is verified is exactly what gets installed."""
    src, dest_root = Path(src), Path(dest_root)
    m = inspect(src)
    dest_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{m.id}-", dir=dest_root))
    try:
        if src.is_dir():
            shutil.copytree(src, stage / "p", symlinks=True,          # links were refused above
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
        from phraseforge.plugins import signing
        sig = signing.verify(signing.folder_files(stage / "p"), trusted)
        if sig.state == "invalid":
            raise ManifestError(f"the plugin's signature is not valid: {sig.reason}")
        if require_signed and sig.state != "trusted":
            raise ManifestError("this PC only installs plugins signed by a trusted publisher")
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
    from phraseforge.plugins.manifest import valid_id
    if not valid_id(plugin_id):                     # never "..", never a path (R105)
        return
    root = Path(dest_root).resolve()
    d = (root / plugin_id).resolve()
    if d.is_dir() and d.parent == root:
        shutil.rmtree(d)


def stage(src: str | Path) -> Path:
    """A private copy of the package, made once before the user is asked: what is shown is
    what gets installed, even if the file on a share changes meanwhile (R99)."""
    src = Path(src)
    inspect(src)                                     # refuse links and oversize before copying
    tmp = Path(tempfile.mkdtemp(prefix="pf-plugin-"))
    if src.is_dir():
        shutil.copytree(src, tmp / "p", symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
        return tmp / "p"
    shutil.copyfile(src, tmp / "p.pfplugin")
    return tmp / "p.pfplugin"


def unstage(path: str | Path) -> None:
    p = Path(path)
    if p.parent.name.startswith("pf-plugin-"):
        shutil.rmtree(p.parent, ignore_errors=True)
