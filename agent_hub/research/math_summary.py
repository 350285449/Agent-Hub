from __future__ import annotations

from pathlib import Path
from typing import Any

from .analysis import analyze_research_dir, compute_pareto_frontier
from .context_curve import compute_context_efficiency_curve
from .curve_fit import compute_curve_fit
from .hypothesis import compute_hypothesis_tests
from .information_density import top_information_density_files
from .metrics import load_research_runs
from .real_model_validation import compute_real_model_validation_status
from .real_model_ablation import compute_real_model_tau
from .strategy_comparison import compute_context_strategy_comparison
from .tau_repo_correlation import compute_tau_repo_correlation
from .tau_validation import compute_cross_repo_tau
from .telemetry import research_dir


def generate_math_research_summary(state_dir: str | Path, output: str | Path | None = None) -> Path:
    analysis = analyze_research_dir(state_dir)
    runs = load_research_runs(state_dir)
    pareto = compute_pareto_frontier(runs)
    curve = compute_context_efficiency_curve(state_dir)
    top_files = top_information_density_files(state_dir, limit=10)
    curve_fit = compute_curve_fit(state_dir)
    hypotheses = compute_hypothesis_tests(state_dir)
    strategy = compute_context_strategy_comparison(state_dir)
    real_model = compute_real_model_validation_status()
    cross_tau = compute_cross_repo_tau(state_dir)
    tau_correlation = compute_tau_repo_correlation(state_dir)
    real_tau = compute_real_model_tau(state_dir)
    path = Path(output) if output is not None else research_dir(state_dir) / "math_research_summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _markdown(analysis, pareto, curve, top_files, curve_fit, hypotheses, strategy, real_model, cross_tau, tau_correlation, real_tau),
        encoding="utf-8",
    )
    return path


