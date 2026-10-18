import hashlib
import os
import stat
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sdkmgr import InstallationRequired, Manager, SDKError, android
from sdkmgr.cli import main
from sdkmgr.providers import Platform

HOST = Platform("linux", "x64")


def tools(home, host=HOST):
    directory = home / "cmdline-tools" / "latest"
    launcher = directory / "bin" / ("android.exe" if host.system == "windows" else "android")
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("fake")
    return android.AndroidInstallation(home, directory, host)


def package(home, name, revision="1"):
    directory = home.joinpath(*name.split("/"))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "package.xml").write_text(
        '<sdk:sdk-repository xmlns:sdk="urn:android">'
        f'<localPackage path="{name.replace("/", ";")}"><revision><major>{revision}</major>'
        '</revision></localPackage></sdk:sdk-repository>'
    )
    for artifact in ("adb", "android.jar", "aapt2", "d8"):
        (directory / artifact).touch()


@pytest.fixture
def bootstrap_archive(tmp_path, monkeypatch):
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("cmdline-tools/bin/android", "launcher")
        archive.writestr("cmdline-tools/bin/android.exe", "launcher")
        archive.writestr("cmdline-tools/lib/tool.jar", "library")
        archive.writestr("cmdline-tools/NOTICE.txt", "license notice")
    payload = source.read_bytes()
    monkeypatch.setattr(android, "TOOLS_ARCHIVES", {
        key: (suffix, hashlib.sha256(payload).hexdigest())
        for key, (suffix, digest) in android.TOOLS_ARCHIVES.items()
    })
    calls = []

    def fetch(url, target, **kwargs):
        calls.append(url)
        target.write_bytes(payload)

    monkeypatch.setattr(android, "fetch", fetch)
    return calls


@pytest.mark.parametrize("system,expected", [
    ("linux", "Android/Sdk"), ("macos", "Library/Android/sdk"),
    ("windows", "AppData/Local/Android/Sdk"),
])
def test_default_roots(monkeypatch, tmp_path, system, expected):
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "LOCALAPPDATA"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert android.sdk_root(Platform(system, "x64")) == tmp_path / expected


def test_conflicting_environment_requires_explicit_root(monkeypatch, tmp_path):
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path / "a"))
    monkeypatch.setenv("ANDROID_SDK_ROOT", str(tmp_path / "b"))
    with pytest.raises(SDKError, match="disagree"):
        android.sdk_root(HOST)
    assert android.sdk_root(HOST, tmp_path / "chosen") == tmp_path / "chosen"


def test_read_only_discovery_never_creates_files(tmp_path):
    home = tmp_path / "missing"
    assert android.find(home, HOST) is None
    assert android.installed_packages(home) == {}
    assert not home.exists()


def test_cli_lists_packages_without_command_line_tools(tmp_path, monkeypatch, capsys):
    package(tmp_path, "platforms/android-35")
    monkeypatch.setattr(android.subprocess, "run", lambda *a, **kw: pytest.fail("Offline listing"))
    assert main(["android", "--sdk-root", str(tmp_path), "list"]) == 0
    assert capsys.readouterr().out == "platforms/android-35\t1.0.0\n"
    assert not (tmp_path / "cmdline-tools").exists()


def test_cli_lists_missing_sdk_without_creating_it(tmp_path, capsys):
    home = tmp_path / "missing"
    assert main(["android", "--sdk-root", str(home), "list"]) == 0
    assert capsys.readouterr().out == ""
    assert not home.exists()


def test_unreadable_package_directory_is_not_reported_as_empty(tmp_path, monkeypatch):
    def walk(path, *, onerror):
        onerror(PermissionError("cannot read SDK"))

    monkeypatch.setattr(android.os, "walk", walk)
    with pytest.raises(SDKError, match="Cannot read Android package records"):
        android.installed_packages(tmp_path)


@pytest.mark.parametrize("host", [HOST, Platform("macos", "arm64"), Platform("windows", "x64")])
def test_paths_environment_and_versioned_tools(tmp_path, host):
    sdk = tools(tmp_path, host)
    renamed = sdk.tools.with_name("20.0")
    sdk.tools.rename(renamed)
    sdk = android.find(tmp_path, host)
    assert sdk.tools == renamed
    suffix = ".exe" if host.system == "windows" else ""
    assert sdk.executable("adb") == tmp_path / "platform-tools" / f"adb{suffix}"
    assert sdk.executable("emulator") == tmp_path / "emulator" / f"emulator{suffix}"
    base = {"PATH": "original", "JAVA_HOME": "jdk", "REPO_OS_OVERRIDE": "wrong"}
    result = sdk.environment(base)
    assert result["ANDROID_HOME"] == result["ANDROID_SDK_ROOT"] == str(tmp_path)
    assert result["JAVA_HOME"] == "jdk"
    assert "REPO_OS_OVERRIDE" not in result
    assert result["PATH"].endswith(os.pathsep + "original")
    assert base["REPO_OS_OVERRIDE"] == "wrong"
    with pytest.raises(SDKError, match="Unknown Android executable"):
        sdk.executable("../outside")


