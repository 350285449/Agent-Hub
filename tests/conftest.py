from __future__ import annotations

from pathlib import Path


PACKAGING_NAMES = {
    "test_phase8_packaging.py",
    "test_phase9_release.py",
    "test_vscode_extension.py",
}

INTEGRATION_NAMES = {
    "test_api_golden_fixtures.py",
    "test_server.py",
    "test_smoke.py",
    "test_team_agent_runner.py",
}

STRESS_NAMES = {
    "test_cline_stress.py",
}


def pytest_addoption(parser):  # type: ignore[no-untyped-def]
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run tests marked integration.",
    )
    parser.addoption(
        "--run-stress",
        action="store_true",
        default=False,
        help="Run stress tests marked stress.",
    )


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    import pytest

    run_integration = bool(config.getoption("--run-integration")) or _marker_requested(config, "integration")
    run_stress = bool(config.getoption("--run-stress")) or _marker_requested(config, "stress")
    skip_integration = pytest.mark.skip(reason='integration test; run with -m "integration"')
    skip_stress = pytest.mark.skip(reason='stress test; run with -m "stress"')

    for item in items:
        path = Path(str(item.fspath))
        name = path.name
        if name in PACKAGING_NAMES:
            item.add_marker(pytest.mark.packaging)
            item.add_marker(pytest.mark.timeout(30))
        elif name in STRESS_NAMES:
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.stress)
            item.add_marker(pytest.mark.timeout(45))
            if not run_stress:
                item.add_marker(skip_stress)
        elif name in INTEGRATION_NAMES:
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.timeout(30))
            if not run_integration:
                item.add_marker(skip_integration)
        else:
            item.add_marker(pytest.mark.unit)


def _marker_requested(config, marker: str) -> bool:  # type: ignore[no-untyped-def]
    expression = str(getattr(config.option, "markexpr", "") or "")
    return marker in expression
