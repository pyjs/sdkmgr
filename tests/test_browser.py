import hashlib
import os
import stat
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sdkmgr import Manager, SDKError, artifacts, browser
from sdkmgr.cli import main
from sdkmgr.providers import Platform

HOST = Platform("linux", "x64")
LOCATIONS = browser._locations


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.delenv("CHROME_BIN", raising=False)
    monkeypatch.setattr(browser, "_locations", lambda host: ())
    monkeypatch.setattr(Platform, "current", classmethod(lambda cls: HOST))


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    archive = tmp_path / "download.zip"
    entry = zipfile.ZipInfo("chrome-linux64/chrome")
    entry.external_attr = (stat.S_IFREG | 0o755) << 16
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr(entry, b"executable")
        source.writestr("chrome-linux64/resources.pak", b"resource")
    data = archive.read_bytes()
    monkeypatch.setitem(browser.ARCHIVES, HOST.tag, ("linux64", hashlib.sha256(data).hexdigest()))
    calls = []

    def fetch(url, destination):
        calls.append(url)
        destination.write_bytes(data)

    monkeypatch.setattr(artifacts, "fetch", fetch)
    return calls


def executable(path):
    path.write_bytes(b"external")
    path.chmod(0o755)
    return path


def test_read_only_missing_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "fetch", lambda *a: pytest.fail("download"))
    root = tmp_path / "absent"
    assert Manager(root).find_browser() is None
    assert Manager(root).find_browser(managed=True) is None
    assert not root.exists()


def test_install_reuse_and_no_launch(tmp_path, downloads):
    manager = Manager(tmp_path / "cache")
    result = manager.ensure_browser()
    assert result.managed and result.version == browser.VERSION
    assert result.executable().read_bytes() == b"executable"
    assert manager.find_browser() == manager.ensure_browser(managed=True) == result
    assert len(downloads) == 1
    assert downloads[0].endswith(f"/{browser.VERSION}/linux64/chrome-linux64.zip")
    assert not list(manager.root.rglob(".install-*"))


def test_external_override_and_managed_selection(tmp_path, monkeypatch, downloads):
    external = executable(tmp_path / "chrome")
    monkeypatch.setenv("CHROME_BIN", str(external))
    manager = Manager(tmp_path / "cache")
    found = manager.ensure_browser()
    assert found.path == external and not found.managed and found.version is None
    assert downloads == []
    assert manager.ensure_browser(managed=True).managed
    with pytest.raises(SDKError, match="not both"):
        manager.ensure_browser(executable=external, managed=True)


def test_explicit_path_precedes_environment(tmp_path, monkeypatch):
    explicit = executable(tmp_path / "explicit")
    monkeypatch.setenv("CHROME_BIN", "missing")
    assert Manager(tmp_path).find_browser(executable=explicit).path == explicit


@pytest.mark.parametrize("configured", ["", "missing"])
def test_invalid_override_does_not_download(tmp_path, monkeypatch, downloads, configured):
    monkeypatch.setenv("CHROME_BIN", configured)
    with pytest.raises(SDKError, match="Configured Chrome executable"):
        Manager(tmp_path).ensure_browser()
    assert downloads == []


def test_path_discovery(tmp_path, monkeypatch):
    binary = executable(tmp_path / "chromium")
    monkeypatch.setattr(browser, "_locations", lambda host: (tmp_path / "missing", binary))
    assert Manager(tmp_path).find_browser().path == binary


