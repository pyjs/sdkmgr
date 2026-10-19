import pytest

from sdkmgr import AndroidInstallation, SDKError
from sdkmgr.providers import Platform


@pytest.mark.parametrize("system", ["linux", "macos", "windows"])
@pytest.mark.parametrize("name", ["aapt", "aapt2", "aidl", "d8", "dexdump", "zipalign", "apksigner"])
def test_exact_build_tool(tmp_path, system, name):
    sdk = AndroidInstallation(tmp_path, tmp_path / "tools", Platform(system, "x64"))
    suffix = ""
    if system == "windows":
        suffix = ".bat" if name in {"d8", "apksigner"} else ".exe"
    for version in ("35.0.1", "36.0.0", "36.0.0-rc1"):
        path = tmp_path / "build-tools" / version / (name + suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    expected = tmp_path / "build-tools/35.0.1" / (name + suffix)
    assert sdk.build_tool(name, version="35.0.1") == expected
    with pytest.raises(SDKError, match="build-tools/34.0.0 is missing"):
        sdk.build_tool(name, version="34.0.0")


@pytest.mark.parametrize("name,version", [
    ("../aapt2", "35.0.1"), ("aapt2", "../35.0.1"), ("aapt2", "latest"),
    ("aapt2", "35"), ("aapt2", "35.0.1/../../other"),
])
def test_invalid_build_tool(tmp_path, name, version):
    sdk = AndroidInstallation(tmp_path, tmp_path / "tools", Platform("linux", "x64"))
    with pytest.raises(SDKError):
        sdk.build_tool(name, version=version)
    assert not list(tmp_path.iterdir())


def test_platform_jar(tmp_path):
    sdk = AndroidInstallation(tmp_path, tmp_path / "tools", Platform("linux", "x64"))
    jar = tmp_path / "platforms/android-35/android.jar"
    jar.parent.mkdir(parents=True)
    jar.touch()
    assert sdk.platform_jar(35) == jar
    with pytest.raises(SDKError, match="platforms/android-36 is missing android.jar"):
        sdk.platform_jar(36)


@pytest.mark.parametrize("api", [True, 0, -1, "35", "../35", 35.0])
def test_invalid_api(tmp_path, api):
    sdk = AndroidInstallation(tmp_path, tmp_path / "tools", Platform("linux", "x64"))
    with pytest.raises(SDKError, match="positive integer"):
        sdk.platform_jar(api)
