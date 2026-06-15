from __future__ import annotations

import json

from agent_hub.research.ablation import append_context_ablation_result
from agent_hub.research.curve_fit import compute_curve_fit, export_curve_fit


def test_curve_fit_exports_best_model(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
    _write_curve_rows(state)

    payload = compute_curve_fit(state)
    paths = export_curve_fit(state)

    assert payload["best_fit_model"] in payload["fits"]
    assert "mse" in payload["best_fit"]
    assert json.loads(open(paths["json"], encoding="utf-8").read())["object"] == "agent_hub.research.curve_fit"


def _write_curve_rows(state):
    for tokens, success in [(0, False), (1000, True), (2500, True), (7000, True)]:
        append_context_ablation_result(
            state,
            {
                "task_id": f"t-{tokens}",
                "context_token_count": tokens,
                "tokens_used": tokens,
                "success": success,
                "validation_score": 1.0 if success else 0.3,
            },
        )
