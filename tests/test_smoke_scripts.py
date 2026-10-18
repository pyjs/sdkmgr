import runpy
import sys
from pathlib import Path

from sdkmgr import Manager


def test_android_smoke_never_bootstraps_the_user_sdk(monkeypatch):
    calls = []

    class SDK:
        def __init__(self, home):
            self.home = home

        def installed(self):
            return {"platforms/android-35": "1.0.0"}

    result = None

    def ensure(self, packages, *, sdk_root, accept_sdk_license=False):
        nonlocal result
        calls.append((sdk_root, accept_sdk_license))
        assert packages == ["platforms/android-35"]
        assert sdk_root.name.startswith("sdkmgr-android-smoke-")
        if result is None:
            artifact = sdk_root / "platforms/android-35/android.jar"
            artifact.parent.mkdir(parents=True)
            artifact.touch()
            result = SDK(sdk_root)
        return result

    monkeypatch.setattr(Manager, "ensure_android", ensure)
    monkeypatch.setattr(sys, "argv", ["smoke_android.py", "--accept-sdk-license"])
    runpy.run_path(str(Path(__file__).parents[1] / "scripts/smoke_android.py"), run_name="__main__")
    assert calls == [(result.home, True), (result.home, False)]
    assert not result.home.exists()
