import pytest


@pytest.fixture
def pinned_workspace(monkeypatch):
    # GitHub Actions sets CI for this suite; set it locally too so `asta workspace
    # sync` keeps fixture pins as written. Only sync/version/bump-pin tests opt
    # in; tests of local pin moves unset it.
    monkeypatch.setenv("CI", "true")
