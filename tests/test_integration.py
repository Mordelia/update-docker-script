from __future__ import annotations

import json
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ducore.checker import (
    check_docker_access,
    check_updates_with_progress,
    setup_logging,
    LOG_FILE,
    logger,
)
from ducore.ui import output_json

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_DOCKER_TESTS"),
    reason="Docker integration tests disabled via SKIP_DOCKER_TESTS",
)


def docker_available() -> bool:
    """Check if the Docker daemon is reachable."""
    try:
        import docker
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


docker_only = pytest.mark.skipif(
    not docker_available(),
    reason="Docker daemon not available",
)



@docker_only
class TestDockerDaemon:
    def test_ping_succeeds(self):
        client = check_docker_access()
        assert client is not None

    def test_list_containers(self):
        from ducore.checker import filter_containers
        from ducore.cli import parse_args

        client = check_docker_access()
        containers = client.containers.list(all=True)
        assert isinstance(containers, list)

        args = parse_args([])
        filtered = filter_containers(containers, args)
        assert len(filtered) == len(containers)

@docker_only
class TestCheckUpdatesReal:
    def test_runs_without_error(self):
        client = check_docker_access()
        containers = client.containers.list()
        results = check_updates_with_progress(client, containers, dry_run=True)
        assert len(results) == len(containers)
        for r in results:
            assert "name" in r
            assert "image_ref" in r
            assert "needs_update" in r

class TestOutputJson:
    def test_valid_json(self, capsys):
        infos = [
            {"name": "web", "image_ref": "nginx:latest",
             "needs_update": True, "error": None,
             "local_id": "sha1", "latest_id": "sha2"},
            {"name": "db", "image_ref": "postgres:16",
             "needs_update": False, "error": None,
             "local_id": "sha3", "latest_id": "sha3"},
        ]
        output_json(infos)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "web"
        assert parsed[0]["needs_update"] is True
        assert parsed[1]["name"] == "db"

    def test_handles_empty(self, capsys):
        output_json([])
        captured = capsys.readouterr()
        assert json.loads(captured.out) == []
