"use strict";

const APPROVAL_MODES = new Set(["ask", "auto", "safe", "readonly", "shell-ask", "deny"]);

function normalizeApprovalMode(value) {
  const mode = typeof value === "string" ? value.trim().toLowerCase() : "";
  return APPROVAL_MODES.has(mode) ? mode : "ask";
}

function missingBackendFeatures(health, requiredFeatures) {
  const features = health && health.features && typeof health.features === "object"
    ? health.features
    : {};
  return (requiredFeatures || []).filter((feature) => features[feature] !== true);
}

function backendReadiness(health, requiredFeatures) {
  const missing = missingBackendFeatures(health, requiredFeatures);
  return {
    connected: !!health,
    ready: !!health && missing.length === 0,
    version: health && health.version ? String(health.version) : "",
    missingFeatures: missing
  };
}

function splitCommandLine(value) {
  const parts = [];
  const pattern = /"([^"]+)"|'([^']+)'|(\S+)/g;
  let match;
  while ((match = pattern.exec(String(value || ""))) !== null) {
    parts.push(match[1] || match[2] || match[3]);
  }
  return parts;
}

function shouldShowFirstRunProofPrompt(storedVersion, currentVersion) {
  const current = typeof currentVersion === "string" ? currentVersion.trim() : "";
  if (!current) {
    return false;
  }
  return String(storedVersion || "").trim() !== current;
}

module.exports = {
  backendReadiness,
  missingBackendFeatures,
  normalizeApprovalMode,
  shouldShowFirstRunProofPrompt,
  splitCommandLine
};
