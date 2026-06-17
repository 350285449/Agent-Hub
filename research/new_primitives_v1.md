# New Primitives v1

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Rules enforced: cloud models only; no Codex, Ollama, local, self-hosted, quantized, or edge rows; pre-run variables only; post-run traces excluded from candidate status.

## Candidate Test

| candidate | field | pre-run measurement | single corr | holdout R2 | prospective R2 | delta Brier gain vs existing | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Task Ambiguity | task_ambiguity | underspecification from sparse expected/relevant labels | -0.072284 | 0.417165 | 0.015875 | 1.1e-05 | weak diagnostic improvement |
| Planning Horizon | planning_horizon | category-level need for multistep design before execution | -0.030037 | 0.42439 | 0.021441 | 0.001023 | weak diagnostic improvement |
| Tool Dependency Risk | tool_dependency_risk | pre-run category prior for tests, edits, API constraints, and tool orchestration | 0.059802 | 0.399592 | 0.0 | -0.009651 | reject |
| Retrieval Difficulty | retrieval_difficulty | expected/relevant evidence burden before retrieval | 0.065723 | 0.412765 | 0.015105 | -0.000129 | reject |
| Context Completeness | context_completeness | planned context adequacy relative to expected evidence burden | 0.078934 | 0.427671 | 0.014391 | -0.000259 | reject |
| Context Noise | context_noise | planned context surplus likely to dilute decisive evidence | -0.034283 | 0.413193 | 0.016056 | 4.4e-05 | weak diagnostic improvement |
| Novelty Distance | novelty_distance | coldness of the repository/category/model cell | -0.106827 | 0.432679 | 0.024869 | 0.001646 | weak diagnostic improvement |
| Distribution Shift Risk | distribution_shift_risk | distance from historical model/repo/category support | -0.088407 | 0.434716 | 0.024182 | 0.001521 | weak diagnostic improvement |
| Calibration History | calibration_history | leave-one historical model success prior | 0.694277 | 0.539611 | 0.0 | -0.008579 | reject |
| Benchmark Entropy | benchmark_entropy | diversity/uncertainty of category and repository labels | -0.105545 | 0.429695 | 0.020581 | 0.000866 | weak diagnostic improvement |
| Task Decomposability | task_decomposability | pre-run proxy for modular subtasks versus monolithic changes | 0.049606 | 0.415257 | 0.018492 | 0.000486 | weak diagnostic improvement |
| Verification Difficulty | verification_difficulty | pre-run category prior for hard-to-verify tasks | -0.018679 | 0.416953 | 0.011562 | -0.000773 | reject |
| Search Complexity | search_complexity | retrieval burden plus ambiguity plus cell novelty | -0.096742 | 0.431117 | 0.025455 | 0.001752 | weak diagnostic improvement |
| Solution Branching Factor | solution_branching_factor | expected number of plausible implementation paths | -0.11563 | 0.432777 | 0.024967 | 0.001663 | weak diagnostic improvement |

## Finding

No completely new primitive survives. `Calibration History` can improve reconstructed prediction, but it is frozen historical memory, not a primitive. The structural candidates mostly re-express task labels, evidence burden, context budget, or distribution support, and they do not materially clear the prospective ceiling.