@pytest.mark.parametrize("invalid", ["platform-tools", ["--licenses"], ["../outside"],
                                    ["platforms/.."], ["platforms;android-35"],
                                    [";bad"], ["bad&command"], [None]])
def test_invalid_packages_do_not_install(tmp_path, monkeypatch, invalid):
    monkeypatch.setattr(Manager, "ensure", lambda *a, **kw: pytest.fail("Installed Java"))
    with pytest.raises(SDKError, match="packages must|Invalid Android"):
        Manager().ensure_android(invalid, sdk_root=tmp_path / "missing")
    assert not (tmp_path / "missing").exists()


def test_package_records_are_offline_and_match_their_location(tmp_path):
    package(tmp_path, "platforms/android-35", "2")
    package(tmp_path, "platform-tools", "37")
    package(tmp_path, "wrong")
    (tmp_path / "wrong").rename(tmp_path / "moved")
    assert android.installed_packages(tmp_path) == {
        "platforms/android-35": "2.0.0", "platform-tools": "37.0.0",
    }
    (tmp_path / "moved" / "package.xml").write_text("broken")
    with pytest.raises(SDKError, match="Invalid Android package record"):
        android.installed_packages(tmp_path)


def test_bootstrap_consent_precedes_download_and_jdk(tmp_path, monkeypatch):
    monkeypatch.setattr(android, "fetch", lambda *a, **kw: pytest.fail("Downloaded"))
    monkeypatch.setattr(Manager, "ensure", lambda *a, **kw: pytest.fail("Installed Java"))
    with pytest.raises(InstallationRequired, match="accept-sdk-license"):
        Manager().ensure_android((), sdk_root=tmp_path / "missing")
    assert not (tmp_path / "missing").exists()


def test_discovery_ignores_staging_and_orders_numeric_versions(tmp_path):
    sdk = tools(tmp_path)
    sdk.tools.rename(sdk.tools.with_name("9.0"))
    sdk = tools(tmp_path)
    sdk.tools.rename(sdk.tools.with_name("20.0"))
    sdk = tools(tmp_path)
    sdk.tools.rename(sdk.tools.with_name(".sdkmgr-partial"))
    assert android.find(tmp_path, HOST).tools.name == "20.0"


def test_partial_registered_package_is_not_silently_reinstalled(tmp_path, monkeypatch):
    tools(tmp_path)
    package(tmp_path, "platform-tools")
    (tmp_path / "platform-tools" / "adb").unlink()
    monkeypatch.setattr(android.subprocess, "run", lambda *a, **kw: pytest.fail("Overwrote partial SDK"))
    with pytest.raises(SDKError, match="registered but missing"):
        android.ensure(tmp_path, HOST, ("platform-tools",), interactive=False, accept_sdk_license=True)


@pytest.mark.parametrize("host", [HOST, Platform("macos", "x64"),
                                 Platform("macos", "arm64"), Platform("windows", "x64")])
def test_pinned_bootstrap_and_reuse(tmp_path, bootstrap_archive, host):
    home = tmp_path / "sdk"
    sdk = android.ensure(home, host, (), interactive=False, accept_sdk_license=True)
    assert sdk.executable().is_file()
    assert (sdk.tools / "NOTICE.txt").read_text() == "license notice"
    if os.name != "nt":
        assert sdk.executable().stat().st_mode & stat.S_IXUSR
    assert android.ensure(home, host, (), interactive=False) == sdk
    assert len(bootstrap_archive) == 1
    assert android.TOOLS_BUILD in bootstrap_archive[0]
    assert not list(home.rglob(".sdkmgr-*"))


def test_concurrent_bootstrap_downloads_once(tmp_path, bootstrap_archive):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: android.ensure(
            tmp_path / "sdk", HOST, (), interactive=False, accept_sdk_license=True,
        ), range(2)))
    assert results[0] == results[1]
    assert len(bootstrap_archive) == 1


def test_bad_checksum_never_publishes(tmp_path, bootstrap_archive, monkeypatch):
    monkeypatch.setattr(android, "fetch", lambda url, target, **kw: target.write_bytes(b"bad"))
    with pytest.raises(SDKError, match="SHA-256"):
        android.ensure(tmp_path / "sdk", HOST, (), interactive=False, accept_sdk_license=True)
    assert android.find(tmp_path / "sdk", HOST) is None
    assert not list((tmp_path / "sdk").rglob(".sdkmgr-*"))


@pytest.mark.parametrize("name", ["../escape", "/absolute", "cmdline-tools/../../escape",
                                "cmdline-tools/bin\\escape", "cmdline-tools/C:escape", "other/file",
                                "cmdline-tools/bin/android\x00hidden"])
