import hashlib
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from sdkmgr import SDKError, bootstrap
from sdkmgr.providers import Platform


@pytest.fixture
def provision(tmp_path, monkeypatch):
    calls = []
    payload = b"fake mise"
    monkeypatch.setattr(bootstrap, "MISE_BINARIES", {
        key: (suffix, hashlib.sha256(payload).hexdigest())
        for key, (suffix, _) in bootstrap.MISE_BINARIES.items()
    })

    def fetch(url, path, **kwargs):
        calls.append(url)
        path.write_bytes(payload)

    monkeypatch.setattr(bootstrap, "fetch", fetch)
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, bootstrap.MISE_VERSION + "\n", ""))
    return tmp_path, calls


@pytest.mark.parametrize("system", ["linux", "macos", "windows"])
@pytest.mark.parametrize("architecture", ["x64", "arm64"])
def test_bootstrap_is_pinned_verified_and_reused(provision, system, architecture):
    root, calls = provision
    host = Platform(system, architecture)
    assert bootstrap.find(root, host) is None
    executable = bootstrap.ensure(root, host)
    assert bootstrap.ensure(root, host) == executable
    assert bootstrap.find(root, host) == executable
    assert len(calls) == 1
    assert f"/v{bootstrap.MISE_VERSION}/" in calls[0]
    assert not list(root.rglob(".install-*"))


def test_concurrent_bootstrap_downloads_once(provision):
    root, calls = provision
    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = list(executor.map(lambda _: bootstrap.ensure(root, Platform("linux", "x64")), range(2)))
    assert paths[0] == paths[1]
    assert len(calls) == 1


def test_bad_digest_never_executes_or_publishes(provision, monkeypatch):
    root, _ = provision
    host = Platform("linux", "x64")
    monkeypatch.setattr(bootstrap, "fetch", lambda url, path, **kw: path.write_bytes(b"bad"))
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **kw: pytest.fail("Unverified binary"))
    with pytest.raises(SDKError, match="SHA-256 mismatch"):
        bootstrap.ensure(root, host)
    assert bootstrap.find(root, host) is None
    assert not list(root.rglob(".install-*"))


def test_corrupt_cached_binary_is_not_overwritten(provision):
    root, calls = provision
    host = Platform("linux", "x64")
    bootstrap.ensure(root, host)
    target = bootstrap._target(root, host)
    target.write_bytes(b"changed")
    with pytest.raises(SDKError, match="SHA-256 mismatch"):
        bootstrap.ensure(root, host)
    assert target.read_bytes() == b"changed"
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["wrong-version", "timeout", "execution-error"])
def test_failed_binary_validation_is_not_published(provision, monkeypatch, failure):
    root, _ = provision

    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("mise", 10)
        if failure == "execution-error":
            raise OSError("Cannot execute")
        return subprocess.CompletedProcess(args, 0, "1.0.0\n", "")

    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    with pytest.raises(SDKError):
        bootstrap.ensure(root, Platform("linux", "x64"))
    assert bootstrap.find(root, Platform("linux", "x64")) is None
