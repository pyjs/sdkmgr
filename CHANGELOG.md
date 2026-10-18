# Changelog

## Unreleased

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
