import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sdkmgr import Installation, Manager, SDKError, bootstrap, mise, nvm
from sdkmgr.cli import main
from sdkmgr.mise import executable as discover_mise
from sdkmgr.providers import Platform


def test_discover_mise_on_path(monkeypatch):
    monkeypatch.setattr(mise.shutil, "which", lambda name: "/tools/mise")
    assert discover_mise() == "/tools/mise"


def test_discover_unactivated_mise(tmp_path, monkeypatch):
    monkeypatch.setattr(mise.shutil, "which", lambda name: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    candidate = tmp_path / ".local/bin" / ("mise.exe" if os.name == "nt" else "mise")
    assert discover_mise() is None
    candidate.parent.mkdir(parents=True)
    candidate.touch()
    candidate.chmod(0o755)
    assert discover_mise() == str(candidate)


def test_invalid_version_never_runs_mise(tmp_path, monkeypatch):
    monkeypatch.setattr(mise, "executable", lambda: "mise")
    monkeypatch.setattr(mise.subprocess, "run", lambda *a, **kw: pytest.fail("Must not run"))
    with pytest.raises(SDKError, match="exact version"):
        Manager(tmp_path).ensure("node", version="22; echo surprise")


@pytest.fixture(params=["linux", "macos", "windows"])
def provider(request, tmp_path, monkeypatch):
    host = Platform(request.param, "x64")
    monkeypatch.setattr(Platform, "current", classmethod(lambda cls: host))
    monkeypatch.setattr(mise, "executable", lambda: "mise")
    installation = Installation("node", "22.14.0", tmp_path / "mise node", host, False)
    versions = {}
    calls = []

    def create():
        installation.bin_directory.mkdir(parents=True, exist_ok=True)
        for name in ("node", "npm", "npx"):
            installation.executable(name).touch()
        versions[installation.version] = installation.home

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] != "mise":
            assert command == [str(installation.executable()), "--version"]
            return subprocess.CompletedProcess(command, 0, "v22.14.0\n", "")
        assert command[1:3] == ("--no-config", "--no-hooks")
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["env"]["MISE_NODE_DEFAULT_PACKAGES_FILE"] == os.devnull
        assert kwargs["env"]["MISE_NODE_COMPILE"] == "false"
        if command[3] == "ls":
            assert command[3:] == ("ls", "--installed", "--json", "core:node")
            assert kwargs["timeout"] == 30
            output = json.dumps([
                {"version": version, "install_path": str(home), "installed": True}
                for version, home in versions.items()
            ])
        else:
            assert command[3:] == ("install", "core:node@22.14.0", "--jobs=1")
            assert kwargs["stdout"] is sys.stderr
            assert kwargs["stderr"] is sys.stderr
            assert kwargs["timeout"] == 600
            create()
            output = None
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(mise.subprocess, "run", run)
    monkeypatch.setattr(bootstrap, "ensure", lambda *a: pytest.fail("No bootstrap fallback"))
    return Manager(tmp_path / "cache"), installation, create, calls


def test_reuse_inactive_mise_node(provider):
    manager, installation, create, calls = provider
    create()
    assert manager.ensure("node", version="22.14.0") == installation
    assert manager.find("node", version="22.14.0") == installation
    assert manager.installed() == [installation]
    assert all(command[3] == "ls" for command, _ in calls if command[0] == "mise")
    assert not manager.root.exists()


def test_install_missing_version_and_reuse(provider, capsys):
    manager, installation, _, calls = provider
    assert manager.find("node", version="22.14.0") is None
    assert manager.ensure("node", version="22.14.0") == installation
    assert manager.ensure("node", version="22.14.0") == installation
    assert sum(command[3] == "install" for command, _ in calls if command[0] == "mise") == 1
    assert not manager.root.exists()
    output = capsys.readouterr()
    assert output.out == ""
    assert "Installing Node 22.14.0 using mise" in output.err


def test_mise_takes_precedence_over_nvm(provider, monkeypatch):
    manager, installation, create, _ = provider
    create()
    monkeypatch.setattr(nvm, "discover", lambda *a: pytest.fail("Mise takes precedence"))
    assert manager.ensure("node", version="22.14.0") == installation
    assert manager.installed() == [installation]


def test_cli_prints_only_executable_to_stdout(provider, capsys):
    manager, installation, _, _ = provider
    assert main(["--root", str(manager.root), "install", "node@22.14.0"]) == 0
    output = capsys.readouterr()
    assert output.out == f"{installation.executable()}\n"
    assert "using mise" in output.err


@pytest.mark.parametrize("error", [
    OSError("unavailable"), subprocess.TimeoutExpired("mise", 30),
    subprocess.CalledProcessError(1, "mise", stderr="unsupported option"),
])
def test_mise_errors_never_trigger_fallback(provider, monkeypatch, error):
    manager, _, _, _ = provider

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(mise.subprocess, "run", fail)
    with pytest.raises(SDKError, match="mise"):
        manager.ensure("node", version="22.14.0")


@pytest.mark.parametrize("output", [
    "invalid", "{}", '[null]',
    '[{"installed": true, "version": "22.14.0", "install_path": "relative"}]',
])
def test_invalid_listing_is_diagnostic(monkeypatch, output):
    monkeypatch.setattr(mise.subprocess, "run", lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, output, ""))
    with pytest.raises(SDKError, match="Invalid mise Node installation listing"):
        mise.node_installations("mise", Platform("linux", "x64"))


def test_listing_skips_missing_and_nonrelease_versions(monkeypatch):
    output = json.dumps([
        {"installed": False, "version": "22.14.0"},
        {"installed": True, "version": "26.0.0-nightly20260901"},
    ])
    monkeypatch.setattr(mise.subprocess, "run", lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, output, ""))
    assert mise.node_installations("mise", Platform("linux", "x64")) == {}


def test_broken_installation_is_not_replaced(provider):
    manager, installation, create, calls = provider
    create()
    installation.executable("npm").unlink()
    with pytest.raises(SDKError, match="SDK is missing"):
        manager.ensure("node", version="22.14.0")
    assert all(command[3] == "ls" for command, _ in calls if command[0] == "mise")


def test_wrong_version_is_not_reused(provider, monkeypatch):
    manager, _, create, _ = provider
    create()
    original = mise.subprocess.run

    def run(command, **kwargs):
        result = original(command, **kwargs)
        if command[0] != "mise":
            result.stdout = "v22.14.1\n"
        return result

    monkeypatch.setattr(mise.subprocess, "run", run)
    with pytest.raises(SDKError, match="expected version 22.14.0"):
        manager.ensure("node", version="22.14.0")


def test_installer_success_requires_rediscovery(provider, monkeypatch):
    manager, _, _, _ = provider
    monkeypatch.setattr(mise, "install_node", lambda *a: None)
    with pytest.raises(SDKError, match="mise completed, but Node 22.14.0 was not found"):
        manager.ensure("node", version="22.14.0")
