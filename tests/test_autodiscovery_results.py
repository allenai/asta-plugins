"""Tests for `asta autodiscovery results`."""

import json

import pytest
from click.testing import CliRunner

from asta.autodiscovery import commands
from asta.autodiscovery.client import AutoDiscoveryClient
from asta.cli import cli


class FakeClient(AutoDiscoveryClient):
    """Answers like the service for one run with a finished and a running experiment."""

    def __init__(self):
        self.experiment_calls = []

    def get_run(self, runid):
        return {
            "runid": runid,
            "name": "Plant growth",
            "status": "RUNNING",
            "run_details": {"status": "RUNNING", "created_at": "2026-10-15T10:00:00"},
            "run_metadata": {"name": "Plant growth", "n_experiments": 2},
            "run_stats": {"requested_experiments": 2, "completed_experiments": 1},
        }

    def get_status(self, runid):
        return {
            "run_details": {"status": "SUCCEEDED", "finished_at": "2026-10-15T11:00:00"}
        }

    def get_metadata(self, runid):
        raise AssertionError("metadata comes with the run")

    def list_experiments(self, runid):
        return {
            "experiments": [
                {"experiment_id": "node_1_0", "status": "SUCCEEDED", "id_in_run": 1},
                {"experiment_id": "node_1_1", "status": "RUNNING", "id_in_run": 2},
            ]
        }

    def get_experiment(self, runid, experiment_id):
        self.experiment_calls.append(experiment_id)
        return {"experiment": {"experiment_id": experiment_id, "code": "print(1)"}}


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(commands, "AutoDiscoveryClient", lambda: fake)
    return fake


def test_results_assembles_run_and_finished_experiment_detail(client, tmp_path):
    out = tmp_path / "results.json"
    result = CliRunner().invoke(cli, ["autodiscovery", "results", "r1", "-o", str(out)])

    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert data["run"]["runid"] == "r1"
    # The status endpoint is fresher than the run's own copy.
    assert data["run"]["status"] == "SUCCEEDED"
    assert data["run"]["details"]["created_at"] == "2026-10-15T10:00:00"
    assert data["run"]["details"]["finished_at"] == "2026-10-15T11:00:00"
    assert data["run"]["stats"]["completed_experiments"] == 1
    finished, running = data["experiments"]
    assert finished == {
        "experiment_id": "node_1_0",
        "status": "SUCCEEDED",
        "id_in_run": 1,
        "code": "print(1)",
    }
    assert running == {"experiment_id": "node_1_1", "status": "RUNNING", "id_in_run": 2}
    assert client.experiment_calls == ["node_1_0"]


def test_results_cache_fetches_each_finished_experiment_once(client, tmp_path):
    args = ["autodiscovery", "results", "r1", "-o", str(tmp_path / "r.json")]
    cache = ["--cache-dir", str(tmp_path / "cache")]
    for _ in range(2):
        assert CliRunner().invoke(cli, args + cache).exit_code == 0

    assert client.experiment_calls == ["node_1_0"]
    assert (tmp_path / "cache" / "node_1_0.json").exists()
    assert not (tmp_path / "cache" / "node_1_1.json").exists()


def test_results_without_output_prints_json(client):
    result = CliRunner().invoke(cli, ["autodiscovery", "results", "r1"])

    assert result.exit_code == 0
    assert json.loads(result.output)["run"]["name"] == "Plant growth"
