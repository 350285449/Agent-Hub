from __future__ import annotations

from agent_hub.research.cross_repo_experiment import cross_repo_experiment_path, run_cross_repo_context_experiment
from agent_hub.research.tau_validation import compute_cross_repo_tau, export_cross_repo_tau


def test_cross_repo_experiment_and_tau_export(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
    repo_a = _repo(tmp_path, "small", files=1)
    repo_b = _repo(tmp_path, "medium", files=3)

    result = run_cross_repo_context_experiment(
        state,
        [
            {"path": repo_a, "source": "synthetic", "size_label": "small"},
            {"path": repo_b, "source": "synthetic", "size_label": "medium"},
        ],
        repetitions=1,
    )
    tau = compute_cross_repo_tau(state)
    paths = export_cross_repo_tau(state)

    assert result["rows_generated"] == 240
    assert cross_repo_experiment_path(state).exists()
    assert len(tau["repositories"]) == 2
    assert all(repo["tau_estimate"] > 0 for repo in tau["repositories"])
    assert paths["json"].endswith("cross_repo_tau.json")


def _repo(tmp_path, name, files):
    repo = tmp_path / name
    repo.mkdir()
    for index in range(files):
        (repo / f"module_{index}.py").write_text("import json\n\ndef f():\n    return json.dumps({})\n", encoding="utf-8")
    return repo