def _markdown(
    analysis: dict[str, Any],
    pareto: list[dict[str, Any]],
    curve: list[dict[str, Any]],
    top_files: list[dict[str, Any]],
    curve_fit: dict[str, Any],
    hypotheses: dict[str, Any],
    strategy: dict[str, Any],
    real_model: dict[str, Any],
    cross_tau: dict[str, Any],
    tau_correlation: dict[str, Any],
    real_tau: dict[str, Any],
) -> str:
    best_success = _best_model(analysis, "success_rate")
    best_efficiency = _best_model(analysis, "efficiency_score")
    best_context = _best_context_bucket(analysis)
    diminishing = _diminishing_returns(curve)
    more_context = _more_context_improves(curve)
    diminishing_point = _diminishing_point(curve)
    lines = [
        "# Agent-Hub Math Research Summary",
        "",
        "## Main Dataset Statistics",
        f"- Total experiment rows: {analysis.get('total_runs', 0)}",
        f"- Total runs: {analysis.get('total_runs', 0)}",
        f"- Success rate: {analysis.get('success_rate', 0)}",
        f"- Average validation score: {analysis.get('average_validation_score', 0)}",
        f"- Average latency: {analysis.get('average_latency', 0)} ms",
        f"- Average cost: {analysis.get('average_cost', 0)}",
        f"- Average context tokens: {analysis.get('average_context_tokens', 0)}",
        "",
        "## Best Models",
        f"- Best model by success rate: {best_success}",
        f"- Best model by efficiency: {best_efficiency}",
        "",
        "## Context Efficiency",
        f"- Context bucket with best success per token: {best_context}",
        f"- Diminishing returns evidence: {'yes' if diminishing else 'not enough evidence'}",
        f"- Best-fit curve: {curve_fit.get('best_fit_model', 'not enough data')}",
        f"- Diminishing returns threshold: {diminishing_point}",
        "",
        "## Curve Fit",
        f"- Best-fit model: {curve_fit.get('best_fit_model', 'not enough data')}",
        f"- Best-fit R2: {_best_fit_metric(curve_fit, 'r2')}",
        f"- Best-fit MSE: {_best_fit_metric(curve_fit, 'mse')}",
        "",
        "## Hypothesis Results",
        *_hypothesis_lines(hypotheses),
        "",
        "## Strategy Comparison",
        *_strategy_lines(strategy),
        "",
        "## Real-Model Status",
        f"- Status: {real_model.get('status', 'unknown')}",
        f"- Real model subset run: {real_model.get('real_model_subset_run', False)}",
        f"- Detail: {real_model.get('reason', '')}",
        "",
        "## Real Model Validation",
        *_real_model_tau_lines(real_tau, strategy),
        "",
        "## Cross-Repository Tau Validation",
        *_cross_repo_tau_lines(cross_tau, tau_correlation),
        "",
        "## Experiment Questions",
        f"1. Does more context improve success? {more_context}",
        f"2. Where do marginal gains start decreasing? {diminishing_point}",
        f"3. Which context budget gives the best success per token? {best_context}",
        f"4. Is there evidence of diminishing returns? {'yes' if diminishing else 'not enough evidence'}",
        f"5. Which files appear most information-dense? {_top_file_answer(top_files)}",
        "6. What are the limitations of the experiment? See limitations below; key limits are local sampling, sparse validation, and context attribution quality.",
        "",
        "## Top Files By Information Density",
        *_file_lines(top_files),
        "",
        "## Pareto-Optimal Runs",
        *_pareto_lines(pareto[:20]),
        "",
        "## Pilot Study Interpretation",
        "- This is a deterministic local benchmark/proof experiment.",
        "- Results are not yet based on real API/model execution.",
        "- Conclusions are valid only for the Agent-Hub local benchmark setting.",
        "- Future work should repeat the experiment with real models and larger task sets.",
        "",
        "## Limitations And Missing Data",
        "- Telemetry is opt-in and may under-sample normal usage.",
        "- Validation scores depend on configured validators and may be sparse.",
        "- Context file attribution is only as complete as request metadata.",
        "- Cost estimates depend on configured provider pricing.",
        "",
        "## Next Research Steps",
        "- Repeat the ablation with real local models and then with paid cloud models under explicit budget controls.",
        "- Increase task diversity beyond the bundled deterministic benchmark tasks.",
        "- Add confidence intervals and paired tests by task family.",
        "- Compare learned information-density context planning against default selection on real repository edits.",
        "",
    ]
    return "\n".join(lines)


def _best_model(analysis: dict[str, Any], metric: str) -> str:
    models = analysis.get("model_efficiency_score")
    if not isinstance(models, dict) or not models:
        return "not enough data"
    best = max(models.items(), key=lambda item: float(item[1].get(metric, 0.0) or 0.0))
    return f"{best[0]} ({metric}={best[1].get(metric, 0)})"


def _best_context_bucket(analysis: dict[str, Any]) -> str:
    buckets = analysis.get("success_rate_by_context_bucket")
    if not isinstance(buckets, dict) or not buckets:
        return "not enough data"
    best_label = ""
    best_score = -1.0
    for label, row in buckets.items():
        if not isinstance(row, dict):
            continue
        score = float(row.get("success_rate") or 0.0) / _bucket_weight(label)
        if score > best_score:
            best_label = label
            best_score = score
    return best_label or "not enough data"


def _bucket_weight(label: str) -> float:
    return {
        "0 tokens": 1.0,
        "1-2k": 1.5,
        "2k-5k": 3.5,
        "5k-10k": 7.5,
        "10k-25k": 17.5,
        "25k+": 25.0,
    }.get(label, 1.0)


def _diminishing_returns(curve: list[dict[str, Any]]) -> bool:
    gains = [float(row.get("marginal_success_gain") or 0.0) for row in curve if int(row.get("runs") or 0) > 0]
    positive = [gain for gain in gains if gain > 0]
    return any(current < previous for previous, current in zip(positive, positive[1:]))


