from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .structure_vs_experience import evaluate_dataset
from .telemetry import research_dir


def compute_cold_start_results(structure: dict[str, Any], experience: dict[str, Any], combined: dict[str, Any]) -> dict[str, Any]:
    structure_result = evaluate_dataset(structure)["targets"]["success"]
    experience_result = evaluate_dataset(experience)["targets"]["success"]
    combined_result = evaluate_dataset(combined)["targets"]["success"]
    retained = structure_result["r2"] / combined_result["r2"] if combined_result["r2"] else 0.0
    return {
        "object": "agent_hub.research.cold_start_results",
        "simulation": "brand_new_repository_remove_historical_priors_routing_memory_adaptive_feedback",
        "structure_only": structure_result,
        "experience_only_reference": experience_result,
        "combined_reference": combined_result,
        "cold_start_performance_retained": round(retained, 6),
        "interpretation": "structure retains substantial cold-start power" if retained >= 0.5 else "cold start depends heavily on experience",
    }


def export_cold_start_results(
    state_dir: str | Path,
    structure: dict[str, Any],
    experience: dict[str, Any],
    combined: dict[str, Any],
) -> tuple[Path, Path, dict[str, Any]]:
    directory = research_dir(state_dir)
    payload = compute_cold_start_results(structure, experience, combined)
    json_path = directory / "cold_start_results.json"
    md_path = directory / "cold_start_results.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(cold_start_markdown(payload), encoding="utf-8")
    return json_path, md_path, payload


def cold_start_markdown(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Cold Start Results",
            "",
            f"- Simulation: {payload['simulation']}",
            f"- Structure-only R2: {payload['structure_only']['r2']}",
            f"- Structure-only correlation: {payload['structure_only']['correlation']}",
            f"- Combined reference R2: {payload['combined_reference']['r2']}",
            f"- Cold-start performance retained: {payload['cold_start_performance_retained']}",
            f"- Interpretation: {payload['interpretation']}",
            "",
        ]
    )


__all__ = ["compute_cold_start_results", "export_cold_start_results"]