def test_archive_traversal_is_rejected(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        # ZipInfo's constructor normalizes backslashes on Windows and truncates NULs.
        entry = zipfile.ZipInfo("placeholder")
        entry.filename = name
        output.writestr(entry, "bad")
    with pytest.raises(SDKError, match="Unsafe Android archive member"):
        android._extract(archive, tmp_path / "stage")
    assert not (tmp_path / "escape").exists()


def test_archive_symlink_is_rejected(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        info = zipfile.ZipInfo("cmdline-tools/link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(info, "../../escape")
    with pytest.raises(SDKError, match="Unsafe Android archive member"):
        android._extract(archive, tmp_path / "stage")


def test_existing_partial_bootstrap_is_not_overwritten(tmp_path, bootstrap_archive):
    target = tmp_path / "cmdline-tools" / f"sdkmgr-{android.TOOLS_BUILD}"
    target.mkdir(parents=True)
    with pytest.raises(SDKError, match="Incomplete Android tools"):
        android.bootstrap(tmp_path, HOST, accept_sdk_license=True)
    assert not bootstrap_archive


def test_missing_packages_only_and_rerun_is_noop(tmp_path, monkeypatch):
    sdk = tools(tmp_path)
    package(tmp_path, "platform-tools")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        package(tmp_path, "platforms/android-35")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(android.subprocess, "run", run)
    requested = ("platform-tools", "platforms/android-35", "platforms/android-35")
    assert android.ensure(tmp_path, HOST, requested, interactive=False, accept_sdk_license=True) == sdk
    assert android.ensure(tmp_path, HOST, requested, interactive=False, accept_sdk_license=True) == sdk
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == sdk.command("sdk", "install", "platforms/android-35")
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["timeout"] == 1200
    assert "--no-metrics" in command
    assert f"--sdk={tmp_path}" in command


def test_success_exit_does_not_hide_missing_packages(tmp_path, monkeypatch):
    sdk = tools(tmp_path)
    monkeypatch.setattr(android.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0))
    with pytest.raises(InstallationRequired, match="packages still missing") as caught:
        android.ensure(tmp_path, HOST, ("platform-tools",), interactive=False, accept_sdk_license=True)
    assert caught.value.command == sdk.command("sdk", "install", "platform-tools")


@pytest.mark.parametrize("failure", ["status", "timeout", "missing-executable"])
def test_installer_errors_are_actionable(tmp_path, monkeypatch, failure):
    tools(tmp_path)

    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("android", 1200)
        if failure == "missing-executable":
            raise OSError("missing")
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(android.subprocess, "run", run)
    with pytest.raises(SDKError, match="Android installer|Android provisioning"):
        android.ensure(tmp_path, HOST, ("platform-tools",), interactive=False, accept_sdk_license=True)


def test_package_install_requires_consent_even_with_existing_cli(tmp_path, monkeypatch):
    tools(tmp_path)
    monkeypatch.setattr(android.subprocess, "run", lambda *a, **kw: pytest.fail("Ran installer"))
    with pytest.raises(InstallationRequired, match="accept-sdk-license"):
        android.ensure(tmp_path, HOST, ("platform-tools",), interactive=False)


def test_old_sdkmanager_is_not_a_fallback(tmp_path):
    launcher = tmp_path / "cmdline-tools" / "latest" / "bin" / "sdkmanager"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("old")
    assert android.find(tmp_path, HOST) is None


def test_old_license_command_is_not_exposed():
    with pytest.raises(SystemExit) as caught:
        main(["android", "licenses"])
    assert caught.value.code == 2


def test_android_command_is_explicit_about_root_and_metrics(tmp_path):
    sdk = tools(tmp_path)
    assert sdk.command("sdk", "install", "platforms/android-35") == (
        str(sdk.executable()), "--no-metrics", f"--sdk={tmp_path}",
        "sdk", "install", "platforms/android-35",
    )
    for removed in ("sdkmanager", "avdmanager"):
        with pytest.raises(SDKError, match="Unknown Android executable"):
            sdk.executable(removed)


def test_cli_lists_and_installs_without_java(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(Platform, "current", classmethod(lambda cls: HOST))
    tools(tmp_path)
    package(tmp_path, "platform-tools", "37")
    calls = []
    monkeypatch.setattr(Manager, "ensure", lambda *a, **kw: pytest.fail("Installed Java"))
    assert main(["android", "--sdk-root", str(tmp_path), "list"]) == 0
    assert capsys.readouterr().out == "platform-tools\t37.0.0\n"
    assert calls == []
    assert main(["--non-interactive", "android", "--sdk-root", str(tmp_path),
                 "install", "platform-tools"]) == 0
    assert calls == []
    assert capsys.readouterr().out == str(tmp_path) + "\n"


def test_cli_missing_bootstrap_license_exit_code(tmp_path, capsys):
    assert main(["--non-interactive", "android", "--sdk-root", str(tmp_path), "install"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "accept-sdk-license" in output.err
