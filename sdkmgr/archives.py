"""Staged ZIP extraction, including contained macOS framework symlinks."""

import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from .errors import SDKError


def extract_zip(archive: Path, destination: Path, *, root: str, symlinks: bool = False):
    """Extract into a fresh staging directory, never into a live installation."""
    destination.mkdir()
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > 20000 or sum(p.file_size for p in entries) > 2 * 1024 ** 3:
            raise SDKError("Tool archive exceeds extraction limits.")
        names = set()
        links = []
        for entry in entries:
            path = PurePosixPath(entry.filename)
            original = entry.orig_filename
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if (
                path.is_absolute() or ".." in path.parts or not path.parts
                or path.parts[0] != root or "\\" in original or "\x00" in original
                or ":" in original or path in names
                or kind not in {0, stat.S_IFREG, stat.S_IFDIR, stat.S_IFLNK}
                or (stat.S_ISLNK(mode) and (not symlinks or entry.file_size > 4096 or len(path.parts) == 1))
            ):
                raise SDKError(f"Unsafe tool archive member: {original!r}.")
            names.add(path)
            target = destination.joinpath(*path.parts)
            if stat.S_ISLNK(mode):
                link = source.read(entry).decode("utf-8")
                if (not link or PurePosixPath(link).is_absolute()
                        or "\\" in link or "\x00" in link or ":" in link):
                    raise SDKError(f"Unsafe tool archive symlink: {original!r}.")
                links.append((target, link))
            elif entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                target.chmod(0o755 if mode & 0o111 else 0o644)
        # Creating links last prevents any archived file from writing through one.
        link_paths = {target for target, _ in links}
        for target, _ in links:
            if any(parent in link_paths for parent in target.parents):
                raise SDKError(f"Tool archive nests a member under a symlink: {target.name!r}.")
        for target, link in links:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(link)
        boundary = (destination / root).resolve()
        for target, _ in links:
            try:
                resolved = target.resolve(strict=True)
            except (OSError, RuntimeError) as error:
                raise SDKError(f"Invalid tool archive symlink: {target.name!r}.") from error
            if not resolved.is_relative_to(boundary):
                raise SDKError(f"Tool archive symlink escapes its root: {target.name!r}.")
