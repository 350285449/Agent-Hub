"use strict";

const fs = require("fs");
const path = require("path");

const extensionRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionRoot, "..");
const backendRoot = path.join(extensionRoot, "backend");
const sourcePackage = path.join(repoRoot, "agent_hub");

if (!fs.existsSync(path.join(sourcePackage, "__main__.py"))) {
  throw new Error(`Could not find Agent Hub Python package at ${sourcePackage}`);
}

fs.rmSync(backendRoot, { recursive: true, force: true });
fs.mkdirSync(backendRoot, { recursive: true });
copyDirectory(sourcePackage, path.join(backendRoot, "agent_hub"));

for (const file of ["pyproject.toml", "README.md"]) {
  const source = path.join(repoRoot, file);
  if (fs.existsSync(source)) {
    fs.copyFileSync(source, path.join(backendRoot, file));
  }
}

console.log(`Prepared bundled Agent Hub backend at ${backendRoot}`);

function copyDirectory(source, destination) {
  fs.mkdirSync(destination, { recursive: true });
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    if (entry.name === "__pycache__" || entry.name.endsWith(".pyc")) {
      continue;
    }
    const sourcePath = path.join(source, entry.name);
    const destinationPath = path.join(destination, entry.name);
    if (entry.isDirectory()) {
      copyDirectory(sourcePath, destinationPath);
    } else if (entry.isFile()) {
      fs.copyFileSync(sourcePath, destinationPath);
    }
  }
}
