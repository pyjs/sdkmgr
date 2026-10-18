import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager, suppress
from io import text_encoding


@contextmanager
def progress_output(enabled=True):
    if not enabled:
        yield subprocess.PIPE
        return
    stream = sys.stderr
    if stream is None:
        yield None
        return
    try:
        stream.fileno()
    except (AttributeError, OSError, ValueError):
        # Captured Python streams cannot be passed to a child process. Spool
        # to disk, rather than retaining arbitrarily large installer output.
        with tempfile.TemporaryFile(
            mode="w+", encoding=text_encoding(None), errors="replace", newline="",
        ) as output:
            try:
                yield output
            finally:
                # Progress reporting must not replace the installer's outcome
                # when a captured console closes or loses its output sink.
                with suppress(OSError, ValueError):
                    output.seek(0)
                    shutil.copyfileobj(output, stream)
                    stream.flush()
    else:
        yield stream
