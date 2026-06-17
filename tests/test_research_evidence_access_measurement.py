from __future__ import annotations

import json

from agent_hub.research.evidence_access_measurement import (
    aggregate_evidence_access,
    compute_components,
    run_evidence_access_measurement,
)


def test_evidence_components_measure_direct_access() -> None:
    components = compute_components(
        selected=["app.py", "README.md", "tests/test_app.py"],
        decisive=["app.py"],
        relevant=["app.py", "tests/test_app.py"],
        edited=["app.py"],
        referenced=["app.py"],
        verifiers=["tests/test_app.py"],
        token_counts={"app.py": 80, "README.md": 20, "tests/test_app.py": 40},
        output="Patch app.py and run pytest tests/test_app.py",
    )

    assert components["E1"] == 1.0
    assert components["E2"] == 1.0
    assert components["E3"] > 0.5
    assert components["E4"] == 0.666667
    assert components["E5"] == 1.0
    assert components["E6"] == 1.0
    assert components["E7"] == 1.0
    assert aggregate_evidence_access(components) > 0.8


def test_evidence_access_artifacts_generate_from_minimal_cloud_state(tmp_path) -> None:
    research = tmp_path / ".agent-hub" / "research"
    research.mkdir(parents=True)
    (research / "benchmark_tasks.json").write_text(
        json.dumps(
            [
                {
                    "task_id": "demo-bug-01",
                    "repository": "demo",
                    "category": "bug_fix",
                    "focus_files": ["demo/app.py", "demo/templates/index.html"],
                    "tests": ["tests/test_demo.py"],
                }
            ]
        ),
        encoding="utf-8",
    )
    rows = [
        _row("r1", "demo-bug-01", True, ["demo/app.py", "demo/README.md"], "Use demo/app.py and run tests/test_demo.py"),
        _row("r2", "demo-bug-01", False, ["demo/README.md"], "No source file found"),
    ]
    (research / "live_matrix.jsonl").write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    paths = run_evidence_access_measurement(tmp_path / ".agent-hub")
    dataset = json.loads(paths["dataset"].read_text(encoding="utf-8"))

    assert dataset["row_count"] == 2
    assert dataset["summary"]["labeled_rows"] == 2
    assert dataset["rows"][0]["components"]["E1"] == 0.5
    assert paths["old_vs_new"].exists()
    assert paths["primitive_reanalysis"].exists()
    assert paths["verdict"].read_text(encoding="utf-8").startswith("# Evidence Access Measurement Verdict")


def _row(row_id: str, task_id: str, success: bool, selected_files: list[str], output: str) -> dict:
    return {
        "row_id": row_id,
        "task_id": task_id,
        "task": task_id,
        "live": True,
        "model": "gpt-5.5",
        "provider": "openai",
        "provider_type": "openai-compatible",
        "repository": "demo",
        "category": "bug_fix",
        "context_budget": 50,
        "context_tokens": 200,
        "selected_files": selected_files,
        "output_preview": output,
        "success": success,
        "validation_score": 0.9 if success else 0.2,
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
