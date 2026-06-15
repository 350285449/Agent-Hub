from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

from .context_curve import compute_context_efficiency_curve
from .telemetry import research_dir


def compute_curve_fit(state_dir: str | Path) -> dict[str, Any]:
    points = [
        (float(row["average_tokens"]), float(row["success_rate"]))
        for row in compute_context_efficiency_curve(state_dir)
        if int(row.get("runs") or 0) > 0
    ]
    fits = {
        "linear": _fit_linear(points, transform=lambda x: x, predict_x=lambda x: x),
        "logarithmic": _fit_linear(points, transform=lambda x: math.log1p(x), predict_x=lambda x: math.log1p(x)),
        "saturating_exponential": _fit_saturating(points),
        "michaelis_menten": _fit_michaelis(points),
    }
    best_name, best_fit = min(fits.items(), key=lambda item: (item[1]["mse"], -item[1]["r2"], item[0]))
    return {
        "object": "agent_hub.research.curve_fit",
        "points": [{"context_tokens": x, "success_rate": y} for x, y in points],
        "fits": fits,
        "best_fit_model": best_name,
        "best_fit": best_fit,
    }


def export_curve_fit(state_dir: str | Path) -> dict[str, str]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = compute_curve_fit(state_dir)
    json_path = directory / "curve_fit.json"
    md_path = directory / "curve_fit.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(_markdown(payload), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def _fit_linear(
    points: list[tuple[float, float]],
    *,
    transform: Callable[[float], float],
    predict_x: Callable[[float], float],
) -> dict[str, Any]:
    if not points:
        return _fit_result("y = 0", {}, [], [])
    xs = [transform(x) for x, _y in points]
    ys = [y for _x, y in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denom = sum((x - mean_x) ** 2 for x in xs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom if denom else 0.0
    intercept = mean_y - slope * mean_x
    predictions = [intercept + slope * predict_x(x) for x, _y in points]
    return _fit_result("y = intercept + slope*x", {"intercept": intercept, "slope": slope}, ys, predictions)


def _fit_saturating(points: list[tuple[float, float]]) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    ys = [y for _x, y in points]
    for rate in _grid(0.00005, 0.01, 160):
        fs = [1.0 - math.exp(-rate * x) for x, _y in points]
        scale = _least_squares_scale(fs, ys)
        predictions = [scale * f for f in fs]
        fit = _fit_result("y = asymptote * (1 - exp(-rate*x))", {"asymptote": scale, "rate": rate}, ys, predictions)
        if best is None or fit["mse"] < best["mse"]:
            best = fit
    return best or _fit_result("y = 0", {}, ys, [])


def _fit_michaelis(points: list[tuple[float, float]]) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    ys = [y for _x, y in points]
    for km in _grid(100.0, 30_000.0, 180):
        fs = [x / (km + x) if x > 0 else 0.0 for x, _y in points]
        vmax = _least_squares_scale(fs, ys)
        predictions = [vmax * f for f in fs]
        fit = _fit_result("y = vmax*x/(km+x)", {"vmax": vmax, "km": km}, ys, predictions)
        if best is None or fit["mse"] < best["mse"]:
            best = fit
    return best or _fit_result("y = 0", {}, ys, [])


def _fit_result(equation: str, params: dict[str, float], ys: list[float], predictions: list[float]) -> dict[str, Any]:
    mse = _mse(ys, predictions)
    return {
        "equation": equation,
        "parameters": {key: round(value, 10) for key, value in params.items()},
        "r2": round(_r2(ys, predictions), 6),
        "mse": round(mse, 10),
        "predictions": [round(value, 6) for value in predictions],
    }


def _least_squares_scale(features: list[float], targets: list[float]) -> float:
    denom = sum(value * value for value in features)
    return sum(feature * target for feature, target in zip(features, targets)) / denom if denom else 0.0


def _r2(targets: list[float], predictions: list[float]) -> float:
    if not targets or not predictions:
        return 0.0
    mean = sum(targets) / len(targets)
    total = sum((target - mean) ** 2 for target in targets)
    residual = sum((target - predicted) ** 2 for target, predicted in zip(targets, predictions))
    return 1.0 - residual / total if total else 1.0


def _mse(targets: list[float], predictions: list[float]) -> float:
    return sum((target - predicted) ** 2 for target, predicted in zip(targets, predictions)) / len(targets) if targets else 0.0


def _grid(start: float, stop: float, count: int) -> list[float]:
    if count <= 1:
        return [start]
    step = (stop - start) / (count - 1)
    return [start + step * index for index in range(count)]


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Curve Fit Analysis",
        "",
        f"Best-fit model: `{payload.get('best_fit_model')}`",
        "",
        "| model | R2 | MSE | equation |",
        "| --- | --- | --- | --- |",
    ]
    fits = payload.get("fits") if isinstance(payload.get("fits"), dict) else {}
    for name, fit in fits.items():
        lines.append(f"| {name} | {fit.get('r2')} | {fit.get('mse')} | {fit.get('equation')} |")
    lines.append("")
    return "\n".join(lines)


__all__ = ["compute_curve_fit", "export_curve_fit"]
