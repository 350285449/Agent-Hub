from __future__ import annotations

from agent_hub.research.cross_repo_experiment import run_cross_repo_context_experiment
from agent_hub.research.tau_repo_correlation import compute_tau_repo_correlation, export_tau_repo_correlation


def test_tau_repo_correlation_exports_metrics(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
    repos = []
    for name, count in [("a", 1), ("b", 4), ("c", 8)]:
        repo = tmp_path / name
        repo.mkdir()
        for index in range(count):
            (repo / f"m{index}.py").write_text("import os\n\ndef f():\n    return os.name\n", encoding="utf-8")
        repos.append({"path": repo, "source": "synthetic", "size_label": name})
    run_cross_repo_context_experiment(state, repos, repetitions=1)

    payload = compute_tau_repo_correlation(state)
    paths = export_tau_repo_correlation(state)

    assert payload["repository_count"] == 3
    assert "total_loc" in payload["correlations"]
    assert paths["markdown"].endswith("tau_repo_correlation.md")
