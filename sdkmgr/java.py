import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from .errors import SDKError
from .providers import Platform


def validate_version(version: str):
    if version not in ("21", "25"):
        raise SDKError("Java supports major versions 21 and 25 only; request java@21 or java@25.")


def _output(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
        return result.stdout + result.stderr
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def _registry_homes():
    import winreg

    key_name = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, key_name, access=winreg.KEY_READ | view) as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            with winreg.OpenKey(key, winreg.EnumKey(key, index)) as entry:
                                name = winreg.QueryValueEx(entry, "DisplayName")[0]
                                if isinstance(name, str) and re.search(r"jdk|temurin", name, re.I):
                                    location = winreg.QueryValueEx(entry, "InstallLocation")[0]
                                    if isinstance(location, str) and location:
                                        yield Path(location)
                        except OSError:
                            continue
            except OSError:
                continue


def candidate_homes(host: Platform, version: str):
    if configured := os.environ.get("JAVA_HOME"):
        yield Path(configured).expanduser()
    for name in ("javac", "java"):
        if executable := shutil.which(name):
            yield Path(executable).resolve().parent.parent
    if host.system == "linux":
        yield from sorted(Path("/usr/lib/jvm").glob("*"))
    elif host.system == "macos":
        output = _output(["/usr/libexec/java_home", "-v", version])
        if output:
            yield Path(output.strip())
        for root in (Path("/Library/Java/JavaVirtualMachines"),
                     Path.home() / "Library/Java/JavaVirtualMachines"):
            yield from sorted(root.glob("*/Contents/Home"))
        if brew := shutil.which("brew"):
            output = _output([brew, "--prefix", f"openjdk@{version}"])
            if output:
                yield Path(output.strip()) / "libexec/openjdk.jdk/Contents/Home"
    else:
        yield from _registry_homes()
        for variable in ("ProgramW6432", "ProgramFiles", "LOCALAPPDATA"):
            if location := os.environ.get(variable):
                for vendor in ("Microsoft", "Eclipse Adoptium", "Java"):
                    yield from sorted((Path(location) / vendor).glob("jdk*"))


def find(host: Platform, version: str) -> tuple[Path, str] | None:
    validate_version(version)
    seen = set()
    suffix = ".exe" if host.system == "windows" else ""
    for home in candidate_homes(host, version):
        home = home.resolve()
        if home in seen:
            continue
        seen.add(home)
        if not all((home / "bin" / (name + suffix)).is_file()
                   for name in ("java", "javac", "jar")):
            continue
        output = _output([str(home / "bin" / ("java" + suffix)), "--version"])
        compiler = _output([str(home / "bin" / ("javac" + suffix)), "-version"])
        runtime_match = re.match(r"(?:openjdk|java)\s+(\d+(?:\.\d+)*)(?:[+\s]|$)", output or "")
        compiler_match = re.match(r"javac\s+(\d+(?:\.\d+)*)(?:[+\s]|$)", compiler or "")
        if runtime_match and compiler_match and all(
            match[1].split(".", 1)[0] == version for match in (runtime_match, compiler_match)
        ):
            return home, runtime_match[1]
    return None


def install_command(host: Platform, version: str) -> tuple[str, ...]:
    validate_version(version)
    if host.system == "macos":
        manager, arguments = "brew", ("install", f"openjdk@{version}")
    elif host.system == "windows":
        manager, arguments = "winget", (
            "install", "--exact", "--id", f"Microsoft.OpenJDK.{version}", "--source", "winget",
        )
    else:
        try:
            release = platform.freedesktop_os_release()
        except OSError as error:
            raise SDKError("Cannot identify Linux distribution; install JDK 21 or 25 manually.") from error
        identifiers = {release.get("ID", ""), *release.get("ID_LIKE", "").split()}
        if identifiers & {"debian", "ubuntu"}:
            manager, arguments = "apt-get", ("install", f"openjdk-{version}-jdk")
        elif identifiers & {"fedora", "rhel", "centos", "rocky", "almalinux"}:
            manager, arguments = "dnf", ("install", f"java-{version}-openjdk-devel")
        elif identifiers & {"arch", "omarchy"}:
            manager, arguments = "pacman", ("-S", "--needed", f"jdk{version}-openjdk")
        else:
            raise SDKError("No JDK package provider for this Linux distribution; install Java manually.")
    executable = shutil.which(manager)
    if not executable:
        raise SDKError(f"{manager} is required for JDK installation; install it or a JDK manually.")
    command = (executable, *arguments)
    if host.system == "linux" and os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if not sudo:
            raise SDKError(f"sudo is unavailable; ask an administrator to run: {manager} {' '.join(arguments)}")
        command = (sudo, "--", *command)
    return command
