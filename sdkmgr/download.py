import os
import tempfile
import time
from pathlib import Path

import httpx

from .errors import SDKError

MAX_DOWNLOAD = 1024 ** 3


def fetch(url: str, destination: Path, *, limit: int = MAX_DOWNLOAD):
    """Download over HTTPS, retrying transient failures without retaining partial data."""
    if not url.startswith("https://"):
        raise SDKError("Downloads require HTTPS.")
    for attempt in range(3):
        staged = None
        try:
            started = time.monotonic()
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                current = url
                for redirect in range(6):
                    with client.stream("GET", current) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise SDKError("Download redirect is missing its Location header.")
                            target = response.url.join(location)
                            if target.scheme != "https":
                                raise SDKError("Refusing an insecure download redirect.")
                            current = str(target)
                            continue
                        response.raise_for_status()
                        size = 0
                        with tempfile.NamedTemporaryFile(
                            dir=destination.parent, prefix=".download-", delete=False,
                        ) as output:
                            staged = Path(output.name)
                            for chunk in response.iter_bytes(128 * 1024):
                                size += len(chunk)
                                if size > limit or time.monotonic() - started > 600:
                                    raise SDKError("Download exceeded its size or time limit.")
                                output.write(chunk)
                        os.replace(staged, destination)
                        return
                raise SDKError("Too many download redirects.")
        except httpx.HTTPError as error:
            retryable = not isinstance(error, httpx.HTTPStatusError) or (
                error.response.status_code in {408, 429, 500, 502, 503, 504}
            )
            if attempt == 2 or not retryable:
                raise SDKError(f"Could not download {url}: {error}") from error
            time.sleep(0.5 * (attempt + 1))
        except (OSError, httpx.InvalidURL) as error:
            raise SDKError(f"Could not download {url}: {error}") from error
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)
