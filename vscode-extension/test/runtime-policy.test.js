"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const policy = require("../runtime-policy");

test("backend readiness reports missing contracts", () => {
  const required = ["streaming", "cost_dashboard"];
  const result = policy.backendReadiness(
    { version: "1.2.3", features: { streaming: true } },
    required
  );

  assert.equal(result.connected, true);
  assert.equal(result.ready, false);
  assert.equal(result.version, "1.2.3");
  assert.deepEqual(result.missingFeatures, ["cost_dashboard"]);
});

test("backend readiness rejects unavailable health", () => {
  assert.deepEqual(policy.backendReadiness(null, ["streaming"]), {
    connected: false,
    ready: false,
    version: "",
    missingFeatures: ["streaming"]
  });
});

test("approval modes are normalized safely", () => {
  assert.equal(policy.normalizeApprovalMode(" AUTO "), "auto");
  assert.equal(policy.normalizeApprovalMode("unexpected"), "ask");
  assert.equal(policy.normalizeApprovalMode(null), "ask");
});

test("command parsing preserves quoted Python paths", () => {
  assert.deepEqual(
    policy.splitCommandLine('"C:\\Program Files\\Python\\python.exe" -S'),
    ["C:\\Program Files\\Python\\python.exe", "-S"]
  );
});

test("first-run proof prompt is version gated", () => {
  assert.equal(policy.shouldShowFirstRunProofPrompt("", "9.3.0"), true);
  assert.equal(policy.shouldShowFirstRunProofPrompt("9.2.0", "9.3.0"), true);
  assert.equal(policy.shouldShowFirstRunProofPrompt("9.3.0", "9.3.0"), false);
  assert.equal(policy.shouldShowFirstRunProofPrompt("", ""), false);
});
