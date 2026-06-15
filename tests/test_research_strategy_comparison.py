from __future__ import annotations

from agent_hub.research.ablation import append_context_ablation_result
from agent_hub.research.strategy_comparison import compute_context_strategy_comparison, export_context_strategy_comparison


def test_strategy_comparison_scores_success_per_token(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
    append_context_ablation_result(state, _row("default_context", 4000, True, 0.9))
    append_context_ablation_result(state, _row("information_density", 1000, True, 0.9))

    payload = compute_context_strategy_comparison(state)
    paths = export_context_strategy_comparison(state)

    assert payload["strategies"]["default_context"]["runs"] == 1
    assert payload["winner_by_success_per_1k_tokens"] == "information_density"
    assert paths["json"].endswith("context_strategy_comparison.json")


def _row(strategy, tokens, success, score):
    return {
        "task_id": strategy,
        "context_strategy": strategy,
        "context_token_count": tokens,
        "success": success,
        "validation_score": score,
    }
