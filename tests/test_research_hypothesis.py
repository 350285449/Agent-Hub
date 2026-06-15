from __future__ import annotations

from agent_hub.research.ablation import append_context_ablation_result
from agent_hub.research.hypothesis import compute_hypothesis_tests, export_hypothesis_tests


def test_hypothesis_tests_identify_context_gain_and_efficiency(tmp_path):
    state = tmp_path / ".agent-hub" / "state"
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

    payload = compute_hypothesis_tests(state)
    paths = export_hypothesis_tests(state)

    assert payload["tests"]["more_context_improves_success"]["supported"] is True
    assert payload["tests"]["one_to_two_k_best_success_per_token"]["best_bucket"] == "1-2k"
    assert paths["markdown"].endswith("hypothesis_tests.md")
