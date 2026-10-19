import hashlib
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sdkmgr import Manager, SDKError, providers, tailwind
from sdkmgr.cli import main
from sdkmgr.providers import Platform

HOST = Platform("linux", "x64")
VERSION = "4.3.3"
PAYLOAD = b"fake executable"


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.delenv("TAILWINDCSS", raising=False)
    monkeypatch.setattr(tailwind.shutil, "which", lambda name: None)
    monkeypatch.setattr(providers.platform, "libc_ver", lambda: ("glibc", "2.39"))
    monkeypatch.setattr(Platform, "current", classmethod(lambda cls: HOST))


@pytest.fixture
def downloads(monkeypatch):
    calls = []

    def fetch(url, destination, **kwargs):
        calls.append(url)
        if url.endswith("sha256sums.txt"):
            asset = tailwind.asset_name(HOST)
            destination.write_text(f"{hashlib.sha256(PAYLOAD).hexdigest()}  ./{asset}\n")
        else:
            destination.write_bytes(PAYLOAD)

    monkeypatch.setattr(tailwind, "fetch", fetch)
    monkeypatch.setattr(tailwind, "_version", lambda path: VERSION)
    return calls


def test_install_reuse_and_environment(tmp_path, downloads):
    manager = Manager(tmp_path)
    tool = manager.ensure("tailwindcss", version=VERSION)
    assert tool.managed
    assert tool.executable().read_bytes() == PAYLOAD
    assert manager.ensure("tailwindcss", version=VERSION) == tool
    assert manager.find("tailwindcss", version=VERSION) == tool
    assert len(downloads) == 2
    base = {"PATH": "original"}
    assert tool.environment(base)["PATH"].startswith(str(tool.path.parent))
    assert base == {"PATH": "original"}
    assert not list(tmp_path.rglob(".install-*"))


def test_concurrent_install_rechecks_under_lock(tmp_path, monkeypatch, downloads):
    original = tailwind.find
    barrier = threading.Barrier(2)

    def find(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(tailwind, "find", find)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: tailwind.ensure(tmp_path, HOST, VERSION), range(2)))
    assert results[0] == results[1]
    assert len(downloads) == 2


def test_lock_timeout_is_diagnostic(tmp_path, monkeypatch):
    class Locked:
        def __init__(self, path, **kwargs):
            self.path = path

        def __enter__(self):
            raise tailwind.Timeout(str(self.path))

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(tailwind, "FileLock", Locked)
    with pytest.raises(SDKError, match="Timed out waiting for Tailwind"):
        tailwind.ensure(tmp_path, HOST, VERSION)


def test_incomplete_cache_is_not_overwritten(tmp_path, downloads):
    directory = tmp_path / "tools/tailwindcss" / VERSION / tailwind.asset_name(HOST)
    directory.mkdir(parents=True)
    marker = directory / "keep"
    marker.write_text("existing content")
    with pytest.raises(SDKError, match="Incomplete Tailwind files"):
        tailwind.ensure(tmp_path, HOST, VERSION)
    assert marker.read_text() == "existing content"
    assert downloads == []


def test_find_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(tailwind, "fetch", lambda *a, **kw: pytest.fail("network"))
    root = tmp_path / "unused"
    assert Manager(root).find("tailwindcss", version=VERSION) is None
    assert not root.exists()


def test_reuse_external_and_strict_override(tmp_path, monkeypatch):
    external = tmp_path / "external"
    external.touch()
    monkeypatch.setenv("TAILWINDCSS", str(external))
    monkeypatch.setattr(tailwind, "_version", lambda path: VERSION)
    tool = Manager(tmp_path).ensure("tailwindcss", version=VERSION)
    assert not tool.managed
    assert tool.path == external
    monkeypatch.setattr(tailwind, "_version", lambda path: "4.0.0")
    with pytest.raises(SDKError, match="Configured Tailwind"):
        Manager(tmp_path).ensure("tailwindcss", version=VERSION)


def test_wrong_path_version_uses_managed_copy(tmp_path, monkeypatch, downloads):
    external = tmp_path / "external"
    external.touch()
    monkeypatch.setattr(tailwind.shutil, "which", lambda name: str(external))
    monkeypatch.setattr(tailwind, "_version", lambda path: "4.0.0" if path == external else VERSION)
    tool = Manager(tmp_path).ensure("tailwindcss", version=VERSION)
    assert tool.managed
    assert external.read_bytes() == b""


@pytest.mark.parametrize("version", ["latest", "4", "../4.3.3", "4.3.3-beta.1", "4.3.3\n"])
def test_version_validation(tmp_path, version):
    with pytest.raises(SDKError, match="exact release"):
        Manager(tmp_path).ensure("tailwindcss", version=version)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("system,arch,libc,asset", [
    ("linux", "x64", "glibc", "tailwindcss-linux-x64"),
    ("linux", "arm64", "musl", "tailwindcss-linux-arm64-musl"),
    ("macos", "arm64", "", "tailwindcss-macos-arm64"),
    ("macos", "x64", "", "tailwindcss-macos-x64"),
    ("windows", "x64", "", "tailwindcss-windows-x64.exe"),
])
def test_asset_selection(monkeypatch, system, arch, libc, asset):
    monkeypatch.setattr(providers.platform, "libc_ver", lambda: (libc, ""))
    assert tailwind.asset_name(Platform(system, arch)) == asset


