import io
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from sdkmgr import SDKError, android, mise, nvm, process
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
    assert captured.err.endswith(f"progress{os.linesep}detail{os.linesep}")


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


@pytest.mark.parametrize("provider", ["mise", "nvm", "android"])
@pytest.mark.parametrize("status", [0, 7])
def test_installer_without_stderr(monkeypatch, provider, status):
    run = subprocess.run

    def child(command, **options):
        assert options["stdout"] is None
        return run([sys.executable, "-c", f"raise SystemExit({status})"], **options)

    monkeypatch.setattr(sys, "stderr", None)
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


@pytest.mark.parametrize("encoding", ["utf-8", "cp1252"])
def test_replay_preserves_newlines_and_uses_text_encoding(monkeypatch, encoding):
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    select_encoding = Mock(return_value=encoding)
    monkeypatch.setattr(process, "text_encoding", select_encoding)
    message = "10%\r50%\r100%\r\ncafé\n"
    with progress_output() as output:
        subprocess.run([
            sys.executable, "-c",
            f"import sys; sys.stdout.buffer.write({message.encode(encoding)!r})",
        ], stdout=output, check=True)
    select_encoding.assert_called_once_with(None)
    assert stream.getvalue() == message


@pytest.mark.parametrize("operation", ["write", "flush"])
@pytest.mark.parametrize("error_type", [OSError, ValueError, UnicodeError])
@pytest.mark.parametrize("outcome", [None, subprocess.CalledProcessError(7, "installer"),
                                     subprocess.TimeoutExpired("installer", 1), KeyboardInterrupt()])
def test_replay_failure_preserves_outcome(monkeypatch, operation, error_type, outcome):
    stream = io.StringIO()
    monkeypatch.setattr(stream, operation, Mock(side_effect=error_type("console unavailable")))
    monkeypatch.setattr(sys, "stderr", stream)

    def invoke():
        with progress_output() as output:
            output.write("progress\n")
            if outcome is not None:
                raise outcome
        assert output.closed

    if outcome is None:
        invoke()
    else:
        with pytest.raises(type(outcome)) as caught:
            invoke()
        assert caught.value is outcome


@pytest.mark.parametrize("prefix_size", [0, 65535])
@pytest.mark.parametrize("status", [0, 7])
def test_replay_escapes_unencodable_text_without_losing_diagnostics(monkeypatch, prefix_size, status):
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii", errors="strict", newline="")
    monkeypatch.setattr(sys, "stderr", stream)
    monkeypatch.setattr(process, "text_encoding", lambda value: "utf-8")
    message = "x" * prefix_size + "✓\nERROR: checksum mismatch\n" + "y" * 65536

    def invoke():
        with progress_output() as output:
            output.write(message)
            if status:
                raise subprocess.CalledProcessError(status, "installer")

    if status:
        with pytest.raises(subprocess.CalledProcessError) as caught:
            invoke()
        assert caught.value.returncode == status
    else:
        invoke()
    assert raw.getvalue() == message.encode("ascii", "backslashreplace")
