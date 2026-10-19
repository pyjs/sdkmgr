import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from sdkmgr import Artifact, ArtifactCache, SDKError, artifacts

PAYLOAD = b"locked artifact"
ARTIFACT = Artifact("https://example.com/library.jar", hashlib.sha256(PAYLOAD).hexdigest(), "library.jar")


@pytest.fixture
def downloads(monkeypatch):
    calls = []

    def fetch(url, destination):
        calls.append(url)
        destination.write_bytes(PAYLOAD)

    monkeypatch.setattr(artifacts, "fetch", fetch)
    return calls


def test_read_only_lookup_and_verified_reuse(tmp_path, downloads):
    root = tmp_path / "cache"
    cache = ArtifactCache(root)
    assert cache.find(ARTIFACT) is None
    assert not root.exists()
    path = cache.ensure(ARTIFACT)
    assert path.read_bytes() == PAYLOAD
    assert path == root / "artifacts" / ARTIFACT.sha256 / ARTIFACT.filename
    assert cache.find(ARTIFACT) == cache.ensure(ARTIFACT) == path
    assert downloads == [ARTIFACT.url]
    assert not list(root.rglob(".install-*"))


def test_cached_bytes_are_rehashed_not_a_sidecar(tmp_path, downloads):
    cache = ArtifactCache(tmp_path)
    path = cache.ensure(ARTIFACT)
    path.write_bytes(b"damaged")
    path.with_suffix(".sha256").write_text(ARTIFACT.sha256)
    with pytest.raises(SDKError, match="SHA-256 mismatch.*Move"):
        cache.ensure(ARTIFACT)
    assert path.read_bytes() == b"damaged"
    assert downloads == [ARTIFACT.url]


@pytest.mark.parametrize("failure", ["checksum", "download", "interrupted"])
def test_failures_do_not_publish_and_retry_works(tmp_path, monkeypatch, downloads, failure):
    original = artifacts.fetch

    def broken(url, destination):
        destination.write_bytes(b"partial")
        if failure == "download":
            raise SDKError("download failed")
        if failure == "interrupted":
            raise KeyboardInterrupt

    cache = ArtifactCache(tmp_path)
    monkeypatch.setattr(artifacts, "fetch", broken)
    with pytest.raises(KeyboardInterrupt if failure == "interrupted" else SDKError):
        cache.ensure(ARTIFACT)
    assert cache.find(ARTIFACT) is None
    assert not list(tmp_path.rglob(".install-*"))
    monkeypatch.setattr(artifacts, "fetch", original)
    assert cache.ensure(ARTIFACT).read_bytes() == PAYLOAD


def test_concurrent_publication_rechecks_under_lock(tmp_path, monkeypatch, downloads):
    original = ArtifactCache.find
    barrier = threading.Barrier(2)
    local = threading.local()

    def find(self, artifact):
        result = original(self, artifact)
        if not getattr(local, "checked", False):
            local.checked = True
            barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(ArtifactCache, "find", find)
    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda _: ArtifactCache(tmp_path).ensure(ARTIFACT), range(2)))
    assert paths[0] == paths[1]
    assert downloads == [ARTIFACT.url]


@pytest.mark.parametrize("field,value", [
    ("url", "http://example.com/a"), ("url", "https://user:pass@example.com/a"),
    ("url", "https:///a"), ("url", "https://[broken/a"), ("url", None),
    ("url", 42), ("url", "https://@example.com/a"), ("url", "https://example.com/a\n"),
    ("sha256", "f" * 63), ("sha256", "F" * 64), ("sha256", None),
    ("filename", "../a"), ("filename", "a/b"), ("filename", "a\\b"),
    ("filename", "a:b"), ("filename", "a."), ("filename", "NUL.jar"),
    ("filename", "COM1"), ("filename", "a\x00b"), ("filename", None),
])
def test_invalid_artifact_inputs(field, value):
    values = dict(url=ARTIFACT.url, sha256=ARTIFACT.sha256, filename=ARTIFACT.filename)
    values[field] = value
    with pytest.raises(SDKError):
        Artifact(**values)


def test_non_file_cache_entry_is_not_replaced(tmp_path, downloads):
    path = tmp_path / "artifacts" / ARTIFACT.sha256 / ARTIFACT.filename
    path.mkdir(parents=True)
    with pytest.raises(SDKError, match="not a file"):
        ArtifactCache(tmp_path).ensure(ARTIFACT)
    assert path.is_dir()
    assert downloads == []


def test_lock_timeout(tmp_path, monkeypatch):
    class Locked:
        def __init__(self, path, **kwargs):
            self.path = path

        def __enter__(self):
            raise artifacts.Timeout(str(self.path))

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(artifacts, "FileLock", Locked)
    with pytest.raises(SDKError, match="Timed out waiting for artifact"):
        ArtifactCache(tmp_path).ensure(ARTIFACT)
