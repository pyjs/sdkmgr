import httpx
import pytest

from sdkmgr import SDKError, download


@pytest.fixture
def mock_http(monkeypatch):
    client_type = httpx.Client
    monkeypatch.setattr(download.time, "sleep", lambda duration: None)

    def configure(handler):
        monkeypatch.setattr(download.httpx, "Client", lambda **kwargs:
                            client_type(transport=httpx.MockTransport(handler), **kwargs))

    return configure


def test_download_follows_https_redirect(tmp_path, mock_http):
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == "/archive":
            return httpx.Response(302, headers={"location": "https://cdn.example/sdk"})
        return httpx.Response(200, content=b"contents")

    mock_http(handler)
    target = tmp_path / "sdk"
    download.fetch("https://example.org/archive", target)
    assert visited == ["https://example.org/archive", "https://cdn.example/sdk"]
    assert target.read_bytes() == b"contents"


def test_insecure_redirect_is_not_requested(tmp_path, mock_http):
    visited = []

    def handler(request):
        visited.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://example.org/sdk"})

    mock_http(handler)
    with pytest.raises(SDKError, match="insecure"):
        download.fetch("https://example.org/sdk", tmp_path / "sdk")
    assert len(visited) == 1


@pytest.mark.parametrize("status,count", [(404, 1), (403, 1), (429, 3), (503, 3)])
def test_retry_policy(tmp_path, mock_http, status, count):
    visited = []

    def handler(request):
        visited.append(request)
        return httpx.Response(status)

    mock_http(handler)
    with pytest.raises(SDKError, match="Could not download"):
        download.fetch("https://example.org/sdk", tmp_path / "sdk")
    assert len(visited) == count


def test_timeout_is_retried(tmp_path, mock_http):
    visited = []

    def handler(request):
        visited.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    mock_http(handler)
    with pytest.raises(SDKError, match="timed out"):
        download.fetch("https://example.org/sdk", tmp_path / "sdk")
    assert len(visited) == 3


def test_retry_replaces_partial_download(tmp_path, mock_http):
    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield b"wrong" * 100_000
            raise httpx.ReadError("disconnected")

    visited = []

    def handler(request):
        visited.append(request)
        if len(visited) == 1:
            return httpx.Response(200, stream=Interrupted())
        return httpx.Response(200, content=b"correct")

    mock_http(handler)
    target = tmp_path / "sdk"
    download.fetch("https://example.org/sdk", target)
    assert target.read_bytes() == b"correct"


def test_download_limit(tmp_path, mock_http):
    mock_http(lambda request: httpx.Response(200, content=b"123"))
    with pytest.raises(SDKError, match="limit"):
        download.fetch("https://example.org/sdk", tmp_path / "sdk", limit=2)


def test_redirect_limit(tmp_path, mock_http):
    mock_http(lambda request: httpx.Response(302, headers={"location": "/again"}))
    with pytest.raises(SDKError, match="Too many"):
        download.fetch("https://example.org/sdk", tmp_path / "sdk")


def test_reject_http(tmp_path):
    with pytest.raises(SDKError, match="HTTPS"):
        download.fetch("http://example.org/sdk", tmp_path / "sdk")


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", ["disconnect", "limit", "interrupt"])
def test_failed_download_does_not_publish_partial_data(tmp_path, mock_http, existing, failure):
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b"x" * (128 * 1024)
            if failure == "interrupt":
                raise KeyboardInterrupt
            raise httpx.ReadError("disconnected")

    target = tmp_path / "sdk"
    if existing:
        target.write_bytes(b"original")
    mock_http(lambda request: httpx.Response(200, stream=Broken()))
    expected = KeyboardInterrupt if failure == "interrupt" else SDKError
    with pytest.raises(expected):
        download.fetch("https://example.org/sdk", target,
                       limit=1 if failure == "limit" else download.MAX_DOWNLOAD)
    if existing:
        assert target.read_bytes() == b"original"
    else:
        assert not target.exists()
    assert not list(tmp_path.glob(".download-*"))


def test_redirect_without_location_is_diagnostic(tmp_path, mock_http):
    mock_http(lambda request: httpx.Response(302))
    with pytest.raises(SDKError, match="missing its Location header"):
        download.fetch("https://example.org/sdk", tmp_path / "sdk")


def test_download_filesystem_failure_is_not_retried(tmp_path, mock_http):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=b"data")

    mock_http(handler)
    with pytest.raises(SDKError, match="Could not download"):
        download.fetch("https://example.org/sdk", tmp_path / "missing" / "sdk")
    assert len(requests) == 1
