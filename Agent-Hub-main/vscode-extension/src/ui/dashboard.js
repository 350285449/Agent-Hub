"use strict";

const PROOF_CARDS = [
  "Tokens saved",
  "Cost avoided",
  "Retries avoided",
  "Best model for this repo",
  "Worst model for this repo"
];

function proofCards(metrics = {}) {
  return PROOF_CARDS.map((label) => {
    const snakeKey = label.toLowerCase().replaceAll(" ", "_");
    const camelKey = snakeKey.replace(/_([a-z])/g, (_match, value) => value.toUpperCase());
    return { label, value: metrics[label] || metrics[snakeKey] || metrics[camelKey] || "--" };
  });
}

module.exports = { PROOF_CARDS, proofCards };
