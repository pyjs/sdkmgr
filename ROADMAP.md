# Roadmap

## 0.3.1 published

- Published to PyPI with source tagged `v0.3.1`. Both archive hashes match the
  inspected artifacts; a fresh registry installation reports 0.3.1 through
  the CLI, library and distribution metadata.

- Bound retries for Windows access/sharing errors during Tailwind cache
  publication. Persistent errors still fail; checksums and atomicity remain
  unchanged. Simulated retry-boundary coverage and real provider smokes pass,
  but the intermittent lock holder and duration remain unknown.
- Include Chrome/browser in the package summary and keywords.
- Follow-up: preserve the original publication error if a persistent Windows
  lock also prevents temporary-directory cleanup, and make retries observable.
  Investigate the similar mise bootstrap sequence if a real failure occurs;
  no mise lock failure is currently established.

## 0.3.0 published

- Published to PyPI with source tagged `v0.3.0`. Published wheel and source
  archive hashes match the inspected artifacts. A fresh registry installation
  reports 0.3.0 through the CLI, library and distribution metadata.
- Browser provisioning, Android inspection, locked artifacts, Clang and
  Tailwind are available. Real provider smokes pass on Linux, macOS and Windows
  at the approved release candidate; the merged release tree is identical.
- The 0.3.0 long description documents the browser APIs; summary and keywords
  are expanded in 0.3.1.

## 0.2.0 published

- Published to PyPI with source tagged `v0.2.0`. Both published archive hashes
  match the inspected artifacts; a fresh registry installation passes CLI,
  library and captured-output smoke checks.
- Captured installer consoles, missing stderr, bounded embedded Android
  execution and diagnostic escaping are supported. Installation consent and
  provider selection remain unchanged.
- Follow-up: harden replay against custom console streams that advertise
  invalid or inaccurate encoding metadata.

## Initial release complete

- Version 0.1.0 was published to PyPI on 2026-10-18 with user approval.
  Both published artifact hashes match the validated local distributions.
  A fresh, uncached PyPI installation passes the CLI and library smoke checks.
  Source is published at `pyjs/sdkmgr`.
- Local readiness review: 191 tests pass on Python 3.13, including download
  failure cleanup, offline Android listing without tools, and isolated smoke
  bootstrap regressions. Ruff passes. Both wheel and source installations
  pass the packaged tests outside the checkout.
- All eleven GitHub CI jobs pass: Python 3.12/3.14 tests and installed-artifact
  checks on Linux, macOS, and Windows; real mise/Node installs on all three;
  and real nvm/Node installs on Linux and macOS. The Windows fixture and raw
  ZIP filename issues found in the first CI run are fixed.
- Fresh Linux mise/Node and Android bootstrap/API 35 smokes pass. Android's
  temporary SDK is removed after verification and a no-op retry. Package
  metadata passes `twine check --strict` for both distributions.
- The initial alpha is published, with the platform
  validation limits below documented rather than implied to be covered.
- Follow `RELEASING.md` for artifact checks and explicit publication approval.

## Further validation and follow-up

- Browser discovery and pinned Chrome for Testing provisioning, installer-free
  Android SDK inspection, and checksum-addressed artifact acquisition are
  implemented for 0.3.0. Editable-source integration has been exercised;
  the downstream dependency update follows publication.
- Linux pinned browser download, reuse, and headless rendering pass. This
  Ubuntu host needs an explicit test-only sandbox option; no host policy was
  changed. Browser discovery does not imply launch compatibility. Real Linux,
  macOS and Windows browser installation/reuse/rendering smokes pass.
- Initial pre-release validation: 365 local tests passed, including tests run
  against isolated wheel and source installations. Ruff and diff checks pass.
  Fresh Linux Tailwind 4.3.3 download, checksum/version validation, cache
  reuse, and CSS generation pass. Existing Android API 35 and build-tools
  35.0.1 lookups pass without changing SDK packages.
- Manual-dispatch CI verifies real Clang linking and Tailwind download, cache
  reuse, and CSS generation on Linux, macOS, and Windows. Colored Tailwind
  banners and explicit relative executable selection have regression coverage.
- Smoke-test real package installations on supported systems and ARM64.
- Update the CI action versions to remove GitHub's Node 20 deprecation
  warnings; the current actions pass under its Node 24 compatibility mode.
- PyJS already uses Node and JDK provisioning without replacing its runners.
  Complete adoption of the additional 0.3.0 APIs after publication.
- Verify real nvm-windows v1/v2 installations, beyond simulated commands.
- Validate real Android bootstrap/package installs on Windows and macOS;
  Linux bootstrap, temporary API 35 installation, and no-op retries pass.
- Add an opt-in Android provisioning CI smoke after explicit license review.
- Clang provisioning and C/LLVM IR link probes are included in 0.3.0.
  Linux validates against the existing Clang 21.1.8, including address and
  undefined sanitizer linking. Verify real OS installation and macOS/Windows
  prerequisites before claiming those installation paths are validated.
- Reuse inactive versions from popular installed runtime managers.
- Add a project manifest and lock file before supporting version ranges.
- Tailwind provisioning and exact Android build-tool/platform lookup are
  included in 0.3.0. Complete PyJS adoption after publication;
  PyJS runners and compilation flags remain outside sdkmgr.
- Evaluate browser and other PyJS tool requirements individually. Maven
  dependency resolution and Gradle orchestration remain outside this slice.
- Add cache inspection, repair, and removal without deleting external SDKs.
- Evaluate additional provider-owned package verification beyond sdkmgr's
  existing version and required-file checks.

Implemented: flat package layout; Java 21/25 package providers including
Arch/Omarchy through pacman; discovery, confirmation, OS-owned authentication,
and restart after manual installation; mise/nvm Node adapters and pinned mise
bootstrap. Provider selection is existing mise, existing nvm, then bootstrap
mise. The direct Node downloader is removed. Local regressions and the CI
provider smokes above pass using disposable stores. No system package
installation or local manager migration has occurred.

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
