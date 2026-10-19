import os
import stat
import zipfile

import pytest

from sdkmgr import SDKError
from sdkmgr.archives import extract_zip


def archive(tmp_path, entries):
    path = tmp_path / "payload.zip"
    with zipfile.ZipFile(path, "w") as source:
        for name, contents, mode in entries:
            # Preserve malformed raw names; ZipInfo normalizes them on Windows.
            entry = zipfile.ZipInfo("placeholder")
            entry.filename = name
            entry.external_attr = mode << 16
            source.writestr(entry, contents)
    return path


@pytest.mark.parametrize("name", ["../outside", "/outside", "tool/../outside", "wrong/file",
                                      "tool\\file", "tool/file:stream", "tool/file\x00hidden"])
def test_unsafe_members_rejected(tmp_path, name):
    path = archive(tmp_path, [(name, "payload", stat.S_IFREG | 0o644)])
    with pytest.raises(SDKError, match="Unsafe tool archive member"):
        extract_zip(path, tmp_path / "stage", root="tool")


def test_permissions_and_contents(tmp_path):
    path = archive(tmp_path, [("tool/bin", "executable", stat.S_IFREG | 0o755),
                              ("tool/data", "resource", stat.S_IFREG | 0o644)])
    extract_zip(path, tmp_path / "stage", root="tool")
    assert (tmp_path / "stage/tool/bin").read_text() == "executable"
    assert (tmp_path / "stage/tool/data").read_text() == "resource"
    if os.name != "nt":
        assert (tmp_path / "stage/tool/bin").stat().st_mode & 0o777 == 0o755
        assert (tmp_path / "stage/tool/data").stat().st_mode & 0o777 == 0o644


@pytest.mark.skipif(os.name == "nt", reason="Only macOS provider extracts symlinks")
def test_framework_symlink_chain(tmp_path):
    path = archive(tmp_path, [
        ("tool/Resources", "Versions/Current/Resources", stat.S_IFLNK | 0o777),
        ("tool/Versions/Current", "1.2.3", stat.S_IFLNK | 0o777),
        ("tool/Versions/1.2.3/Resources/data", "resource", stat.S_IFREG | 0o644),
    ])
    extract_zip(path, tmp_path / "stage", root="tool", symlinks=True)
    assert (tmp_path / "stage/tool/Resources/data").read_text() == "resource"


@pytest.mark.parametrize("target", ["../outside", "/outside", "a\\b", "C:/outside", ""])
def test_symlinks_disabled_by_default(tmp_path, target):
    path = archive(tmp_path, [("tool/link", target, stat.S_IFLNK | 0o777)])
    with pytest.raises(SDKError, match="Unsafe tool archive member"):
        extract_zip(path, tmp_path / "stage", root="tool")


@pytest.mark.skipif(os.name == "nt", reason="Only macOS provider extracts symlinks")
@pytest.mark.parametrize("links", [
    [("tool/link", "../../outside")],
    [("tool/link", "missing")],
    [("tool/a", "b"), ("tool/b", "a")],
    [("tool/escape", "../../outside"), ("tool/escape/nested", "target")],
])
def test_invalid_link_graph_never_writes_outside_staging(tmp_path, links):
    outside = tmp_path / "outside"
    outside.mkdir()
    path = archive(tmp_path, [(name, target, stat.S_IFLNK | 0o777) for name, target in links])
    with pytest.raises(SDKError, match="symlink"):
        extract_zip(path, tmp_path / "stage", root="tool", symlinks=True)
    assert not list(outside.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="Only macOS provider extracts symlinks")
@pytest.mark.parametrize("name,alias", [("A", "a"), ("caf\u00e9", "cafe\u0301")])
@pytest.mark.parametrize("nested", ["link", "directory/link"])
def test_filesystem_alias_never_writes_through_link(tmp_path, name, alias, nested):
    probe = tmp_path / name
    probe.touch()
    if not (tmp_path / alias).exists():
        pytest.skip("Filesystem does not alias these names")
    probe.unlink()
    outside = tmp_path / "outside"
    outside.mkdir()
    path = archive(tmp_path, [
        (f"tool/{name}", "../../outside", stat.S_IFLNK | 0o777),
        (f"tool/{alias}/{nested}", "target", stat.S_IFLNK | 0o777),
    ])
    with pytest.raises(SDKError, match="nests a member under a symlink"):
        extract_zip(path, tmp_path / "stage", root="tool", symlinks=True)
    assert not list(outside.iterdir())


@pytest.mark.skipif(os.name == "nt", reason="Only macOS provider extracts symlinks")
def test_trusted_symlink_outside_staging_is_allowed(tmp_path):
    directory = tmp_path / "directory"
    directory.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    path = archive(tmp_path, [
        ("tool/data", "resource", stat.S_IFREG | 0o644),
        ("tool/link", "data", stat.S_IFLNK | 0o777),
    ])
    extract_zip(path, alias / "stage", root="tool", symlinks=True)
    assert (directory / "stage/tool/link").read_text() == "resource"


def test_duplicate_names_rejected(tmp_path):
    with pytest.warns(UserWarning, match="Duplicate"):
        path = archive(tmp_path, [("tool/file", "data", stat.S_IFREG | 0o644)] * 2)
    with pytest.raises(SDKError, match="Unsafe tool archive member"):
        extract_zip(path, tmp_path / "stage", root="tool")


def test_existing_extraction_destination_not_overwritten(tmp_path):
    path = archive(tmp_path, [("tool/file", "data", stat.S_IFREG | 0o644)])
    stage = tmp_path / "stage"
    stage.mkdir()
    with pytest.raises(FileExistsError):
        extract_zip(path, stage, root="tool")
