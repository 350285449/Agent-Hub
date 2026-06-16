from __future__ import annotations

from pathlib import Path
from typing import Any

from .analysis import export_analysis_json, export_pareto_frontier_json
from .context_curve import export_context_efficiency_curve
from .curve_fit import export_curve_fit
from .dataset import export_dataset_csv
from .hypothesis import export_hypothesis_tests
from .information_density import export_information_density_json
from .math_summary import generate_math_research_summary
from .real_model_ablation import export_real_model_outputs
from .report import generate_research_report
from .strategy_comparison import export_context_strategy_comparison
from .tau_repo_correlation import export_tau_repo_correlation
from .tau_validation import export_cross_repo_tau


def run_research_analysis(state_dir: str | Path) -> dict[str, Any]:
    report_paths = generate_research_report(state_dir)
    curve_paths = export_context_efficiency_curve(state_dir)
    curve_fit_paths = export_curve_fit(state_dir)
    hypothesis_paths = export_hypothesis_tests(state_dir)
    strategy_paths = export_context_strategy_comparison(state_dir)
    real_ablation_paths = export_real_model_outputs(state_dir)
    tau_paths = export_cross_repo_tau(state_dir)
    correlation_paths = export_tau_repo_correlation(state_dir)
    return {
        "object": "agent_hub.research.analysis_run",
        "analysis": str(export_analysis_json(state_dir)),
        "pareto_frontier": str(export_pareto_frontier_json(state_dir)),
        "information_density": str(export_information_density_json(state_dir)),
        "context_efficiency_curve": curve_paths["json"],
        "context_efficiency_curve_markdown": curve_paths["markdown"],
        "curve_fit": curve_fit_paths["json"],
        "curve_fit_markdown": curve_fit_paths["markdown"],
        "hypothesis_tests": hypothesis_paths["json"],
        "hypothesis_tests_markdown": hypothesis_paths["markdown"],
        "context_strategy_comparison": strategy_paths["json"],
        "context_strategy_comparison_markdown": strategy_paths["markdown"],
        "real_model_validation": real_ablation_paths["real_model_validation"],
        "real_model_validation_markdown": real_ablation_paths["real_model_validation_markdown"],
        "real_model_tau": real_ablation_paths["real_model_tau"],
        "real_model_tau_markdown": real_ablation_paths["real_model_tau_markdown"],
        "real_model_comparison": real_ablation_paths["real_model_comparison"],
        "cross_repo_tau": tau_paths["json"],
        "cross_repo_tau_markdown": tau_paths["markdown"],
        "tau_repo_correlation": correlation_paths["json"],
        "tau_repo_correlation_markdown": correlation_paths["markdown"],
        "math_research_summary": str(generate_math_research_summary(state_dir)),
        "dataset": str(export_dataset_csv(state_dir)),
        "report": report_paths.get("report", ""),
    }


__all__ = ["run_research_analysis"]
