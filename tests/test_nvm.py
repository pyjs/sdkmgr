import json
import os
import subprocess
from pathlib import Path

import pytest

from sdkmgr import Installation, InstallationRequired, Manager, SDKError, bootstrap, nvm
from sdkmgr.nvm import discover as discover_nvm
from sdkmgr.providers import Platform


def make_node(home, host, version="22.14.0"):
    installation = Installation("node", version, home, host)
    installation.bin_directory.mkdir(parents=True, exist_ok=True)
    for name in ("node", "npm", "npx"):
        installation.executable(name).touch()
    return installation


@pytest.fixture
def unix(tmp_path, monkeypatch):
    host = Platform("linux", "x64")
    root = tmp_path / "nvm with spaces"
    root.mkdir()
    script = root / "nvm.sh"
    script.touch()
    context = nvm.Nvm(script, root)
    monkeypatch.setattr(nvm, "discover", lambda host: context)
    monkeypatch.setattr(Platform, "current", classmethod(lambda cls: host))
    monkeypatch.setattr(bootstrap, "ensure", lambda *a: pytest.fail("Must reuse nvm"))
    return context, host


@pytest.mark.parametrize("discovery", ["NVM_DIR", "XDG_CONFIG_HOME", "home"])
def test_unix_discovery(tmp_path, monkeypatch, discovery):
    monkeypatch.delenv("NVM_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    root = tmp_path / (".nvm" if discovery == "home" else "nvm")
    if discovery != "home":
        monkeypatch.setenv(discovery, str(root if discovery == "NVM_DIR" else tmp_path))
    root.mkdir()
    (root / "nvm.sh").touch()
    assert discover_nvm(Platform("linux", "x64")) == nvm.Nvm(root / "nvm.sh", root)


def test_unix_installer_stages_without_touching_aliases(unix, tmp_path, monkeypatch):
    context, host = unix
    alias = context.root / "alias/default"
    alias.parent.mkdir()
    alias.write_text("v20.0.0\n")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == "bash":
            assert command[1:4] == ("--noprofile", "--norc", "-c")
            assert command[-2:] == (str(context.executable), "22.14.0")
            environment = kwargs["env"]
            assert "BASH_ENV" not in environment
            assert "ENV" not in environment
            stage = Path(environment["NVM_DIR"])
            assert stage != context.root
            (stage / "alias").mkdir()
            (stage / "alias/default").write_text("changed by nvm")
            make_node(stage / "versions/node/v22.14.0", host)
            return subprocess.CompletedProcess(command, 0, None, "")
        return subprocess.CompletedProcess(command, 0, "v22.14.0\n", "")

    monkeypatch.setenv("BASH_ENV", "must-not-run")
    monkeypatch.setenv("ENV", "must-not-run")
    monkeypatch.setattr(nvm.shutil, "which", lambda name: "bash")
    monkeypatch.setattr(nvm.subprocess, "run", run)
    manager = Manager(tmp_path / "sdkmgr")
    installed = manager.ensure("node", version="22.14.0")
    assert installed.home == context.root / "versions/node/v22.14.0"
    assert manager.ensure("node", version="22.14.0") == installed
    assert manager.installed() == [installed]
    assert sum(command[0] == "bash" for command in calls) == 1
    assert alias.read_text() == "v20.0.0\n"
    assert not [path for path in context.root.glob(".sdkmgr-*") if path.is_dir()]
    assert not manager.root.exists()


def test_unix_install_failure_preserves_user_files(unix, monkeypatch):
    context, host = unix
    marker = context.root / "keep"
    marker.touch()
    monkeypatch.setattr(nvm.shutil, "which", lambda name: "bash")

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(nvm.subprocess, "run", fail)
    with pytest.raises(SDKError, match="nvm failed"):
        nvm.install_node(context, "22.14.0", host)
    assert marker.exists()
    assert not [path for path in context.root.glob(".sdkmgr-*") if path.is_dir()]
    assert nvm.node_installations(context, host) == {}


def test_partial_nvm_version_is_not_overwritten(unix, tmp_path, monkeypatch):
    context, host = unix
    directory = context.root / "versions/node/v22.14.0"
    directory.mkdir(parents=True)
    marker = directory / "user-file"
    marker.touch()
    monkeypatch.setattr(nvm, "install_node", lambda *a: pytest.fail("Must not overwrite"))
    with pytest.raises(SDKError, match="SDK is missing"):
        Manager(tmp_path).ensure("node", version="22.14.0")
    assert marker.exists()


@pytest.mark.parametrize("major", [1, 2])
def test_windows_discovery(tmp_path, monkeypatch, major):
    root = tmp_path / "nvm root"
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[1] == "--version":
            output = f"{major}.0.0\n"
        elif command[1] == "root":
            output = f"\nCurrent Root: {root}\n"
        else:
            assert command[1:] == ("config", "get", "root", "--json")
            output = json.dumps({"root": str(root)})
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(nvm.shutil, "which", lambda name: "nvm.exe")
    monkeypatch.setattr(nvm.subprocess, "run", run)
    assert discover_nvm(Platform("windows", "x64")) == nvm.Nvm(Path("nvm.exe"), root, major)
    assert len(commands) == 2


@pytest.mark.parametrize("major", [1, 2])
@pytest.mark.parametrize("architecture", ["x64", "arm64"])
def test_windows_install_does_not_switch_version(tmp_path, monkeypatch, major, architecture):
    host = Platform("windows", architecture)
    context = nvm.Nvm(Path("nvm.exe"), tmp_path, major)
    make_node(tmp_path / "v20.0.0", host, "20.0.0")
    calls = []
    monkeypatch.setattr(nvm.subprocess, "run", lambda command, **kw: calls.append(command))
    nvm.install_node(context, "22.14.0", host)
    expected = ("nvm.exe", "install", "22.14.0")
    if major == 1:
        expected += ("arm64" if architecture == "arm64" else "64",)
    assert calls == [expected]


def test_windows_v2_first_install_is_explicit(tmp_path, monkeypatch):
    context = nvm.Nvm(Path("nvm.exe"), tmp_path, 2)
    monkeypatch.setattr(nvm.subprocess, "run", lambda *a, **kw: pytest.fail("Must not activate"))
    with pytest.raises(InstallationRequired, match="activates its first") as caught:
        nvm.install_node(context, "22.14.0", Platform("windows", "x64"))
    assert caught.value.command == ("nvm.exe", "install", "22.14.0")


@pytest.mark.parametrize("version,root_output", [
    ("unexpected", ""), ("3.0.0", ""), ("1.2.2", "bad root output"),
    ("2.0.0", "invalid json"), ("2.0.0", '{"root": "relative"}'),
])
def test_bad_windows_metadata_is_diagnostic(monkeypatch, version, root_output):
    monkeypatch.setattr(nvm.shutil, "which", lambda name: "nvm.exe")
    monkeypatch.setattr(nvm.subprocess, "run", lambda command, **kw:
                        subprocess.CompletedProcess(command, 0,
                                                    version if command[1] == "--version"
                                                    else root_output, ""))
    with pytest.raises(SDKError):
        discover_nvm(Platform("windows", "x64"))


def test_invalid_staged_node_is_not_published(unix, monkeypatch):
    context, host = unix
    monkeypatch.setattr(nvm.shutil, "which", lambda name: "bash")

    def run(command, **kwargs):
        if command[0] == "bash":
            make_node(Path(kwargs["env"]["NVM_DIR"]) / "versions/node/v22.14.0", host)
        return subprocess.CompletedProcess(command, 0, "v1.0.0\n", "")

    monkeypatch.setattr(nvm.subprocess, "run", run)
    with pytest.raises(SDKError, match="expected version"):
        nvm.install_node(context, "22.14.0", host)
    assert nvm.node_installations(context, host) == {}


def test_windows_success_still_requires_rediscovery(tmp_path, monkeypatch):
    host = Platform("windows", "x64")
    context = nvm.Nvm(Path("nvm.exe"), tmp_path, 1)
    monkeypatch.setattr(Platform, "current", classmethod(lambda cls: host))
    monkeypatch.setattr(nvm, "discover", lambda host: context)
    monkeypatch.setattr(nvm.subprocess, "run", lambda *a, **kw: None)
    with pytest.raises(SDKError, match="nvm completed, but Node"):
        Manager(tmp_path).ensure("node", version="22.14.0")


@pytest.mark.skipif(os.name == "nt", reason="Unix shell adapter")
def test_shell_arguments_are_literal_and_profiles_are_not_loaded(unix, tmp_path, monkeypatch):
    context, host = unix
    # A tiny fake manager exercises the actual shell invocation, not a command mock.
    context.executable.write_text(
        'test "$1" = --no-use || return 1\n'
        'nvm() {\n'
        '  test "$1" = install && test "$2" = -b || return 1\n'
        '  test "$3" = --skip-default-packages || return 1\n'
        '  test "$4" = --no-progress && test "$5" = 22.14.0 || return 1\n'
        '  mkdir -p "$NVM_DIR/versions/node/v$5/bin"\n'
        '  touch "$NVM_DIR/versions/node/v$5/bin/"{node,npm,npx}\n'
        '}\n'
    )
    monkeypatch.setattr(nvm, "validated_node", lambda *a: None)
    nvm.install_node(context, "22.14.0", host)
    assert (context.root / "versions/node/v22.14.0/bin/node").exists()
