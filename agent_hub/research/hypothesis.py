from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .context_curve import compute_context_efficiency_curve
from .telemetry import research_dir


def compute_hypothesis_tests(state_dir: str | Path) -> dict[str, Any]:
    curve = [row for row in compute_context_efficiency_curve(state_dir) if int(row.get("runs") or 0) > 0]
    more_context = _more_context_improves(curve)
    diminishing = _diminishing_returns(curve)
    best_efficiency = _best_success_per_token_bucket(curve)
    return {
        "object": "agent_hub.research.hypothesis_tests",
        "tests": {
            "more_context_improves_success": more_context,
            "marginal_gains_decrease": diminishing,
            "one_to_two_k_best_success_per_token": {
                "supported": best_efficiency["context_bucket"] == "1-2k",
                "best_bucket": best_efficiency["context_bucket"],
                "best_success_per_1k_tokens": best_efficiency["success_per_1k_tokens"],
                "interpretation": "1-2k has the highest observed success per 1k context tokens."
                if best_efficiency["context_bucket"] == "1-2k"
                else "The observed efficiency peak is outside 1-2k.",
            },
        },
        "curve": curve,
    }


def export_hypothesis_tests(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = compute_hypothesis_tests(state_dir)
    json_path = directory / "hypothesis_tests.json"
    md_path = directory / "hypothesis_tests.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _more_context_improves(curve: list[dict[str, Any]]) -> dict[str, Any]:
    if len(curve) < 2:
        return {"supported": False, "interpretation": "Not enough context buckets."}
    baseline = float(curve[0].get("success_rate") or 0.0)
    best = max(float(row.get("success_rate") or 0.0) for row in curve[1:])
    return {
        "supported": best > baseline,
        "baseline_success_rate": baseline,
        "best_larger_context_success_rate": best,
        "effect_size": round(best - baseline, 6),
        "interpretation": "More context improved observed success." if best > baseline else "More context did not improve observed success.",
    }


def _diminishing_returns(curve: list[dict[str, Any]]) -> dict[str, Any]:
    previous_gain: float | None = None
    threshold = ""
    for row in curve:
        gain = float(row.get("marginal_success_gain") or 0.0)
        if previous_gain is not None and gain < previous_gain:
            threshold = str(row.get("context_bucket") or "")
            break
        previous_gain = gain
    return {
        "supported": bool(threshold),
        "threshold_bucket": threshold or "not_detected",
        "interpretation": f"Marginal success gains decrease starting at {threshold}." if threshold else "No decreasing marginal-gain threshold detected.",
    }


def _best_success_per_token_bucket(curve: list[dict[str, Any]]) -> dict[str, Any]:
    best = {"context_bucket": "not_enough_data", "success_per_1k_tokens": 0.0}
    for row in curve:
        tokens = float(row.get("average_tokens") or 0.0)
        if tokens <= 0:
            continue
        score = float(row.get("success_rate") or 0.0) / (tokens / 1000.0)
        if score > best["success_per_1k_tokens"]:
            best = {"context_bucket": str(row.get("context_bucket") or ""), "success_per_1k_tokens": round(score, 6)}
    return best


def _markdown(payload: dict[str, Any]) -> str:
    tests = payload.get("tests") if isinstance(payload.get("tests"), dict) else {}
    lines = ["# Hypothesis Tests", ""]
    for name, result in tests.items():
        if isinstance(result, dict):
            lines.append(f"## {name}")
            lines.append(f"- Supported: {result.get('supported')}")
            lines.append(f"- Interpretation: {result.get('interpretation')}")
            if result.get("threshold_bucket"):
                lines.append(f"- Threshold bucket: {result.get('threshold_bucket')}")
            if result.get("best_bucket"):
                lines.append(f"- Best bucket: {result.get('best_bucket')}")
            lines.append("")
    return "\n".join(lines)


__all__ = ["compute_hypothesis_tests", "export_hypothesis_tests"]
