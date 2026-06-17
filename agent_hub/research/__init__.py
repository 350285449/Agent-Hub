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
from .task_generator import generate_benchmark_tasks, validate_benchmark_tasks, write_benchmark_tasks
from .telemetry import ResearchRun, record_research_outcome, record_research_route_start


def generate_research_benchmark(*args, **kwargs):
    from .benchmark_generator import generate_research_benchmark as _run

    return _run(*args, **kwargs)


def discover_candidate_quantities(*args, **kwargs):
    from .research_discovery import discover_candidate_quantities as _run

    return _run(*args, **kwargs)


def run_research_discovery(*args, **kwargs):
    from .research_discovery import run_research_discovery as _run

    return _run(*args, **kwargs)


def collect_live_matrix(*args, **kwargs):
    from .live_matrix_runner import collect_live_matrix as _run

    return _run(*args, **kwargs)


def summarize_live_matrix(*args, **kwargs):
    from .live_matrix_runner import summarize_live_matrix as _run

    return _run(*args, **kwargs)


def load_audited_rows(*args, **kwargs):
    from .data_quality_audit import load_audited_rows as _run

    return _run(*args, **kwargs)


def run_data_quality_audit(*args, **kwargs):
    from .data_quality_audit import run_data_quality_audit as _run

    return _run(*args, **kwargs)


def run_full_live_matrix_collection(*args, **kwargs):
    from .full_live_matrix_collection import run_full_live_matrix_collection as _run

    return _run(*args, **kwargs)


def evaluate_theory(*args, **kwargs):
    from .theory_test_harness import evaluate_theory as _run

    return _run(*args, **kwargs)


def run_theory_suite(*args, **kwargs):
    from .theory_test_harness import run_theory_suite as _run

    return _run(*args, **kwargs)


def infer_certificate_features(*args, **kwargs):
    from .certificate_features import infer_certificate_features as _run

    return _run(*args, **kwargs)


def cross_repo_holdout_validation(*args, **kwargs):
    from .theory_test_harness import cross_repo_holdout_validation as _run

    return _run(*args, **kwargs)


def certificate_theory_validation(*args, **kwargs):
    from .theory_test_harness import certificate_theory_validation as _run

    return _run(*args, **kwargs)


def cross_model_holdout_validation(*args, **kwargs):
    from .theory_test_harness import cross_model_holdout_validation as _run

    return _run(*args, **kwargs)


def ml_ceiling_benchmark(*args, **kwargs):
    from .theory_test_harness import ml_ceiling_benchmark as _run

    return _run(*args, **kwargs)


def prospective_predictions(*args, **kwargs):
    from .theory_test_harness import prospective_predictions as _run

    return _run(*args, **kwargs)


def run_prospective_validation(*args, **kwargs):
    from .prospective_evaluator import run_prospective_validation as _run

    return _run(*args, **kwargs)


def geometry_diagnostic(*args, **kwargs):
    from .theory_test_harness import geometry_diagnostic as _run

    return _run(*args, **kwargs)


def unified_theory_validation(*args, **kwargs):
    from .theory_test_harness import unified_theory_validation as _run

    return _run(*args, **kwargs)


def run_state_space_theory_research_program(*args, **kwargs):
    from .state_space_theory import run_state_space_theory_research_program as _run

    return _run(*args, **kwargs)


def analyze_balanced_live_matrix(*args, **kwargs):
    from .balanced_live_matrix import analyze_balanced_live_matrix as _run

    return _run(*args, **kwargs)


def run_balanced_live_matrix_experiment(*args, **kwargs):
    from .balanced_live_matrix import run_balanced_live_matrix_experiment as _run

    return _run(*args, **kwargs)


def run_eac_theory_evaluation(*args, **kwargs):
    from .eac_theory import run_eac_theory_evaluation as _run

    return _run(*args, **kwargs)


def evaluate_eac_theory(*args, **kwargs):
    from .eac_theory import evaluate_eac_theory as _run

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
    "collect_live_matrix",
    "dominates",
    "discover_candidate_quantities",
    "evaluate_theory",
    "export_dataset_csv",
    "generate_benchmark_tasks",
    "generate_research_benchmark",
    "infer_certificate_features",
    "load_audited_rows",
    "load_file_stats",
    "load_research_runs",
    "load_research_observations",
    "most_useful_files",
    "pareto_frontier",
    "rank_research_portfolio",
    "record_research_outcome",
    "record_research_route_start",
    "cross_repo_holdout_validation",
    "cross_model_holdout_validation",
    "certificate_theory_validation",
    "ml_ceiling_benchmark",
    "prospective_predictions",
    "run_prospective_validation",
    "geometry_diagnostic",
    "unified_theory_validation",
    "run_data_quality_audit",
    "run_eac_theory_evaluation",
    "evaluate_eac_theory",
    "run_full_live_matrix_collection",
    "run_agent_difficulty_research_program",
    "run_balanced_live_matrix_experiment",
    "run_fundamental_research_lab",
    "run_research_discovery",
    "run_research_analysis",
    "run_state_space_theory_research_program",
    "run_theory_suite",
    "select_context_files",
    "summarize_live_matrix",
    "summarize_fundamental_lab",
    "summarize_runs",
    "update_file_stats",
    "validate_benchmark_tasks",
    "write_benchmark_tasks",
    "wilson_interval",
]
