# Roadmap

Publication is on hold until the user approves it. The first release
establishes independent provisioning before PyJS adopts it.

## First-release gate

- The user approved creating `pyjs/sdkmgr` and pushing the source. PyPI
  publication is still on hold.
- Local readiness review: 190 tests pass on Python 3.13, including download
  failure cleanup, offline Android listing without tools, and isolated smoke
  bootstrap regressions. Ruff passes. Both wheel and source installations
  pass the same 190 packaged tests outside the checkout.
- A fresh Linux mise bootstrap and real Node installation smoke pass; package
  metadata also passes `twine check --strict` for both distributions.
- GitHub CI must verify Python 3.12/3.14 and provider smokes on Linux, macOS,
  and Windows before the first PyPI upload.
- Follow `RELEASING.md` for artifact checks and explicit publication approval.

## Further validation and follow-up

- Smoke-test real package installations on supported systems and ARM64.
- Integrate Node and JDK provisioning into PyJS without changing its runners:
  keep the developer's local nvm; install mise explicitly in PyJS CI so both
  provider paths are exercised regularly. This awaits PyJS adoption of sdkmgr.
- Verify real nvm-windows v1/v2 installations, beyond simulated commands.
- Validate real Android bootstrap/package installs on Windows and macOS;
  Linux bootstrap, temporary API 35 installation, and no-op retries pass.
- Add an opt-in Android provisioning CI smoke after explicit license review.
- Next version: provision LLVM compilation dependencies; keep these outside
  the initial release's Node/JDK/Android scope.
- Reuse inactive versions from popular installed runtime managers.
- Add a project manifest and lock file before supporting version ranges.
- Evaluate browser, LLVM, Gradle, and other PyJS tool requirements individually.
- Add cache inspection, repair, and removal without deleting external SDKs.
- Evaluate additional provider-owned package verification beyond sdkmgr's
  existing version and required-file checks.

Implemented: flat package layout; Java 21/25 package providers including
Arch/Omarchy through pacman; discovery, confirmation, OS-owned authentication,
and restart after manual installation; mise/nvm Node adapters and pinned mise
bootstrap. Provider selection is existing mise, existing nvm, then bootstrap
mise. The direct Node downloader is removed. Local regression tests and real
Linux mise/nvm Node installation smokes pass using temporary storage. Networked
provider smoke jobs are configured but have not run on GitHub yet. No system
package installation, local manager migration, or publication has occurred.

Android uses only `android sdk`, with slash-separated package IDs and offline
package records. The legacy adapter and license-review command are removed.
It requires explicit SDK/package license consent before installation, disables
metrics, and does not provision a JDK. Archive safety, locks, partial installs,
and retry behavior have regression tests. After user license acceptance, the
new CLI was installed alongside the existing tools and tested locally. API 35
was installed into a temporary SDK, verified, reused, and cleaned up. Existing
SDK packages were not upgraded or removed; no emulator was launched.

The checksum pin covers Google's bootstrap archive, not the CLI payload its
launcher downloads on first use. Google owns that payload's cache/update path.
Evaluate reproducible payload pinning and standalone CLI discovery separately.

Java supports only majors 21 and 25, through OS package managers. No private
JDK archive provider or automatic alternative repository should be added.
Do not turn this into a build runner or explicitly switch global defaults.