def _more_context_improves(curve: list[dict[str, Any]]) -> str:
    rows = [row for row in curve if int(row.get("runs") or 0) > 0]
    if len(rows) < 2:
        return "not enough data"
    first = float(rows[0].get("success_rate") or 0.0)
    best = max(float(row.get("success_rate") or 0.0) for row in rows[1:])
    if best > first:
        return f"yes; success rises from {first} to {best} across measured context buckets."
    if best == first:
        return "not in this sample; measured success does not exceed the lowest-context bucket."
    return "no; measured success decreases as context increases in this sample."


def _diminishing_point(curve: list[dict[str, Any]]) -> str:
    rows = [row for row in curve if int(row.get("runs") or 0) > 0]
    previous_gain: float | None = None
    for row in rows:
        gain = float(row.get("marginal_success_gain") or 0.0)
        if previous_gain is not None and gain < previous_gain:
            return str(row.get("context_bucket") or "unknown")
        previous_gain = gain
    return "not detected"


def _top_file_answer(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "not enough file data"
    return ", ".join(str(row.get("path") or "") for row in rows[:3])


def _best_fit_metric(curve_fit: dict[str, Any], metric: str) -> Any:
    best = curve_fit.get("best_fit") if isinstance(curve_fit.get("best_fit"), dict) else {}
    return best.get(metric, "not enough data")


def _hypothesis_lines(payload: dict[str, Any]) -> list[str]:
    tests = payload.get("tests") if isinstance(payload.get("tests"), dict) else {}
    if not tests:
        return ["- not enough hypothesis data"]
    lines: list[str] = []
    for name, row in tests.items():
        if isinstance(row, dict):
            lines.append(f"- {name}: supported={row.get('supported')} ({row.get('interpretation')})")
    return lines


def _strategy_lines(payload: dict[str, Any]) -> list[str]:
    strategies = payload.get("strategies") if isinstance(payload.get("strategies"), dict) else {}
    if not strategies:
        return ["- not enough strategy data"]
    lines = [
        f"- Winner by success per 1k tokens: {payload.get('winner_by_success_per_1k_tokens')}",
        f"- Winner by validation score: {payload.get('winner_by_validation_score')}",
    ]
    for name, row in strategies.items():
        if isinstance(row, dict):
            lines.append(
                f"- {name}: runs={row.get('runs')} success={row.get('success_rate')} validation={row.get('average_validation_score')} tokens={row.get('average_context_tokens')} success_per_1k={row.get('success_per_1k_tokens')}"
            )
    return lines


def _cross_repo_tau_lines(cross_tau: dict[str, Any], tau_correlation: dict[str, Any]) -> list[str]:
    repos = cross_tau.get("repositories") if isinstance(cross_tau.get("repositories"), list) else []
    if not repos:
        return [
            "- Stable tau by repository: not enough cross-repository data.",
            "- Saturating curve fit: not evaluated.",
            "- Tau versus complexity: not evaluated.",
            "- Repository sources: not available.",
            "- Cannot claim cross-repository validity yet.",
        ]
    stable = all(float(repo.get("r2") or 0.0) >= 0.8 for repo in repos)
    curve_fit = all(repo.get("best_fit_curve") == "saturating_exponential" for repo in repos)
    sources = sorted({str(repo.get("repo_source") or "unknown") for repo in repos})
    correlations = tau_correlation.get("correlations") if isinstance(tau_correlation.get("correlations"), dict) else {}
    complexity_corr = correlations.get("approximate_complexity_score", 0.0)
    lines = [
        f"- Does each repository have a stable tau? {'yes' if stable else 'mixed'}; minimum R2={min(float(repo.get('r2') or 0.0) for repo in repos):.3f}.",
        f"- Does the saturating curve still fit? {'yes' if curve_fit else 'mixed'} across {len(repos)} repositories.",
        f"- Does tau increase with repository complexity? correlation={complexity_corr}.",
        f"- Repository sources: {', '.join(sources)}.",
        "- What cannot be claimed yet? These deterministic local results do not prove real-model behavior, causal context effects, or generality across large external corpora.",
    ]
    for repo in repos:
        lines.append(
            f"- {repo.get('repo_id')}: source={repo.get('repo_source')} tau={repo.get('tau_estimate')} R2={repo.get('r2')} best_bucket={repo.get('best_success_per_token_bucket')} diminishing={repo.get('diminishing_return_bucket')}"
        )
    return lines


def _real_model_tau_lines(real_tau: dict[str, Any], strategy: dict[str, Any]) -> list[str]:
    rows = real_tau.get("results") if isinstance(real_tau.get("results"), list) else []
    if not rows:
        return [
            "- Did the context law survive? not evaluated with real model rows.",
            "- Is tau stable across real models? not enough real model data.",
            "- Which model has lowest tau? not enough data.",
            "- Which model has highest tau? not enough data.",
            f"- Does information-density context still win? deterministic strategy winner remains {strategy.get('winner_by_success_per_1k_tokens', 'unknown')}; real strategy data not collected.",
            "- What evidence contradicts the theory? no real-model rows available.",
            "- Final conclusion: B) Evidence is mixed.",
        ]
    saturating_wins = sum(1 for row in rows if row.get("winning_curve") == "saturating_exponential")
    poor_fits = [row for row in rows if float(row.get("r2") or 0.0) < 0.5]
    linear_wins = [row for row in rows if row.get("winning_curve") == "linear"]
    no_gain = [row for row in rows if _real_more_context_does_not_help(row)]
    lowest = min(rows, key=lambda row: float(row.get("tau") or 0.0))
    highest = max(rows, key=lambda row: float(row.get("tau") or 0.0))
    mixed = bool(poor_fits or linear_wins or no_gain or saturating_wins < len(rows))
    conclusion = "B) Evidence is mixed." if mixed else "A) Evidence supports tau under real-model execution."
    lines = [
        f"- Did the context law survive? {'partially' if mixed else 'yes'}; saturating exponential won {saturating_wins}/{len(rows)} model-repository fits.",
        f"- Is tau stable across real models? only one real model was tested; stability across models cannot be claimed.",
        f"- Which model has lowest tau? {lowest.get('model')} on {lowest.get('repo_id')} tau={lowest.get('tau')}.",
        f"- Which model has highest tau? {highest.get('model')} on {highest.get('repo_id')} tau={highest.get('tau')}.",
        f"- Does information-density context still win? not measured in real ablation; deterministic strategy winner remains {strategy.get('winner_by_success_per_1k_tokens', 'unknown')}.",
        f"- What evidence contradicts the theory? linear_wins={len(linear_wins)}, poor_tau_fits={len(poor_fits)}, no_context_gain={len(no_gain)}.",
        f"- Final conclusion: {conclusion}",
    ]
    return lines


def _real_more_context_does_not_help(row: dict[str, Any]) -> bool:
    points = row.get("points") if isinstance(row.get("points"), list) else []
    if len(points) < 2:
        return True
    baseline = float(points[0].get("success_rate") or 0.0)
    return max(float(point.get("success_rate") or 0.0) for point in points[1:]) <= baseline


def _file_lines(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["- not enough file data"]
    return [
        f"- {row['path']}: density={row.get('information_density', 0)} success_rate={row.get('success_rate_when_selected', 0)}"
        for row in rows
    ]


def _pareto_lines(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["- not enough run data"]
    return [
        f"- {row.get('task_id')}: model={row.get('selected_model')} score={row.get('validation_score')} cost={row.get('cost_estimate')} latency={row.get('latency_ms')} context={row.get('context_token_count')}"
        for row in rows
    ]


__all__ = ["generate_math_research_summary"]
