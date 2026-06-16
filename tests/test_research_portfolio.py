from __future__ import annotations

import json

from agent_hub.research.research_portfolio import export_research_portfolio, portfolio_markdown, rank_research_portfolio


def test_rank_research_portfolio_orders_and_tiers():
    portfolio = rank_research_portfolio(
        [
            _result("weak", "Weak Quantity", 0.2, survives=False),
            _result("strong", "Strong Quantity", 0.7, survives=True),
            _result("middle", "Middle Quantity", 0.4, survives=False),
        ]
    )

    ranked = portfolio["ranked_quantities"]
    assert [row["name"] for row in ranked] == ["Strong Quantity", "Middle Quantity", "Weak Quantity"]
    assert ranked[0]["tier"] == "S"
    assert ranked[-1]["tier"] == "C"
    assert ranked[0]["continue_or_kill"] == "continue"


def test_portfolio_markdown_answers_required_questions():
    portfolio = rank_research_portfolio([_result("routing_risk_score", "Routing Risk Score", 0.65, survives=True)])

    markdown = portfolio_markdown(portfolio)

    assert "What does it measure?" in markdown
    assert "Why could it matter?" in markdown
    assert "How is it calculated?" in markdown
    assert "Does it predict anything useful?" in markdown
    assert "Does it survive falsification?" in markdown
    assert "Should we continue or kill this direction?" in markdown
    assert "What next experiment would strengthen or disprove it?" in markdown


def test_export_research_portfolio_writes_json_and_markdown(tmp_path):
    paths = export_research_portfolio(tmp_path / ".agent-hub", [_result("strong", "Strong Quantity", 0.7, survives=True)])

    saved = json.loads(paths["research_portfolio_rankings_json"].read_text(encoding="utf-8"))
    markdown = paths["research_portfolio_rankings_markdown"].read_text(encoding="utf-8")

    assert saved["object"] == "agent_hub.research.research_portfolio_rankings"
    assert "Strong Quantity" in markdown


def _result(key: str, name: str, score: float, *, survives: bool):
    return {
        "key": key,
        "name": name,
        "value": score,
        "stability": score,
        "predictive_power": score,
        "correlation_with_success": score,
        "correlation_with_validation_score": score,
        "usefulness_for_routing": score,
        "novelty_proxy": score,
        "falsification_resistance": score,
        "research_potential_score": score,
        "falsification_evidence": ["test evidence"],
        "limitations": ["test limitation"],
        "survives_falsification": survives,
        "recommendation": "continue" if survives else "kill or redesign",
        "what_it_measures": "A test quantity.",
        "why_it_could_matter": "It might help routing.",
        "how_it_is_calculated": "A deterministic fake calculation.",
        "details": {},
    }
