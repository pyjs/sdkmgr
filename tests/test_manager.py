from pathlib import Path

import pytest

from sdkmgr import Installation, Manager, SDKError, bootstrap, mise, nvm
from sdkmgr.providers import Platform


@pytest.mark.parametrize("external,private,existing_nvm,expected", [
    ("external", "private", "nvm", "external"),
    (None, "private", "nvm", "private"),
    (None, None, "nvm", "nvm"),
    (None, None, None, "bootstrapped"),
])
def test_selection_order(tmp_path, monkeypatch, external, private, existing_nvm, expected):
    monkeypatch.setattr(mise, "executable", lambda: external)
    monkeypatch.setattr(bootstrap, "find", lambda *a: private)
    monkeypatch.setattr(nvm, "discover", lambda host: existing_nvm)
    calls = []
    monkeypatch.setattr(bootstrap, "ensure", lambda *a: calls.append("bootstrap") or "bootstrapped")
    manager = Manager(tmp_path)
    module, context = manager._node_provider(install=True)
    assert context == expected
    assert module is (nvm if expected == "nvm" else mise)
    assert calls == (["bootstrap"] if expected == "bootstrapped" else [])


def test_read_only_commands_do_not_bootstrap(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "ensure", lambda *a: pytest.fail("Must not install"))
    manager = Manager(tmp_path / "unused")
    assert manager.find("node", version="22.14.0") is None
    assert manager.installed() == []
    assert not manager.root.exists()


@pytest.mark.parametrize("tool,version", [
    ("node", "latest"), ("node", "22"), ("node", "../../bad"), ("unknown", "1.0.0"),
])
def test_invalid_requests_do_not_bootstrap(tmp_path, monkeypatch, tool, version):
    monkeypatch.setattr(bootstrap, "ensure", lambda *a: pytest.fail("Must not install"))
    with pytest.raises(SDKError):
        Manager(tmp_path).ensure(tool, version=version)


def test_environment_does_not_mutate_input():
    base = {"PATH": "old", "KEEP": "yes"}
    java = Installation("java", "21.0.8", Path("jdk"), Platform("linux", "x64"))
    assert java.environment(base)["JAVA_HOME"] == "jdk"
    assert java.environment(base)["KEEP"] == "yes"
    assert base == {"PATH": "old", "KEEP": "yes"}
    with pytest.raises(SDKError, match="Unknown java executable"):
        java.executable("../outside")


def test_windows_launchers():
    node = Installation("node", "22.14.0", Path("sdk"), Platform("windows", "x64"))
    assert node.executable("npm") == Path("sdk/npm.cmd")
    assert node.executable("npx") == Path("sdk/npx.cmd")
