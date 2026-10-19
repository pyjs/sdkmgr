from pathlib import Path

import pytest

from sdkmgr import clang, tailwind
from sdkmgr.errors import SDKError
from sdkmgr.installation import executable_path
from sdkmgr.providers import Platform


@pytest.mark.parametrize("tool", ["clang", "tailwindcss"])
@pytest.mark.parametrize("configured", ["./tool", Path("tool")])
@pytest.mark.parametrize("exists", [True, False])
def test_explicit_relative_path_does_not_select_path_collision(tmp_path, monkeypatch, tool, configured, exists):
    local = tmp_path / "tool"
    if exists:
        local.touch()
    other = tmp_path / "path/tool"
    other.parent.mkdir()
    other.touch()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(clang.shutil, "which", lambda name: str(other) if name == "tool" else None)
    monkeypatch.setattr(clang, "_output", lambda command: "clang version 21.1.8")
    monkeypatch.setattr(tailwind, "_version", lambda path: "4.3.3")
    host = Platform("linux", "x64")
    def find():
        if tool == "clang":
            return clang.find(host, configured)
        return tailwind.find(tmp_path / "cache", host, "4.3.3", executable=configured)

    if not exists:
        with pytest.raises(SDKError, match="Configured"):
            find()
        return
    found = find()
    assert found.executable() == local


def test_bare_command_uses_path(tmp_path, monkeypatch):
    other = tmp_path / "path/tool"
    monkeypatch.setattr(clang.shutil, "which", lambda name: str(other) if name == "tool" else None)
    assert executable_path("tool") == other
