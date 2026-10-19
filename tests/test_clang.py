import subprocess
from pathlib import Path

import pytest

from sdkmgr import (
    ClangInstallation,
    InstallationRequired,
    Manager,
    SDKError,
    clang,
    core,
)
from sdkmgr.cli import main
from sdkmgr.providers import Platform

HOST = Platform("linux", "x64")


@pytest.fixture
def compiler(tmp_path, monkeypatch):
    path = tmp_path / "llvm/bin/clang"
    path.parent.mkdir(parents=True)
    path.touch()
    monkeypatch.delenv("CLANG", raising=False)
    monkeypatch.setattr(clang, "candidates", lambda host: [path])
    monkeypatch.setattr(clang, "_output", lambda command: "Ubuntu clang version 21.1.8\nTarget: x86_64-linux-gnu")
    monkeypatch.setattr(Platform, "current", classmethod(lambda cls: HOST))
    return path


@pytest.mark.parametrize("banner,expected", [
    ("Ubuntu clang version 21.1.8", "21.1.8"),
    ("Apple clang version 17.0.0 (clang-1700)", "17.0.0"),
    ("clang version 22.1.0", "22.1.0"),
    ("gcc version 14.2.0", None),
    (None, None),
])
def test_find_version(compiler, monkeypatch, banner, expected):
    monkeypatch.setattr(clang, "_output", lambda command: banner)
    found = clang.find(HOST)
    if expected is None:
        assert found is None
    else:
        assert found.version == expected
        assert found.executable() == compiler
        assert not found.managed


def test_find_does_not_compile_or_install(compiler, monkeypatch, tmp_path):
    monkeypatch.setattr(ClangInstallation, "validate", lambda *a, **kw: pytest.fail("compile"))
    monkeypatch.setattr(core, "install_package", lambda *a, **kw: pytest.fail("install"))
    assert Manager(tmp_path / "unused").find_clang().executable() == compiler
    assert not (tmp_path / "unused").exists()


def test_explicit_and_environment_paths_do_not_fall_back(compiler, monkeypatch, tmp_path):
    bad = tmp_path / "missing"
    monkeypatch.setenv("CLANG", str(bad))
    with pytest.raises(SDKError, match="Configured Clang"):
        Manager().ensure_clang()
    assert Manager().find_clang(executable=compiler).executable() == compiler
    with pytest.raises(SDKError, match="Configured Clang"):
        Manager().ensure_clang(executable=bad)


def test_ensure_validates_existing(compiler, monkeypatch):
    calls = []
    monkeypatch.setattr(ClangInstallation, "validate", lambda self, **kw: calls.append(kw))
    assert Manager().ensure_clang(sanitizers=["address", "address"]).executable() == compiler
    assert calls == [{"sanitizers": ("address",)}]


def test_manual_install_restart(compiler, monkeypatch):
    compiler.unlink()
    monkeypatch.setattr(clang, "install_command", lambda host: ("apt-get", "install", "clang"))
    monkeypatch.setattr(ClangInstallation, "validate", lambda *a, **kw: None)
    manager = Manager(interactive=False)
    with pytest.raises(InstallationRequired) as caught:
        manager.ensure_clang()
    assert caught.value.command == ("apt-get", "install", "clang")
    compiler.touch()
    assert manager.ensure_clang().executable() == compiler


def test_installer_success_is_rechecked(compiler, monkeypatch):
    compiler.unlink()
    monkeypatch.setattr(clang, "install_command", lambda host: ("installer",))
    calls = []
    monkeypatch.setattr(core, "install_package", lambda *args, **kw: calls.append((args, kw)))
    with pytest.raises(SDKError, match="completed, but Clang was not found"):
        Manager(interactive=False).ensure_clang()
    assert calls == [((("installer",),), {"interactive": False, "label": "Clang"})]


@pytest.mark.parametrize("sanitizers", ["address", ["thread"], ["address,-bad"]])
def test_invalid_sanitizers_before_install(compiler, monkeypatch, sanitizers):
    monkeypatch.setattr(core, "install_package", lambda *a, **kw: pytest.fail("install"))
    with pytest.raises(SDKError, match="Sanitizers|sanitizer"):
        Manager().ensure_clang(sanitizers=sanitizers)


