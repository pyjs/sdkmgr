"""Build and test both distributions outside the source checkout; never publish."""

import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from email.parser import Parser
from pathlib import Path


def run(*command, cwd, env):
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=300)


def main():
    project = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    for name in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="sdkmgr-release-") as temporary:
        root = Path(temporary)
        dist = root / "dist"
        run("uv", "build", "--out-dir", str(dist), cwd=project, env=env)
        wheel, = dist.glob("*.whl")
        source, = dist.glob("*.tar.gz")
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            metadata_name, = [name for name in names if name.endswith(".dist-info/METADATA")]
            metadata = Parser().parsestr(archive.read(metadata_name).decode())
            version = metadata["Version"]
            assert metadata["Name"] == "sdkmgr"
            assert all(name.startswith(("sdkmgr/", f"sdkmgr-{version}.dist-info/"))
                       for name in names), names
            assert not any(name.endswith((".exe", ".so", ".dll", ".pyc")) for name in names)
            assert any(name.endswith("/LICENSE") for name in names)
        with tarfile.open(source) as archive:
            names = archive.getnames()
            prefix = f"sdkmgr-{version}/"
            allowed = {
                "sdkmgr", "tests", "scripts", "README.md", "CHANGELOG.md", "LICENSE",
                "pyproject.toml", "uv.lock", "PKG-INFO", ".gitignore",
            }
            assert all(name.startswith(prefix) and name[len(prefix):].split("/", 1)[0] in allowed
                       for name in names), names
            assert all((not part.startswith(".") or part == ".gitignore")
                       and part != "__pycache__"
                       for name in names for part in Path(name).parts), names
            archive.extractall(root / "source", filter="data")
        tests = root / "source" / f"sdkmgr-{version}" / "tests"
        for artifact in (wheel, source):
            environment = root / artifact.suffix.removeprefix(".")
            run("uv", "venv", "--python", sys.executable, str(environment), cwd=root, env=env)
            binaries = environment / ("Scripts" if os.name == "nt" else "bin")
            python = binaries / ("python.exe" if os.name == "nt" else "python")
            command = binaries / ("sdkmgr.exe" if os.name == "nt" else "sdkmgr")
            run("uv", "pip", "install", "--python", str(python), str(artifact), "pytest",
                cwd=root, env=env)
            run(str(python), "-I", "-c",
                "from importlib.metadata import version; import sdkmgr; "
                f"assert sdkmgr.__version__ == version('sdkmgr') == {version!r}",
                cwd=root, env=env)
            run(str(command), "--version", cwd=root, env=env)
            run(str(python), "-I", "-m", "sdkmgr", "--help", cwd=root, env=env)
            run(str(python), "-I", "-m", "pytest", "--import-mode=importlib", "-q", str(tests),
                cwd=root, env=env)
        print(f"sdkmgr {version}: wheel and source distribution installed and tested successfully.")


if __name__ == "__main__":
    main()
