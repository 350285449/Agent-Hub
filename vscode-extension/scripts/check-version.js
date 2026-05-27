"use strict";

const fs = require("fs");
const path = require("path");

const extensionRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionRoot, "..");
const manifestPath = path.join(extensionRoot, "package.json");
const lockPath = path.join(extensionRoot, "package-lock.json");
const sourcePath = path.join(extensionRoot, "extension.js");
const pyprojectPath = path.join(repoRoot, "pyproject.toml");
const backendVersionPath = path.join(repoRoot, "agent_hub", "version.py");

const manifest = readJson(manifestPath);
const lock = readJson(lockPath);
const source = fs.readFileSync(sourcePath, "utf8");
const failures = [];

if (!manifest.version) {
  failures.push("package.json is missing version");
}
if (lock.version !== manifest.version) {
  failures.push(`package-lock.json version ${lock.version || "<missing>"} does not match package.json ${manifest.version}`);
}
if (lock.packages && lock.packages[""] && lock.packages[""].version !== manifest.version) {
  failures.push(`package-lock root package version ${lock.packages[""].version || "<missing>"} does not match package.json ${manifest.version}`);
}
if (/EXTENSION_VERSION\s*=\s*["']/.test(source)) {
  failures.push("extension.js must not hardcode EXTENSION_VERSION; read package.json instead");
}
if (!source.includes("readExtensionPackageVersion")) {
  failures.push("extension.js does not read the extension version from package.json");
}

const pyprojectVersion = readTomlVersion(pyprojectPath);
const backendBaseVersion = readBackendBaseVersion(backendVersionPath);
if (pyprojectVersion && backendBaseVersion && pyprojectVersion !== backendBaseVersion) {
  failures.push(`pyproject.toml version ${pyprojectVersion} does not match agent_hub/version.py BASE_VERSION ${backendBaseVersion}`);
}

if (failures.length) {
  console.error("Extension version consistency check failed:");
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

if (pyprojectVersion && pyprojectVersion !== manifest.version) {
  console.log(
    `Extension version ${manifest.version}; Python backend version ${pyprojectVersion} is intentionally separate.`
  );
} else {
  console.log(`Extension version metadata is consistent at ${manifest.version}.`);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readTomlVersion(filePath) {
  if (!fs.existsSync(filePath)) {
    return "";
  }
  const match = fs.readFileSync(filePath, "utf8").match(/^\s*version\s*=\s*"([^"]+)"/m);
  return match ? match[1] : "";
}

function readBackendBaseVersion(filePath) {
  if (!fs.existsSync(filePath)) {
    return "";
  }
  const match = fs.readFileSync(filePath, "utf8").match(/^\s*BASE_VERSION\s*=\s*"([^"]+)"/m);
  return match ? match[1] : "";
}