@pytest.mark.parametrize("system,shared,suffix", [
    ("linux", "-shared", ".so"), ("macos", "-dynamiclib", ".dylib"),
    ("windows", "-shared", ".dll"),
])
def test_probe_compiles_c_and_ir_without_execution(compiler, monkeypatch, system, shared, suffix):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert command[0] == str(compiler)
        input_path = Path(command[command.index("-o") - 1])
        assert input_path.suffix in {".c", ".ll"}
        Path(command[-1]).touch()
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(clang.subprocess, "run", run)
    tool = ClangInstallation("clang", "21.1.8", compiler, Platform(system, "x64"))
    tool.validate(sanitizers=("address",))
    assert len(calls) == 2
    assert "-fsanitize=address" in calls[0][0]
    assert shared in calls[1][0]
    assert calls[1][0][-1].endswith(suffix)
    assert ("-fPIC" in calls[1][0]) == (system != "windows")
    assert calls[0][1]["timeout"] == 60
    assert calls[0][1]["stdin"] == subprocess.DEVNULL
    assert not Path(calls[0][0][-1]).parent.exists()


@pytest.mark.parametrize("failure", ["link", "timeout", "missing"])
def test_probe_failure_is_actionable_and_cleans_up(compiler, monkeypatch, failure):
    paths = []

    def run(command, **kwargs):
        paths.append(Path(command[-1]))
        if failure == "link":
            raise subprocess.CalledProcessError(1, command, stderr="missing runtime")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 60)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(clang.subprocess, "run", run)
    with pytest.raises(SDKError, match="development headers"):
        ClangInstallation("clang", "21.1.8", compiler, HOST).validate()
    assert not paths[0].parent.exists()


@pytest.mark.parametrize("distribution,manager,packages", [
    ("ubuntu", "apt-get", ("clang", "build-essential", "libclang-rt-dev")),
    ("fedora", "dnf", ("clang", "gcc", "glibc-devel", "compiler-rt")),
    ("omarchy", "pacman", ("clang", "base-devel", "compiler-rt")),
])
@pytest.mark.parametrize("uid", [0, 1000])
def test_linux_install_commands(monkeypatch, distribution, manager, packages, uid):
    monkeypatch.setattr(clang.platform, "freedesktop_os_release", lambda: {"ID": distribution})
    monkeypatch.setattr(clang.shutil, "which", lambda name: name)
    monkeypatch.setattr(clang.os, "geteuid", lambda: uid, raising=False)
    prefix = ("sudo", "--") if uid else ()
    arguments = ("-S", "--needed") if manager == "pacman" else ("install",)
    assert clang.install_command(HOST) == (*prefix, manager, *arguments, *packages)


@pytest.mark.parametrize("system,command", [
    ("macos", ("brew", "install", "llvm")),
    ("windows", ("winget", "install", "--exact", "--id", "LLVM.LLVM", "--source", "winget")),
])
def test_other_install_commands(monkeypatch, system, command):
    monkeypatch.setattr(clang.shutil, "which", lambda name: name)
    assert clang.install_command(Platform(system, "arm64")) == command


@pytest.mark.parametrize("problem,expected", [
    ("distribution", "No Clang package provider"),
    ("manager", "apt-get is required"),
    ("sudo", "sudo is unavailable"),
])
def test_unavailable_install_routes(monkeypatch, problem, expected):
    monkeypatch.setattr(clang.platform, "freedesktop_os_release",
                        lambda: {"ID": "unknown" if problem == "distribution" else "ubuntu"})
    monkeypatch.setattr(clang.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(clang.shutil, "which",
                        lambda name: None if problem == "manager" or name == "sudo" else name)
    with pytest.raises(SDKError, match=expected):
        clang.install_command(HOST)


def test_install_rediscovers_new_compiler(compiler, monkeypatch):
    compiler.unlink()
    monkeypatch.setattr(clang, "install_command", lambda host: ("installer",))
    monkeypatch.setattr(core, "install_package", lambda *a, **kw: compiler.touch())
    monkeypatch.setattr(ClangInstallation, "validate", lambda *a, **kw: None)
    assert Manager().ensure_clang().executable() == compiler


def test_version_probe_failure_returns_none(monkeypatch):
    def run(command, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL
        raise subprocess.TimeoutExpired(command, 15)

    monkeypatch.setattr(clang.subprocess, "run", run)
    assert clang._output(["clang", "--version"]) is None


def test_tool_environment_does_not_mutate_input(compiler):
    tool = clang.find(HOST)
    original = {"PATH": "original", "INCLUDE": "sdk-headers"}
    result = tool.environment(original)
    assert result["INCLUDE"] == "sdk-headers"
    assert result["PATH"].startswith(str(compiler.parent))
    assert original == {"PATH": "original", "INCLUDE": "sdk-headers"}


def test_cli(compiler, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(ClangInstallation, "validate", lambda self, **kw: calls.append(kw))
    assert main(["clang", "which"]) == 0
    assert capsys.readouterr().out.strip() == str(compiler)
    assert calls == []
    assert main(["clang", "install", "--sanitizer", "undefined"]) == 0
    assert calls == [{"sanitizers": ("undefined",)}]
    assert main(["clang", "which", "--sanitizer", "address"]) == 1
