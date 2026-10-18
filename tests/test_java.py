import io
import subprocess
from pathlib import Path

import pytest

from sdkmgr import InstallationRequired, Manager, SDKError, core, java, system
from sdkmgr.cli import main
from sdkmgr.providers import Platform


@pytest.mark.parametrize("version", ["17", "26", "21.0.8+9", "latest", "21;whoami"])
def test_only_supported_majors(tmp_path, version):
    with pytest.raises(SDKError, match="major versions 21 and 25 only"):
        Manager(tmp_path).ensure("java", version=version)


@pytest.mark.parametrize("distribution,executable,package", [
    ({"ID": "ubuntu", "ID_LIKE": "debian"}, "apt-get", "openjdk-21-jdk"),
    ({"ID": "debian"}, "apt-get", "openjdk-21-jdk"),
    ({"ID": "fedora"}, "dnf", "java-21-openjdk-devel"),
    ({"ID": "rhel"}, "dnf", "java-21-openjdk-devel"),
    ({"ID": "rocky", "ID_LIKE": "rhel centos fedora"}, "dnf", "java-21-openjdk-devel"),
])
def test_linux_package_commands(monkeypatch, distribution, executable, package):
    monkeypatch.setattr(java.platform, "freedesktop_os_release", lambda: distribution)
    monkeypatch.setattr(java.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(java.os, "geteuid", lambda: 1000, raising=False)
    assert java.install_command(Platform("linux", "x64"), "21") == (
        "/usr/bin/sudo", "--", f"/usr/bin/{executable}", "install", package,
    )


def test_root_does_not_use_sudo(monkeypatch):
    monkeypatch.setattr(java.platform, "freedesktop_os_release", lambda: {"ID": "debian"})
    monkeypatch.setattr(java.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(java.os, "geteuid", lambda: 0, raising=False)
    assert java.install_command(Platform("linux", "x64"), "25") == (
        "/usr/bin/apt-get", "install", "openjdk-25-jdk",
    )


@pytest.mark.parametrize("distribution", [
    {"ID": "arch"}, {"ID": "omarchy"}, {"ID": "derivative", "ID_LIKE": "arch"},
])
@pytest.mark.parametrize("version", ["21", "25"])
@pytest.mark.parametrize("uid", [0, 1000])
def test_pacman_does_not_refresh_or_upgrade(monkeypatch, distribution, version, uid):
    monkeypatch.setattr(java.platform, "freedesktop_os_release", lambda: distribution)
    monkeypatch.setattr(java.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(java.os, "geteuid", lambda: uid, raising=False)
    prefix = ("/usr/bin/sudo", "--") if uid else ()
    assert java.install_command(Platform("linux", "x64"), version) == (
        *prefix, "/usr/bin/pacman", "-S", "--needed", f"jdk{version}-openjdk",
    )


@pytest.mark.parametrize("host,expected", [
    ("macos", ("brew", "install", "openjdk@25")),
    ("windows", ("winget", "install", "--exact", "--id", "Microsoft.OpenJDK.25", "--source", "winget")),
])
def test_other_package_commands(monkeypatch, host, expected):
    monkeypatch.setattr(java.shutil, "which", lambda name: name)
    assert java.install_command(Platform(host, "arm64"), "25") == expected


def test_no_manager_bootstrap(monkeypatch):
    monkeypatch.setattr(java.shutil, "which", lambda name: None)
    with pytest.raises(SDKError, match="brew is required"):
        java.install_command(Platform("macos", "arm64"), "21")


@pytest.fixture
def fake_jdk(tmp_path, monkeypatch):
    host = Platform("linux", "x64")
    monkeypatch.setattr(Platform, "current", classmethod(lambda cls: host))
    home = tmp_path / "system-jdk"

    def create(major="21"):
        (home / "bin").mkdir(parents=True, exist_ok=True)
        for name in ("java", "javac", "jar"):
            (home / "bin" / name).touch()

        def output(command):
            prefix = "javac" if Path(command[0]).name == "javac" else "openjdk"
            return f"{prefix} {major}.0.12 2026-07-21\n"

        monkeypatch.setattr(java, "_output", output)
        return home

    monkeypatch.setattr(java, "candidate_homes", lambda *args: [home])
    monkeypatch.setattr(java, "install_command", lambda *args: ("sudo", "apt-get", "install", "openjdk-21-jdk"))
    return create


def test_discovery_accepts_vendor_and_patch_updates(tmp_path, fake_jdk):
    home = fake_jdk()
    manager = Manager(tmp_path / "cache")
    installation = manager.ensure("java", version="21")
    assert installation.home == home
    assert installation.version == "21.0.12"
    assert not installation.managed
    assert not manager.root.exists()
    assert manager.installed() == [installation]
    assert manager.find("java", version="25") is None


def test_jre_is_not_a_jdk(tmp_path, fake_jdk):
    home = fake_jdk()
    (home / "bin" / "javac").unlink()
    assert Manager(tmp_path).find("java", version="21") is None


def test_mismatched_compiler_rejected(tmp_path, fake_jdk, monkeypatch):
    fake_jdk()
    monkeypatch.setattr(java, "_output", lambda command:
                        "javac 17.0.1" if Path(command[0]).name == "javac" else "openjdk 21.0.1")
    assert Manager(tmp_path).find("java", version="21") is None


def test_resume_after_manual_install(tmp_path, fake_jdk):
    manager = Manager(tmp_path / "cache", interactive=False)
    with pytest.raises(InstallationRequired) as caught:
        manager.ensure("java", version="21")
    assert caught.value.command == ("sudo", "apt-get", "install", "openjdk-21-jdk")
    fake_jdk()
    assert manager.ensure("java", version="21").version == "21.0.12"


def test_continues_after_interactive_install(tmp_path, fake_jdk, monkeypatch):
    calls = []

    def install(command, *, interactive):
        calls.append(command)
        fake_jdk()

    monkeypatch.setattr(core, "install_package", install)
    assert Manager(tmp_path).ensure("java", version="21").version == "21.0.12"
    assert len(calls) == 1


def test_success_exit_still_requires_valid_jdk(tmp_path, monkeypatch):
    monkeypatch.setattr(java, "install_command", lambda *args: ("installer",))
    monkeypatch.setattr(core, "install_package", lambda *args, **kwargs: None)
    with pytest.raises(SDKError, match="completed, but JDK 21 was not found"):
        Manager(tmp_path).ensure("java", version="21")


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize("answer", ["q\n", "no\n", "", "unexpected\n"])
def test_decline_never_runs_command(monkeypatch, answer):
    monkeypatch.setattr(system.sys, "stdin", Terminal(answer))
    monkeypatch.setattr(system.sys, "stderr", Terminal())
    monkeypatch.setattr(system.subprocess, "run", lambda *a, **kw: pytest.fail("Must not run"))
    with pytest.raises(InstallationRequired):
        system.install_package(("sudo", "apt-get", "install", "openjdk-21-jdk"), interactive=None)


def test_password_and_terminal_are_inherited(monkeypatch):
    output = Terminal()
    monkeypatch.setattr(system.sys, "stdin", Terminal("\n"))
    monkeypatch.setattr(system.sys, "stderr", output)
    calls = []
    monkeypatch.setattr(system.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    command = ("sudo", "--", "/usr/bin/apt-get", "install", "openjdk-21-jdk")
    system.install_package(command, interactive=None)
    assert calls == [((command,), {"check": True, "stdout": output, "stderr": output})]
    assert "sudo -- /usr/bin/apt-get install openjdk-21-jdk" in output.getvalue()
    assert "restart your original command" in output.getvalue()


def test_pacman_deferral_explains_update_policy(monkeypatch):
    output = Terminal()
    monkeypatch.setattr(system.sys, "stderr", output)
    command = ("sudo", "--", "/usr/bin/pacman", "-S", "--needed", "jdk21-openjdk")
    with pytest.raises(InstallationRequired) as caught:
        system.install_package(command, interactive=False)
    assert caught.value.command == command
    assert "Omarchy's updater" in output.getvalue()
    assert "will not refresh package databases or upgrade the system" in output.getvalue()


def test_package_failure_is_not_retried(monkeypatch):
    monkeypatch.setattr(system.sys, "stdin", Terminal("\n"))
    monkeypatch.setattr(system.sys, "stderr", Terminal())

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(100, args[0])

    monkeypatch.setattr(system.subprocess, "run", fail)
    with pytest.raises(SDKError, match="status 100"):
        system.install_package(("apt-get", "install", "openjdk-21-jdk"), interactive=None)


def test_noninteractive_cli_can_be_restarted(tmp_path, fake_jdk, capsys):
    args = ["--root", str(tmp_path), "--non-interactive", "install", "java@21"]
    assert main(args) == 2
    output = capsys.readouterr()
    assert "apt-get install openjdk-21-jdk" in output.err
    assert output.out == ""
    home = fake_jdk()
    assert main(args) == 0
    assert capsys.readouterr().out.strip() == str(home / "bin/java")
