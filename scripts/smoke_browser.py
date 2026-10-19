"""Opt-in Chrome for Testing download, reuse, and headless rendering smoke."""

import argparse
import subprocess
import tempfile
from pathlib import Path

from sdkmgr import Manager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Reuse this cache instead of a disposable installation")
    parser.add_argument("--browser-argument", action="append", default=[], help="Explicit browser launch flag")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="sdkmgr-browser-smoke-") as temporary:
        root = Path(temporary)
        manager = Manager(args.root or root / "cache", interactive=False)
        tool = manager.ensure_browser(managed=True)
        assert manager.find_browser(managed=True) == tool
        assert manager.ensure_browser(managed=True) == tool
        page = root / "page.html"
        page.write_text('<body><script>document.body.textContent = "browser-ready";</script></body>')
        try:
            result = subprocess.run(
                [str(tool.executable()), "--headless=new", "--disable-gpu", "--no-first-run",
                 f"--user-data-dir={root / 'profile'}", *args.browser_argument, "--dump-dom", page.as_uri()],
                check=True, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(f"Chrome rendering failed: {error.stderr[-8000:]}") from error
        assert "<body>browser-ready</body>" in result.stdout, result
        print(f"Chrome for Testing {tool.version}: pinned installation, reuse, and headless rendering passed.")


if __name__ == "__main__":
    main()
