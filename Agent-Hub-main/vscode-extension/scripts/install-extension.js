#!/usr/bin/env node
"use strict";

const cp = require("child_process");
const fs = require("fs");
const path = require("path");

const extensionRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(extensionRoot, "..");
const manifestPath = path.join(extensionRoot, "package.json");

const HELP = `
Usage:
  .\\install-extension.ps1
  sh ./install-extension.sh
  node vscode-extension/scripts/install-extension.js [options]
  cd vscode-extension && npm run install-extension -- [options]

Options:
  --code <path>       Use a specific VS Code-compatible CLI.
  --vsix <path>       Install an existing VSIX instead of building one.
  --package-only      Build the VSIX but do not install it.
  --skip-package      Install the current versioned VSIX if it already exists.
  --skip-deps         Do not install npm dependencies before packaging.
  --refresh-deps      Reinstall npm dependencies before packaging.
  -h, --help          Show this help.

Environment:
  AGENT_HUB_CODE_CLI  Same as --code.
  VSCODE_CLI          Same as --code.
`;

try {
  main();
} catch (error) {
  console.error("");
  console.error(`Agent Hub extension install failed: ${error.message}`);
  console.error("");
  console.error("Try one of these fixes:");
  console.error("- Install Node.js 20 or newer and Visual Studio Code.");
  console.error("- In VS Code, run 'Shell Command: Install code command in PATH'.");
  console.error("- Or pass the CLI path with --code \"/path/to/code\".");
  process.exit(1);
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    console.log(HELP.trim());
    return;
  }

  if (options.vsix && options.packageOnly) {
    throw new Error("--vsix and --package-only cannot be used together.");
  }

  const manifest = readJson(manifestPath);
  const extensionId = `${manifest.publisher}.${manifest.name}`;
  const expectedVsix = path.join(extensionRoot, `${manifest.name}-${manifest.version}.vsix`);
  const vsixPath = options.vsix
    ? path.resolve(process.cwd(), options.vsix)
    : expectedVsix;
  const shouldPackage = !options.vsix && !options.skipPackage;

  console.log(`Agent Hub VS Code extension ${manifest.version}`);
  console.log(`Repository: ${repoRoot}`);
  console.log("");

  if (shouldPackage) {
    requireNodeMajor(20);
  }

  const codeCli = options.packageOnly ? null : findCodeCli(options.code);
  if (codeCli) {
    console.log(`VS Code CLI: ${codeCli}`);
  }

  const python = findPython();
  if (python) {
    console.log(`Python runtime: ${python.label} (${python.version})`);
  } else {
    console.warn("Warning: Python 3.11+ was not found. The extension can install, but Agent Hub will need Python before it can start the backend.");
  }

  if (shouldPackage) {
    installDependencies(options);
    packageExtension(expectedVsix);
  } else {
    requireFile(vsixPath, "VSIX package");
    console.log(`Using VSIX: ${vsixPath}`);
  }

  if (options.packageOnly) {
    console.log("");
    console.log(`${shouldPackage ? "Built" : "VSIX ready"}: ${vsixPath}`);
    return;
  }

  installVsix(codeCli, vsixPath);
  verifyInstall(codeCli, extensionId, manifest.version);

  console.log("");
  console.log("Done. Reload VS Code, open any workspace, then run 'Agent Hub: Open Chat'.");
}

