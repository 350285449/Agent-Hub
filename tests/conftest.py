from __future__ import annotations

from pathlib import Path


PACKAGING_NAMES = {
    "test_phase8_packaging.py",
    "test_phase9_release.py",
    "test_vscode_extension.py",
}

INTEGRATION_NAMES = {
    "test_api_golden_fixtures.py",
    "test_cline_stress.py",
    "test_server.py",
    "test_smoke.py",
    "test_team_agent_runner.py",
}


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    import pytest

    for item in items:
        path = Path(str(item.fspath))
        name = path.name
        if name in PACKAGING_NAMES:
            item.add_marker(pytest.mark.packaging)
        elif name in INTEGRATION_NAMES:
            item.add_marker(pytest.mark.integration)
        else:
            item.add_marker(pytest.mark.unit)
