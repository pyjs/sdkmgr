# sdkmgr

A Python library and command-line tool for finding development SDKs and
installing missing tools through established package managers.

This is an alpha project preparing its first PyPI release. Java provisioning
supports **JDK 21 and 25** through apt, dnf, pacman, Homebrew, or WinGet.
There is no JDK fallback,
vendor requirement for existing installations, or exact patch-version pinning.

Node provisioning prefers existing mise, otherwise existing nvm, otherwise
bootstraps mise. sdkmgr no longer downloads Node archives itself. Android
provisioning delegates package installation to Google's command-line tools.
LLVM compilation dependencies follow in a later version.

## Install from source

Python 3.12 or newer is required. Until the first PyPI release, install the CLI
from this repository:

```sh
uv tool install git+https://github.com/pyjs/sdkmgr.git
sdkmgr --help
```

For a library dependency, use
`pip install git+https://github.com/pyjs/sdkmgr.git` in your environment.
Installing sdkmgr itself does not download any SDK or change tool selections.

## Android SDK packages

```sh
sdkmgr android list
sdkmgr android install platform-tools platforms/android-35 build-tools/35.0.1
```

Android provisioning uses Google's **`android sdk` CLI only**. There is no
legacy `sdkmanager` adapter or fallback. Package IDs use the CLI's slash
syntax; sdkmgr translates semicolons only when reading Google's package
records. Existing SDK packages do not need to be reinstalled when changing
the management tool.

Root selection is `--sdk-root`, then `ANDROID_HOME`/`ANDROID_SDK_ROOT`, then
the standard user location on Linux, macOS, or Windows. Conflicting environment
variables require an explicit root. The install command prints the SDK root
to stdout; progress goes to stderr.

Installation reuses registered packages without upgrading them, verifies key
files for platform/build tools, and delegates dependencies to Google.
Packages such as `platform-tools` select Google's stable release when absent,
not a pinned revision. This is not yet a reproducible package lock.
The `list` command reads local records without network access and does not
require the Android CLI. A missing SDK root produces an empty listing.

