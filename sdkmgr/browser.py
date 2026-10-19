import os
import platform
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock, Timeout

from .archives import extract_zip
from .artifacts import Artifact, ArtifactCache
from .errors import SDKError
from .installation import executable_path
from .providers import Platform

VERSION = "155.0.8059.84"
# SHA-256 of the official Chrome for Testing archives, not publisher signatures.
ARCHIVES = {
    "linux-x64": ("linux64", "cf0f049892dea22e6a6db26d47ed0d7776b7158edcbec4634086633df8bafcbc"),
    "linux-arm64": ("linux-arm64", "1692a407908867de88eb1f1b2a93ca47c348d8fb2e3c04752d966e0f2e0344b4"),
    "macos-arm64": ("mac-arm64", "13b9e98ce56f5ce18e100a009f455c9285f399e7c9dc8a76fdf2f3a9755bb5f2"),
    "macos-x64": ("mac-x64", "d805a173118daa5f6f5cf464500789e1e00022a9a6aed8abfec821ab828fa862"),
    "windows-x64": ("win64", "507f2a031441d10c62b5e3d4e863f09ac1198a571c1419976cbd8387f639afde"),
}


@dataclass(frozen=True)
class BrowserInstallation:
    """A discovered browser; only managed copies have a known version.

    Discovery checks executable files but never launches a browser. Installed
    OS libraries, runtime compatibility, profiles and processes belong to callers.
    """

    path: Path
    platform: Platform
    version: str | None = None
    managed: bool = False

    def executable(self) -> Path:
        return self.path


def _locations(host: Platform):
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        if path := shutil.which(name):
            yield Path(path)
    if host.system == "linux":
        yield Path("/snap/bin/chromium")
    elif host.system == "macos":
        for base in (Path("/Applications"), Path.home() / "Applications"):
            for app in ("Google Chrome", "Chromium", "Google Chrome for Testing"):
                yield base / f"{app}.app/Contents/MacOS/{app}"
    elif host.system == "windows":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if base := os.environ.get(variable):
                yield Path(base) / "Google/Chrome/Application/chrome.exe"


def _executable(path: Path, host: Platform) -> bool:
    return path.is_file() and (host.system == "windows" or os.access(path, os.X_OK))


def _managed_path(root: Path, host: Platform):
    if host.tag not in ARCHIVES:
        raise SDKError(f"No pinned Chrome for Testing provider for {host.tag}; supply a browser explicitly.")
    if host.system == "linux" and platform.libc_ver()[0].lower() == "musl":
        raise SDKError("Chrome for Testing requires glibc; install a compatible Chromium and set CHROME_BIN.")
    asset, digest = ARCHIVES[host.tag]
    directory = root / "tools/chrome" / VERSION / asset
    relative = "chrome.exe" if host.system == "windows" else "chrome"
    if host.system == "macos":
        relative = "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
    return directory, Path(f"chrome-{asset}") / relative, asset, digest


def _cached(directory: Path, relative: Path, host: Platform):
    if not directory.exists():
        return None
    path = directory / relative
    if not _executable(path, host):
        raise SDKError(f"Incomplete Chrome installation at {directory}; move it aside and retry.")
    return BrowserInstallation(path, host, VERSION, managed=True)


def find(root: Path, host: Platform, *, executable=None, managed: bool = False):
    if managed and executable is not None:
        raise SDKError("Choose a pinned managed browser or an explicit executable, not both.")
    try:
        if not managed:
            configured = executable if executable is not None else os.environ.get("CHROME_BIN")
            if configured is not None:
                path = executable_path(configured)
                if not _executable(path, host):
                    raise SDKError(f"Configured Chrome executable is unavailable: {configured!r}.")
                return BrowserInstallation(path, host)
            for path in _locations(host):
                if _executable(path, host):
                    return BrowserInstallation(path.absolute(), host)
            if host.tag not in ARCHIVES:
                return None
        directory, relative, _, _ = _managed_path(root, host)
        return _cached(directory, relative, host)
    except OSError as error:
        raise SDKError(f"Cannot inspect Chrome installation: {error}") from error


def ensure(root: Path, host: Platform, *, executable=None, managed: bool = False):
    if existing := find(root, host, executable=executable, managed=managed):
        return existing
    directory, relative, asset, digest = _managed_path(root, host)
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(directory.parent / f".{asset}.lock", timeout=600):
            if existing := _cached(directory, relative, host):
                return existing
            filename = f"chrome-{asset}.zip"
            url = f"https://storage.googleapis.com/chrome-for-testing-public/{VERSION}/{asset}/{filename}"
            print(f"Installing Chrome for Testing {VERSION} ({asset})...", file=sys.stderr)
            archive = ArtifactCache(root).ensure(Artifact(url, digest, filename))
            with tempfile.TemporaryDirectory(prefix=".install-", dir=directory.parent) as temporary:
                staged = Path(temporary) / "payload"
                extract_zip(archive, staged, root=f"chrome-{asset}", symlinks=host.system == "macos")
                if not _executable(staged / relative, host):
                    raise SDKError("Chrome archive is missing its executable.")
                staged.replace(directory)
            return _cached(directory, relative, host)
    except Timeout as error:
        raise SDKError("Timed out waiting for Chrome installation; retry later.") from error
    except (OSError, UnicodeError, zipfile.BadZipFile) as error:
        raise SDKError(f"Could not install Chrome: {error}") from error
