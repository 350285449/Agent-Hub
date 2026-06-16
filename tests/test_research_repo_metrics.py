from __future__ import annotations

from agent_hub.research.repo_metrics import compute_repo_metrics, export_repo_metrics


def test_repo_metrics_counts_python_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("import os\n\n\ndef run():\n    return os.getcwd()\n", encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("from app import run\n\ndef test_run():\n    assert run()\n", encoding="utf-8")

    metrics = compute_repo_metrics(repo)
    path = export_repo_metrics(tmp_path / ".agent-hub" / "state", [repo])

    assert metrics["total_loc"] == 9
    assert metrics["python_file_count"] == 2
    assert metrics["estimated_dependency_import_count"] == 2
    assert metrics["test_file_count"] == 1
    assert path.exists()
