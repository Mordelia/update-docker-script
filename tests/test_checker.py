from __future__ import annotations

import logging
import os
import sys
import subprocess
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ducore.checker import (
    setup_logging,
    check_docker_access,
    filter_containers,
    check_updates_with_progress,
    LOG_FILE,
    logger,
)
from ducore.cli import parse_args
from ducore.ui import non_interactive_update



class TestSetupLogging:
    def test_log_file_created(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.object(sys.modules["ducore.checker"], "LOG_FILE", str(log_file)):
            setup_logging()
            assert log_file.exists()
            assert logger.handlers

    def test_handlers_configured(self, tmp_path):
        log_file = tmp_path / "test.log"
        with patch.object(sys.modules["ducore.checker"], "LOG_FILE", str(log_file)):
            setup_logging()
            handler_types = [type(h) for h in logger.handlers]
            assert logging.FileHandler in handler_types
            assert logging.StreamHandler in handler_types

class TestSelfInstall:
    def test_no_missing_packages(self):
        from ducore import self_install

        with (
            patch("importlib.import_module") as mock_import,
            patch("subprocess.check_call") as mock_sub,
        ):
            mock_import.return_value = True
            self_install()
            mock_sub.assert_not_called()

    def test_missing_docker_installs_and_exits(self):
        from ducore import self_install
        import importlib as _il
        _real_import_module = _il.import_module

        def selective_import(module):
            if module == "docker":
                raise ImportError(f"No module named {module!r}")
            return _real_import_module(module)

        with (
            patch("importlib.import_module", side_effect=selective_import),
            patch("subprocess.check_call") as mock_sub,
            patch("platform.system", return_value="Linux"),
            patch.object(sys, "exit") as mock_exit,
        ):
            self_install()
            mock_sub.assert_called_once()
            mock_exit.assert_called_once_with(0)

class TestCheckDockerAccess:
    def test_success(self):
        mock_client = MagicMock()
        with patch("docker.from_env", return_value=mock_client):
            result = check_docker_access()
            mock_client.ping.assert_called_once()
            assert result is mock_client

    def test_docker_exception_exits(self):
        import docker
        with (
            patch("docker.from_env", side_effect=docker.errors.DockerException("boom")),
            patch.object(sys, "exit") as mock_exit,
        ):
            check_docker_access()
            mock_exit.assert_called_once_with(1)

def make_mock_container(name: str, image: str, local_id: str):
    c = MagicMock()
    c.name = name
    c.attrs = {"Config": {"Image": image}}
    type(c.image).id = PropertyMock(return_value=local_id)
    return c


def make_mock_subprocess(returncode=0, stderr=b""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stderr=stderr
    )


class TestCheckUpdatesWithProgress:
    def test_update_available(self):
        container = make_mock_container("web", "nginx:latest", "old_sha")
        client = MagicMock()
        client.images.get.return_value.id = "new_sha"

        with patch("subprocess.run", return_value=make_mock_subprocess()):
            results = check_updates_with_progress(client, [container])

        assert len(results) == 1
        assert results[0]["name"] == "web"
        assert results[0]["needs_update"] is True
        assert results[0]["error"] is None

    def test_up_to_date(self):
        container = make_mock_container("web", "nginx:latest", "same_sha")
        client = MagicMock()
        client.images.get.return_value.id = "same_sha"

        with patch("subprocess.run", return_value=make_mock_subprocess()):
            results = check_updates_with_progress(client, [container])

        assert len(results) == 1
        assert results[0]["needs_update"] is False
        assert results[0]["error"] is None

    def test_pull_failure(self):
        container = make_mock_container("web", "nginx:latest", "old")
        client = MagicMock()
        err = b"manifest for nginx:latest not found"

        with patch("subprocess.run", return_value=make_mock_subprocess(1, err)):
            results = check_updates_with_progress(client, [container])

        assert results[0]["error"] is not None
        assert results[0]["needs_update"] is False

    def test_exception_during_check(self):
        container = make_mock_container("web", "nginx:latest", "old")
        client = MagicMock()
        client.images.get.side_effect = Exception("unexpected error")

        with patch("subprocess.run", return_value=make_mock_subprocess()):
            results = check_updates_with_progress(client, [container])

        assert results[0]["error"] == "unexpected error"

    def test_adds_latest_tag_when_missing(self):
        container = make_mock_container("app", "myimage", "old")
        client = MagicMock()
        client.images.get.return_value.id = "new"

        with patch("subprocess.run", return_value=make_mock_subprocess()):
            results = check_updates_with_progress(client, [container])

        assert results[0]["image_ref"] == "myimage:latest"

    def test_multiple_containers(self):
        c1 = make_mock_container("a", "img1", "old")
        c2 = make_mock_container("b", "img2", "same")
        client = MagicMock()

        def image_side_effect(ref):
            return MagicMock(id="new" if "img1" in ref else "same")

        client.images.get.side_effect = image_side_effect

        with patch("subprocess.run", return_value=make_mock_subprocess()):
            results = check_updates_with_progress(client, [c1, c2])

        by_name = {r["name"]: r for r in results}
        assert by_name["a"]["needs_update"] is True
        assert by_name["b"]["needs_update"] is False

    def test_dry_run_skips_pull(self):
        container = make_mock_container("web", "nginx:latest", "old_sha")
        client = MagicMock()

        with patch("subprocess.run") as mock_run:
            results = check_updates_with_progress(
                client, [container], dry_run=True,
            )

        mock_run.assert_not_called()
        assert results[0]["needs_update"] is False
        assert results[0]["local_id"] == "old_sha"

    def test_dry_run_sets_no_latest_id(self):
        container = make_mock_container("web", "nginx:latest", "sha")
        client = MagicMock()

        with patch("subprocess.run") as mock_run:
            results = check_updates_with_progress(
                client, [container], dry_run=True,
            )

        assert results[0]["latest_id"] is None

def make_filter_container(name: str, labels: dict[str, str] | None = None):
    c = MagicMock()
    c.name = name
    c.labels = labels or {}
    return c


class TestFilterContainers:
    def test_no_filter_returns_all(self):
        containers = [make_filter_container("a"), make_filter_container("b")]
        args = parse_args([])
        result = filter_containers(containers, args)
        assert len(result) == 2

    def test_only(self):
        containers = [make_filter_container("a"), make_filter_container("b")]
        args = parse_args(["--only", "a"])
        result = filter_containers(containers, args)
        assert [c.name for c in result] == ["a"]

    def test_only_multiple(self):
        containers = [make_filter_container("a"), make_filter_container("b"), make_filter_container("c")]
        args = parse_args(["--only", "a", "--only", "c"])
        result = filter_containers(containers, args)
        assert [c.name for c in result] == ["a", "c"]

    def test_exclude(self):
        containers = [make_filter_container("a"), make_filter_container("b")]
        args = parse_args(["--exclude", "a"])
        result = filter_containers(containers, args)
        assert [c.name for c in result] == ["b"]

    def test_exclude_and_only(self):
        containers = [make_filter_container("a"), make_filter_container("b"), make_filter_container("c")]
        args = parse_args(["--only", "a", "--only", "b", "--exclude", "a"])
        result = filter_containers(containers, args)
        assert [c.name for c in result] == ["b"]

    def test_only_label(self):
        containers = [
            make_filter_container("a", {"env": "prod"}),
            make_filter_container("b", {"env": "dev"}),
        ]
        args = parse_args(["--only-label", "env=prod"])
        result = filter_containers(containers, args)
        assert [c.name for c in result] == ["a"]

    def test_exclude_label(self):
        containers = [
            make_filter_container("a", {"env": "prod"}),
            make_filter_container("b", {"env": "dev"}),
        ]
        args = parse_args(["--exclude-label", "env=prod"])
        result = filter_containers(containers, args)
        assert [c.name for c in result] == ["b"]

    def test_exclude_label_missing_key(self):
        containers = [
            make_filter_container("a", {}),
            make_filter_container("b", {"env": "prod"}),
        ]
        args = parse_args(["--exclude-label", "env=prod"])
        result = filter_containers(containers, args)
        assert [c.name for c in result] == ["a"]

    def test_complex_filters(self):
        containers = [
            make_filter_container("a", {"tier": "web", "env": "prod"}),
            make_filter_container("b", {"tier": "web", "env": "dev"}),
            make_filter_container("c", {"tier": "db", "env": "prod"}),
            make_filter_container("d", {"tier": "db", "env": "dev"}),
        ]
        args = parse_args(["--only-label", "tier=web", "--exclude-label", "env=dev"])
        result = filter_containers(containers, args)
        assert [c.name for c in result] == ["a"]

class TestParseArgs:
    def test_defaults(self):
        args = parse_args([])
        assert args.dry_run is False
        assert args.apply is False
        assert args.max_workers == 4
        assert args.only == []
        assert args.exclude == []
        assert args.only_label == []
        assert args.exclude_label == []

    def test_dry_run(self):
        args = parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_apply(self):
        args = parse_args(["--apply"])
        assert args.apply is True

    def test_max_workers(self):
        args = parse_args(["--max-workers", "8"])
        assert args.max_workers == 8

    def test_only_and_exclude(self):
        args = parse_args(["--only", "web", "--exclude", "db"])
        assert args.only == ["web"]
        assert args.exclude == ["db"]

    def test_yes(self):
        args = parse_args(["--yes"])
        assert args.yes is True

    def test_json(self):
        args = parse_args(["--json"])
        assert args.json is True

    def test_yes_default_false(self):
        args = parse_args([])
        assert args.yes is False

    def test_json_default_false(self):
        args = parse_args([])
        assert args.json is False

class TestOutputJson:
    def test_valid_json(self, capsys):
        from ducore.ui import output_json
        import json
        infos = [
            {"name": "web", "image_ref": "nginx:latest",
             "needs_update": True, "error": None,
             "local_id": "sha1", "latest_id": "sha2"},
        ]
        output_json(infos)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "web"

    def test_empty(self, capsys):
        from ducore.ui import output_json
        import json
        output_json([])
        captured = capsys.readouterr()
        assert json.loads(captured.out) == []

class TestNonInteractiveUpdate:
    def test_all_up_to_date(self):
        infos = [{"name": "web", "needs_update": False}]
        result = non_interactive_update(infos, [], MagicMock())
        assert result is None

    def test_updates_container(self):
        container = make_mock_container("web", "nginx:latest", "old_sha")
        infos = [{"name": "web", "needs_update": True, "image_ref": "nginx:latest"}]

        with patch("subprocess.run", return_value=make_mock_subprocess()):
            result = non_interactive_update(infos, [container], MagicMock())

        assert result is None
