# Releasing sdkmgr

Publishing source to GitHub does not authorize a PyPI upload. Obtain explicit
approval before creating a release or publishing a package.

## Validate

1. Update `sdkmgr.__version__` and the changelog. The build reads its version
   from `sdkmgr/__init__.py`; do not duplicate it in `pyproject.toml`.
   Keep the license, copyright, author identity, and community links aligned
   with PyJS. Preserve sdkmgr's own package name, URLs, and Python requirements;
   building sdkmgr must not require a sibling PyJS checkout.
2. Run the local checks from an activated development environment:

   ```sh
   uv sync --locked
   pytest
   ruff check .
   python scripts/check_release.py
   ```

3. Review the source and artifact inventory for local files, credentials, and
   downloaded binaries. The release checker audits the distributions and runs
   the packaged tests from fresh wheel and source installations.
4. Commit and push the reviewed source. Require green GitHub tests and Node
   provider smokes on Linux, macOS, and Windows before publication. Inspect
   skipped jobs as well as failures; simulation is not a real installation.
5. Check the current platform limitations in `ROADMAP.md` and `README.md`.
   Do not imply real-platform coverage that has not been exercised.

Android network smokes require prior acceptance of Google's SDK and requested
package terms. Never enable that acceptance by default in CI. The local
command is `python scripts/smoke_android.py --accept-sdk-license` after review
and acceptance. Do not install system JDK packages just to validate a release
without separate authorization.

## Build and publish after approval

Build from the approved, clean commit into a new directory. For version
0.1.0, for example:

```sh
uv build --out-dir dist/release-0.1.0
uvx twine check --strict dist/release-0.1.0/*
```

Inspect those exact artifacts before uploading them. Use a PyPI project-scoped
token through the publishing tool's prompt or environment; never place it in
source, shell history, or a committed configuration file.

```sh
uv publish dist/release-0.1.0/*
```

After publishing, install that exact version from PyPI in a fresh environment,
check `sdkmgr --version` and `python -m sdkmgr --help`, then tag the approved
commit and create its GitHub release. Record the result in the roadmap.
PyPI versions cannot be overwritten; corrections need another version.
