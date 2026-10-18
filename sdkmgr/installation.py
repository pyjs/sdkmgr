import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import SDKError
from .providers import Platform, reported_version


@dataclass(frozen=True)
class Installation:
    """Resolved tool paths; environment() returns a complete subprocess environment."""

    tool: str
    version: str
    home: Path
    platform: Platform
    managed: bool = False

    @property
    def bin_directory(self) -> Path:
        if self.tool == "node" and self.platform.system == "windows":
            return self.home
        return self.home / "bin"

    def executable(self, name: str | None = None) -> Path:
        name = name or self.tool
        allowed = {"node": ("node", "npm", "npx"), "java": ("java", "javac", "jar")}
        if name not in allowed[self.tool]:
            raise SDKError(f"Unknown {self.tool} executable: {name!r}.")
        if self.platform.system == "windows":
            name += ".cmd" if name in {"npm", "npx"} else ".exe"
        return self.bin_directory / name

    def environment(self, base: dict[str, str] | None = None) -> dict[str, str]:
        result = dict(os.environ if base is None else base)
        result["PATH"] = str(self.bin_directory) + os.pathsep + result.get("PATH", "")
        if self.tool == "java":
            result["JAVA_HOME"] = str(self.home)
        return result


def validated_node(home: Path, version: str, host: Platform) -> Installation:
    installation = Installation("node", version, home, host)
    for name in ("node", "npm", "npx"):
        if not installation.executable(name).is_file():
            raise SDKError(f"SDK is missing {installation.executable(name)}.")
    try:
        result = subprocess.run(
            [str(installation.executable()), "--version"], check=True,
            capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL,
            env=installation.environment(),
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as error:
        raise SDKError(f"SDK executable failed validation: {error}") from error
    if reported_version("node", result.stdout + result.stderr) != version:
        raise SDKError(f"SDK did not report expected version {version}.")
    return installation
