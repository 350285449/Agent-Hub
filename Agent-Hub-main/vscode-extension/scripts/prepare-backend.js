"use strict";

const cp = require("child_process");
const path = require("path");

const extensionRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionRoot, "..");
const scriptPath = path.join(repoRoot, "scripts", "generate_backend_snapshot.py");

const candidates = [];
if (process.env.PYTHON) {
  candidates.push({ command: process.env.PYTHON, args: [] });
}
candidates.push(
  { command: "python", args: [] },
  { command: "python3", args: [] },
  { command: "py", args: ["-3"] }
);

let lastError = "";
for (const candidate of candidates) {
  const result = cp.spawnSync(
    candidate.command,
    [...candidate.args, scriptPath],
    {
      cwd: repoRoot,
      encoding: "utf8",
      stdio: "pipe"
    }
  );
  if (result.status === 0) {
    process.stdout.write(result.stdout || "");
    process.stderr.write(result.stderr || "");
    process.exit(0);
  }
  lastError = `${candidate.command} ${candidate.args.join(" ")}: ${result.stderr || result.stdout || result.error || "failed"}`;
}

throw new Error(`Could not generate Agent Hub backend snapshot. Last error: ${lastError}`);
