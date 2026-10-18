import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager


@contextmanager
def progress_output(enabled=True):
    if not enabled:
        yield subprocess.PIPE
        return
    stream = sys.stderr
    try:
        stream.fileno()
    except (AttributeError, OSError, ValueError):
        # Captured Python streams cannot be passed to a child process. Spool
        # to disk, rather than retaining arbitrarily large installer output.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as output:
            try:
                yield output
            finally:
                output.seek(0)
                shutil.copyfileobj(output, stream)
                stream.flush()
    else:
        yield stream