@pytest.mark.parametrize("system", ["linux", "macos", "windows"])
def test_system_locations_and_path_precedence(tmp_path, monkeypatch, system):
    monkeypatch.setattr(browser.shutil, "which", lambda name: str(tmp_path / name) if name == "chromium" else None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    paths = list(LOCATIONS(Platform(system, "x64")))
    assert paths[0] == tmp_path / "chromium"
    if system == "linux":
        assert Path("/snap/bin/chromium") in paths
    elif system == "macos":
        assert tmp_path / "Applications/Chromium.app/Contents/MacOS/Chromium" in paths
    else:
        assert paths[1:] == [tmp_path / "local/Google/Chrome/Application/chrome.exe"]


def test_unavailable_native_provider(tmp_path):
    host = Platform("windows", "arm64")
    assert browser.find(tmp_path, host) is None
    with pytest.raises(SDKError, match="No pinned.*windows-arm64"):
        browser.ensure(tmp_path, host)
    binary = executable(tmp_path / "chrome.exe")
    assert browser.ensure(tmp_path, host, executable=binary).path == binary


def test_musl_uses_external_browser_not_glibc_download(tmp_path, monkeypatch, downloads):
    monkeypatch.setattr(browser.platform, "libc_ver", lambda: ("musl", "1.2"))
    with pytest.raises(SDKError, match="requires glibc"):
        Manager(tmp_path).ensure_browser(managed=True)
    binary = executable(tmp_path / "chromium")
    assert Manager(tmp_path).ensure_browser(executable=binary).path == binary
    assert downloads == []


@pytest.mark.parametrize("tag,asset,relative", [
    ("linux-x64", "linux64", "chrome-linux64/chrome"),
    ("linux-arm64", "linux-arm64", "chrome-linux-arm64/chrome"),
    ("windows-x64", "win64", "chrome-win64/chrome.exe"),
    ("macos-x64", "mac-x64", "chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
    ("macos-arm64", "mac-arm64", "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
])
def test_pinned_layout(tmp_path, tag, asset, relative):
    host = Platform(*tag.split("-"))
    directory, path, selected, digest = browser._managed_path(tmp_path, host)
    assert directory == tmp_path / "tools/chrome" / browser.VERSION / asset
    assert path.as_posix() == relative
    assert selected == asset
    assert len(digest) == 64


def test_partial_installation_requires_repair(tmp_path, downloads):
    manager = Manager(tmp_path / "cache")
    tool = manager.ensure_browser()
    tool.path.unlink()
    with pytest.raises(SDKError, match="Incomplete Chrome installation"):
        manager.ensure_browser()
    assert len(downloads) == 1


@pytest.mark.parametrize("failure", ["checksum", "interrupted", "extract", "missing-executable"])
def test_failed_install_never_publishes(tmp_path, monkeypatch, downloads, failure):
    manager = Manager(tmp_path / "cache")
    if failure in {"checksum", "interrupted"}:
        def fetch(url, destination):
            destination.write_bytes(b"partial")
            if failure == "interrupted":
                raise KeyboardInterrupt
        monkeypatch.setattr(artifacts, "fetch", fetch)
    else:
        def extract(source, destination, **kwargs):
            destination.mkdir()
            if failure == "extract":
                raise zipfile.BadZipFile("broken archive")
        monkeypatch.setattr(browser, "extract_zip", extract)
    with pytest.raises(KeyboardInterrupt if failure == "interrupted" else SDKError):
        manager.ensure_browser()
    directory, *_ = browser._managed_path(manager.root, HOST)
    assert not directory.exists()
    assert not list(manager.root.rglob(".install-*"))


def test_browser_lock_timeout(tmp_path, monkeypatch):
    class Locked:
        def __init__(self, path, **kwargs):
            self.path = path

        def __enter__(self):
            raise browser.Timeout(str(self.path))

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(browser, "FileLock", Locked)
    with pytest.raises(SDKError, match="Timed out waiting for Chrome"):
        Manager(tmp_path).ensure_browser()


def test_concurrent_install(tmp_path, monkeypatch, downloads):
    original = browser.find
    barrier = threading.Barrier(2)

    def find(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(browser, "find", find)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: Manager(tmp_path / "cache").ensure_browser(), range(2)))
    assert results[0] == results[1]
    assert len(downloads) == 1


def test_cli_install_and_which(tmp_path, downloads, capsys):
    args = ["--root", str(tmp_path / "cache"), "browser"]
    assert main([*args, "which"]) == 1
    assert "was not found" in capsys.readouterr().err
    assert main([*args, "install", "--managed"]) == 0
    installed = Path(capsys.readouterr().out.strip())
    assert installed.is_file()
    assert main([*args, "which", "--managed"]) == 0
    assert Path(capsys.readouterr().out.strip()) == installed


@pytest.mark.skipif(os.name == "nt", reason="Unix executable permission contract")
def test_nonexecutable_override(tmp_path):
    path = executable(tmp_path / "chrome")
    path.chmod(0o644)
    with pytest.raises(SDKError, match="Configured Chrome"):
        Manager(tmp_path).find_browser(executable=path)
