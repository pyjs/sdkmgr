# Changelog

## 0.3.1 — 2026-10-19

- Retry transient Windows access and sharing errors when publishing the
  verified Tailwind executable, with a bounded wait and no repeated download.

## 0.3.0 — 2026-10-19

- Discover Chrome/Chromium without launching it; optionally provision pinned,
  checksum-verified Chrome for Testing with explicit managed selection.
- Inspect existing Android SDKs without requiring the installer CLI.
- Acquire caller-selected HTTPS artifacts through a checksum-addressed cache
  with verified reuse, installation locks, and atomic publication.
- Discover and provision host Clang through OS package managers, with explicit
  consent and C/LLVM IR compile/link validation. Report missing platform SDKs
  and optionally check sanitizer linking without running generated programs.
- Provision exact standalone Tailwind versions with platform/libc selection,
  release checksums, install locks, atomic cache publication, and reuse of
  matching installed executables.
- Resolve exact Android build-tool versions and platform jars, including
  Windows executable/script suffixes, without installing during lookup.

## 0.2.0 — 2026-10-18

- Node and Android installation work with captured Python stderr, including
  pytest's `capsys` fixture and embedded consoles. Output goes to stderr;
  streams without a file descriptor receive it when the child process exits.
  Terminal output still streams directly, and installation consent is unchanged.
- Preserve installer results when stderr is absent or a captured console stops
  accepting output. Replayed progress retains carriage returns and uses Python's
  default text encoding, including UTF-8 mode.
- Require real terminal descriptors for interactive Android installs, avoiding
  hidden prompts in embedded consoles. Escape characters unsupported by the
  output console instead of losing the surrounding diagnostic text.

## 0.1.0 — 2026-10-18

- Use PyJS's BSD-3-Clause license, copyright, author identity, and community
  metadata for this companion project.
- Keep failed or interrupted downloads out of their destination paths and
  preserve existing files. Report malformed redirects without tracebacks.
- List Android packages offline even when command-line tools are absent.
- Validate wheel and source installations against the packaged tests, with a
  single source for the package and CLI version.
- Keep the Android installation smoke's bootstrap inside its temporary SDK.
- Validate original ZIP member names before Windows path normalization or
  NUL truncation can hide malformed archive entries.

- Provision Android SDK package sets through Google's `android sdk` CLI,
  reusing existing SDKs and delegating package dependencies to Google.
- Bootstrap missing Android tools from pinned, checksum-verified archives,
  with explicit download-license consent and safe staged extraction.
- Add offline Android package listings, explicit installation consent, install
  locking, and diagnostics for partial installations. Disable CLI metrics.
- Use slash-separated Android package IDs; omit the deprecated `sdkmanager`
  adapter, license-review command, and unnecessary external JDK dependency.

- Discover JDK 21 and 25 across environment, system, and package locations.
- Install JDKs through apt, dnf, pacman, Homebrew, or WinGet after confirmation.
- Support Arch/Omarchy without refreshing databases or upgrading the system.
- Prefer existing mise for Node, reusing inactive versions without switching
  global defaults or running project hooks.
- Defer privileged authentication to the OS and support manual-install retries.
- Return executable paths and subprocess-local environments.
- Reuse existing nvm when mise is absent; otherwise bootstrap a pinned,
  checksum-verified mise without editing shell profiles.
- Replace the direct Node downloader with manager-owned provisioning.
- Preserve Unix nvm defaults by staging installations before publishing them.
- Add real-provider CI smoke jobs alongside the isolated unit tests.
