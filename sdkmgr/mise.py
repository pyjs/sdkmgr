import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .errors import SDKError
from .process import progress_output
from .providers import Platform, validate_node_version


def executable() -> str | None:
    if found := shutil.which("mise"):
        return found
    candidate = Path.home() / ".local/bin" / ("mise.exe" if os.name == "nt" else "mise")
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def _run(executable: str, *arguments: str, installing: bool = False):
    # Loading project configuration can run hooks or select an external plugin.
    command = (executable, "--no-config", "--no-hooks", *arguments)
    environment = dict(os.environ)
    environment.update({
        "MISE_NODE_COMPILE": "false",
        "MISE_NODE_DEFAULT_PACKAGES_FILE": os.devnull,
    })
    try:
        with progress_output(installing) as output:
            return subprocess.run(
                command, check=True, text=True, stdin=subprocess.DEVNULL,
                stdout=output, stderr=output,
                timeout=600 if installing else 30, env=environment,
            )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip()
        raise SDKError(
            f"mise exited with status {error.returncode}. "
            "Check the mise installation and retry; sdkmgr will not switch providers."
            + (f"\n{detail}" if detail else "")
        ) from error
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        raise SDKError(f"Could not run mise: {error}") from error


def node_installations(executable: str, host: Platform) -> dict[str, Path]:
    output = _run(executable, "ls", "--installed", "--json", "core:node").stdout
    try:
        data = json.loads(output)
        if not isinstance(data, list):
            raise ValueError("expected a list")
        result = {}
        for entry in data:
            if entry["installed"] is not True:
                continue
            version = entry["version"]
            if not isinstance(version, str):
                raise ValueError("expected a version string")
            try:
                validate_node_version(version)
            except SDKError:
                # Nightlies and custom linked versions are not exact releases.
                continue
            home = Path(entry["install_path"]).expanduser()
            if not home.is_absolute():
                raise ValueError("expected an absolute installation path")
            result[version] = home
        return result
    except (ValueError, KeyError, TypeError, SDKError) as error:
        raise SDKError(f"Invalid mise Node installation listing: {error}") from error


def install_node(executable: str, version: str, host: Platform):
    validate_node_version(version)
    print(f"Installing Node {version} using mise...", file=sys.stderr)
    _run(executable, "install", f"core:node@{version}", "--jobs=1", installing=True)
