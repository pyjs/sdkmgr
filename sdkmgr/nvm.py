import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock, Timeout

from .errors import InstallationRequired, SDKError
from .installation import validated_node
from .providers import Platform, validate_node_version


@dataclass(frozen=True)
class Nvm:
    executable: Path
    root: Path
    windows_major: int = 0


def _run(command, *, installing=False, env=None):
    try:
        return subprocess.run(
            command, check=True, text=True, stdin=subprocess.DEVNULL,
            stdout=sys.stderr if installing else subprocess.PIPE,
            stderr=sys.stderr if installing else subprocess.PIPE,
            timeout=600 if installing else 30, env=env,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip()
        raise SDKError(f"nvm failed with status {error.returncode}. {detail}".strip()) from error
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        raise SDKError(f"Could not run nvm: {error}") from error


def discover(host: Platform) -> Nvm | None:
    if host.system != "windows":
        roots = []
        if configured := os.environ.get("NVM_DIR"):
            roots.append(Path(configured).expanduser())
        roots.append(Path.home() / ".nvm")
        if xdg := os.environ.get("XDG_CONFIG_HOME"):
            roots.append(Path(xdg) / "nvm")
        for root in roots:
            script = root / "nvm.sh"
            if script.is_file():
                return Nvm(script.resolve(), root.resolve())
        for script in (Path("/opt/homebrew/opt/nvm/nvm.sh"),
                       Path("/usr/local/opt/nvm/nvm.sh"), Path("/usr/share/nvm/nvm.sh")):
            if script.is_file():
                return Nvm(script.resolve(), roots[0].resolve())
        return None
    executable = shutil.which("nvm.exe")
    if not executable and (home := os.environ.get("NVM_HOME")):
        candidate = Path(home) / "nvm.exe"
        if candidate.is_file():
            executable = str(candidate)
    if not executable:
        return None
    version = _run((executable, "--version")).stdout.strip()
    match = re.search(r"\b([12])\.\d+\.\d+\b", version)
    if not match:
        raise SDKError(f"Unrecognized nvm-windows version: {version!r}.")
    major = int(match[1])
    if major == 1:
        output = _run((executable, "root")).stdout.strip()
        if not output.startswith("Current Root:"):
            raise SDKError("Cannot read the nvm-windows installation root.")
        root = output.partition(":")[2].strip()
    else:
        try:
            data = json.loads(_run((executable, "config", "get", "root", "--json")).stdout)
            root = data["root"]
        except (ValueError, KeyError, TypeError) as error:
            raise SDKError("Cannot read the nvm-windows installation root.") from error
    if not isinstance(root, str) or not Path(os.path.expandvars(root)).is_absolute():
        raise SDKError("nvm-windows must report an absolute installation root.")
    return Nvm(Path(executable), Path(os.path.expandvars(root)), major)


def node_installations(context: Nvm, host: Platform) -> dict[str, Path]:
    root = context.root if context.windows_major else context.root / "versions/node"
    result = {}
    for path in sorted(root.glob("v*")):
        if not path.is_dir():
            continue
        version = path.name[1:]
        try:
            validate_node_version(version)
        except SDKError:
            continue
        result[version] = path
    return result


def install_node(context: Nvm, version: str, host: Platform):
    validate_node_version(version)
    print(f"Installing Node {version} using nvm...", file=sys.stderr)
    try:
        context.root.mkdir(parents=True, exist_ok=True)
        with FileLock(context.root / ".sdkmgr-install.lock", timeout=120):
            if version in node_installations(context, host):
                return
            if context.windows_major:
                command = (str(context.executable), "install", version)
                if context.windows_major == 1:
                    command += ("arm64" if host.architecture == "arm64" else "64",)
                elif not any((home / "node.exe").is_file()
                             for home in node_installations(context, host).values()):
                    # v2 activates a default automatically on its first installation.
                    raise InstallationRequired(
                        command, "nvm-windows v2 activates its first Node installation. "
                        f"Run nvm install {version} yourself, then retry; "
                        "sdkmgr will not change your global selection automatically.",
                    )
                _run(command, installing=True)
                return
            shell = shutil.which("bash")
            if not shell:
                raise SDKError("bash is required to use this Unix nvm installation.")
            destination = context.root / "versions/node" / f"v{version}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".sdkmgr-", dir=context.root) as temporary:
                stage = Path(temporary)
                environment = dict(os.environ)
                environment["NVM_DIR"] = str(stage)
                environment.pop("BASH_ENV", None)
                environment.pop("ENV", None)
                command = (
                    shell, "--noprofile", "--norc", "-c",
                    '. "$1" --no-use && nvm install -b --skip-default-packages --no-progress "$2"',
                    "sdkmgr-nvm", str(context.executable), version,
                )
                _run(command, installing=True, env=environment)
                home = stage / "versions/node" / f"v{version}"
                # Validate before publishing into the user's existing nvm store.
                validated_node(home, version, host)
                if destination.exists() or destination.is_symlink():
                    raise SDKError(f"Node appeared concurrently at {destination}; retry discovery.")
                home.rename(destination)
    except Timeout as error:
        raise SDKError("Timed out waiting for nvm installation; retry later.") from error
    except OSError as error:
        raise SDKError(f"Could not install Node through nvm: {error}") from error
