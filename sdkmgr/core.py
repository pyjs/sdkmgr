from pathlib import Path

from platformdirs import user_data_path

from . import android, bootstrap, java, mise, nvm
from .errors import SDKError
from .installation import Installation, validated_node
from .providers import Platform, validate_node_version
from .system import install_package


class Manager:
    """Provision Node through mise/nvm and Java 21/25 through OS packages.

    Existing mise takes precedence over nvm; with neither installed, ensure()
    bootstraps a pinned mise under root. find() and installed() never install.
    Java package installation requires terminal confirmation; interactive=False
    raises InstallationRequired instead. Authentication belongs to the OS.
    """

    def __init__(self, root: str | Path | None = None, *, interactive: bool | None = None):
        self.root = Path(root) if root is not None else user_data_path("sdkmgr", appauthor=False)
        self.root = self.root.expanduser().resolve()
        self.interactive = interactive
        self.platform = Platform.current()

    def _node_provider(self, *, install: bool = False):
        if executable := mise.executable() or bootstrap.find(self.root, self.platform):
            return mise, executable
        if existing := nvm.discover(self.platform):
            return nvm, existing
        if install:
            return mise, bootstrap.ensure(self.root, self.platform)
        return None

    def _check_tool(self, tool: str, version: str):
        if tool != "node":
            raise SDKError(f"Unknown tool: {tool!r}; expected node or java.")
        validate_node_version(version)

    def ensure(self, tool: str, *, version: str) -> Installation:
        """Return a matching installation, installing only when discovery fails."""
        if tool == "java":
            if existing := self.find(tool, version=version):
                return existing
            install_package(java.install_command(self.platform, version), interactive=self.interactive)
            if installed := self.find(tool, version=version):
                return installed
            raise SDKError(
                f"The installer completed, but JDK {version} was not found. "
                "Set JAVA_HOME to its installation directory and retry."
            )
        self._check_tool(tool, version)
        provider, context = self._node_provider(install=True)
        if home := provider.node_installations(context, self.platform).get(version):
            return validated_node(home, version, self.platform)
        provider.install_node(context, version, self.platform)
        if home := provider.node_installations(context, self.platform).get(version):
            return validated_node(home, version, self.platform)
        raise SDKError(f"{provider.__name__.rsplit('.', 1)[-1]} completed, but Node {version} was not found.")

    def find(self, tool: str, *, version: str) -> Installation | None:
        """Look up an installation without downloading anything."""
        if tool == "java":
            found = java.find(self.platform, version)
            return Installation(tool, found[1], found[0], self.platform) if found else None
        self._check_tool(tool, version)
        if selection := self._node_provider():
            provider, context = selection
            if home := provider.node_installations(context, self.platform).get(version):
                return validated_node(home, version, self.platform)
        return None

    def installed(self) -> list[Installation]:
        """List the selected Node manager's installations and discovered Java 21/25."""
        result = []
        if selection := self._node_provider():
            provider, context = selection
            for version, home in provider.node_installations(context, self.platform).items():
                result.append(validated_node(home, version, self.platform))
        for version in ("21", "25"):
            if installation := self.find("java", version=version):
                result.append(installation)
        return result

    def find_android(self, *, sdk_root: str | Path | None = None) -> android.AndroidInstallation | None:
        """Discover Android command-line tools without installing or running them."""
        return android.find(android.sdk_root(self.platform, sdk_root), self.platform)

    def ensure_android(self, packages=(), *, sdk_root: str | Path | None = None,
                       accept_sdk_license: bool = False) -> android.AndroidInstallation:
        """Ensure Android package IDs, delegating dependencies to Google's CLI.

        Existing packages are not updated. accept_sdk_license confirms prior
        acceptance of Google's SDK and requested package licenses. It is required
        before any downloads or package installation, but not for existing SDKs.
        IDs use slashes, for example platforms/android-35. No JDK is required;
        no emulator is launched or virtual device created.
        """
        packages = android.validate_packages(packages)
        home = android.sdk_root(self.platform, sdk_root)
        return android.ensure(home, self.platform, packages,
                              interactive=self.interactive, accept_sdk_license=accept_sdk_license)
