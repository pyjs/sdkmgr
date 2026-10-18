"""Download and execute Node through a provider; intended for disposable CI hosts."""

import argparse
import os
import subprocess
import tempfile
from pathlib import Path

from sdkmgr import bootstrap, mise, nvm
from sdkmgr.installation import validated_node
from sdkmgr.providers import Platform


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=("mise", "nvm"))
    parser.add_argument("--version", default="22.14.0")
    args = parser.parse_args()
    host = Platform.current()
    with tempfile.TemporaryDirectory(prefix="sdkmgr-smoke-") as temporary:
        root = Path(temporary)
        if args.provider == "mise":
            os.environ["MISE_DATA_DIR"] = str(root / "mise-data")
            os.environ["MISE_CACHE_DIR"] = str(root / "mise-cache")
            os.environ["MISE_STATE_DIR"] = str(root / "mise-state")
            provider = mise
            context = bootstrap.ensure(root, host)
        else:
            provider = nvm
            context = nvm.discover(host)
            if context is None:
                raise RuntimeError("Install nvm in a disposable location before this test.")
        provider.install_node(context, args.version, host)
        home = provider.node_installations(context, host)[args.version]
        installation = validated_node(home, args.version, host)
        subprocess.run(
            [installation.executable(), "-e", "console.log('sdkmgr smoke: ' + process.version)"],
            env=installation.environment(), check=True, timeout=10,
        )


if __name__ == "__main__":
    main()
