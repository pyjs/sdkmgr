import io
import subprocess
import sys
from unittest.mock import Mock

import pytest

from sdkmgr import SDKError, android, mise, nvm
from sdkmgr.process import progress_output


@pytest.mark.parametrize("provider", ["mise", "nvm", "android"])
@pytest.mark.parametrize("status", [0, 7])
def test_installer_output_under_python_capture(monkeypatch, capsys, provider, status):
    run = subprocess.run

    def child(command, **options):
        return run([
            sys.executable, "-c",
            "import sys; print('progress', flush=True); "
            f"print('detail', file=sys.stderr, flush=True); sys.exit({status})",
        ], **options)

    monkeypatch.setattr(subprocess, "run", child)
    if provider == "android":
        sdk = Mock()
        sdk.command.return_value = ("android", "sdk", "install")
        sdk.environment.return_value = None
        assert android._run(sdk, (), interactive=False).returncode == status
    else:
        def invoke():
            if provider == "mise":
                return mise._run("mise", "install", installing=True)
            return nvm._run(("nvm", "install"), installing=True)

        if status:
            with pytest.raises(SDKError, match="status 7"):
                invoke()
        else:
            assert invoke().returncode == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.endswith("progress\ndetail\n")


def test_progress_output_preserves_descriptor_stream(monkeypatch, tmp_path):
    with (tmp_path / "stderr").open("w+") as stream:
        monkeypatch.setattr(sys, "stderr", stream)
        with progress_output() as output:
            assert output is stream
        assert not stream.closed


def test_progress_output_replays_on_timeout(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    with pytest.raises(subprocess.TimeoutExpired):
        with progress_output() as output:
            output.write("before timeout\n")
            raise subprocess.TimeoutExpired("installer", 600)
    assert stream.getvalue() == "before timeout\n"
    assert output.closed


def test_discovery_keeps_separate_pipes():
    with progress_output(False) as output:
        assert output == subprocess.PIPE