def test_windows_arm64_not_silently_x64():
    with pytest.raises(SDKError, match="ARM64"):
        tailwind.asset_name(Platform("windows", "arm64"))


def test_glibc_wins_over_installed_musl_loader(monkeypatch):
    monkeypatch.setattr(Path, "glob", lambda *a: iter([Path("/lib/ld-musl-x86_64.so.1")]))
    assert tailwind.asset_name(HOST) == "tailwindcss-linux-x64"
    monkeypatch.setattr(providers.platform, "libc_ver", lambda: ("", ""))
    assert tailwind.asset_name(HOST) == "tailwindcss-linux-x64-musl"


@pytest.mark.parametrize("failure", ["digest", "duplicate", "missing", "version", "interrupted"])
def test_failed_install_never_publishes(tmp_path, monkeypatch, downloads, failure):
    original = tailwind.fetch

    def fetch(url, destination, **kwargs):
        original(url, destination, **kwargs)
        if url.endswith("sha256sums.txt"):
            if failure == "duplicate":
                destination.write_text(destination.read_text() * 2)
            if failure == "missing":
                destination.write_text("")
        elif failure == "digest":
            destination.write_bytes(b"corrupt")
        elif failure == "interrupted":
            raise KeyboardInterrupt

    monkeypatch.setattr(tailwind, "fetch", fetch)
    if failure == "version":
        monkeypatch.setattr(tailwind, "_version", lambda path: "4.0.0")
    with pytest.raises(KeyboardInterrupt if failure == "interrupted" else SDKError):
        Manager(tmp_path).ensure("tailwindcss", version=VERSION)
    directory = tmp_path / "tools/tailwindcss" / VERSION / tailwind.asset_name(HOST)
    assert not directory.exists()
    assert not list(tmp_path.rglob(".install-*"))


def test_cached_tampering_rejected_without_download(tmp_path, downloads):
    tool = Manager(tmp_path).ensure("tailwindcss", version=VERSION)
    tool.path.write_bytes(b"changed")
    with pytest.raises(SDKError, match="SHA-256 mismatch") as caught:
        Manager(tmp_path).ensure("tailwindcss", version=VERSION)
    assert f"Move {tool.path.parent} aside and retry." in str(caught.value)
    assert tool.path.exists()
    assert len(downloads) == 2


def test_download_checksum_failure_does_not_request_cache_repair(tmp_path, downloads, monkeypatch):
    original = tailwind.fetch

    def corrupt(url, destination, **kwargs):
        original(url, destination, **kwargs)
        if not url.endswith("sha256sums.txt"):
            destination.write_bytes(b"corrupt")

    monkeypatch.setattr(tailwind, "fetch", corrupt)
    with pytest.raises(SDKError, match="SHA-256 mismatch") as caught:
        Manager(tmp_path).ensure("tailwindcss", version=VERSION)
    assert "aside" not in str(caught.value)
    assert not list(tmp_path.rglob(".install-*"))


@pytest.mark.parametrize("prefix", ["", "./", "*", "*./"])
def test_manifest_filename_conventions(tmp_path, prefix):
    asset = tailwind.asset_name(HOST)
    binary = tmp_path / "tool"
    binary.write_bytes(PAYLOAD)
    manifest = tmp_path / "manifest"
    manifest.write_text(f"{hashlib.sha256(PAYLOAD).hexdigest()}  {prefix}{asset}\n")
    tailwind._verify(binary, manifest, asset)


def test_manifest_ignores_other_directories(tmp_path):
    asset = tailwind.asset_name(HOST)
    binary = tmp_path / "tool"
    binary.write_bytes(PAYLOAD)
    manifest = tmp_path / "manifest"
    manifest.write_text(f"{hashlib.sha256(PAYLOAD).hexdigest()}  ../{asset}\n")
    with pytest.raises(SDKError, match="Expected one SHA-256 entry"):
        tailwind._verify(binary, manifest, asset)


@pytest.mark.parametrize("output,expected", [
    ("≈ tailwindcss v4.3.3\nUsage", "4.3.3"),
    ("≈ tailwindcss \x1b[34mv4.3.3\x1b[39m\nUsage", "4.3.3"),
    ("≈ tailwindcss \x1b[34mv4.3.3-beta.1\x1b[39m", None),
    ("tailwindcss v4.3.3-beta.1", None), ("other v4.3.3", None),
])
def test_version_probe(monkeypatch, output, expected):
    def run(command, **kwargs):
        assert command == ["tool", "--help"]
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 15
        return subprocess.CompletedProcess(command, 0, "", output)

    monkeypatch.setattr(tailwind.subprocess, "run", run)
    assert tailwind._version(Path("tool")) == expected


def test_cli(tmp_path, downloads, capsys):
    assert main(["--root", str(tmp_path), "install", f"tailwindcss@{VERSION}"]) == 0
    installed = capsys.readouterr().out
    assert Path(installed.strip()).is_file()
    assert main(["--root", str(tmp_path), "which", f"tailwindcss@{VERSION}"]) == 0
    assert capsys.readouterr().out == installed
