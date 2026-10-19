import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from filelock import FileLock, Timeout

from .download import fetch
from .errors import InstallationRequired, SDKError
from .process import is_terminal, progress_output
from .providers import Platform
from .system import display_command

TOOLS_BUILD = "15859902"
# SHA-256 values published at https://developer.android.com/studio.
TOOLS_ARCHIVES = {
    "linux-x64": ("linux", "4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583"),
    "macos-x64": ("mac_x86_64", "c5a6378ab5cf7e0d5701921405115befff13e9ff7417fb588389338f8bd050f3"),
    "macos-arm64": ("mac_arm64", "835b62a26162b229b441d1f6d4680383815a270809eb33522c0d480fa5002c4e"),
    "windows-x64": ("win", "90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a"),
}


def sdk_root(host: Platform, explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    home = os.environ.get("ANDROID_HOME")
    legacy = os.environ.get("ANDROID_SDK_ROOT")
    if home and legacy and Path(home).expanduser().resolve() != Path(legacy).expanduser().resolve():
        raise SDKError("ANDROID_HOME and ANDROID_SDK_ROOT disagree; set one SDK root explicitly.")
    if configured := home or legacy:
        return Path(configured).expanduser().resolve()
    if host.system == "windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Android" / "Sdk"
    if host.system == "macos":
        return Path.home() / "Library" / "Android" / "sdk"
    return Path.home() / "Android" / "Sdk"


def validate_packages(packages) -> tuple[str, ...]:
    if isinstance(packages, str):
        raise SDKError("Android packages must be a sequence, not a single string.")
    result = []
    for package in packages:
        if not isinstance(package, str) or not re.fullmatch(
            r"[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)*", package,
        ) or any(part in {".", ".."} for part in package.split("/")):
            raise SDKError(f"Invalid Android package identifier: {package!r}.")
        if package not in result:
            result.append(package)
    return tuple(result)


def command_tools(home: Path, host: Platform) -> Path | None:
    suffix = ".exe" if host.system == "windows" else ""
    directory = home / "cmdline-tools"
    candidates = [directory / "latest", directory / f"sdkmgr-{TOOLS_BUILD}"]
    if directory.is_dir():
        versions = [p for p in directory.iterdir() if re.fullmatch(r"[0-9]+(\.[0-9]+)*", p.name)]
        candidates.extend(sorted(versions, key=lambda p: tuple(map(int, p.name.split("."))), reverse=True))
    for candidate in candidates:
        if (candidate / "bin" / f"android{suffix}").is_file():
            return candidate
    return None


def installed_packages(home: Path) -> dict[str, str]:
    """Read Google's local package records without contacting the repository."""
    try:
        return _installed_packages(home)
    except OSError as error:
        raise SDKError(f"Cannot read Android package records: {error}") from error


def _installed_packages(home: Path) -> dict[str, str]:
    result = {}
    if not home.exists():
        return result
    def unreadable(error):
        raise error

    for directory, subdirectories, files in os.walk(home, onerror=unreadable):
        subdirectories[:] = [p for p in subdirectories if not p.startswith(".")]
        if "package.xml" not in files:
            continue
        # Package contents (notably NDK toolchains) are not more SDK packages.
        subdirectories.clear()
        record = Path(directory) / "package.xml"
        if record.stat().st_size > 1024 * 1024:
            raise SDKError(f"Oversized Android package record: {record}.")
        try:
            root = ET.parse(record).getroot()
            for package in root.iter():
                if package.tag.rsplit("}", 1)[-1] != "localPackage":
                    continue
                # SDK records retain semicolons; the public CLI uses slashes.
                name = package.attrib["path"].replace(";", "/")
                validate_packages((name,))
                if home.joinpath(*name.split("/")).resolve() != record.parent.resolve():
                    continue
                revision = next((p for p in package if p.tag.rsplit("}", 1)[-1] == "revision"), None)
                parts = {} if revision is None else {
                    p.tag.rsplit("}", 1)[-1]: p.text for p in revision
                }
                result[name] = ".".join(parts.get(p) or "0" for p in ("major", "minor", "micro"))
        except (ET.ParseError, KeyError) as error:
            raise SDKError(f"Invalid Android package record {record}: {error}") from error
    return result


@dataclass(frozen=True)
class AndroidInstallation:
    """An installed SDK root, optionally with Google's native installer CLI."""

    home: Path
    tools: Path | None
    platform: Platform

    def executable(self, name: str = "android") -> Path:
        if name == "android":
            if self.tools is None:
                raise SDKError(f"Android installer CLI is not installed under {self.home}.")
            suffix = ".exe" if self.platform.system == "windows" else ""
            return self.tools / "bin" / (name + suffix)
        if name in {"adb", "fastboot", "emulator"}:
            suffix = ".exe" if self.platform.system == "windows" else ""
            return self.home / ("emulator" if name == "emulator" else "platform-tools") / (name + suffix)
        raise SDKError(f"Unknown Android executable: {name!r}.")

    def environment(self, base: dict[str, str] | None = None) -> dict[str, str]:
        result = dict(os.environ if base is None else base)
        result["ANDROID_HOME"] = result["ANDROID_SDK_ROOT"] = str(self.home)
        paths = [self.home / "platform-tools", self.home / "emulator"]
        if self.tools is not None:
            paths.insert(0, self.tools / "bin")
        result["PATH"] = os.pathsep.join(map(str, paths)) + os.pathsep + result.get("PATH", "")
        # Cross-OS download overrides must not silently provision unusable tools.
        result.pop("REPO_OS_OVERRIDE", None)
        return result

    def installed(self) -> dict[str, str]:
        return installed_packages(self.home)

    def build_tool(self, name: str, *, version: str) -> Path:
        """Resolve a tool from one exact installed build-tools revision."""
        allowed = {"aapt", "aapt2", "aidl", "d8", "dexdump", "zipalign", "apksigner"}
        if name not in allowed:
            raise SDKError(f"Unknown Android build tool: {name!r}.")
        if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\d+)?", version):
            raise SDKError("Android build tools require an exact version, for example 35.0.1.")
        suffix = ""
        if self.platform.system == "windows":
            suffix = ".bat" if name in {"d8", "apksigner"} else ".exe"
        return self._package_file(f"build-tools/{version}", name + suffix)

    def platform_jar(self, api: int) -> Path:
        """Resolve android.jar for a released integer API level, without installing."""
        if type(api) is not int or api <= 0:
            raise SDKError("Android API level must be a positive integer.")
        return self._package_file(f"platforms/android-{api}", "android.jar")

    def _package_file(self, package: str, name: str) -> Path:
        path = self.home.joinpath(*package.split("/"), name)
        if not path.is_file():
            raise SDKError(
                f"Android package {package} is missing {name} at {path}. "
                "Install the package, or repair it if already registered."
            )
        return path

    def command(self, *arguments: str) -> tuple[str, ...]:
        return (str(self.executable()), "--no-metrics", f"--sdk={self.home}", *arguments)


