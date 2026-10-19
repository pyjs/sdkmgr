"""Opt-in host Clang validation or Tailwind installation in temporary storage."""

import argparse
import subprocess
import tempfile
from pathlib import Path

from sdkmgr import Manager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=("clang", "tailwindcss"))
    parser.add_argument("--version", default="4.3.3", help="Exact Tailwind release")
    parser.add_argument("--sanitizer", action="append", default=[], choices=("address", "undefined"))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="sdkmgr-tools-smoke-") as temporary:
        root = Path(temporary)
        manager = Manager(root, interactive=False)
        if args.tool == "clang":
            compiler = manager.find_clang()
            if compiler is None:
                raise RuntimeError("Install Clang before this smoke test; it does not run OS installers.")
            compiler.validate(sanitizers=args.sanitizer)
            print(f"Clang {compiler.version}: C executable and LLVM IR shared-library links passed.")
        else:
            tool = manager.ensure("tailwindcss", version=args.version)
            assert manager.ensure("tailwindcss", version=args.version) == tool
            source = root / "input.css"
            output = root / "output.css"
            source.write_text(
                '@import "tailwindcss" source(none);\n@source inline("underline");\n',
                encoding="utf-8",
            )
            subprocess.run(
                [tool.executable(), "-i", source, "-o", output],
                cwd=root, env=tool.environment(), check=True, timeout=60,
                stdin=subprocess.DEVNULL,
            )
            assert "text-decoration-line: underline" in output.read_text(encoding="utf-8")
            location = "temporary managed cache" if tool.managed else "existing installation"
            print(f"Tailwind {tool.version}: {location}, reuse, and CSS compilation passed.")


if __name__ == "__main__":
    main()