Before downloading the CLI or installing missing packages, review Google's
[SDK terms](https://developer.android.com/studio/terms) and the requested
packages' licenses, then explicitly confirm acceptance:

```sh
sdkmgr android install --accept-sdk-license platform-tools platforms/android-35
```

This flag acknowledges prior acceptance; sdkmgr never supplies automatic
affirmative input. Google's new CLI no longer provides the old
`--licenses` flow, so sdkmgr requires confirmation before invoking installation,
even if the CLI would proceed without prompting. Reusing already installed
packages does not require the flag. Failed or incomplete installs are reported
even when Google's command exits successfully.

The CLI bootstrap archive is pinned and SHA-256 verified, extracted in staging,
then atomically published to a separate command-tools directory. **The launcher
fetches Google's CLI payload on first use.** That subsequent payload and its
cache are managed by Google, not pinned or independently verified by sdkmgr.
Commands launched by sdkmgr include `--no-metrics` and an explicit `--sdk`.
Discovery and no-op provisioning do not launch the CLI.

Existing tools are not replaced. SDK installs are serialized among sdkmgr
callers; do not run Android Studio's SDK installer concurrently. Interrupted
installs are rechecked on retry; registered but damaged packages need explicit
repair. No external JDK is required for provisioning. Obtain one separately
with `ensure("java", version="21")` when your build needs it.

Bootstrap covers Linux x64, macOS x64/ARM64, and Windows x64. Other hosts need
compatible command-line tools installed separately. Windows/macOS support has
simulated tests but still needs real installation verification. Linux bootstrap
and existing SDK reuse are verified locally. See the
[CLI reference](https://developer.android.com/tools/agents/android-cli).

```python
from sdkmgr import Manager

sdk = Manager().ensure_android(
    ["platform-tools", "platforms/android-35", "build-tools/35.0.1"],
    accept_sdk_license=True,  # Only after reviewing and accepting the terms.
)
adb = sdk.executable("adb")
environment = sdk.environment()
```

The returned environment sets SDK paths without changing your shell. Emulator
packages and system images must be requested explicitly. Provisioning never
creates an AVD or starts an emulator.

For an opt-in live smoke, after accepting the terms:

```sh
python scripts/smoke_android.py --accept-sdk-license
```

The smoke bootstraps tools and installs API 35 into a temporary SDK, then
checks a no-op retry and removes that SDK. Google's separate CLI payload cache
may persist; no packages are added to the user's existing SDK.

This bootstraps the CLI if needed, installs API 35 into a temporary SDK,
verifies it, checks a no-op retry, and removes the temporary packages.

## Java from the command line

```sh
sdkmgr install java@21
sdkmgr install java@25
sdkmgr which java@21
sdkmgr list
```

`which` only discovers installations. `install` first looks for a complete,
working JDK of the requested major version. It accepts maintenance updates
and does not require Temurin. A runtime without `javac` and `jar` is not enough.

Discovery checks `JAVA_HOME`, resolved executables on `PATH`, and platform
installation locations. macOS also uses `java_home` and Homebrew's prefix;
Windows also checks registered JDK uninstall locations. It verifies both
`java` and `javac` with ten-second subprocess timeouts.

If the JDK is missing, sdkmgr shows the package-manager command:

```text
JDK installation requires this command:

  /usr/bin/sudo -- /usr/bin/apt-get install openjdk-21-jdk

You can quit, run it yourself, and restart your original command.
Completed installations will be detected automatically.
```

Press Enter to continue, or type `q` to exit. Authentication is handled by
sudo or the Windows installer, never by sdkmgr. On typical sudo systems,
the password requested is your account password, not the root password.
Package-manager confirmation and license prompts remain visible.

If you exit, run the displayed command yourself and restart the command you
originally ran. Discovery happens again, so sdkmgr proceeds without repeating
the completed installation. No separate resume flag or checkpoint is needed.

Without an interactive terminal, or with `--non-interactive`, missing Java
produces instructions and exit status **2** without running an installer:

```sh
sdkmgr --non-interactive install java@21
```

Successful `install` and `which` print the executable path to stdout.
Messages and package-manager output go to stderr. Other expected failures
return status 1; interruption returns 130.

## Package providers

| Platform | Installation command, before elevation |
| --- | --- |
| Debian/Ubuntu | `apt-get install openjdk-21-jdk` |
| Fedora/RHEL family | `dnf install java-21-openjdk-devel` |
| Arch/Omarchy | `pacman -S --needed jdk21-openjdk` |
| macOS | `brew install openjdk@21` |
| Windows | `winget install --exact --id Microsoft.OpenJDK.21 --source winget` |

Java 25 uses the corresponding `25` package names. Linux commands use sudo
unless already running as root. Homebrew is never run through sudo by sdkmgr;
Windows installers handle elevation through the OS.

The package manager must already be installed. sdkmgr does not add repositories,
refresh package indexes, install Homebrew, accept licenses automatically, or
silently substitute another major version. If the requested package is absent
from your OS repositories, installation fails with the package-manager output.
Install an appropriate JDK yourself or use a supported OS release, then retry.

Arch and Omarchy require complete system updates; partial upgrades are not
supported. sdkmgr does not run `pacman -Sy` or perform a whole-system upgrade.
If packages cannot be installed, use your normal system updater (Omarchy's
updater on Omarchy), then retry the original sdkmgr command.

sdkmgr does not explicitly change Java alternatives, shell profiles, or global
environment variables. Package-manager installers can have their own system
side effects. Security updates remain the responsibility of the package manager
and the user's update policy; `ensure()` does not force upgrades.

## Node manager selection

```sh
sdkmgr install node@22.14.0
sdkmgr which node@22.14.0
```

Selection follows this order:

1. Existing mise on `PATH`, in `~/.local/bin`, or previously bootstrapped by
   sdkmgr under its private root.
2. Existing Unix nvm or nvm-windows.
3. Bootstrap a pinned mise if neither manager is present.

A selected manager's failure does not trigger fallback to another provider.
`which` and `list` never bootstrap managers or install Node. A standalone Node
on `PATH` does not bypass this selection order.

### Mise

When mise is present, sdkmgr prefers it, including
versions that are installed but not currently active. It requests an exact
version through mise's built-in Node provider, validates `node --version`, and
requires the bundled npm and npx executables. A missing version is installed
in mise's storage, not sdkmgr's cache. No sudo is used.

Discovery uses `mise ls --installed --json core:node`; installation uses
`mise install core:node@VERSION --jobs=1`. sdkmgr does not run `mise use`,
activate a shell, edit project configuration, or switch global defaults.
Returned paths bypass shims, and `environment()` selects Node only for the
subprocess receiving that environment.

The adapter requires mise's `--no-config` and `--no-hooks` options. These
prevent unrelated project configuration or hooks from running. It also
disables source compilation and the default extra-npm-packages file. Existing
environment settings, including mise's data directory, remain available.
Configuration-file-only customizations are intentionally not loaded.

A broken or incompatible mise installation produces an error instead of a
silent fallback to another installer. Upgrade or repair mise and retry.
Discovery commands have a 30-second timeout; installation has ten minutes and
sends progress to stderr. `find()` never installs a missing version.

Bootstrap downloads mise 2026.9.12 from its official GitHub release and checks
the binary against a SHA-256 pinned in sdkmgr before executing it. No shell
installer runs. Linux uses the musl binary; macOS and Windows use their native
binaries. Both x64 and ARM64 assets are pinned. The executable is installed
atomically under `ROOT/managers/`, without changing `PATH` or shell profiles.
Concurrent bootstrap calls share a lock. A corrupt cached binary produces an
error rather than being silently overwritten.

### Nvm

Unix discovery checks `NVM_DIR`, `~/.nvm`, `XDG_CONFIG_HOME/nvm`, and common
Homebrew/Arch script locations. Inactive versions are reusable. Installation
sources the existing script in a noninteractive Bash subprocess without
loading shell profiles. It requests a prebuilt Node and skips default extra
npm packages. To avoid nvm creating a default alias, installation uses a
temporary `NVM_DIR`; only the validated version is moved into the user's store.

On Windows, sdkmgr discovers `nvm.exe` through `PATH` or `NVM_HOME`, then asks
nvm-windows v1 or v2 for its installation root. It installs missing versions
without invoking `nvm use`. Existing manager settings still apply, including
v2's configured extra npm packages. Version 2 automatically activates its first
Node installation, so an empty v2 store produces manual-install instructions
and exit status 2. Run the displayed command and retry. sdkmgr does not modify
registry preferences or undo manager-owned state changes.

`--non-interactive` disables prompts for privileged Java installation; ordinary
Node provisioning and mise bootstrap remain automatic, including in CI.

## Python integration

```python
import subprocess

from sdkmgr import Manager

manager = Manager()
jdk = manager.ensure("java", version="21")

subprocess.run(
    [jdk.executable("javac"), "Example.java"],
    env=jdk.environment(),
    check=True,
)
```

`environment()` returns a new complete environment with the selected JDK's
`bin` directory first in `PATH` and its home in `JAVA_HOME`. Pass an explicit
mapping to `environment(base)` if needed. Neither form mutates `os.environ`.
`Installation.version` records the detected runtime version, such as
`21.0.12`, rather than just the requested major.

`find("java", version="21")` returns an installation or `None` without
installing anything. `installed()` returns discovered Java 21/25 installations
and versions from the selected Node manager. Old prototype Node caches are not
used or removed.

For unattended callers, disable prompting explicitly:

```python
from sdkmgr import InstallationRequired, Manager

manager = Manager(interactive=False)
try:
    jdk = manager.ensure("java", version="21")
except InstallationRequired as error:
    required_command = error.command
    raise
```

`InstallationRequired.command` is an argument tuple; no shell parsing is needed.
`InstallationRequired` is an `SDKError`. Library calls never terminate the
calling process. Even `interactive=True` cannot launch an installer without
terminal input and terminal stderr. Installer processes inherit stdin;
sdkmgr never reads, stores, forwards, or logs a password.

After an installer reports success, discovery runs again. If its installation
location is not recognized, set `JAVA_HOME` and retry. Long-running interactive
package installations are not given an arbitrary timeout while authentication
or user confirmation may be pending.

## Development

Python 3.12 or newer is required. Activate the environment after `uv sync`:

```sh
uv sync
source .venv/bin/activate
pytest
ruff check .
python scripts/check_release.py
```

The default tests use simulated SDKs and installers. They do not install
packages, ask for passwords, or depend on installed Java, mise, or nvm versions.
The CI configuration covers Python 3.12 and 3.14 on Linux, macOS, and Windows.
The release check builds both distributions in temporary storage, audits their
contents, installs each into a fresh environment, and runs the packaged tests
outside the checkout. It does not publish anything. `uv build` creates the
wheel and source archive in `dist/` when you are ready to retain artifacts.
The Python 3.12/3.14 tests and installed-artifact checks pass on all three
systems. Real mise/Node smokes pass on Linux, macOS, and Windows; real nvm/Node
smokes pass on Linux and macOS. Real OS JDK installation still needs
verification on those platforms.
Do not run an automatic source formatter.

Separate CI jobs exercise real mise bootstrap and Node installation on Linux,
macOS, and Windows, plus Unix nvm on Linux and macOS. These networked smoke
tests are outside the default pytest run:

```sh
python scripts/smoke_node.py mise
python scripts/smoke_node.py nvm
```

The mise smoke uses temporary storage. The nvm smoke installs into the detected
nvm store: use a disposable `NVM_DIR` when testing missing versions. Native
nvm-windows installation still needs a real Windows smoke test.