def find(home: Path, host: Platform) -> AndroidInstallation | None:
    try:
        if tools := command_tools(home, host):
            return AndroidInstallation(home, tools, host)
        return None
    except OSError as error:
        raise SDKError(f"Cannot discover Android command-line tools: {error}") from error


def inspect(home: Path, host: Platform) -> AndroidInstallation | None:
    """Inspect an existing root; individual tool lookups validate their files."""
    try:
        if home.is_dir():
            return AndroidInstallation(home, command_tools(home, host), host)
        return None
    except OSError as error:
        raise SDKError(f"Cannot inspect Android SDK: {error}") from error


def _verify_packages(sdk: AndroidInstallation, packages):
    suffix = ".exe" if sdk.platform.system == "windows" else ""
    for package in packages:
        directory = sdk.home.joinpath(*package.split("/"))
        required = ()
        if package == "platform-tools":
            required = (f"adb{suffix}",)
        elif package == "emulator":
            required = (f"emulator{suffix}",)
        elif package.startswith("platforms/"):
            required = ("android.jar",)
        elif package.startswith("build-tools/"):
            required = (f"aapt2{suffix}", "d8.bat" if suffix else "d8")
        for name in required:
            if not (directory / name).is_file():
                raise SDKError(
                    f"Android package {package} is registered but missing {directory / name}. "
                    "Repair it with Android Studio or Google's SDK manager, then retry; "
                    "sdkmgr will not overwrite a partial installation."
                )