function parseArgs(args) {
  const options = {
    code: "",
    help: false,
    packageOnly: false,
    refreshDeps: false,
    skipDeps: false,
    skipPackage: false,
    vsix: ""
  };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "-h" || arg === "--help") {
      options.help = true;
    } else if (arg === "--package-only") {
      options.packageOnly = true;
    } else if (arg === "--refresh-deps") {
      options.refreshDeps = true;
    } else if (arg === "--skip-deps") {
      options.skipDeps = true;
    } else if (arg === "--skip-package") {
      options.skipPackage = true;
    } else if (arg === "--code") {
      options.code = requireValue(args, index, arg);
      index += 1;
    } else if (arg.startsWith("--code=")) {
      options.code = arg.slice("--code=".length);
    } else if (arg === "--vsix") {
      options.vsix = requireValue(args, index, arg);
      index += 1;
    } else if (arg.startsWith("--vsix=")) {
      options.vsix = arg.slice("--vsix=".length);
    } else {
      throw new Error(`Unknown option: ${arg}`);
    }
  }

  if (!options.code) {
    options.code = process.env.AGENT_HUB_CODE_CLI || process.env.VSCODE_CLI || "";
  }
  if (options.vsix) {
    options.skipPackage = true;
  }
  return options;
}

function requireValue(args, index, optionName) {
  const value = args[index + 1];
  if (!value || value.startsWith("--")) {
    throw new Error(`${optionName} requires a value.`);
  }
  return value;
}

function readJson(filePath) {
  requireFile(filePath, "JSON file");
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function requireFile(filePath, label) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`Missing ${label}: ${filePath}`);
  }
}

function installDependencies(options) {
  if (options.skipDeps) {
    console.log("Skipping npm dependency install.");
    return;
  }

  const vscePackage = path.join(extensionRoot, "node_modules", "@vscode", "vsce", "package.json");
  if (!options.refreshDeps && fs.existsSync(vscePackage)) {
    console.log("npm dependencies are already installed.");
    return;
  }

  const npm = commandName("npm");
  const packageLock = path.join(extensionRoot, "package-lock.json");
  const args = fs.existsSync(packageLock) ? ["ci"] : ["install"];
  console.log("Installing extension dependencies...");
  run(npm, args, { cwd: extensionRoot });
}

function packageExtension(vsixPath) {
  if (fs.existsSync(vsixPath)) {
    fs.rmSync(vsixPath, { force: true });
  }

  console.log("Packaging the extension...");
  run(commandName("npm"), ["run", "package"], { cwd: extensionRoot });
  requireFile(vsixPath, "packaged VSIX");
}

function installVsix(codeCli, vsixPath) {
  requireFile(vsixPath, "VSIX package");
  console.log("Installing the extension into VS Code...");
  run(codeCli, ["--install-extension", vsixPath, "--force"], { cwd: extensionRoot });
}

function verifyInstall(codeCli, extensionId, version) {
  const result = runCapture(codeCli, ["--list-extensions", "--show-versions"], {
    cwd: extensionRoot,
    optional: true
  });
  if (!result) {
    console.log("Install command completed. Could not verify the installed extension list.");
    return;
  }

  const expected = `${extensionId}@${version}`.toLowerCase();
  const installed = result.stdout
    .split(/\r?\n/)
    .map((line) => line.trim().toLowerCase())
    .includes(expected);
  if (installed) {
    console.log(`Verified installed extension: ${extensionId}@${version}`);
  } else {
    console.log("Install command completed. Reload VS Code if the old extension is still active.");
  }
}

function findCodeCli(override) {
  const candidates = [];
  if (override) {
    candidates.push(override);
  }
  candidates.push(...codeCliCandidates());

  const seen = new Set();
  for (const candidate of candidates) {
    if (!candidate || seen.has(candidate)) {
      continue;
    }
    seen.add(candidate);
    const result = runCapture(candidate, ["--version"], { optional: true });
    if (result) {
      return candidate;
    }
  }

  throw new Error("Could not find the VS Code CLI.");
}

