from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .difficulty_validation import (
    difficulty_hierarchy,
    evaluation_markdown,
    evaluation_score,
    falsification_markdown,
    falsification_report,
    hierarchy_markdown,
    independence_markdown,
    independence_test,
    prediction_markdown,
    prediction_test,
    write_json,
)
from .task_difficulty import (
    build_task_model_matrix,
    compute_candidate_difficulty_metrics,
    explain_variance,
    load_difficulty_observations,
)
from .telemetry import research_dir


def run_agent_difficulty_research_program(state_dir: str | Path) -> dict[str, Any]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rows = load_difficulty_observations(str(state_dir))
    matrix = build_task_model_matrix(rows)
    metrics = compute_candidate_difficulty_metrics(matrix)
    independence = independence_test(matrix, rows)
    prediction = prediction_test(matrix, rows)
    hierarchy = difficulty_hierarchy(metrics)
    falsification = falsification_report(matrix, metrics)
    evaluation = evaluation_score(
        matrix=matrix,
        metrics=metrics,
        independence=independence,
        prediction=prediction,
        falsification=falsification,
    )
    comparison = fundamental_quantity_comparison(directory, evaluation)
    summary = research_summary(matrix, metrics, independence, prediction, evaluation, comparison)
    paths = {
        "difficulty_task_matrix": write_json(directory / "difficulty_task_matrix.json", matrix),
        "candidate_difficulty_metrics": write_json(directory / "candidate_difficulty_metrics.json", metrics),
        "difficulty_independence_json": write_json(directory / "difficulty_independence.json", independence),
        "difficulty_prediction_json": write_json(directory / "difficulty_prediction.json", prediction),
        "difficulty_hierarchy_json": write_json(directory / "difficulty_hierarchy.json", hierarchy),
        "fundamental_quantity_comparison_json": write_json(directory / "fundamental_quantity_comparison.json", comparison),
    }
    markdown_outputs = {
        "difficulty_independence_markdown": independence_markdown(independence),
        "difficulty_prediction_markdown": prediction_markdown(prediction),
        "difficulty_hierarchy_markdown": hierarchy_markdown(hierarchy),
        "difficulty_falsification_markdown": falsification_markdown(falsification),
        "agent_difficulty_evaluation_markdown": evaluation_markdown(evaluation),
        "fundamental_quantity_comparison_markdown": comparison_markdown(comparison),
        "agent_difficulty_research_summary_markdown": summary_markdown(summary),
    }
    filenames = {
        "difficulty_independence_markdown": "difficulty_independence.md",
        "difficulty_prediction_markdown": "difficulty_prediction.md",
        "difficulty_hierarchy_markdown": "difficulty_hierarchy.md",
        "difficulty_falsification_markdown": "difficulty_falsification.md",
        "agent_difficulty_evaluation_markdown": "agent_difficulty_evaluation.md",
        "fundamental_quantity_comparison_markdown": "fundamental_quantity_comparison.md",
        "agent_difficulty_research_summary_markdown": "agent_difficulty_research_summary.md",
    }
    for key, text in markdown_outputs.items():
        path = directory / filenames[key]
        path.write_text(text, encoding="utf-8")
        paths[key] = path
    return {
        "object": "agent_hub.research.agent_difficulty",
        "rows": len(rows),
        "tasks": len(matrix.get("tasks", {})),
        "multi_model_tasks": matrix.get("multi_model_task_count", 0),
        "evaluation": evaluation,
        "summary": summary,
        "paths": {key: str(path) for key, path in paths.items()},
    }


def fundamental_quantity_comparison(directory: Path, difficulty_evaluation: dict[str, Any]) -> dict[str, Any]:
    baseline_scores = {
        "Agent Difficulty": float(difficulty_evaluation["score"]) / 100.0,
        "Information Density": _score_from_json(directory / "information_density_fundamental_evaluation.md", default=0.62),
        "Context Complexity Index": _portfolio_score(directory, "Context Complexity Index", default=0.55),
        "Failure Entropy": _portfolio_score(directory, "Failure Entropy", default=0.25),
        "Repository Intelligence": _portfolio_score(directory, "Repository Intelligence Index", default=0.35),
        "Routing Risk": _portfolio_score(directory, "Routing Risk Score", default=0.50),
    }
    ranking = [
        {
            "rank": index,
            "quantity": name,
            "score": round(score, 6),
            "interpretation": _comparison_interpretation(name, score, difficulty_evaluation),
        }
        for index, (name, score) in enumerate(sorted(baseline_scores.items(), key=lambda item: (-item[1], item[0])), start=1)
    ]
    return {
        "object": "agent_hub.research.fundamental_quantity_comparison",
        "ranked_quantities": ranking,
    }


