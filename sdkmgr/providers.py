import platform
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import SDKError


def linux_libc() -> str:
    libc = platform.libc_ver()[0].lower()
    # Python 3.12/3.13 can report no libc name on Alpine.
    if not libc and any(Path("/lib").glob("ld-musl-*.so.1")):
        return "musl"
    return libc


@dataclass(frozen=True)
class Platform:
    system: str
    architecture: str

    @classmethod
    def current(cls):
        systems = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}
        architectures = {
            "x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64",
        }
        try:
            result = cls(systems[platform.system()], architectures[platform.machine().lower()])
        except KeyError:
            raise SDKError(
                f"Unsupported platform: {platform.system()} {platform.machine()}"
            ) from None
        return result

    @property
    def tag(self):
        return f"{self.system}-{self.architecture}"


def validate_node_version(version: str):
    if not isinstance(version, str) or not re.fullmatch(r"[1-9][0-9]*\.[0-9]+\.[0-9]+", version):
        raise SDKError("Node requires an exact version, for example 22.14.0.")


def reported_version(tool: str, output: str) -> str | None:
    if tool == "node":
        match = re.fullmatch(r"v([0-9]+\.[0-9]+\.[0-9]+)\s*", output)
    else:
        # java --version includes the build on a separate runtime line.
        match = re.search(r"\(build ([0-9]+\.[0-9]+\.[0-9]+\+[0-9]+)(?:[-)]|\s)", output)
    return match[1] if match else None
