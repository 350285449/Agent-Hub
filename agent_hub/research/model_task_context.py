from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .context_embedding import export_context_embeddings, load_context_observations
from .telemetry import research_dir
from .triadic_compatibility import export_triadic_compatibility
from .triadic_validation import (
    export_triadic_ablation,
    export_triadic_falsification,
    export_triadic_prediction,
    export_triadic_stability,
    export_triadic_summary,
)


def run_model_task_context_research_program(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rows = load_context_observations(state_dir)
    context_json, context_md, context_payload = export_context_embeddings(state_dir, rows)
    model_payload = _load_required(directory / "model_behavior_vectors.json")
    task_payload = _load_required(directory / "task_embedding.json")
    shared_payload = _load_required(directory / "shared_geometry.json")
    model_task_payload = _load_required(directory / "compatibility_metrics.json")
    triadic_json, triadic_md, triadic_payload = export_triadic_compatibility(
        state_dir,
        context_payload,
        model_payload,
        task_payload,
        shared_payload,
        model_task_payload,
    )
    prediction_json, prediction_md, prediction = export_triadic_prediction(state_dir, triadic_payload)
    ablation_json, ablation_md, ablation = export_triadic_ablation(state_dir, triadic_payload)
    falsification_md = export_triadic_falsification(state_dir, triadic_payload, prediction, ablation)
    stability_json, stability_md, stability = export_triadic_stability(state_dir, triadic_payload)
    summary_md = export_triadic_summary(state_dir, triadic_payload, prediction, ablation, stability)
    return {
        "context_embedding": str(context_json),
        "context_embedding_markdown": str(context_md),
        "triadic_compatibility_metrics": str(triadic_json),
        "triadic_compatibility_metrics_markdown": str(triadic_md),
        "triadic_prediction": str(prediction_json),
        "triadic_prediction_markdown": str(prediction_md),
        "triadic_ablation": str(ablation_json),
        "triadic_ablation_markdown": str(ablation_md),
        "triadic_falsification": str(falsification_md),
        "triadic_stability": str(stability_json),
        "triadic_stability_markdown": str(stability_md),
        "model_task_context_research_summary": str(summary_md),
    }


def _load_required(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"required research artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the model-task-context compatibility research program.")
    parser.add_argument("--state-dir", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        from ..config import load_config

        state_dir = load_config().state_dir
    result = run_model_task_context_research_program(state_dir)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_model_task_context_research_program"]
