from __future__ import annotations

from .ablation import ContextAblationRecord, append_context_ablation_result, context_ablation_path
from .agent_difficulty import run_agent_difficulty_research_program
from .analysis import analyze_research_dir, analyze_runs, compute_pareto_frontier
from .analyze import run_research_analysis
from .bayesian_router import BayesianSuccessRouter, SuccessKey
from .context_curve import compute_context_efficiency_curve
from .dataset import export_dataset_csv
from .experiments import ContextAblationExperiment, ContextAblationResult
from .file_stats import load_file_stats, most_useful_files, update_file_stats
from .fundamental_lab import load_research_observations, run_fundamental_research_lab, summarize_fundamental_lab
from .information_density import compute_information_density
from .information_context import ContextFileSignal, compare_context_rankings, select_context_files
from .metrics import ResearchSummary, load_research_runs, summarize_runs, wilson_interval
from .pareto import ModelObjective, dominates, pareto_frontier
from .research_portfolio import rank_research_portfolio
from .rl_router import BanditArm, EpsilonGreedyRouter
from .telemetry import ResearchRun, record_research_outcome, record_research_route_start


def run_state_space_theory_research_program(*args, **kwargs):
    from .state_space_theory import run_state_space_theory_research_program as _run

    return _run(*args, **kwargs)


def analyze_balanced_live_matrix(*args, **kwargs):
    from .balanced_live_matrix import analyze_balanced_live_matrix as _run

    return _run(*args, **kwargs)


def run_balanced_live_matrix_experiment(*args, **kwargs):
    from .balanced_live_matrix import run_balanced_live_matrix_experiment as _run

    return _run(*args, **kwargs)

__all__ = [
    "BanditArm",
    "BayesianSuccessRouter",
    "ContextAblationRecord",
    "ContextAblationExperiment",
    "ContextAblationResult",
    "ContextFileSignal",
    "EpsilonGreedyRouter",
    "ModelObjective",
    "ResearchRun",
    "ResearchSummary",
    "SuccessKey",
    "append_context_ablation_result",
    "analyze_research_dir",
    "analyze_balanced_live_matrix",
    "analyze_runs",
    "compute_context_efficiency_curve",
    "compute_information_density",
    "compute_pareto_frontier",
    "context_ablation_path",
    "compare_context_rankings",
    "dominates",
    "export_dataset_csv",
    "load_file_stats",
    "load_research_runs",
    "load_research_observations",
    "most_useful_files",
    "pareto_frontier",
    "rank_research_portfolio",
    "record_research_outcome",
    "record_research_route_start",
    "run_agent_difficulty_research_program",
    "run_balanced_live_matrix_experiment",
    "run_fundamental_research_lab",
    "run_research_analysis",
    "run_state_space_theory_research_program",
    "select_context_files",
    "summarize_fundamental_lab",
    "summarize_runs",
    "update_file_stats",
    "wilson_interval",
]
