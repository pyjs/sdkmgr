import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import SDKError
from .installation import ToolInstallation
from .providers import Platform


def _output(command) -> str | None:
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, encoding="utf-8", errors="replace", timeout=15,
            stdin=subprocess.DEVNULL,
        )
        return result.stdout + result.stderr
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def candidates(host: Platform):
    if executable := shutil.which("clang"):
        yield Path(executable)
    if host.system == "linux":
        paths = Path("/usr/lib").glob("llvm-*/bin/clang")
        yield from sorted(paths, key=lambda path: tuple(map(int, re.findall(r"\d+", path.parent.parent.name))),
                          reverse=True)
    elif host.system == "macos":
        if brew := shutil.which("brew"):
            if prefix := _output([brew, "--prefix", "llvm"]):
                yield Path(prefix.strip()) / "bin/clang"
        if executable := _output(["/usr/bin/xcrun", "--find", "clang"]):
            yield Path(executable.strip())
    else:
        for variable in ("ProgramW6432", "ProgramFiles", "LOCALAPPDATA"):
            if root := os.environ.get(variable):
                yield Path(root) / "LLVM/bin/clang.exe"
        if root := os.environ.get("VCINSTALLDIR"):
            yield Path(root) / "Tools/Llvm/bin/clang.exe"
            yield Path(root) / "Tools/Llvm/x64/bin/clang.exe"


def find(host: Platform, executable: str | Path | None = None) -> "ClangInstallation | None":
    """Discover Clang without installing or compiling; an explicit path is strict."""
    configured = executable or os.environ.get("CLANG")
    if configured:
        expanded = str(Path(configured).expanduser())
        paths = [Path(shutil.which(expanded) or expanded)]
    else:
        paths = candidates(host)
    seen = set()
    for path in paths:
        path = path.absolute()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        output = _output([str(path), "--version"])
        match = re.search(r"\bclang version (\d+\.\d+\.\d+)\b", output or "")
        if match:
            return ClangInstallation("clang", match[1], path, host)
    if configured:
        raise SDKError(f"Configured Clang {configured!s} is missing or failed version validation.")
    return None


def install_command(host: Platform) -> tuple[str, ...]:
    if host.system == "macos":
        manager, arguments = "brew", ("install", "llvm")
    elif host.system == "windows":
        manager, arguments = "winget", (
            "install", "--exact", "--id", "LLVM.LLVM", "--source", "winget",
        )
    else:
        try:
            release = platform.freedesktop_os_release()
        except OSError as error:
            raise SDKError("Cannot identify Linux distribution; install Clang manually.") from error
        identifiers = {release.get("ID", ""), *release.get("ID_LIKE", "").split()}
        if identifiers & {"debian", "ubuntu"}:
            manager, arguments = "apt-get", ("install", "clang", "build-essential", "libclang-rt-dev")
        elif identifiers & {"fedora", "rhel", "centos", "rocky", "almalinux"}:
            manager, arguments = "dnf", ("install", "clang", "gcc", "glibc-devel", "compiler-rt")
        elif identifiers & {"arch", "omarchy"}:
            manager, arguments = "pacman", ("-S", "--needed", "clang", "base-devel", "compiler-rt")
        else:
            raise SDKError("No Clang package provider for this Linux distribution; install it manually.")
    executable = shutil.which(manager)
    if not executable:
        raise SDKError(f"{manager} is required to install Clang; install it or Clang manually.")
    command = (executable, *arguments)
    if host.system == "linux" and os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if not sudo:
            raise SDKError(f"sudo is unavailable; ask an administrator to run: {manager} {' '.join(arguments)}")
        command = (sudo, "--", *command)
    return command


def validate_sanitizers(sanitizers) -> tuple[str, ...]:
    if isinstance(sanitizers, str):
        raise SDKError("Sanitizers must be a sequence, not a string.")
    values = tuple(sanitizers)
    if any(value not in {"address", "undefined"} for value in values):
        raise SDKError("Supported sanitizer probes are address and undefined.")
    return tuple(dict.fromkeys(values))


@dataclass(frozen=True)
class ClangInstallation(ToolInstallation):
    def validate(self, *, sanitizers=()) -> None:
        """Compile/link tiny C and LLVM IR probes; never execute their outputs.

        No capability cache is kept: platform SDKs and linker environments may
        change independently of the compiler. This is host validation, not a
        guarantee that arbitrary IR, cross-targets, or sanitizers will run.
        """
        sanitizers = validate_sanitizers(sanitizers)
        guidance = {
            "linux": "Check your C development headers, linker, and Clang runtime packages.",
            "macos": "Install Xcode Command Line Tools (xcode-select --install) and check SDKROOT.",
            "windows": "Install Visual Studio C++ Build Tools and a Windows SDK; retry in a developer terminal.",
        }[self.platform.system]
        try:
            with tempfile.TemporaryDirectory(prefix="sdkmgr-clang-") as temporary:
                root = Path(temporary)
                source = root / "probe.c"
                source.write_text(
                    '#include <stdio.h>\n#include <stdlib.h>\n'
                    'int main(void) { void *p = malloc(8); free(p); return puts("sdkmgr") < 0; }\n',
                    encoding="utf-8",
                )
                ir = root / "probe.ll"
                ir.write_text("define i32 @sdkmgr_probe() { ret i32 42 }\n", encoding="utf-8")
                suffix = {"linux": ".so", "macos": ".dylib", "windows": ".dll"}[self.platform.system]
                shared = ["-dynamiclib"] if self.platform.system == "macos" else ["-shared"]
                if self.platform.system != "windows":
                    shared.append("-fPIC")
                options = [f"-fsanitize={','.join(sanitizers)}"] if sanitizers else []
                for input_path, output_path, flags in (
                    (source, root / "probe.exe", options),
                    (ir, root / f"probe{suffix}", shared),
                ):
                    subprocess.run(
                        [str(self.path), *flags, str(input_path), "-o", str(output_path)],
                        check=True, capture_output=True, encoding="utf-8", errors="replace", timeout=60,
                        stdin=subprocess.DEVNULL, env=self.environment(),
                    )
                    if not output_path.is_file():
                        raise SDKError(f"Clang did not produce {output_path.name}. {guidance}")
        except (OSError, subprocess.SubprocessError, UnicodeError) as error:
            detail = getattr(error, "stderr", None) or str(error)
            if isinstance(detail, bytes):
                detail = detail.decode(errors="replace")
            raise SDKError(f"Clang compile/link validation failed. {guidance}\n{detail[-4000:]}") from error
