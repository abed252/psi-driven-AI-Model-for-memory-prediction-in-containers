import pytest

from psi_memory.environment.docker_cli import daemon_running
from psi_memory.environment.probe import start_temp_container, stop_container


def pytest_collection_modifyitems(config, items):
    if daemon_running():
        return
    skip = pytest.mark.skip(reason="Docker daemon not running")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="module")
def temp_container():
    """One shared temporary target container per test module."""
    name = start_temp_container(name_prefix="psi-itest")
    yield name
    stop_container(name)