def research_summary(
    matrix: dict[str, Any],
    metrics: dict[str, Any],
    independence: dict[str, Any],
    prediction: dict[str, Any],
    evaluation: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    top_quantity = comparison["ranked_quantities"][0]["quantity"] if comparison["ranked_quantities"] else ""
    exists = evaluation["score"] >= 60 and evaluation["generalizes_across_models"]
    predictive = bool(evaluation["predictive"])
    more_than_context = _rank_of(comparison, "Agent Difficulty") < _rank_of(comparison, "Context Complexity Index")
    more_than_density = _rank_of(comparison, "Agent Difficulty") < _rank_of(comparison, "Information Density")
    return {
        "does_agent_difficulty_exist": exists,
        "is_independent_of_model": bool(evaluation["generalizes_across_models"]),
        "is_predictive": predictive,
        "more_fundamental_than_context": more_than_context,
        "more_fundamental_than_information_density": more_than_density,
        "should_future_research_focus_on_agent_difficulty": exists or evaluation["score"] >= 50,
        "score": evaluation["score"],
        "top_ranked_quantity": top_quantity,
        "task_count": len(matrix.get("tasks", {})),
        "multi_model_task_count": matrix.get("multi_model_task_count", 0),
        "explained_variance": explain_variance(matrix, {task: row["consensus_difficulty"] for task, row in metrics.get("tasks", {}).items()}),
        "independence_mean_rank_correlation": independence.get("mean_rank_correlation"),
        "prediction_overall": prediction.get("overall"),
        "final_conclusion": _final_conclusion(exists, predictive, evaluation),
    }


def comparison_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Fundamental Quantity Comparison",
        "",
        "| rank | quantity | score | interpretation |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["ranked_quantities"]:
        lines.append(f"| {row['rank']} | {row['quantity']} | {row['score']} | {row['interpretation']} |")
    lines.append("")
    return "\n".join(lines)


def summary_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Agent Difficulty Research Summary",
        "",
        f"Tasks analyzed: {payload['task_count']} total; {payload['multi_model_task_count']} have at least two observed models.",
        f"Agent Difficulty score: {payload['score']} / 100.",
        "",
        "| question | answer |",
        "| --- | --- |",
        f"| Does an Agent Difficulty quantity appear to exist? | {payload['does_agent_difficulty_exist']} |",
        f"| Is it independent of model? | {payload['is_independent_of_model']} |",
        f"| Is it predictive? | {payload['is_predictive']} |",
        f"| Is it more fundamental than context? | {payload['more_fundamental_than_context']} |",
        f"| Is it more fundamental than information density? | {payload['more_fundamental_than_information_density']} |",
        f"| Should future research focus on Agent Difficulty? | {payload['should_future_research_focus_on_agent_difficulty']} |",
        "",
        f"Top-ranked quantity in this comparison: {payload['top_ranked_quantity']}.",
        f"Explained variance: {payload['explained_variance']}.",
        f"Independence mean rank correlation: {payload['independence_mean_rank_correlation']}.",
        f"Prediction overall: {json.dumps(payload['prediction_overall'], sort_keys=True)}.",
        "",
        f"Final conclusion: {payload['final_conclusion']}",
        "",
    ]
    return "\n".join(lines)


def _portfolio_score(directory: Path, name: str, *, default: float) -> float:
    path = directory / "research_portfolio_rankings.json"
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    for row in payload.get("ranked_quantities", []):
        if row.get("name") == name:
            return float(row.get("research_potential_score") or default)
    return default


def _score_from_json(path: Path, *, default: float) -> float:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "not a causal factor" in text:
        return 0.58
    if "causal driver" in text:
        return 0.92
    return default


def _comparison_interpretation(name: str, score: float, difficulty: dict[str, Any]) -> str:
    if name == "Agent Difficulty":
        if difficulty["generalizes_across_models"] and difficulty["predictive"]:
            return "Potentially fundamental; survived the model-invariance tests."
        if difficulty["generalizes_across_models"]:
            return "Stable across model removal, but predictive evidence is incomplete."
        return "Interesting heuristic; model independence remains weak."
    if name == "Information Density":
        return "Useful context heuristic, but prior causal study did not support S+ promotion."
    return "Compared using prior Fundamental Research Lab score."


def _rank_of(comparison: dict[str, Any], quantity: str) -> int:
    for row in comparison.get("ranked_quantities", []):
        if row["quantity"] == quantity:
            return int(row["rank"])
    return 999


def _final_conclusion(exists: bool, predictive: bool, evaluation: dict[str, Any]) -> str:
    if exists and predictive:
        return "Agent Difficulty appears to be a candidate fundamental quantity, but it still needs prospective benchmarks."
    if evaluation["score"] >= 50:
        return "Agent Difficulty shows partial structure, but the current data supports a heuristic rather than a fundamental quantity."
    return "Current evidence does not support Agent Difficulty as model-independent."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Agent Difficulty research program.")
    parser.add_argument("--state-dir", default=".agent-hub")
    args = parser.parse_args(argv)
    result = run_agent_difficulty_research_program(args.state_dir)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_agent_difficulty_research_program"]
