import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from filelock import FileLock, Timeout

from .download import fetch
from .errors import SDKError
from .installation import ToolInstallation, executable_path
from .providers import Platform, linux_libc


def validate_version(version: str):
    if not isinstance(version, str) or not re.fullmatch(r"[1-9][0-9]*\.[0-9]+\.[0-9]+", version):
        raise SDKError("Tailwind requires an exact release version, for example 4.3.3.")


def asset_name(host: Platform) -> str:
    if host.system == "windows" and host.architecture != "x64":
        raise SDKError("No native Windows ARM64 Tailwind provider; supply a compatible executable explicitly.")
    variant = ""
    if host.system == "linux":
        libc = linux_libc()
        if libc == "musl":
            variant = "-musl"
        elif libc not in {"glibc", ""}:
            raise SDKError(f"Unsupported Linux C library for Tailwind: {libc}.")
    suffix = ".exe" if host.system == "windows" else ""
    return f"tailwindcss-{host.system}-{host.architecture}{variant}{suffix}"


def _version(path: Path) -> str | None:
    try:
        result = subprocess.run(
            [str(path), "--help"], check=True, capture_output=True, encoding="utf-8", errors="replace",
            timeout=15, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    output = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)
    match = re.search(r"\btailwindcss\s+v(\d+\.\d+\.\d+)(?![\w.-])", output)
    return match[1] if match else None


def _verify(path: Path, manifest: Path, asset: str):
    if not path.is_file() or not manifest.is_file():
        raise SDKError(f"Incomplete Tailwind files at {path.parent}.")
    if manifest.stat().st_size > 1024 * 1024:
        raise SDKError("Tailwind checksum manifest is too large.")
    matches = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?(.+)", line)
        if match and match[2].removeprefix("./") == asset:
            matches.append(match[1].lower())
    if len(matches) != 1:
        raise SDKError(f"Expected one SHA-256 entry for {asset}.")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != matches[0]:
        raise SDKError(f"SHA-256 mismatch for {path}.")


def _cached(directory: Path, host: Platform, version: str, asset: str) -> ToolInstallation | None:
    if not directory.exists():
        return None
    path = directory / ("tailwindcss.exe" if host.system == "windows" else "tailwindcss")
    try:
        _verify(path, directory / "sha256sums.txt", asset)
    except SDKError as error:
        raise SDKError(f"{error} Move {directory} aside and retry.") from error
    if _version(path) != version:
        raise SDKError(f"Cached Tailwind did not report requested version {version}.")
    return ToolInstallation("tailwindcss", version, path, host, managed=True)


def find(root: Path, host: Platform, version: str, *, executable=None) -> ToolInstallation | None:
    validate_version(version)
    configured = executable or os.environ.get("TAILWINDCSS")
    try:
        candidate = configured or shutil.which("tailwindcss")
        if candidate:
            path = executable_path(candidate)
            if path.is_file() and _version(path) == version:
                return ToolInstallation("tailwindcss", version, path, host)
            if configured:
                raise SDKError(f"Configured Tailwind {candidate} did not report version {version}.")
        asset = asset_name(host)
        return _cached(root / "tools/tailwindcss" / version / asset, host, version, asset)
    except (OSError, UnicodeError) as error:
        raise SDKError(f"Cannot inspect Tailwind installation: {error}") from error


def ensure(root: Path, host: Platform, version: str, *, executable=None) -> ToolInstallation:
    if existing := find(root, host, version, executable=executable):
        return existing
    asset = asset_name(host)
    directory = root / "tools/tailwindcss" / version / asset
    try:
        directory.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(directory.parent / f".{asset}.lock", timeout=120):
            if existing := _cached(directory, host, version, asset):
                return existing
            base = f"https://github.com/tailwindlabs/tailwindcss/releases/download/v{version}"
            print(f"Installing Tailwind {version} ({asset})...", file=sys.stderr)
            with tempfile.TemporaryDirectory(prefix=".install-", dir=directory.parent) as temporary:
                staged = Path(temporary) / "payload"
                staged.mkdir()
                binary = staged / ("tailwindcss.exe" if host.system == "windows" else "tailwindcss")
                manifest = staged / "sha256sums.txt"
                fetch(f"{base}/sha256sums.txt", manifest, limit=1024 * 1024)
                fetch(f"{base}/{asset}", binary, limit=256 * 1024 ** 2)
                _verify(binary, manifest, asset)
                binary.chmod(0o755)
                if _version(binary) != version:
                    raise SDKError(f"Downloaded Tailwind did not report version {version}.")
                os.replace(staged, directory)
            result = _cached(directory, host, version, asset)
            assert result is not None
            return result
    except Timeout as error:
        raise SDKError("Timed out waiting for Tailwind installation; retry later.") from error
    except (OSError, UnicodeError) as error:
        raise SDKError(f"Could not install Tailwind: {error}") from error
