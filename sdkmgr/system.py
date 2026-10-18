import os
import shlex
import subprocess
import sys

from .errors import InstallationRequired, SDKError


def display_command(command: tuple[str, ...]) -> str:
    return subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)


def install_package(command: tuple[str, ...], *, interactive: bool | None):
    """Ask before installing; leave authentication to sudo or the OS installer.

    Standard input remains attached to the terminal. Passwords never pass
    through sdkmgr, and package-manager output does not pollute CLI stdout.
    """
    rendered = display_command(command)
    print(f"JDK installation requires this command:\n\n  {rendered}\n", file=sys.stderr)
    if any(os.path.basename(part) == "pacman" for part in command):
        print(
            "Arch requires complete system updates. If packages are unavailable,\n"
            "run your normal system updater (Omarchy's updater on Omarchy), then retry.\n"
            "sdkmgr will not refresh package databases or upgrade the system.",
            file=sys.stderr,
        )
    print(
        "You can quit, run it yourself, and restart your original command.\n"
        "Completed installations will be detected automatically.",
        file=sys.stderr,
    )
    if interactive is False or not sys.stdin.isatty() or not sys.stderr.isatty():
        raise InstallationRequired(command, f"Run {rendered}, then retry the original command.")
    print(
        "Press Enter to run it now, or type q to quit.\n"
        "If elevated access is required, sudo or Windows will ask you to\n"
        "authenticate directly (sudo normally asks for your account password).",
        file=sys.stderr,
    )
    answer = sys.stdin.readline()
    if answer == "" or answer.strip():
        raise InstallationRequired(command, "Installation deferred; rerun after installing the JDK.")
    try:
        subprocess.run(command, check=True, stdout=sys.stderr, stderr=sys.stderr)
    except subprocess.CalledProcessError as error:
        raise SDKError(
            f"JDK installation exited with status {error.returncode}. "
            f"Resolve the package-manager error, then retry. Command: {rendered}"
        ) from error
    except OSError as error:
        raise SDKError(f"Could not run {rendered}: {error}") from error
