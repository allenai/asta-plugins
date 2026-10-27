import pytest


@pytest.fixture(autouse=True)
def _ci(monkeypatch):
    # GitHub Actions sets CI for this suite; set it locally too so `asta workspace
    # sync` keeps test pins as written. Tests of local pin moves unset it.
    monkeypatch.setenv("CI", "true")
