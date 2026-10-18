import pytest

from sdkmgr import java, mise, nvm


@pytest.fixture(autouse=True)
def isolated_java_discovery(monkeypatch):
    monkeypatch.setattr(java, "candidate_homes", lambda host, version: ())


@pytest.fixture(autouse=True)
def isolated_mise_discovery(monkeypatch):
    monkeypatch.setattr(mise, "executable", lambda: None)


@pytest.fixture(autouse=True)
def isolated_nvm_discovery(monkeypatch):
    monkeypatch.setattr(nvm, "discover", lambda host: None)
