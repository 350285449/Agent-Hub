from __future__ import annotations

import argparse
import json
from pathlib import Path

from .compatibility_space import export_compatibility_metrics, export_shared_geometry
from .geometry_validation import (
    evaluate_compatibility,
    export_comparison,
    export_evaluation,
    export_falsification,
    export_prediction,
    export_stability,
    export_summary,
)
from .model_distance import load_model_observations
from .task_embedding import export_task_embeddings
from .telemetry import research_dir


def run_model_task_geometry_research_program(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    observations = load_model_observations(state_dir)

    task_json, task_md, task_payload = export_task_embeddings(state_dir, observations)
    shared_json, shared_md, shared_payload = export_shared_geometry(state_dir, task_payload)
    compatibility_json, compatibility_md, compatibility_payload = export_compatibility_metrics(state_dir, shared_payload)
    prediction_json, prediction_md, prediction = export_prediction(state_dir, compatibility_payload)
    comparison_md, comparison = export_comparison(state_dir, prediction)
    stability_json, stability_md, stability = export_stability(state_dir, observations, shared_payload)
    falsification_md = export_falsification(state_dir, prediction, stability, compatibility_payload)
    evaluation = evaluate_compatibility(prediction, stability, comparison, compatibility_payload)
    evaluation_md = export_evaluation(state_dir, evaluation)
    summary_md = export_summary(state_dir, evaluation, prediction, stability, comparison, compatibility_payload)

    return {
        "task_embedding": str(task_json),
        "task_embedding_markdown": str(task_md),
        "shared_geometry": str(shared_json),
        "shared_geometry_markdown": str(shared_md),
        "compatibility_metrics": str(compatibility_json),
        "compatibility_metrics_markdown": str(compatibility_md),
        "compatibility_prediction": str(prediction_json),
        "compatibility_prediction_markdown": str(prediction_md),
        "geometry_vs_all_theories": str(comparison_md),
        "geometry_falsification": str(falsification_md),
        "geometry_stability": str(stability_json),
        "geometry_stability_markdown": str(stability_md),
        "compatibility_evaluation": str(evaluation_md),
        "model_task_geometry_research_summary": str(summary_md),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the model-task geometry research program.")
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        from ..config import load_config

        state_dir = load_config().state_dir
    result = run_model_task_geometry_research_program(state_dir)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_model_task_geometry_research_program"]
