"""Acquire caller-selected files; dependency resolution belongs to the caller."""

import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from filelock import FileLock, Timeout

from .download import fetch
from .errors import SDKError


@dataclass(frozen=True)
class Artifact:
    url: str
    sha256: str
    filename: str

    def __post_init__(self):
        try:
            url = urlsplit(self.url) if isinstance(self.url, str) else None
            valid_url = (url is not None and url.scheme == "https" and url.hostname
                         and url.username is None and url.password is None
                         and not any(ord(char) < 32 or ord(char) == 127 for char in self.url))
        except (TypeError, ValueError):
            valid_url = False
        if not valid_url:
            raise SDKError("Artifact URL must be HTTPS without embedded credentials.")
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise SDKError("Artifact SHA-256 must be 64 lowercase hexadecimal digits.")
        if (not isinstance(self.filename, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", self.filename)
                or self.filename.endswith(".")
                or self.filename.split(".")[0].upper() in {
                    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10)),
                }):
            raise SDKError("Artifact filename must be a portable single filename.")


def verify(path: Path, sha256: str):
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != sha256:
        raise SDKError(f"SHA-256 mismatch for {path}.")


class ArtifactCache:
    """Checksum-addressed files with read-only lookup and serialized publication."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def _path(self, artifact: Artifact) -> Path:
        return self.root / "artifacts" / artifact.sha256 / artifact.filename

    def find(self, artifact: Artifact) -> Path | None:
        path = self._path(artifact)
        try:
            if not path.exists():
                return None
            if not path.is_file():
                raise SDKError(f"Artifact cache entry is not a file: {path}.")
            try:
                verify(path, artifact.sha256)
            except SDKError as error:
                raise SDKError(f"{error} Move {path} aside and retry.") from error
            return path
        except OSError as error:
            raise SDKError(f"Cannot inspect artifact cache: {error}") from error

    def ensure(self, artifact: Artifact) -> Path:
        if existing := self.find(artifact):
            return existing
        path = self._path(artifact)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with FileLock(path.with_name(f".{path.name}.lock"), timeout=600):
                if existing := self.find(artifact):
                    return existing
                with tempfile.TemporaryDirectory(prefix=".install-", dir=path.parent) as temporary:
                    staged = Path(temporary) / artifact.filename
                    fetch(artifact.url, staged)
                    verify(staged, artifact.sha256)
                    staged.replace(path)
                return path
        except Timeout as error:
            raise SDKError("Timed out waiting for artifact installation; retry later.") from error
        except OSError as error:
            raise SDKError(f"Could not acquire artifact: {error}") from error