function codeCliCandidates() {
  const candidates = [
    commandName("code"),
    commandName("code-insiders"),
    commandName("codium")
  ];

  if (process.platform === "win32") {
    const local = process.env.LOCALAPPDATA;
    const programFiles = process.env.ProgramFiles;
    const programFilesX86 = process.env["ProgramFiles(x86)"];
    candidates.push(
      local && path.join(local, "Programs", "Microsoft VS Code", "bin", "code.cmd"),
      local && path.join(local, "Programs", "Microsoft VS Code Insiders", "bin", "code-insiders.cmd"),
      local && path.join(local, "Programs", "VSCodium", "bin", "codium.cmd"),
      programFiles && path.join(programFiles, "Microsoft VS Code", "bin", "code.cmd"),
      programFilesX86 && path.join(programFilesX86, "Microsoft VS Code", "bin", "code.cmd")
    );
  } else if (process.platform === "darwin") {
    candidates.push(
      "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
      "/Applications/Visual Studio Code - Insiders.app/Contents/Resources/app/bin/code-insiders",
      "/Applications/VSCodium.app/Contents/Resources/app/bin/codium"
    );
  }

  return candidates.filter(Boolean);
}

function findPython() {
  const probe = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}'); raise SystemExit(0 if sys.version_info >= (3, 11) else 1)";
  const candidates = process.platform === "win32"
    ? [
      { command: "py.exe", args: ["-3"] },
      { command: "py.exe", args: ["-3.13"] },
      { command: "py.exe", args: ["-3.12"] },
      { command: "py.exe", args: ["-3.11"] },
      { command: "python", args: [] },
      { command: "python3", args: [] }
    ]
    : [
      { command: "python3", args: [] },
      { command: "python", args: [] }
    ];

  for (const candidate of candidates) {
    const result = runCapture(candidate.command, [...candidate.args, "-c", probe], {
      optional: true
    });
    if (result) {
      return {
        label: [candidate.command, ...candidate.args].join(" "),
        version: result.stdout.trim()
      };
    }
  }
  return null;
}

function requireNodeMajor(minMajor) {
  const major = Number.parseInt(process.versions.node.split(".")[0], 10);
  if (!Number.isFinite(major) || major < minMajor) {
    throw new Error(`Packaging requires Node.js ${minMajor} or newer. Current Node.js: ${process.versions.node}`);
  }
}

function commandName(command) {
  if (process.platform !== "win32") {
    return command;
  }
  if (/[\\/]/.test(command) || /\.[a-z0-9]+$/i.test(command)) {
    return command;
  }
  return `${command}.cmd`;
}

function run(command, args, options = {}) {
  console.log(`> ${formatCommand(command, args)}`);
  const result = spawn(command, args, {
    cwd: options.cwd || repoRoot,
    stdio: "inherit"
  });
  if (result.error) {
    throw new Error(`Could not run ${command}: ${result.error.message}`);
  }
  if (result.status !== 0) {
    throw new Error(`${formatCommand(command, args)} exited with ${result.status}`);
  }
}

function runCapture(command, args, options = {}) {
  const result = spawn(command, args, {
    cwd: options.cwd || repoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"]
  });

  if (result.error || result.status !== 0) {
    if (options.optional) {
      return null;
    }
    const detail = result.error ? result.error.message : (result.stderr || "").trim();
    throw new Error(`Could not run ${formatCommand(command, args)}${detail ? `: ${detail}` : ""}`);
  }
  return {
    stdout: result.stdout || "",
    stderr: result.stderr || ""
  };
}

function spawn(command, args, options) {
  if (process.platform !== "win32") {
    return cp.spawnSync(command, args, {
      ...options,
      windowsHide: true
    });
  }

  const comspec = process.env.ComSpec || "cmd.exe";
  const commandLine = [command, ...args].map(quoteForCmd).join(" ");
  return cp.spawnSync(comspec, ["/d", "/s", "/c", commandLine], {
    ...options,
    windowsHide: true
  });
}

function formatCommand(command, args) {
  return [command, ...args].map(quoteForDisplay).join(" ");
}

function quoteForDisplay(value) {
  const text = String(value);
  return /\s/.test(text) ? `"${text}"` : text;
}

function quoteForCmd(value) {
  const text = String(value);
  if (!/[ \t&()^=;!'+,`~[\]{}]/.test(text)) {
    return text;
  }
  return `"${text.replace(/"/g, '\\"')}"`;
}