def _extract(archive: Path, destination: Path):
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > 20000 or sum(p.file_size for p in entries) > 1024 ** 3:
            raise SDKError("Android tools archive exceeds extraction limits.")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            original = entry.orig_filename
            mode = entry.external_attr >> 16
            if (
                path.is_absolute() or ".." in path.parts or not path.parts
                or path.parts[0] != "cmdline-tools" or "\\" in original or "\x00" in original
                or ":" in entry.filename or stat.S_ISLNK(mode)
                or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR})
            ):
                raise SDKError(f"Unsafe Android archive member: {entry.filename!r}.")
            target = destination.joinpath(*path.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                target.chmod(0o755 if mode & 0o111 or path.parent.name == "bin" else 0o644)


def require_consent(*, accept_sdk_license: bool):
    if not accept_sdk_license:
        raise InstallationRequired((),
            "Review Google's SDK terms and the licenses for the requested packages at "
            "https://developer.android.com/studio#downloads before installing. "
            "After accepting them, retry with --accept-sdk-license "
            "(Python: accept_sdk_license=True), or install manually. "
            "sdkmgr does not run Google's installer without this confirmation.")


def bootstrap(home: Path, host: Platform, *, accept_sdk_license: bool) -> AndroidInstallation:
    if existing := find(home, host):
        return existing
    if host.tag not in TOOLS_ARCHIVES:
        raise SDKError(f"Android command-line tools bootstrap is not supported on {host.tag}.")
    require_consent(accept_sdk_license=accept_sdk_license)
    target = home / "cmdline-tools" / f"sdkmgr-{TOOLS_BUILD}"
    if target.exists():
        raise SDKError(f"Incomplete Android tools at {target}; move them aside and retry.")
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix, expected = TOOLS_ARCHIVES[host.tag]
    url = f"https://dl.google.com/android/repository/commandlinetools-{suffix}-{TOOLS_BUILD}_latest.zip"
    print(f"Installing Android command-line tools in {target}...", file=sys.stderr)
    with tempfile.TemporaryDirectory(prefix=".sdkmgr-", dir=target.parent) as temporary:
        stage = Path(temporary)
        archive = stage / "tools.zip"
        fetch(url, archive, limit=256 * 1024 ** 2)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise SDKError("Android command-line tools SHA-256 mismatch.")
        _extract(archive, stage)
        extracted = stage / "cmdline-tools"
        suffix = ".exe" if host.system == "windows" else ""
        if not (extracted / "bin" / f"android{suffix}").is_file():
            raise SDKError("Android tools archive is missing the Android CLI.")
        os.replace(extracted, target)
    return AndroidInstallation(home, target, host)


def _run(sdk: AndroidInstallation, arguments, *, interactive: bool):
    command = sdk.command(*arguments)
    print(f"Running {display_command(command)}", file=sys.stderr)
    with progress_output() as output:
        attached = (interactive and output is sys.stderr
                    and is_terminal(sys.stdin) and is_terminal(output))
        return subprocess.run(
            command, check=False, env=sdk.environment(),
            stdin=None if attached else subprocess.DEVNULL,
            stdout=output, stderr=output, timeout=None if attached else 1200,
        )


def ensure(home: Path, host: Platform, packages, *,
           interactive: bool | None, accept_sdk_license: bool = False) -> AndroidInstallation:
    packages = validate_packages(packages)
    try:
        existing = find(home, host)
        installed = installed_packages(home)
        if existing is None or any(p not in installed for p in packages):
            require_consent(accept_sdk_license=accept_sdk_license)
        home.mkdir(parents=True, exist_ok=True)
        with FileLock(home / ".sdkmgr.lock", timeout=120):
            sdk = bootstrap(home, host, accept_sdk_license=accept_sdk_license)
            installed = sdk.installed()
            _verify_packages(sdk, (p for p in packages if p in installed))
            missing = tuple(p for p in packages if p not in installed)
            if not missing:
                return sdk
            require_consent(accept_sdk_license=accept_sdk_license)
            result = _run(sdk, ("sdk", "install", *missing), interactive=interactive is not False)
            if result.returncode:
                raise SDKError(f"Android installer exited with status {result.returncode}; retry after resolving its error.")
            if remaining := tuple(p for p in packages if p not in sdk.installed()):
                command = sdk.command("sdk", "install", *remaining)
                raise InstallationRequired(command,
                    f"Android packages still missing: {', '.join(remaining)}. "
                    f"Inspect the installer output and retry {display_command(command)}. "
                    "The installer may have reported unavailable packages or unmet prerequisites.")
            _verify_packages(sdk, packages)
            return sdk
    except Timeout as error:
        raise SDKError("Another sdkmgr Android install is active; retry later.") from error
    except (OSError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        raise SDKError(f"Android provisioning failed: {error}") from error
