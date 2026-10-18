import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from filelock import FileLock, Timeout

from .download import fetch
from .errors import SDKError
from .providers import Platform

MISE_VERSION = "2026.9.12"
# Published in the pinned release's SHASUMS256.txt; no remote installer executes.
MISE_BINARIES = {
    "linux-x64": ("linux-x64-musl", "e59a38683c9d776e0ea6c7b35c9829de915bb7df15d16d0bf6890afa0278bd7c"),
    "linux-arm64": ("linux-arm64-musl", "2d2982b12f7a13894aa88272e4cd360e68591fe105b43cff29b1ac4588c6fe83"),
    "macos-x64": ("macos-x64", "fa1e35456f1e27a4555a1ccec82d5367d7037f3b4f46d48b83c4a3bceb4d78f2"),
    "macos-arm64": ("macos-arm64", "f20d7cc555a5b0ee7b8a504acbc2583be1b0848d64115cfbe84119ceb705025b"),
    "windows-x64": ("windows-x64.exe", "8bc3a2c46246bb00fc49f467c678cf9ff321f707c533ad707061d0f8c7b639b2"),
    "windows-arm64": ("windows-arm64.exe", "6beeb61b829ba60ef3bb1fdda5717a41b8fb91bd400109de8b05b1700a107d8e"),
}


def _target(root: Path, host: Platform) -> Path:
    return root / "managers" / f"mise-{MISE_VERSION}-{host.tag}" / (
        "mise.exe" if host.system == "windows" else "mise"
    )


def _verify(path: Path, host: Platform):
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != MISE_BINARIES[host.tag][1]:
        raise SDKError(f"SHA-256 mismatch for {path}; move it aside and retry.")


def find(root: Path, host: Platform) -> str | None:
    target = _target(root, host)
    try:
        if target.exists():
            _verify(target, host)
            return str(target)
        return None
    except OSError as error:
        raise SDKError(f"Cannot read sdkmgr's mise installation: {error}") from error


def ensure(root: Path, host: Platform) -> str:
    target = _target(root, host)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(target.parent / ".install.lock", timeout=120):
            if existing := find(root, host):
                return existing
            suffix = MISE_BINARIES[host.tag][0]
            url = (
                f"https://github.com/jdx/mise/releases/download/v{MISE_VERSION}/"
                f"mise-v{MISE_VERSION}-{suffix}"
            )
            print(f"Installing mise {MISE_VERSION} in {target.parent}...", file=sys.stderr)
            with tempfile.TemporaryDirectory(prefix=".install-", dir=target.parent) as temporary:
                staged = Path(temporary) / target.name
                fetch(url, staged, limit=128 * 1024 ** 2)
                _verify(staged, host)
                staged.chmod(0o755)
                result = subprocess.run(
                    [str(staged), "--version"], check=True, capture_output=True,
                    text=True, timeout=10, stdin=subprocess.DEVNULL,
                )
                if MISE_VERSION not in result.stdout.split():
                    raise SDKError("Downloaded mise did not report the pinned version.")
                os.replace(staged, target)
            return str(target)
    except Timeout as error:
        raise SDKError("Timed out waiting for mise bootstrap; retry later.") from error
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise SDKError(f"Could not bootstrap mise: {error}") from error
