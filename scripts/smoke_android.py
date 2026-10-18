"""Opt-in live package installation, isolated from the user's SDK packages."""

import argparse
import tempfile
from pathlib import Path

from sdkmgr import Manager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accept-sdk-license", action="store_true", required=True)
    args = parser.parse_args()
    manager = Manager(interactive=False)
    with tempfile.TemporaryDirectory(prefix="sdkmgr-android-smoke-") as temporary:
        home = Path(temporary)
        packages = ["platforms/android-35"]
        sdk = manager.ensure_android(packages, sdk_root=home,
                                     accept_sdk_license=args.accept_sdk_license)
        assert (sdk.home / "platforms" / "android-35" / "android.jar").is_file()
        assert packages[0] in sdk.installed()
        assert manager.ensure_android(packages, sdk_root=home) == sdk
        print("Android package installation, verification, and no-op retry passed.")


if __name__ == "__main__":
    main()
