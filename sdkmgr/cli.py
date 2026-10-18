import argparse
import sys

from . import InstallationRequired, Manager, SDKError, __version__
from .android import installed_packages, sdk_root


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Provision Node, Java 21/25, and Android SDK packages.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--root", help="Private manager bootstrap directory")
    parser.add_argument("--non-interactive", action="store_true", help="Never prompt; defer JDK installs")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List selected-manager Node and discovered JDK installations")
    android_parser = commands.add_parser("android", help="Manage Android SDK packages")
    android_parser.add_argument("--sdk-root", help="Override ANDROID_HOME and the standard SDK location")
    android_commands = android_parser.add_subparsers(dest="android_command", required=True)
    android_commands.add_parser("list", help="Read installed packages without network access")
    android_install = android_commands.add_parser("install", help="Install missing packages and their dependencies")
    android_install.add_argument("packages", nargs="*", help="SDK IDs such as platforms/android-35")
    android_install.add_argument("--accept-sdk-license", action="store_true",
                                 help="Confirm acceptance of Google's SDK and requested package licenses")
    for command in ("install", "which"):
        subparser = commands.add_parser(command)
        subparser.add_argument("sdk", help="node@X.Y.Z, java@21, or java@25")
    args = parser.parse_args(argv)
    try:
        manager = Manager(args.root, interactive=False if args.non_interactive else None)
        if args.command == "android":
            if args.android_command == "install":
                sdk = manager.ensure_android(args.packages, sdk_root=args.sdk_root,
                                             accept_sdk_license=args.accept_sdk_license)
                print(sdk.home)
            else:
                home = sdk_root(manager.platform, args.sdk_root)
                for package, version in sorted(installed_packages(home).items()):
                    print(f"{package}\t{version}")
            return 0
        if args.command == "list":
            for installation in manager.installed():
                print(f"{installation.tool}@{installation.version}\t{installation.home}")
            return 0
        tool, separator, version = args.sdk.partition("@")
        if not separator or not tool or not version:
            raise SDKError("Specify a tool and exact version, for example node@22.14.0.")
        if args.command == "install":
            print(f"Ensuring {tool}@{version}...", file=sys.stderr)
            installation = manager.ensure(tool, version=version)
        else:
            installation = manager.find(tool, version=version)
            if installation is None:
                raise SDKError(f"{args.sdk} is not installed; run sdkmgr install {args.sdk}.")
        print(installation.executable())
        return 0
    except InstallationRequired as error:
        print(f"sdkmgr: {error}", file=sys.stderr)
        return 2
    except SDKError as error:
        print(f"sdkmgr: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("sdkmgr: interrupted", file=sys.stderr)
        return 130
