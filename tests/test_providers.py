from pathlib import Path

import pytest

from sdkmgr import providers


@pytest.mark.parametrize("reported,loader,expected", [
    ("", True, "musl"),
    ("", False, ""),
    ("musl", False, "musl"),
    ("glibc", True, "glibc"),
    ("GLIBC", False, "glibc"),
    ("uclibc", True, "uclibc"),
])
def test_linux_libc_loader_fallback(monkeypatch, reported, loader, expected):
    monkeypatch.setattr(providers.platform, "libc_ver", lambda: (reported, ""))

    def glob(path, pattern):
        assert path == Path("/lib") and pattern == "ld-musl-*.so.1"
        return iter([path / "ld-musl-x86_64.so.1"] if loader else [])

    monkeypatch.setattr(Path, "glob", glob)
    assert providers.linux_libc() == expected
