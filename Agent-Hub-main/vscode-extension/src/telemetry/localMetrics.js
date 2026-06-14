"use strict";

function proofMetrics(summary = {}) {
  const source = summary.savings && typeof summary.savings === "object" ? summary.savings : summary;
  return {
    tokensSaved: Number(source.tokens_saved || source.tokensSaved || 0),
    costAvoided: Number(source.cost_avoided_usd || source.costAvoided || 0),
    retriesAvoided: Number(source.retries_avoided || source.retriesAvoided || 0),
    bestModelForRepo: source.best_model_for_repo || source.bestModelForRepo || "",
    worstModelForRepo: source.worst_model_for_repo || source.worstModelForRepo || ""
  };
}

module.exports = { proofMetrics };
