"use strict";

const cp = require("child_process");
const fs = require("fs");
const path = require("path");

const args = process.argv.slice(2);
if (!args.length) {
  console.error("Usage: node scripts/run-python.js <script.py> [args...]");
  process.exit(2);
}

const repoRoot = path.resolve(__dirname, "..", "..");
const candidates = [
  process.env.PYTHON ? [process.env.PYTHON] : null,
  [path.join(repoRoot, ".venv-check", "Scripts", "python.exe")],
  [path.join(repoRoot, ".venv", "Scripts", "python.exe")],
  [path.join(repoRoot, ".venv-check", "bin", "python")],
  [path.join(repoRoot, ".venv", "bin", "python")],
  process.platform === "win32" ? ["py", "-3"] : null,
  ["python"],
  ["python3"]
].filter(Boolean);

let lastError = "";
for (const candidate of candidates) {
  if (path.isAbsolute(candidate[0]) && !fs.existsSync(candidate[0])) {
    continue;
  }
  const result = cp.spawnSync(candidate[0], [...candidate.slice(1), ...args], {
    cwd: process.cwd(),
    env: process.env,
    stdio: "inherit"
  });
  if (!result.error) {
    process.exit(result.status === null ? 1 : result.status);
  }
  lastError = result.error.message;
}

console.error(`No usable Python executable found. ${lastError}`.trim());
process.exit(1);
