from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .telemetry import research_dir


def rank_research_portfolio(results: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        (dict(row) for row in results),
        key=lambda row: (
            -float(row.get("research_potential_score") or 0.0),
            -float(row.get("falsification_resistance") or 0.0),
            str(row.get("name") or ""),
        ),
    )
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
        row["tier"] = tier_for_score(float(row.get("research_potential_score") or 0.0), bool(row.get("survives_falsification")))
        row["continue_or_kill"] = _decision(row)
        row["next_experiment"] = next_experiment(row)
    return {
        "object": "agent_hub.research.research_portfolio_rankings",
        "ranked_quantities": ranked,
        "tiers": {
            "S": [row["name"] for row in ranked if row["tier"] == "S"],
            "A": [row["name"] for row in ranked if row["tier"] == "A"],
            "B": [row["name"] for row in ranked if row["tier"] == "B"],
            "C": [row["name"] for row in ranked if row["tier"] == "C"],
        },
    }


def tier_for_score(score: float, survives: bool) -> str:
    if survives and score >= 0.62:
        return "S"
    if survives and score >= 0.48:
        return "A"
    if score >= 0.32:
        return "B"
    return "C"


def next_experiment(row: dict[str, Any]) -> str:
    key = str(row.get("key") or "")
    if key == "context_complexity_index":
        return "Hold task and model fixed, sweep retrieval budgets, and test whether the index predicts the minimum context needed before execution."
    if key == "failure_entropy":
        return "Repeat identical task/model/route cells enough times to estimate whether failure entropy remains stable out of sample."
    if key == "agent_difficulty_index":
        return "Run the same task set across more models and repos, then test whether difficulty transfers to an unseen model."
    if key == "model_context_tolerance":
        return "Use controlled context injections with equal token counts and measure when each model's validation score peaks or degrades."
    if key == "model_specialization_index":
        return "Create balanced task families and test whether specialization predicts the best model on held-out tasks."
    if key == "repository_intelligence_index":
        return "Compare matched tasks across repos while controlling for model and context budget to isolate repository effects."
    if key == "routing_risk_score":
        return "Use the score as a pre-execution gate and measure avoided failures, false alarms, and fallback cost on future runs."
    if key == "model_distance_metric":
        return "Check whether distant models improve ensemble fallback success more than nearby models on identical tasks."
    if key == "information_density_index":
        return "Ablate individual files and context chunks to test whether high-density context causally improves validation."
    if key == "expected_utility_score":
        return "Deploy it as a route objective and compare net validation/cost/latency utility against success-only routing."
    return "Run a balanced held-out replication with fixed task, model, repo, and context controls."


def portfolio_markdown(portfolio: dict[str, Any]) -> str:
    rows = list(portfolio.get("ranked_quantities") or [])
    lines = [
        "# Agent-Hub Fundamental Research Lab",
        "",
        "This report ranks candidate fundamental quantities for AI agents. It is deliberately conservative: weak evidence is treated as weak evidence, not as proof.",
        "",
        "## Rankings",
        "",
        "| rank | tier | quantity | score | stability | predictive | routing | decision |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['rank']} | {row['tier']} | {row['name']} | {row['research_potential_score']} | {row['stability']} | {row['predictive_power']} | {row['usefulness_for_routing']} | {row['continue_or_kill']} |"
        )
    for tier, description in [
        ("S", "Most promising, potentially fundamental."),
        ("A", "Strong practical or research value."),
        ("B", "Interesting but needs more evidence."),
        ("C", "Weak or mostly descriptive."),
    ]:
        tier_rows = [row for row in rows if row.get("tier") == tier]
        lines.extend(["", f"## Tier {tier}: {description}"])
        if not tier_rows:
            lines.append("No quantities landed in this tier.")
            continue
        for row in tier_rows:
            lines.extend(_quantity_section(row))
    lines.append("")
    return "\n".join(lines)


def fundamental_quantities_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "# Fundamental Quantity Test Results",
        "",
        "| quantity | value | stability | predictive | success corr | validation corr | routing | falsification |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in sorted(results, key=lambda item: item["name"]):
        lines.append(
            f"| {row['name']} | {row['value']} | {row['stability']} | {row['predictive_power']} | {row['correlation_with_success']} | {row['correlation_with_validation_score']} | {row['usefulness_for_routing']} | {row['falsification_resistance']} |"
        )
    lines.append("")
    return "\n".join(lines)


def export_research_portfolio(state_dir: str | Path, results: list[dict[str, Any]]) -> dict[str, Path]:
    directory = research_dir(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    portfolio = rank_research_portfolio(results)
    quantities_json = directory / "fundamental_quantities.json"
    quantities_md = directory / "fundamental_quantities.md"
    rankings_json = directory / "research_portfolio_rankings.json"
    rankings_md = directory / "research_portfolio_rankings.md"
    quantities_json.write_text(
        json.dumps({"object": "agent_hub.research.fundamental_quantities", "quantities": results}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    quantities_md.write_text(fundamental_quantities_markdown(results), encoding="utf-8")
    rankings_json.write_text(json.dumps(portfolio, indent=2, sort_keys=True), encoding="utf-8")
    rankings_md.write_text(portfolio_markdown(portfolio), encoding="utf-8")
    return {
        "fundamental_quantities_json": quantities_json,
        "fundamental_quantities_markdown": quantities_md,
        "research_portfolio_rankings_json": rankings_json,
        "research_portfolio_rankings_markdown": rankings_md,
    }


def _quantity_section(row: dict[str, Any]) -> list[str]:
    predicts = "Yes, in this dataset." if float(row.get("predictive_power") or 0.0) >= 0.25 else "Only weakly in this dataset."
    survives = "Yes, provisionally." if row.get("survives_falsification") else "No; current evidence is too weak or unstable."
    return [
        "",
        f"### {row['rank']}. {row['name']}",
        "",
        f"- What does it measure? {row['what_it_measures']}",
        f"- Why could it matter? {row['why_it_could_matter']}",
        f"- How is it calculated? {row['how_it_is_calculated']}",
        f"- Does it predict anything useful? {predicts} Predictive power: {row['predictive_power']}; routing usefulness: {row['usefulness_for_routing']}.",
        f"- Does it survive falsification? {survives} Evidence: {' '.join(row.get('falsification_evidence') or [])}",
        f"- Should we continue or kill this direction? {row['continue_or_kill']}.",
        f"- What next experiment would strengthen or disprove it? {row['next_experiment']}",
    ]


def _decision(row: dict[str, Any]) -> str:
    score = float(row.get("research_potential_score") or 0.0)
    if row.get("survives_falsification") and score >= 0.48:
        return "continue"
    if score >= 0.32:
        return "continue cautiously"
    return "kill or redesign"


__all__ = [
    "export_research_portfolio",
    "fundamental_quantities_markdown",
    "next_experiment",
    "portfolio_markdown",
    "rank_research_portfolio",
    "tier_for_score",
]
