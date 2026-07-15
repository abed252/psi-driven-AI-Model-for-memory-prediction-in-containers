"""End-to-end run of the environment validator against the live Docker Desktop."""

import json

import pytest

from psi_memory.environment.validate import validate_environment

pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def report():
    return validate_environment()


def test_overall_pass(report):
    failed = [c.name for c in report.checks if c.status == "fail"]
    assert report.ok, f"failed checks: {failed}"


def test_core_checks_present_and_pass(report):
    by_name = {c.name: c for c in report.checks}
    for required in (
        "host.python",
        "docker.cgroup_version",
        "vm.psi_global",
        "container.readable_files",
        "container.psi",
        "container.sidecar_sampling",
        "container.dynamic_memory_max",
        "container.memory_high_write",
    ):
        assert required in by_name, f"missing check: {required}"
        assert by_name[required].status == "pass", (
            f"{required}: {by_name[required].details}"
        )


def test_report_saves_valid_json(report, tmp_path):
    saved = report.save(tmp_path)
    parsed = json.loads(saved.read_text(encoding="utf-8"))
    assert parsed["validation_id"] == report.validation_id
    assert len(parsed["checks"]) == len(report.checks)
